import rclpy
from rclpy.node import Node
from sensor_msgs.msg import NavSatFix, NavSatStatus, TimeReference
import serial
from datetime import datetime, timezone

class GPSNode(Node):
    def __init__(self):
        super().__init__('gps_node')
        
        # Publikowanie profesjonalnej wiadomości GPS na temat /gps/fix
        self.publisher_ = self.create_publisher(NavSatFix, '/gps/fix', 10)
        self.time_pub = self.create_publisher(TimeReference, '/gps/time_ref', 10)
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
    
    def parse_nmea_rmc(self, line):
        try:
            parts = line.split(',')
            if line.startswith('$'):
                line = line[1:] 
                body, star, checksum = line.partition('*')
                res = 0
                if star and len(checksum) == 2:
                    for ch in body: 
                        res ^= ord(ch)

                    if res == int(checksum, 16) and len(parts) >= 10 and parts[2] == 'A' and parts[1] and parts[9]:
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
    except KeyboardInterrupt:
        pass
    finally:
        if hasattr(node, 'serial_port'): node.serial_port.close()
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()