import rclpy
from rclpy.node import Node
from sensor_msgs.msg import NavSatFix, NavSatStatus
import serial

class GPSNode(Node):
    def __init__(self):
        super().__init__('gps_node')
        
        # Publikowanie profesjonalnej wiadomości GPS na temat /gps/fix
        self.publisher_ = self.create_publisher(NavSatFix, '/gps/fix', 10)
        
        # Konfiguracja portu szeregowego
        self.port = '/dev/ttyAMA0'
        self.baudrate = 9600
        
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

    def read_gps(self):
        if hasattr(self, 'serial_port') and self.serial_port.in_waiting > 0:
            try:
                line = self.serial_port.readline().decode('ascii', errors='ignore').strip()
                if line.startswith('$GPGGA'):
                    coords = self.parse_nmea_gga(line)
                    if coords:
                        lat, lon, alt = coords
                        
                        # Tworzenie wiadomości ROS 2
                        msg = NavSatFix()
                        msg.header.stamp = self.get_clock().now().to_msg()
                        msg.header.frame_id = "gps_link"
                        
                        msg.status.status = NavSatStatus.STATUS_FIX
                        msg.status.service = NavSatStatus.SERVICE_GPS
                        
                        msg.latitude = lat
                        msg.longitude = lon
                        msg.altitude = alt
                        
                        self.publisher_.publish(msg)
                        self.get_logger().info(f"Opublikowano pozycję: Lat={lat:.6f}, Lon={lon:.6f}, Alt={alt}m")
            except Exception as e:
                self.get_logger().error(f"Błąd portu: {e}")

def main(args=None):
    rclpy.init(args=args)
    node = GPSNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if hasattr(node, 'serial_port'): node.serial_port.close()
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()