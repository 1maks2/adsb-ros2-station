#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from std_msgs.msg import String
from sensor_msgs.msg import NavSatFix
from luma.core.interface.serial import spi
from luma.lcd.device import ili9341
from luma.core.render import canvas
from PIL import ImageFont

import time
import math

def haversine(lat1, lon1, lat2, lon2):
    R = 6371000.0  # promień Ziemi w metrach
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return 2 * R * math.asin(math.sqrt(a)) 
    
class DisplayNode(Node):
    def __init__(self):
        super().__init__('display_node')
        self.font_big = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)
        serial = spi(port=0, device=0, gpio_DC=24, gpio_RST=25)
        self.device = ili9341(serial, width=320, height=240)

        self.aircraft = {}
        self.gps = None
        self.create_subscription(String, '/aircraft/raw', self.msg_callback, 10)
        self.create_subscription(NavSatFix, '/gps/fix', self.gps_callback, 10)
        self.create_timer(1.0, self.render)

        self.get_logger().info("Display node uruchomiony!")

    def gps_callback(self,msg):
       self.gps = (msg.latitude, msg.longitude, msg.altitude, "N" if msg.latitude > 0 else "S", "E" if msg.longitude > 0 else "W" )
        
    
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

        now = time.time()
        self.aircraft = {k: v for k, v in self.aircraft.items()
                        if now - v['last_seen'] < 60}


        
    def render(self):
        with canvas(self.device) as draw:
            draw.rectangle(self.device.bounding_box, fill="black")

            if self.gps:
                lat, lon, alt, lat_sign, lon_sign = self.gps
                draw.text((160, 220), f"Pozycja GPS {lat:.4f}{lat_sign} {lon:.4f}{lon_sign} {alt:.0f}m", fill="green", font=self.font_big, anchor="mm")
            else:
                draw.text((160, 220), "GPS: brak fixa", fill="red")
        
            draw.text((5, 5),   "ADS-B RADAR",            fill="yellow")
            draw.text((200, 5), f"Szt: {len(self.aircraft)}", fill="cyan")
            draw.line([(0, 18), (320, 18)], fill="white")

            draw.text((5, 22),   "ICAO",  fill="white")
            draw.text((70, 22),  "CALL",  fill="white")
            draw.text((175, 22), "ALT",   fill="white", anchor="ra")
            draw.text((245, 22), "SPD",   fill="white", anchor="ra")
            draw.text((315, 22), "DIST",  fill="white", anchor="ra")

            y = 38
            for icao, data in list(self.aircraft.items())[:9]:
                if self.gps and data['lat'] is not None and data['lon'] is not None:
                    my_lat, my_lon, my_alt = self.gps[0], self.gps[1], self.gps[2]
                    ground_m = haversine(my_lat, my_lon, data['lat'], data['lon'])
                    try:
                        ac_alt_m = float(data['altitude']) * 0.3048
                    except (ValueError, TypeError):
                        ac_alt_m = my_alt
                    dalt = ac_alt_m - my_alt
                    dist_km = math.sqrt(ground_m**2 + dalt**2) / 1000.0
                    dist_str = f"{dist_km:.1f}km"
                else:
                    dist_str = "---"
                    
                    
                draw.text((5, y),   icao[:6],                      fill="lime")
                draw.text((70, y),  data['callsign'][:6] or '---', fill="white")
                draw.text((175, y), data['altitude'][:5] or '---', fill="cyan",    anchor="ra")
                draw.text((245, y), data['speed'][:4] or '---',    fill="orange",  anchor="ra")
                draw.text((315, y), dist_str,                      fill="magenta", anchor="ra")
                y += 20

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
