#!/usr/bin/env python3
"""decoder_node - dekodowanie ramek ADS-B w czasie rzeczywistym.

Subskrybuje:
  /aircraft/frames  (std_msgs/String)            surowe ramki AVR z sdr_node
  /gps/fix          (sensor_msgs/NavSatFix)      pozycja stacji
  /gps/time_ref     (sensor_msgs/TimeReference)  czas UTC z GPS -> korekta zegara RPi

Publikuje:
  /aircraft/state   (aircraft_interfaces/AircraftState)
      stan samolotu po każdej ramce, która coś zmieniła: pozycja, wysokość,
      prędkość oraz odległość, azymut i elewacja względem stacji.

Czas: RPi nie ma zegara RTC, więc w terenie bez internetu jego zegar może się
mylić o wiele godzin. Węzeł liczy przesunięcie zegara RPi względem GPS
(clock_offset.py) i dodaje je do znaczników czasu w AircraftState
(header.stamp, position_stamp). Pole time_source mówi, czy korekta była już
dostępna (TIME_GPS), czy jeszcze nie (TIME_SYSTEM).

Cała logika dekodowania jest w adsb_decoder.py (bez ROS, do testów).
Czas bierzemy z zegara węzła - przy odtwarzaniu baga z opcją --clock
i parametrem use_sim_time:=true węzeł używa oryginalnego czasu nagrania
(a /gps/time_ref z baga daje tę samą korektę co na żywo).

Parametry:
  use_gps_time (bool, domyślnie true)  - czy poprawiać czas na podstawie GPS
  gps_delay    (float [s], domyślnie 0.0) - opóźnienie odczytu zdania NMEA
"""
import math

import rclpy
from rclpy.node import Node
from rclpy.executors import ExternalShutdownException
from rclpy.time import Time
from std_msgs.msg import String
from sensor_msgs.msg import NavSatFix, TimeReference
from aircraft_interfaces.msg import AircraftState

from aircraft_tracker.adsb_decoder import AdsbDecoder, POSITION_NONE
from aircraft_tracker.clock_offset import ClockOffset

GPS_TIME_TIMEOUT_S = 60.0   # po tylu sekundach bez czasu z GPS ostrzegamy w logu


