#!/usr/bin/env python3
"""Monitor obciążenia RPi podczas pracy stacji (T3.2, T7.1; wskaźniki W8, W10).

Uruchamiać NA RASPBERRY PI (system hosta, nie w kontenerze) - tylko biblioteka
standardowa Pythona. Co --okres sekund zapisuje do CSV:
  t_utc, cpu_calk_proc (wszystkie rdzenie = 100 %), temp_C, ram_MB, obc_1min,
  oraz zużycie CPU każdej grupy procesów w % JEDNEGO rdzenia:
  dump1090, sdr_node, decoder_node, display_node, gps_node, power_monitor_node, rosbag2.

Przykład (60 minut, co 5 s):
  python3 ~/ros2_sdr/badania/rpi/monitor_cpu.py --minuty 60 \\
      --wyjscie ~/ros2_sdr/badania/wyniki/rpi/cpu_$(date -u +%Y%m%d_%H%M)Z.csv
Wykresy i tabelę robi potem wykres_obciazenia.py (na laptopie).
"""
import argparse
import csv
import os
import time

GRUPY = [('dump1090', 'dump1090'), ('sdr_node', 'sdr_node'), ('decoder_node', 'decoder_node'),
         ('display_node', 'display_node'), ('gps_node', 'gps_node'),
         ('power_monitor_node', 'power_monitor_node'), ('rosbag2', 'bag record')]
TCK = os.sysconf('SC_CLK_TCK')


def proc_times():
    """{grupa: suma utime+stime [tiki]} dla procesów pasujących do wzorców."""
    out = {g: 0 for g, _ in GRUPY}
    for pid in os.listdir('/proc'):
        if not pid.isdigit():
            continue
        try:
            with open(f'/proc/{pid}/cmdline', 'rb') as f:
                cmd = f.read().replace(b'\0', b' ').decode(errors='ignore')
            if not cmd or 'ros2 run' in cmd:        # wrapper "ros2 run" pomijamy
                continue
            for g, pat in GRUPY:
                if pat in cmd:
                    with open(f'/proc/{pid}/stat') as f:
                        rest = f.read().rsplit(')', 1)[1].split()
                    out[g] += int(rest[11]) + int(rest[12])   # pola 14 i 15: utime, stime
                    break
        except (FileNotFoundError, ProcessLookupError, PermissionError, IndexError):
            continue
    return out


def cpu_total():
    with open('/proc/stat') as f:
        v = [int(x) for x in f.readline().split()[1:]]
    idle = v[3] + v[4]
    return sum(v), idle


def temp_c():
    try:
        with open('/sys/class/thermal/thermal_zone0/temp') as f:
            return int(f.read()) / 1000.0
    except OSError:
        return float('nan')


def ram_mb():
    m = {}
    with open('/proc/meminfo') as f:
        for line in f:
            k, v = line.split(':')
            m[k] = int(v.split()[0])
    return (m['MemTotal'] - m['MemAvailable']) / 1024.0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--minuty', type=float, default=60.0)
    ap.add_argument('--okres', type=float, default=5.0)
    ap.add_argument('--wyjscie', required=True)
    a = ap.parse_args()
    os.makedirs(os.path.dirname(os.path.abspath(a.wyjscie)), exist_ok=True)
    cols = ['t_utc', 'cpu_calk_proc', 'temp_C', 'ram_MB', 'obc_1min'] + [g for g, _ in GRUPY]
    f = open(a.wyjscie, 'w', newline='')
    w = csv.writer(f)
    w.writerow(cols)
    p_prev, (tot_prev, idle_prev), t_prev = proc_times(), cpu_total(), time.time()
    t_end = t_prev + a.minuty * 60
    print(f'Zapis do {a.wyjscie} (Ctrl+C = koniec)')
    try:
        while time.time() < t_end:
            time.sleep(a.okres)
            p, (tot, idle), t = proc_times(), cpu_total(), time.time()
            dt = t - t_prev
            row = [f'{t:.1f}', f'{100 * (1 - (idle - idle_prev) / max(tot - tot_prev, 1)):.1f}',
                   f'{temp_c():.1f}', f'{ram_mb():.0f}', f'{os.getloadavg()[0]:.2f}']
            row += [f'{100 * max(p[g] - p_prev.get(g, 0), 0) / TCK / dt:.2f}' for g, _ in GRUPY]
            w.writerow(row)
            f.flush()
            print(f"\r{time.strftime('%H:%M:%S')} CPU {row[1]} %  temp {row[2]} °C  "
                  f"decoder {row[cols.index('decoder_node')]} %   ", end='')
            p_prev, tot_prev, idle_prev, t_prev = p, tot, idle, t
    except KeyboardInterrupt:
        pass
    f.close()
    print('\nKoniec.')


if __name__ == '__main__':
    main()
