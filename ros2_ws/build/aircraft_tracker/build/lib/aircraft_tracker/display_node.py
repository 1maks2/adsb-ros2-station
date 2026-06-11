#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from std_msgs.msg import String
from luma.core.interface.serial import spi
from luma.lcd.device import ili9341
from luma.core.render import canvas
import time

class DisplayNode(Node):
    def __init__(self):
        super().__init__('display_node')

        serial = spi(port=0, device=0, gpio_DC=24, gpio_RST=25)
        self.device = ili9341(serial, width=320, height=240)

        self.aircraft = {}

        self.create_subscription(String, '/aircraft/raw', self.msg_callback, 10)
        self.create_timer(1.0, self.render)

        self.get_logger().info("Display node uruchomiony!")

    def msg_callback(self, msg):
        parts = msg.data.split(',')
        if len(parts) < 15:
            return

        icao = parts[4].strip()
        if not icao:
            return

        if icao not in self.aircraft:
            self.aircraft[icao] = {
                'callsign': '',
                'altitude': '',
                'speed': '',
                'last_seen': time.time()
            }

        if parts[10].strip(): self.aircraft[icao]['callsign'] = parts[10].strip()
        if parts[11].strip(): self.aircraft[icao]['altitude'] = parts[11].strip()
        if parts[12].strip(): self.aircraft[icao]['speed'] = parts[12].strip()
        self.aircraft[icao]['last_seen'] = time.time()

        now = time.time()
        self.aircraft = {k: v for k, v in self.aircraft.items()
                        if now - v['last_seen'] < 60}

    def render(self):
        with canvas(self.device) as draw:
            draw.rectangle(self.device.bounding_box, fill="black")

            draw.text((5, 5),   "ADS-B RADAR",            fill="yellow")
            draw.text((200, 5), f"Szt: {len(self.aircraft)}", fill="cyan")
            draw.line([(0, 18), (320, 18)], fill="white")

            draw.text((5, 22),   "ICAO",  fill="white")
            draw.text((70, 22),  "CALL",  fill="white")
            draw.text((160, 22), "ALT",   fill="white")
            draw.text((240, 22), "SPD",   fill="white")
            draw.line([(0, 34), (320, 34)], fill="gray")

            y = 38
            for icao, data in list(self.aircraft.items())[:9]:
                draw.text((5, y),   icao[:6],                      fill="lime")
                draw.text((70, y),  data['callsign'][:6] or '---', fill="white")
                draw.text((160, y), data['altitude'][:6] or '---', fill="cyan")
                draw.text((240, y), data['speed'][:5] or '---',    fill="orange")
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
