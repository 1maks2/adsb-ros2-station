#!/usr/bin/env python3
import socket

import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class SDRRadarNode(Node):
    def __init__(self):
        super().__init__('sdr_radar_node')

        # Publikowanie surowych linii SBS jako String na temat /aircraft/raw
        self.publisher_ = self.create_publisher(String, '/aircraft/raw', 10)

        # Kontener działa z network_mode: host, więc "widzi" sieć RPi jak swoją.
        # dump1090 działa na tym samym RPi -> adres 127.0.0.1 (localhost).
        self.host = '127.0.0.1'
        self.port = 30003

        self.sock = None      # gniazdo sieciowe (None = brak połączenia)
        self.buffer = b''     # niepełna końcówka danych, czekająca na resztę linii
        self.msg_count = 0    # licznik opublikowanych wiadomości (do statystyk)

        # Co 50 ms: odczyt nowych danych z dump1090
        self.create_timer(0.05, self.read_radar)
        # Co 2 s: jeśli nie ma połączenia, spróbuj połączyć się ponownie
        self.create_timer(2.0, self.ensure_connected)
        # Co 10 s: krótka statystyka w logach zamiast wpisu na każdy pakiet
        self.create_timer(10.0, self.report)

        self.ensure_connected()

    def ensure_connected(self):
        if self.sock is not None:
            return  # już połączony
        try:
            s = socket.create_connection((self.host, self.port), timeout=2.0)
            s.setblocking(False)  # tryb nieblokujący: recv() nie czeka na dane
            self.sock = s
            self.buffer = b''
            self.get_logger().info(
                f"Połączono z dump1090 na {self.host}:{self.port}")
        except OSError as e:
            # Np. dump1090 jeszcze nie wystartował - spróbujemy za 2 s.
            # throttle: ten komunikat pojawi się w logach najwyżej raz na 30 s.
            self.get_logger().warn(
                f"Brak połączenia z dump1090 ({e}), ponawiam próby...",
                throttle_duration_sec=30.0)

    def disconnect(self, reason):
        self.get_logger().warn(f"Rozłączono z dump1090: {reason}")
        try:
            self.sock.close()
        except OSError:
            pass
        self.sock = None
        self.buffer = b''

    def read_radar(self):
        if self.sock is None:
            return

        try:
            data = self.sock.recv(65536)
        except BlockingIOError:
            return  # brak nowych danych - normalna sytuacja
        except OSError as e:
            self.disconnect(f"błąd odczytu: {e}")
            return

        if not data:
            # Pusty odczyt = druga strona zamknęła połączenie (np. restart dump1090)
            self.disconnect("dump1090 zamknął połączenie")
            return

        # Doklejamy nowe dane do tego, co zostało z poprzedniego odczytu
        self.buffer += data

        # Dzielimy na linie. Ostatni element to fragment BEZ znaku końca linii
        # (niepełna linia) - zostaje w buforze i poczeka na resztę.
        *complete_lines, self.buffer = self.buffer.split(b'\n')

        for raw in complete_lines:
            line = raw.decode('ascii', errors='ignore').strip()  # strip() usuwa też \r
            if line.startswith('MSG'):
                msg = String()
                msg.data = line
                self.publisher_.publish(msg)
                self.msg_count += 1

        # Zabezpieczenie: gdyby przyszły śmieci bez końca linii, nie rośnij w nieskończoność
        if len(self.buffer) > 65536:
            self.buffer = b''

    def report(self):
        if self.sock is not None:
            self.get_logger().info(
                f"Ostatnie 10 s: {self.msg_count} wiadomości MSG")
        self.msg_count = 0


def main(args=None):
    rclpy.init(args=args)
    node = SDRRadarNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if node.sock is not None:
            node.sock.close()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()