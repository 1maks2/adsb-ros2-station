#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from std_msgs.msg import String
import socket
import select

class SDRRadarNode(Node):
    def __init__(self):
        super().__init__('sdr_radar_node')
        
        # Publikowanie danych samolotów jako zwykły String na temat /aircraft/raw
        self.publisher_ = self.create_publisher(String, '/aircraft/raw', 10)
        
        # Połączenie do dump1090 na port strumieniowania danych (30003)
        self.host = '172.17.0.1'
        self.port = 30003
        
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((self.host, self.port))
            self.sock.setblocking(False)  # Tryb nieblokujący
            self.get_logger().info(f"Połączono z radarem dump1090 na {self.host}:{self.port}")
        except Exception as e:
            self.get_logger().error(f"Nie można połączyć z dump1090: {e}")
            return

        # Timer sprawdzający bufor sieciowy co 50ms (samoloty nadają gęsto!)
        self.timer = self.create_timer(0.05, self.read_radar)

    def read_radar(self):
        if not hasattr(self, 'sock'): return
        
        # Sprawdzamy czy w gnieździe czekają dane do odczytu
        ready_to_read, _, _ = select.select([self.sock], [], [], 0.0)
        
        if ready_to_read:
            try:
                data = self.sock.recv(4096).decode('utf-8', errors='ignore')
                lines = data.strip().split('\r\n')
                
                for line in lines:
                    if line.startswith('MSG'): # Interesują nas tylko komunikaty transmisyjne ES
                        msg = String()
                        msg.data = line
                        self.publisher_.publish(msg)
                        
                        # Logujemy skróconą informację, żeby nie zapchać terminala
                        parts = line.split(',')
                        if len(parts) > 4:
                            icao_hex = parts[4]  # Unikalny ID samolotu
                            self.get_logger().info(f"Przechwycono pakiet z samolotu ICAO: {icao_hex}")
            except Exception as e:
                self.get_logger().error(f"Błąd odczytu z sieci: {e}")

def main(args=None):
    rclpy.init(args=args)
    node = SDRRadarNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if hasattr(node, 'sock'): node.sock.close()
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()