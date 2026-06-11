#!/bin/bash
source /opt/ros/jazzy/setup.bash
cd /ros2_ws
colcon build --packages-select aircraft_tracker
source /ros2_ws/install/setup.bash
ros2 run aircraft_tracker sdr_node &
ros2 run aircraft_tracker display_node