class DecoderNode(Node):
    def __init__(self):
        super().__init__('decoder_node')
        self.decoder = AdsbDecoder()
        self.station_logged = False

        self.use_gps_time = self.declare_parameter('use_gps_time', True).value
        gps_delay = float(self.declare_parameter('gps_delay', 0.0).value)
        self.clock = ClockOffset(gps_delay=gps_delay)
        self.gps_time_warned = False   # żeby nie powtarzać ostrzeżenia o braku czasu GPS

        self.state_pub = self.create_publisher(AircraftState, '/aircraft/state', 50)
        # Większa kolejka dla ramek - przychodzą seriami (nawet ~70 na sekundę)
        self.create_subscription(String, '/aircraft/frames', self.frame_callback, 100)
        self.create_subscription(NavSatFix, '/gps/fix', self.gps_callback, 10)
        self.create_subscription(TimeReference, '/gps/time_ref', self.time_callback, 10)

        self.create_timer(10.0, self.report)   # statystyka w logu co 10 s
        self.create_timer(5.0, self.prune)     # sprzątanie starych samolotów

        self.get_logger().info(
            "Decoder node uruchomiony, czekam na ramki i pozycję GPS... "
            f"(korekta czasu z GPS: {'tak' if self.use_gps_time else 'NIE'}, "
            f"gps_delay = {gps_delay:.3f} s)")

    # ------------------------------------------------------------------ #
    def gps_callback(self, msg):
        if math.isnan(msg.latitude) or math.isnan(msg.longitude):
            return
        self.decoder.set_station(msg.latitude, msg.longitude, msg.altitude)
        if not self.station_logged:
            self.get_logger().info(
                "Mam pozycję stacji z GPS - włączam dekodowanie lokalne i geometrię.")
            self.station_logged = True

    def time_callback(self, msg):
        t_gps = msg.time_ref.sec + msg.time_ref.nanosec * 1e-9
        t_sys = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
        had_offset = self.clock.offset() is not None
        jumped = self.clock.add(t_gps, t_sys)
        off = self.clock.offset()

        if off is not None and not had_offset:
            self.get_logger().info(
                f"Mam czas z GPS - przesunięcie zegara RPi: {off:+.3f} s. "
                "Znaczniki czasu w /aircraft/state będą w UTC z GPS.")
            if abs(off) > 1.0:
                self.get_logger().warn(
                    f"Zegar RPi różni się od GPS o {off:+.1f} s "
                    "(prawdopodobnie brak internetu/NTP) - korekta jest konieczna.")
        if jumped:
            self.get_logger().warn(
                f"Zegar RPi został przestawiony (np. przez NTP) - "
                f"nowe przesunięcie: {off:+.3f} s.")
        self.gps_time_warned = False

    # ------------------------------------------------------------------ #
    def current_offset(self):
        """Przesunięcie do dodania do zegara RPi [s] albo None (brak korekty)."""
        if not self.use_gps_time:
            return None
        return self.clock.offset()

    def frame_callback(self, msg):
        now = self.get_clock().now()
        icao = self.decoder.process(msg.data, now.nanoseconds * 1e-9)
        if icao is None:
            return
        self.state_pub.publish(self.to_msg(self.decoder.state(icao), now))

    def to_msg(self, s, now):
        m = AircraftState()
        # Wewnątrz dekodera czasy są w zegarze RPi (spójne między sobą,
        # potrzebne np. do kontroli skoków). Korektę dodajemy dopiero tutaj.
        off = self.current_offset()
        if off is None:
            m.time_source = AircraftState.TIME_SYSTEM
            m.clock_offset = math.nan
            off_ns = 0
        else:
            m.time_source = AircraftState.TIME_GPS
            m.clock_offset = off
            off_ns = int(round(off * 1e9))

        m.header.stamp = Time(nanoseconds=now.nanoseconds + off_ns).to_msg()
        m.header.frame_id = 'gps_link'   # wielkości liczone względem anteny GPS stacji
        m.icao = s['icao']
        m.callsign = s['callsign']

        m.latitude = s['latitude']
        m.longitude = s['longitude']
        m.position_quality = s['position_quality']
        if s['position_quality'] != POSITION_NONE:
            m.position_stamp = Time(
                nanoseconds=int(s['position_time'] * 1e9) + off_ns).to_msg()

        m.altitude = s['altitude']
        m.altitude_type = s['altitude_type']
        m.altitude_baro = s['altitude_baro']

        m.ground_speed = s['ground_speed']
        m.track = s['track']
        m.vertical_rate = s['vertical_rate']

        m.ground_distance = s['ground_distance']
        m.slant_distance = s['slant_distance']
        m.azimuth = s['azimuth']
        m.elevation = s['elevation']
        return m

    # ------------------------------------------------------------------ #
    def prune(self):
        self.decoder.prune(self.get_clock().now().nanoseconds * 1e-9)

    def report(self):
        st = self.decoder.reset_stats()
        with_pos = sum(1 for a in self.decoder.aircraft.values()
                       if a['position_quality'] != POSITION_NONE)
        off = self.current_offset()
        if off is None:
            czas = "czas: zegar RPi (brak korekty z GPS)"
        else:
            sd = self.clock.spread()
            czas = f"czas: GPS, przesunięcie {off:+.3f} s"
            if sd is not None:
                czas += f" (rozrzut {sd:.3f} s)"
        self.get_logger().info(
            f"Ostatnie 10 s: {st['ramki']} ramek ({st['adsb']} ADS-B, {st['bledne']} błędnych), "
            f"{st['pozycje']} pozycji ({st['potwierdzone']} potwierdzonych). "
            f"Samoloty: {len(self.decoder.aircraft)}, z pozycją: {with_pos}. {czas}.")
        problems = st['niezgodne'] + st['skoki'] + st['poza_zasiegiem']
        if problems:
            self.get_logger().warn(
                f"Odrzucone pozycje: {st['niezgodne']} niezgodnych metod, "
                f"{st['skoki']} skoków, {st['poza_zasiegiem']} poza zasięgiem.")

        # Ostrzeżenie, gdy dawno nie było czasu z GPS (np. utrata sygnału)
        if self.use_gps_time and not self.gps_time_warned:
            age = self.clock.age(self.get_clock().now().nanoseconds * 1e-9)
            if age is not None and age > GPS_TIME_TIMEOUT_S:
                self.get_logger().warn(
                    f"Brak czasu z GPS od {age:.0f} s - używam ostatniego "
                    "znanego przesunięcia zegara.")
                self.gps_time_warned = True


def main(args=None):
    rclpy.init(args=args)
    node = DecoderNode()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass   # normalne zakończenie (Ctrl+C albo SIGINT ze start_nodes.sh)
    finally:
        node.destroy_node()
        # Jazzy przy SIGINT sam zamyka ROS - drugie wywołanie shutdown()
        # dawało błąd "rcl_shutdown already called". Zamykamy tylko, jeśli trzeba.
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()