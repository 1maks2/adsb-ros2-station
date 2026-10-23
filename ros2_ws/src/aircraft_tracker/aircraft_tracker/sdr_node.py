#!/usr/bin/env python3
import socket

import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class TcpLineClient:
    """Jedno połączenie TCP z dump1090, które zwraca CAŁE linie tekstu.

    Dane z sieci przychodzą kawałkami - kawałek może się skończyć w połowie linii.
    Niepełna końcówka czeka w buforze, aż dojdzie reszta.
    """

    def __init__(self, node, label, host, port):
        self.node = node
        self.label = label      # nazwa do logów, np. "SBS"
        self.host = host
        self.port = port
        self.sock = None
        self.buffer = b''
        self.count = 0          # ile linii opublikowano od ostatniej statystyki

    def connected(self):
        return self.sock is not None

    def ensure_connected(self):
        if self.sock is not None:
            return
        try:
            s = socket.create_connection((self.host, self.port), timeout=2.0)
            s.setblocking(False)  # recv() nie czeka na dane
            self.sock = s
            self.buffer = b''
            self.node.get_logger().info(
                f"[{self.label}] Połączono z dump1090 na {self.host}:{self.port}")
        except OSError as e:
            self.node.get_logger().warn(
                f"[{self.label}] Brak połączenia z dump1090 ({e}), ponawiam próby...",
                throttle_duration_sec=30.0)

    def disconnect(self, reason):
        self.node.get_logger().warn(f"[{self.label}] Rozłączono z dump1090: {reason}")
        try:
            self.sock.close()
        except OSError:
            pass
        self.sock = None
        self.buffer = b''

    def read_lines(self):
        """Zwraca listę pełnych linii (bez \\r\\n), które przyszły od ostatniego odczytu."""
        if self.sock is None:
            return []
        try:
            data = self.sock.recv(65536)
        except BlockingIOError:
            return []               # brak nowych danych - normalna sytuacja
        except OSError as e:
            self.disconnect(f"błąd odczytu: {e}")
            return []
        if not data:
            self.disconnect("dump1090 zamknął połączenie")
            return []

        self.buffer += data
        *complete, self.buffer = self.buffer.split(b'\n')
        if len(self.buffer) > 65536:  # zabezpieczenie przed śmieciami bez końca linii
            self.buffer = b''
        return [raw.decode('ascii', errors='ignore').strip() for raw in complete]

    def close(self):
        if self.sock is not None:
            self.sock.close()


class SDRRadarNode(Node):
    def __init__(self):
        super().__init__('sdr_radar_node')

        # /aircraft/raw    - linie SBS (port 30003): dane już rozkodowane przez dump1090
        # /aircraft/frames - surowe ramki Mode S/ADS-B w formacie AVR (port 30002),
        #                    np. "*8D4840D6202CC371C32CE0576098;" - do własnego dekodowania później
        self.sbs_pub = self.create_publisher(String, '/aircraft/raw', 10)
        self.frames_pub = self.create_publisher(String, '/aircraft/frames', 10)

        # network_mode: host -> dump1090 na tym samym RPi jest pod 127.0.0.1
        self.sbs = TcpLineClient(self, 'SBS', '127.0.0.1', 30003)
        self.frames = TcpLineClient(self, 'RAW', '127.0.0.1', 30002)

        self.create_timer(0.05, self.read_all)        # odczyt danych co 50 ms
        self.create_timer(2.0, self.ensure_connected)  # ponowne łączenie co 2 s
        self.create_timer(10.0, self.report)           # statystyka co 10 s

        self.ensure_connected()

    def ensure_connected(self):
        self.sbs.ensure_connected()
        self.frames.ensure_connected()

    def read_all(self):
        for line in self.sbs.read_lines():
            if line.startswith('MSG'):
                msg = String()
                msg.data = line
                self.sbs_pub.publish(msg)
                self.sbs.count += 1

        for line in self.frames.read_lines():
            # Poprawna ramka AVR zaczyna się od '*' i kończy ';' - zapisujemy ją bez zmian
            if line.startswith('*') and line.endswith(';'):
                msg = String()
                msg.data = line
                self.frames_pub.publish(msg)
                self.frames.count += 1

    def report(self):
        parts = []
        if self.sbs.connected():
            parts.append(f"{self.sbs.count} wiadomości MSG")
        if self.frames.connected():
            parts.append(f"{self.frames.count} surowych ramek")
        if parts:
            self.get_logger().info("Ostatnie 10 s: " + ", ".join(parts))
        self.sbs.count = 0
        self.frames.count = 0


def main(args=None):
    rclpy.init(args=args)
    node = SDRRadarNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.sbs.close()
        node.frames.close()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()