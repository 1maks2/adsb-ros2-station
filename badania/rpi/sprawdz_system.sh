#!/bin/bash
# =====================================================================
# T3.1 - test uruchomienia stacji (integracja grafu ROS 2).
# Uruchamiać NA RPi (przez SSH), gdy stacja działa co najmniej 2 minuty:
#     bash ~/ros2_sdr/badania/rpi/sprawdz_system.sh
# Sprawdza: usługi systemd, kontener, 5 węzłów + rosbag2_recorder,
# 7 tematów, częstotliwości tematów (ros2 topic hz, po 12 s), stan rekordera.
# Raport: ~/ros2_sdr/badania/wyniki/rpi/T3_1_<data>Z.txt (+ wynik ZALICZONY/NIE)
# =====================================================================
set -u
KONT=ros2_jazzy_lpa
OUT_DIR=~/ros2_sdr/badania/wyniki/rpi
mkdir -p "$OUT_DIR"
OUT="$OUT_DIR/T3_1_$(date -u +%Y%m%d_%H%M%S)Z.txt"
ROS="source /opt/ros/jazzy/setup.bash; source /ros2_ws/install/setup.bash;"
BLEDY=0

log() { echo "$*" | tee -a "$OUT"; }
ok()  { log "  [OK]  $*"; }
zle() { log "  [BŁĄD] $*"; BLEDY=$((BLEDY+1)); }

log "=== T3.1 test uruchomienia stacji - $(date -u '+%Y-%m-%d %H:%M:%S') UTC ==="
log "Commit repozytorium: $(git -C ~/ros2_sdr log -1 --format='%h %ad' --date=iso 2>/dev/null)"

log "--- Usługi systemd ---"
for s in dump1090 ros2-adsb power-button; do
    st=$(systemctl is-active "$s.service")
    [ "$st" = active ] && ok "$s.service: $st" || zle "$s.service: $st"
done

log "--- Kontener ---"
if docker ps --format '{{.Names}}' | grep -qx "$KONT"; then ok "kontener $KONT działa"; else zle "brak kontenera $KONT"; exit 1; fi

log "--- Węzły ROS 2 ---"
WEZLY=$(docker exec "$KONT" bash -c "$ROS ros2 node list" 2>/dev/null)
echo "$WEZLY" | sed 's/^/      /' | tee -a "$OUT"
for n in sdr_radar_node gps_node power_monitor_node decoder_node display_node rosbag2_recorder; do
    echo "$WEZLY" | grep -q "/$n\$" && ok "węzeł /$n" || zle "brak węzła /$n"
done

log "--- Rekorder (stan procesu: S = działa, T = zatrzymany) ---"
docker exec "$KONT" ps -e -o stat,cmd | grep "bag record" | grep -v grep | tee -a "$OUT"
docker exec "$KONT" ps -e -o stat,cmd | grep "bag record" | grep -v grep | grep -q "^S" \
    && ok "rosbag2 nagrywa" || zle "rosbag2 nie działa poprawnie"
SESJA=$(docker exec "$KONT" bash -c "ls -td /ros2_ws/bags/sesja_* 2>/dev/null | head -1")
log "  bieżąca sesja: $SESJA"

log "--- Częstotliwości tematów (12 s na temat, ok. 1,5 min) ---"
for t in /aircraft/frames /aircraft/raw /aircraft/state /gps/fix /gps/time_ref /system/cpu_temp /system/undervoltage; do
    hz=$(docker exec "$KONT" bash -c "$ROS timeout 12 ros2 topic hz $t 2>/dev/null" | grep "average rate" | tail -1 | awk '{print $3}')
    if [ -n "$hz" ]; then ok "$t: $hz Hz"; else
        case $t in
            /gps/*)        zle "$t: brak (GPS bez fixa?)";;
            /aircraft/*)   zle "$t: brak (brak ruchu lotniczego albo problem z dump1090)";;
            *)             zle "$t: brak";;
        esac
    fi
done

log "--- Ostatnie statystyki dekodera ---"
journalctl -u ros2-adsb.service -n 200 --no-pager | grep "Ostatnie 10 s" | tail -3 | sed 's/^/      /' | tee -a "$OUT"

log ""
if [ "$BLEDY" -eq 0 ]; then log "WYNIK T3.1: ZALICZONY"; else log "WYNIK T3.1: NIEZALICZONY ($BLEDY błędów)"; fi
log "Raport zapisano: $OUT"
