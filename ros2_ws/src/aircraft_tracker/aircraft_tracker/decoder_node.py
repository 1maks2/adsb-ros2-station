#!/usr/bin/env python3
"""decoder_node - dekodowanie ramek ADS-B w czasie rzeczywistym.

Subskrybuje:
  /aircraft/frames  (std_msgs/String)     surowe ramki AVR z sdr_node
  /gps/fix          (sensor_msgs/NavSatFix) pozycja stacji

Publikuje:
  /aircraft/state   (aircraft_interfaces/AircraftState)
      stan samolotu po każdej ramce, która coś zmieniła: pozycja, wysokość,
      prędkość oraz odległość, azymut i elewacja względem stacji.

Cała logika dekodowania jest w adsb_decoder.py (bez ROS, do testów).
Czas bierzemy z zegara węzła - przy odtwarzaniu baga z opcją --clock
i parametrem use_sim_time:=true węzeł używa oryginalnego czasu nagrania.
"""
import math

import rclpy
from rclpy.node import Node
from rclpy.time import Time
from std_msgs.msg import String
from sensor_msgs.msg import NavSatFix
from aircraft_interfaces.msg import AircraftState

from aircraft_tracker.adsb_decoder import AdsbDecoder, POSITION_NONE


class DecoderNode(Node):
    def __init__(self):
        super().__init__('decoder_node')
        self.decoder = AdsbDecoder()
        self.station_logged = False

        self.state_pub = self.create_publisher(AircraftState, '/aircraft/state', 50)
        # Większa kolejka dla ramek - przychodzą seriami (nawet ~70 na sekundę)
        self.create_subscription(String, '/aircraft/frames', self.frame_callback, 100)
        self.create_subscription(NavSatFix, '/gps/fix', self.gps_callback, 10)

        self.create_timer(10.0, self.report)   # statystyka w logu co 10 s
        self.create_timer(5.0, self.prune)     # sprzątanie starych samolotów

        self.get_logger().info("Decoder node uruchomiony, czekam na ramki i pozycję GPS...")

    # ------------------------------------------------------------------ #
    def gps_callback(self, msg):
        if math.isnan(msg.latitude) or math.isnan(msg.longitude):
            return
        self.decoder.set_station(msg.latitude, msg.longitude, msg.altitude)
        if not self.station_logged:
            self.get_logger().info(
                "Mam pozycję stacji z GPS - włączam dekodowanie lokalne i geometrię.")
            self.station_logged = True

    def frame_callback(self, msg):
        now = self.get_clock().now()
        icao = self.decoder.process(msg.data, now.nanoseconds * 1e-9)
        if icao is None:
            return
        self.state_pub.publish(self.to_msg(self.decoder.state(icao), now))

    def to_msg(self, s, now):
        m = AircraftState()
        m.header.stamp = now.to_msg()
        m.header.frame_id = 'gps_link'   # wielkości liczone względem anteny GPS stacji
        m.icao = s['icao']
        m.callsign = s['callsign']

        m.latitude = s['latitude']
        m.longitude = s['longitude']
        m.position_quality = s['position_quality']
        if s['position_quality'] != POSITION_NONE:
            m.position_stamp = Time(nanoseconds=int(s['position_time'] * 1e9)).to_msg()

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
        self.get_logger().info(
            f"Ostatnie 10 s: {st['ramki']} ramek ({st['adsb']} ADS-B, {st['bledne']} błędnych), "
            f"{st['pozycje']} pozycji ({st['potwierdzone']} potwierdzonych). "
            f"Samoloty: {len(self.decoder.aircraft)}, z pozycją: {with_pos}.")
        problems = st['niezgodne'] + st['skoki'] + st['poza_zasiegiem']
        if problems:
            self.get_logger().warn(
                f"Odrzucone pozycje: {st['niezgodne']} niezgodnych metod, "
                f"{st['skoki']} skoków, {st['poza_zasiegiem']} poza zasięgiem.")


def main(args=None):
    rclpy.init(args=args)
    node = DecoderNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()