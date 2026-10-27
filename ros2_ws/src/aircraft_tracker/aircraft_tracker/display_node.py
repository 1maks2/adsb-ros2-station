#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from std_msgs.msg import Bool
from sensor_msgs.msg import NavSatFix, Temperature
from aircraft_interfaces.msg import AircraftState
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

M_TO_FT = 1 / 0.3048      # na ekranie zostają jednostki lotnicze: stopy i węzły
MS_TO_KT = 3600 / 1852.0

# Kolor ICAO = jakość pozycji (stałe z AircraftState.msg)
QUALITY_COLOR = {
    AircraftState.POSITION_VERIFIED: "lime",     # potwierdzona dwiema metodami
    AircraftState.POSITION_LOCAL: "yellow",      # tylko lokalna (z pozycją stacji)
    AircraftState.POSITION_GLOBAL: "yellow",     # tylko globalna (z pary ramek)
    AircraftState.POSITION_NONE: "white",        # brak pozycji
}


def known(x):
    """Czy liczba jest znana (w AircraftState nieznane = NaN)."""
    return x is not None and not math.isnan(x)


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

        self.aircraft = {}           # ICAO -> (ostatni AircraftState, czas odebrania)
        self.gps = None
        self.gps_time = 0.0          # kiedy przyszła ostatnia pozycja GPS

        self.cpu_temp = None
        self.cpu_temp_time = 0.0
        self.undervoltage = False
        self.uv_time = 0.0

        self.start_time = time.monotonic()  # początek sesji (licznik czasu pracy)
        self.blink = False                  # do migania kropki REC

        # Gotowe, zdekodowane dane z decoder_node - ekran niczego już nie dekoduje
        self.create_subscription(AircraftState, '/aircraft/state', self.state_callback, 50)
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

    def state_callback(self, msg):
        self.aircraft[msg.icao] = (msg, time.monotonic())

    def recorder_running(self):
        """Sprawdza, czy w systemie ROS działa node rejestratora rosbag2."""
        return 'rosbag2_recorder' in self.get_node_names()

    def render(self):
        now_mono = time.monotonic()

        # Usuwanie starych samolotów - teraz co sekundę, a nie tylko przy nowej wiadomości
        # (wcześniej, gdy nie było ruchu, stare samoloty wisiały na ekranie)
        self.aircraft = {k: v for k, v in self.aircraft.items()
                         if now_mono - v[1] < AIRCRAFT_TIMEOUT}

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

            # Najpierw zbieramy dane każdego samolotu i jego "kompletność",
            # potem sortujemy i pokazujemy 9 pierwszych.
            # Odległość liczy decoder_node (slant_distance = w linii prostej, 3D).
            rows = []
            for icao, (m, seen) in self.aircraft.items():
                has_pos = m.position_quality != AircraftState.POSITION_NONE
                dist_km = m.slant_distance / 1000.0 if known(m.slant_distance) else None
                # Ile z 4 informacji znamy: znak wywoławczy, wysokość, prędkość, pozycja
                filled = (bool(m.callsign) + known(m.altitude_baro)
                          + known(m.ground_speed) + has_pos)
                rows.append((icao, m, seen, dist_km, filled))

            # Kolejność: najpierw najwięcej wypełnionych pól; przy remisie bliższe wyżej
            # (bez odległości = na końcu remisu); potem te, od których wiadomość przyszła najświeżej.
            rows.sort(key=lambda r: (-r[4],
                                     r[3] if r[3] is not None else float('inf'),
                                     -r[2]))

            y = 38
            for icao, m, seen, dist_km, filled in rows[:9]:
                alt_str = f"{m.altitude_baro * M_TO_FT:.0f}" if known(m.altitude_baro) else "---"
                spd_str = f"{m.ground_speed * MS_TO_KT:.0f}" if known(m.ground_speed) else "---"
                dist_str = f"{dist_km:.1f}km" if dist_km is not None else "---"

                draw.text((5, y),   icao[:6],                fill=QUALITY_COLOR.get(m.position_quality, "white"))
                draw.text((70, y),  m.callsign[:7] or '---', fill="white")
                draw.text((175, y), alt_str[:5],             fill="cyan",    anchor="ra")
                draw.text((245, y), spd_str[:4],             fill="orange",  anchor="ra")
                draw.text((315, y), dist_str,                fill="magenta", anchor="ra")
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