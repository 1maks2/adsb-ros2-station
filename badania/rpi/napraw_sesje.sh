#!/bin/bash
# =====================================================================
# T6.2 - odzyskanie sesji przerwanej nagłym odcięciem zasilania.
#     bash ~/ros2_sdr/badania/rpi/napraw_sesje.sh sesja_20261019_182318Z
# Procedura (sprawdzona 2026-10-19): ostatni, niedomknięty plik .mcap trafia do
# /ros2_ws/bags/uszkodzone/<sesja>/, potem "ros2 bag reindex" odtwarza
# metadata.yaml z kompletnych plików, a "ros2 bag info" pokazuje wynik.
# Polecenia wykonywane są w kontenerze (pliki nagrań należą do roota).
# =====================================================================
set -e
S=${1:?Podaj nazwę sesji, np. sesja_20261019_182318Z}
KONT=ros2_jazzy_lpa
D=/ros2_ws/bags/$S
ROS="source /opt/ros/jazzy/setup.bash; source /ros2_ws/install/setup.bash;"
docker exec "$KONT" test -d "$D" || { echo "Brak sesji $D"; exit 1; }
if docker exec "$KONT" test -f "$D/metadata.yaml"; then
    echo "Sesja ma już metadata.yaml - nie wymaga naprawy."; exit 0; fi
echo "Pliki sesji:"; docker exec "$KONT" ls -l "$D"
LAST=$(docker exec "$KONT" bash -c "ls -v $D/*.mcap | tail -1")
echo; read -r -p "Przenieść ostatni plik $(basename "$LAST") do uszkodzone/ i odbudować metadata.yaml? [t/N] " odp
[ "$odp" = "t" ] || { echo "Przerwano."; exit 0; }
docker exec "$KONT" bash -c "mkdir -p /ros2_ws/bags/uszkodzone/$S && mv '$LAST' /ros2_ws/bags/uszkodzone/$S/"
docker exec "$KONT" bash -c "$ROS ros2 bag reindex $D -s mcap && ros2 bag info $D"
echo "Gotowe. Przeniesiony plik: /ros2_ws/bags/uszkodzone/$S/"
