#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from std_msgs.msg import String, Bool
from sensor_msgs.msg import NavSatFix, Temperature
import RPi.GPIO as GPIO
from luma.core.interface.serial import spi
from luma.lcd.device import ili9341
from luma.core.render import canvas
from PIL import ImageFont

import time
import math

AIRCRAFT_TIMEOUT = 60.0   # [s] po tylu sekundach bez wiadomości samolot znika z listy
GPS_TIMEOUT = 5.0         # [s] po tylu sekundach bez /gps/fix uznajemy, że nie ma fixa
SENSOR_TIMEOUT = 5.0      # [s] to samo dla temperatury i alarmu napięcia


def haversine(lat1, lon1, lat2, lon2):
    R = 6371000.0  # promień Ziemi w metrach
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return 2 * R * math.asin(math.sqrt(a))


def format_elapsed(seconds):
    """Zamienia liczbę sekund na tekst G:MM:SS, np. 3:12:05."""
    s = int(seconds)
    return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"


class DisplayNode(Node):
    def __init__(self):
        super().__init__('display_node')
        self.font_big = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)

        # Wyłącza ostrzeżenie "This channel is already in use" przy restarcie kontenera
        GPIO.setwarnings(False)
        serial = spi(port=0, device=0, gpio_DC=24, gpio_RST=25)
        self.device = ili9341(serial, width=320, height=240)

        self.aircraft = {}
        self.gps = None
        self.gps_time = 0.0          # kiedy przyszła ostatnia pozycja GPS

        self.cpu_temp = None
        self.cpu_temp_time = 0.0
        self.undervoltage = False
        self.uv_time = 0.0

        self.start_time = time.monotonic()  # początek sesji (licznik czasu pracy)
        self.blink = False                  # do migania kropki REC

        self.create_subscription(String, '/aircraft/raw', self.msg_callback, 10)
        self.create_subscription(NavSatFix, '/gps/fix', self.gps_callback, 10)
        self.create_subscription(Temperature, '/system/cpu_temp', self.temp_callback, 10)
        self.create_subscription(Bool, '/system/undervoltage', self.uv_callback, 10)
        self.create_timer(1.0, self.render)

        self.get_logger().info("Display node uruchomiony!")

    def gps_callback(self, msg):
        self.gps = (msg.latitude, msg.longitude, msg.altitude,
                    "N" if msg.latitude > 0 else "S", "E" if msg.longitude > 0 else "W")
        self.gps_time = time.monotonic()

    def temp_callback(self, msg):
        self.cpu_temp = msg.temperature
        self.cpu_temp_time = time.monotonic()

    def uv_callback(self, msg):
        self.undervoltage = msg.data
        self.uv_time = time.monotonic()

    def msg_callback(self, msg):
        parts = msg.data.split(',')
        if len(parts) < 11:
            return

        icao = parts[4].strip()
        if not icao:
            return

        if icao not in self.aircraft:
            self.aircraft[icao] = {
                'callsign': '',
                'altitude': '',
                'speed': '',
                'lat': None,
                'lon': None,
                'last_seen': time.time()
            }

        if len(parts) > 10 and parts[10].strip(): self.aircraft[icao]['callsign'] = parts[10].strip()
        if len(parts) > 11 and parts[11].strip(): self.aircraft[icao]['altitude'] = parts[11].strip()
        if len(parts) > 12 and parts[12].strip(): self.aircraft[icao]['speed']    = parts[12].strip()

        if len(parts) > 15 and parts[14].strip() and parts[15].strip():
            try:
                self.aircraft[icao]['lat'] = float(parts[14].strip())
                self.aircraft[icao]['lon'] = float(parts[15].strip())
            except ValueError:
                pass

        self.aircraft[icao]['last_seen'] = time.time()

    def recorder_running(self):
        """Sprawdza, czy w systemie ROS działa node rejestratora rosbag2."""
        return 'rosbag2_recorder' in self.get_node_names()

    def render(self):
        now_mono = time.monotonic()

        # Usuwanie starych samolotów - teraz co sekundę, a nie tylko przy nowej wiadomości
        # (wcześniej, gdy nie było ruchu, stare samoloty wisiały na ekranie)
        now = time.time()
        self.aircraft = {k: v for k, v in self.aircraft.items()
                         if now - v['last_seen'] < AIRCRAFT_TIMEOUT}

        # GPS uznajemy za aktualny tylko, jeśli pozycja przyszła niedawno
        gps_ok = self.gps is not None and (now_mono - self.gps_time) < GPS_TIMEOUT
        temp_ok = self.cpu_temp is not None and (now_mono - self.cpu_temp_time) < SENSOR_TIMEOUT
        uv_active = self.undervoltage and (now_mono - self.uv_time) < SENSOR_TIMEOUT

        self.blink = not self.blink
        rec = self.recorder_running()

        with canvas(self.device) as draw:
            draw.rectangle(self.device.bounding_box, fill="black")

            # --- Pasek górny: tytuł | REC + czas | temperatura | liczba samolotów ---
            draw.text((5, 5), "ADS-B RADAR", fill="yellow")

            if rec:
                if self.blink:
                    draw.ellipse((80, 5, 88, 13), fill="red")   # migająca kropka
                draw.text((92, 5), f"REC {format_elapsed(now_mono - self.start_time)}", fill="red")
            else:
                draw.text((80, 5), "NIE NAGRYWA!", fill="red" if self.blink else "white")

            if temp_ok:
                t = self.cpu_temp
                t_color = "lime" if t < 70 else ("orange" if t < 80 else "red")
                draw.text((175, 5), f"CPU {t:.0f}C", fill=t_color)
            else:
                draw.text((175, 5), "CPU --", fill="gray")

            draw.text((255, 5), f"Szt: {len(self.aircraft)}", fill="cyan")
            draw.line([(0, 18), (320, 18)], fill="white")

            # --- Tabela samolotów ---
            draw.text((5, 22),   "ICAO",  fill="white")
            draw.text((70, 22),  "CALL",  fill="white")
            draw.text((175, 22), "ALT",   fill="white", anchor="ra")
            draw.text((245, 22), "SPD",   fill="white", anchor="ra")
            draw.text((315, 22), "DIST",  fill="white", anchor="ra")

            # Najpierw liczymy odległość i "kompletność" każdego samolotu,
            # potem sortujemy i pokazujemy 9 pierwszych.
            rows = []
            for icao, data in self.aircraft.items():
                dist_km = None
                if gps_ok and data['lat'] is not None and data['lon'] is not None:
                    my_lat, my_lon, my_alt = self.gps[0], self.gps[1], self.gps[2]
                    ground_m = haversine(my_lat, my_lon, data['lat'], data['lon'])
                    try:
                        ac_alt_m = float(data['altitude']) * 0.3048
                    except (ValueError, TypeError):
                        ac_alt_m = my_alt
                    dalt = ac_alt_m - my_alt
                    dist_km = math.sqrt(ground_m**2 + dalt**2) / 1000.0

                # Ile z 4 informacji znamy: znak wywoławczy, wysokość, prędkość, pozycja
                filled = (bool(data['callsign']) + bool(data['altitude'])
                          + bool(data['speed']) + (data['lat'] is not None))
                rows.append((icao, data, dist_km, filled))

            # Kolejność: najpierw najwięcej wypełnionych pól; przy remisie bliższe wyżej
            # (bez odległości = na końcu remisu); potem te, od których wiadomość przyszła najświeżej.
            rows.sort(key=lambda r: (-r[3],
                                     r[2] if r[2] is not None else float('inf'),
                                     -r[1]['last_seen']))

            y = 38
            for icao, data, dist_km, filled in rows[:9]:
                dist_str = f"{dist_km:.1f}km" if dist_km is not None else "---"

                draw.text((5, y),   icao[:6],                      fill="lime")
                draw.text((70, y),  data['callsign'][:6] or '---', fill="white")
                draw.text((175, y), data['altitude'][:5] or '---', fill="cyan",    anchor="ra")
                draw.text((245, y), data['speed'][:4] or '---',    fill="orange",  anchor="ra")
                draw.text((315, y), dist_str,                      fill="magenta", anchor="ra")
                y += 20

            # --- Pasek dolny: ostrzeżenie o zasilaniu albo pozycja GPS ---
            if uv_active:
                draw.rectangle((0, 208, 320, 240), fill="red")
                draw.text((160, 224), "NISKIE ZASILANIE!", fill="white",
                          font=self.font_big, anchor="mm")
            elif gps_ok:
                lat, lon, alt, lat_sign, lon_sign = self.gps
                draw.text((160, 220), f"Pozycja GPS {lat:.4f}{lat_sign} {lon:.4f}{lon_sign} {alt:.0f}m",
                          fill="green", font=self.font_big, anchor="mm")
            else:
                draw.text((160, 220), "GPS: brak fixa", fill="red",
                          font=self.font_big, anchor="mm")


def main(args=None):
    rclpy.init(args=args)
    node = DisplayNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()