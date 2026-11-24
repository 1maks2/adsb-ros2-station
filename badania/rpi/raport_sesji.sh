#!/bin/bash
# =====================================================================
# T6.2 / T6.3 - przegląd nagranych sesji na RPi.
#     bash ~/ros2_sdr/badania/rpi/raport_sesji.sh
# Dla każdej sesji: liczba plików .mcap, rozmiar, czy jest metadata.yaml
# (brak = sesja przerwana nagłym odcięciem zasilania - do naprawy skryptem
# napraw_sesje.sh), rozmiar i czas modyfikacji ostatniego pliku, czas trwania
# z metadata.yaml. Zapis CSV: ~/ros2_sdr/badania/wyniki/rpi/sesje_rpi.csv
# =====================================================================
BAGS=~/ros2_sdr/ros2_ws/bags
OUT_DIR=~/ros2_sdr/badania/wyniki/rpi
mkdir -p "$OUT_DIR"
CSV="$OUT_DIR/sesje_rpi.csv"
echo "sesja,pliki_mcap,rozmiar_MB,metadata,ostatni_plik_B,ostatni_zapis,czas_trwania_min" > "$CSV"
printf "%-26s %5s %9s %9s %12s %-20s %8s\n" SESJA PLIKI "MB" METADATA "OSTATNI [B]" "OSTATNI ZAPIS" "MIN"
for d in $(ls -d "$BAGS"/sesja_* 2>/dev/null | sort); do
    n=$(ls "$d"/*.mcap 2>/dev/null | wc -l)
    mb=$(du -sm "$d" | cut -f1)
    if [ -f "$d/metadata.yaml" ]; then
        meta=tak
        ns=$(awk '/^  duration:/{getline; print $2; exit}' "$d/metadata.yaml")
        min=$( [ -n "$ns" ] && awk -v n="$ns" 'BEGIN{printf "%.1f", n/6e10}' || echo "")
    else meta=NIE; min=""; fi
    last=$(ls -v "$d"/*.mcap 2>/dev/null | tail -1)
    lsz=$( [ -n "$last" ] && stat -c %s "$last" || echo 0)
    lmt=$( [ -n "$last" ] && date -u -d "@$(stat -c %Y "$last")" '+%Y-%m-%d %H:%M:%S' || echo "")
    printf "%-26s %5s %9s %9s %12s %-20s %8s\n" "$(basename "$d")" "$n" "$mb" "$meta" "$lsz" "$lmt" "$min"
    echo "$(basename "$d"),$n,$mb,$meta,$lsz,$lmt,$min" >> "$CSV"
done
echo
echo "Czasy w UTC (zegar RPi). Zapisano: $CSV"
echo "Sesje z METADATA = NIE naprawisz: bash ~/ros2_sdr/badania/rpi/napraw_sesje.sh <nazwa_sesji>"
