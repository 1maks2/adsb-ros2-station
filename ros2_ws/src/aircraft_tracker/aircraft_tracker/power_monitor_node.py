#!/usr/bin/env python3
import glob
import os

import rclpy
from rclpy.node import Node
from std_msgs.msg import Bool
from sensor_msgs.msg import Temperature


def find_hwmon(name):
    """Szuka folderu czujnika w /sys/class/hwmon po jego nazwie
    (numery hwmon0/hwmon1 mogą się zmienić po restarcie)."""
    for d in sorted(glob.glob('/sys/class/hwmon/hwmon*')):
        try:
            with open(os.path.join(d, 'name')) as f:
                if f.read().strip() == name:
                    return d
        except OSError:
            pass
    return None


def read_int(path):
    with open(path) as f:
        return int(f.read().strip())


class PowerMonitorNode(Node):
    def __init__(self):
        super().__init__('power_monitor_node')

        self.uv_pub = self.create_publisher(Bool, '/system/undervoltage', 10)
        self.temp_pub = self.create_publisher(Temperature, '/system/cpu_temp', 10)

        volt_dir = find_hwmon('rpi_volt')
        temp_dir = find_hwmon('cpu_thermal')
        self.uv_file = os.path.join(volt_dir, 'in0_lcrit_alarm') if volt_dir else None
        self.temp_file = os.path.join(temp_dir, 'temp1_input') if temp_dir else None

        if self.uv_file is None:
            self.get_logger().error("Nie znaleziono czujnika napięcia (rpi_volt)")
        if self.temp_file is None:
            self.get_logger().error("Nie znaleziono czujnika temperatury (cpu_thermal)")

        self.last_uv = None    # poprzedni stan alarmu (do wykrywania zmian)
        self.uv_events = 0     # ile razy od startu pojawił się alarm

        # Odczyt czujników co 1 s
        self.create_timer(1.0, self.check)
        self.get_logger().info("Power monitor uruchomiony")

    def check(self):
        # --- Alarm zbyt niskiego napięcia ---
        if self.uv_file:
            try:
                uv = read_int(self.uv_file) == 1
                msg = Bool()
                msg.data = uv
                self.uv_pub.publish(msg)

                # Wpis w logach tylko przy ZMIANIE stanu, żeby nie zaśmiecać logów
                if uv and self.last_uv is not True:
                    self.uv_events += 1
                    self.get_logger().warn(
                        f"NISKIE NAPIĘCIE ZASILANIA! (zdarzenie nr {self.uv_events})")
                elif not uv and self.last_uv is True:
                    self.get_logger().info("Napięcie zasilania wróciło do normy")
                self.last_uv = uv
            except (OSError, ValueError) as e:
                self.get_logger().error(f"Błąd odczytu napięcia: {e}",
                                        throttle_duration_sec=60.0)

        # --- Temperatura procesora ---
        if self.temp_file:
            try:
                temp_c = read_int(self.temp_file) / 1000.0  # plik podaje tysięczne °C
                msg = Temperature()
                msg.header.stamp = self.get_clock().now().to_msg()
                msg.header.frame_id = 'cpu'
                msg.temperature = temp_c
                msg.variance = 0.0  # 0 = nieznana wariancja
                self.temp_pub.publish(msg)
            except (OSError, ValueError) as e:
                self.get_logger().error(f"Błąd odczytu temperatury: {e}",
                                        throttle_duration_sec=60.0)


def main(args=None):
    rclpy.init(args=args)
    node = PowerMonitorNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()