import rclpy
from rclpy.node import Node
from rclpy.executors import ExternalShutdownException
from sensor_msgs.msg import NavSatFix, NavSatStatus, TimeReference
import serial
from datetime import datetime, timezone


def nmea_checksum_ok(line):
    """Sprawdza sumę kontrolną zdania NMEA, np. '$GPGGA,...,*5A'.

    Suma = XOR kodów wszystkich znaków między '$' a '*',
    zapisany na końcu zdania jako dwie cyfry szesnastkowe.
    """
    if not line.startswith('$'):
        return False
    body, star, checksum = line[1:].partition('*')
    if not star or len(checksum) != 2:
        return False
    res = 0
    for ch in body:
        res ^= ord(ch)
    try:
        return res == int(checksum, 16)
    except ValueError:      # po '*' nie ma liczby szesnastkowej
        return False


class GPSNode(Node):
    def __init__(self):
        super().__init__('gps_node')
        
        # Publikowanie profesjonalnej wiadomości GPS na temat /gps/fix
        self.publisher_ = self.create_publisher(NavSatFix, '/gps/fix', 10)
        self.time_pub = self.create_publisher(TimeReference, '/gps/time_ref', 10)
        # Konfiguracja portu szeregowego
        self.port = '/dev/ttyAMA0'
        self.baudrate = 9600
        self.bad_checksums = 0   # ile zdań odrzucono przez złą sumę kontrolną
        
        try:
            self.serial_port = serial.Serial(self.port, self.baudrate, timeout=1)
            self.get_logger().info(f"Połączono z GPS na porcie {self.port}")
        except Exception as e:
            self.get_logger().error(f"Błąd otwierania portu GPS: {e}")
            return

        # Odczyt danych z portu tak szybko, jak nadchodzą
        self.timer = self.create_timer(0.1, self.read_gps)

    def parse_nmea_gga(self, line):
        try:
            parts = line.split(',')
            # Pozycja 6 to status FIX (1=GPS fix, 2=DGPS fix)
            if len(parts) >= 10 and parts[6] in ['1', '2']:
                # Szerokość DDMM.MMMMM
                raw_lat = parts[2]
                lat_dir = parts[3]
                latitude = float(raw_lat[:2]) + (float(raw_lat[2:]) / 60.0)
                if lat_dir == 'S': latitude = -latitude

                # Długość DDDMM.MMMMM
                raw_lon = parts[4]
                lon_dir = parts[5]
                longitude = float(raw_lon[:3]) + (float(raw_lon[3:]) / 60.0)
                if lon_dir == 'W': longitude = -longitude

                # Wysokość n.p.m.
                altitude = float(parts[9])
                return latitude, longitude, altitude
        except Exception:
            pass
        return None
    
    def parse_nmea_rmc(self, line):
        # Suma kontrolna jest już sprawdzona w read_gps()
        try:
            parts = line.split(',')
            # Pole 2: A = dane ważne, V = nieważne; pole 1 = godzina, pole 9 = data
            if len(parts) >= 10 and parts[2] == 'A' and parts[1] and parts[9]:
                date = str(parts[9])
                dd, mo, yy = int(date[0:2]), int(date[2:4]), 2000 + int(date[4:6])
                time = str(parts[1])
                hh, mm, ss = int(time[0:2]), int(time[2:4]), float(time[4:])

                dt = datetime(yy, mo, dd, hh, mm, int(ss), round((ss % 1) * 1e6), tzinfo=timezone.utc)
                unix_time = dt.timestamp()          # np. 1792156390.25
                sec = int(unix_time)
                nanosec = int(round((unix_time - sec) * 1e9))
                return sec, nanosec
        except Exception:
            pass
        return None

    def read_gps(self):
        if not hasattr(self, 'serial_port'):
            return
        try:
            while self.serial_port.in_waiting > 0:
                line = self.serial_port.readline().decode('ascii', errors='ignore').strip()
                stamp_system = self.get_clock().now().to_msg()   # czas Pi zaraz po odczycie

                if not line.startswith(('$GPGGA', '$GNGGA', '$GPRMC', '$GNRMC')):
                    continue   # inne zdania NMEA nas nie interesują

                # Zdanie uszkodzone w transmisji (np. zakłócenie na kablu) - odrzucamy
                if not nmea_checksum_ok(line):
                    self.bad_checksums += 1
                    self.get_logger().warn(
                        f"Zła suma kontrolna NMEA (łącznie odrzucono: {self.bad_checksums}): {line}",
                        throttle_duration_sec=60.0)
                    continue

                if line.startswith(('$GPGGA', '$GNGGA')):
                    coords = self.parse_nmea_gga(line)
                    if coords:
                        lat, lon, alt = coords
                        msg = NavSatFix()
                        msg.header.stamp = stamp_system
                        msg.header.frame_id = "gps_link"
                        msg.status.status = NavSatStatus.STATUS_FIX
                        msg.status.service = NavSatStatus.SERVICE_GPS
                        msg.latitude = lat
                        msg.longitude = lon
                        msg.altitude = alt
                        self.publisher_.publish(msg)

                elif line.startswith(('$GPRMC', '$GNRMC')):
                    time_gps = self.parse_nmea_rmc(line)
                    if time_gps:
                        msg = TimeReference()
                        msg.header.stamp = stamp_system
                        msg.time_ref.sec, msg.time_ref.nanosec = time_gps
                        msg.source = "gps"
                        self.time_pub.publish(msg)
        except Exception as e:
            self.get_logger().error(f"Błąd odczytu GPS: {e}")

def main(args=None):
    rclpy.init(args=args)
    node = GPSNode()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass   # normalne zakończenie (Ctrl+C albo SIGINT ze start_nodes.sh)
    finally:
        if hasattr(node, 'serial_port'): node.serial_port.close()
        node.destroy_node()
        # Jazzy przy SIGINT sam zamyka ROS - drugie wywołanie shutdown()
        # dawało błąd "rcl_shutdown already called". Zamykamy tylko, jeśli trzeba.
        if rclpy.ok():
            rclpy.shutdown()

if __name__ == '__main__':
    main()