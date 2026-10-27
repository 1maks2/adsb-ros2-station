#!/bin/bash
source /opt/ros/jazzy/setup.bash
cd /ros2_ws
# --packages-up-to = zbuduj aircraft_tracker i wszystko, od czego zależy
# (czyli najpierw aircraft_interfaces z wiadomością AircraftState)
colcon build --packages-up-to aircraft_tracker
source /ros2_ws/install/setup.bash

# Kontrola zadań: każdy program uruchomiony z "&" dostaje własną grupę procesów.
# Dzięki temu sygnał wysłany do grupy trafi też do procesów potomnych
# (np. "ros2 run" uruchamia node'a jako osobny proces).
set -m

ros2 run aircraft_tracker sdr_node &
ros2 run aircraft_tracker display_node &
ros2 run aircraft_tracker gps_node &
ros2 run aircraft_tracker power_monitor_node &
ros2 run aircraft_tracker decoder_node &

# --- Nagrywanie do rosbaga ---
# Nazwa folderu: data i godzina startu w UTC (litera Z = UTC, standard w lotnictwie).
# --max-bag-duration 600 -> nowy plik .mcap co 10 minut (przy nagłej utracie
# zasilania tracimy najwyżej końcówkę jednego pliku).
mkdir -p /ros2_ws/bags
ros2 bag record \
    -o /ros2_ws/bags/sesja_$(date -u +%Y%m%d_%H%M%SZ) \
    --max-bag-duration 600 \
    --topics /aircraft/raw /aircraft/frames /aircraft/state /gps/fix /gps/time_ref /system/undervoltage /system/cpu_temp \
    < /dev/null &
# "< /dev/null" = rosbag nie czyta klawiatury. Bez tego, przy "set -m",
# system zatrzymuje (usypia) rosbaga, bo proces w tle próbuje czytać z terminala.

# --- Poprawne zamykanie ---
# Przy "docker compose down" (np. wyłączenie przyciskiem) Docker wysyła SIGTERM
# do tego skryptu. Bez tej funkcji skrypt by go zignorował, a po kilku sekundach
# Docker zabiłby wszystko na twardo i ostatni plik nagrania byłby niedomknięty.
stop_all() {
    echo "[start_nodes] Zatrzymuję node'y i nagrywanie..."
    for pid in $(jobs -p); do
        kill -INT -- -"$pid" 2>/dev/null   # SIGINT = jak Ctrl+C, do całej grupy
    done
    wait   # czekamy, aż wszystko się zamknie (rosbag domyka plik)
    echo "[start_nodes] Zakończono."
    exit 0
}
trap stop_all SIGTERM SIGINT

# Czekamy w tle, aż przyjdzie sygnał zakończenia
wait