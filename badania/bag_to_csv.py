#!/usr/bin/env python3
"""Eksport sesji rosbag2 (MCAP) do plików CSV - bez ROS 2.

Wejście:  folder sesji, np. dane/sesja_20261124_123000Z  (skopiowany z RPi przez scp)
Wyjście:  folder z plikami CSV (kropka dziesiętna, czasy w sekundach od 1970 UTC):
  ramki.csv        t_log, ramka                 (/aircraft/frames, surowe AVR)
  sbs.csv          t_log, typ, icao, znak, alt_ft, gs_kt, kurs, lat, lon, vr_fpm
  stan.csv         t_log, stamp, pos_stamp, time_source, clock_offset, icao, znak,
                   lat, lon, jakosc, alt_m, typ_alt, alt_baro_m, gs, kurs, vr,
                   odl_pozioma, odl_skosna, azymut, elewacja      (/aircraft/state)
  gps_fix.csv      t_log, stamp, lat, lon, alt
  czas_gps.csv     t_log, stamp, time_ref     (stamp = zegar RPi, time_ref = UTC z GPS)
  temp_cpu.csv     t_log, stamp, temp
  napiecie.csv     t_log, niskie (0/1)
  info.json        pliki, rozmiar, liczba wiadomości na temat, czas trwania

t_log = czas zapisu wiadomości przez rosbag2 (zegar RPi, bez korekty).

UWAGA: gps_fix.csv i stan.csv zawierają lokalizację stacji - nie wrzucaj ich do
publicznego repozytorium (folder wyniki/ jest w .gitignore).

Uruchomienie:
  python3 bag_to_csv.py dane/sesja_20261124_123000Z wyniki/R-02/dane
"""
import argparse
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import bagio, common  # noqa: E402

COLS = {
    'ramki': ['t_log', 'ramka'],
    'sbs': ['t_log', 'typ', 'icao', 'znak', 'alt_ft', 'gs_kt', 'kurs', 'lat', 'lon', 'vr_fpm'],
    'stan': ['t_log', 'stamp', 'pos_stamp', 'time_source', 'clock_offset', 'icao', 'znak',
             'lat', 'lon', 'jakosc', 'alt_m', 'typ_alt', 'alt_baro_m', 'gs', 'kurs', 'vr',
             'odl_pozioma', 'odl_skosna', 'azymut', 'elewacja'],
    'gps_fix': ['t_log', 'stamp', 'lat', 'lon', 'alt'],
    'czas_gps': ['t_log', 'stamp', 'time_ref'],
    'temp_cpu': ['t_log', 'stamp', 'temp'],
    'napiecie': ['t_log', 'niskie'],
}
FLOAT_COLS = {'t_log', 'stamp', 'pos_stamp', 'clock_offset', 'alt_ft', 'gs_kt', 'kurs', 'lat',
              'lon', 'vr_fpm', 'alt_m', 'alt_baro_m', 'gs', 'vr', 'odl_pozioma', 'odl_skosna',
              'azymut', 'elewacja', 'alt', 'time_ref', 'temp'}
INT_COLS = {'time_source', 'jakosc', 'typ_alt', 'niskie', 'typ'}


def _f(s):
    try:
        return float(s) if s not in ('', None) else math.nan
    except ValueError:
        return math.nan


def parse_sbs(line):
    """Linia SBS (BaseStation) z dump1090 -> słownik; pola wg project_context."""
    p = line.split(',')
    if len(p) < 16 or p[0] != 'MSG':
        return None
    return {'typ': int(p[1]) if p[1].isdigit() else -1, 'icao': p[4].strip().upper(),
            'znak': p[10].strip(), 'alt_ft': _f(p[11]), 'gs_kt': _f(p[12]),
            'kurs': _f(p[13]), 'lat': _f(p[14]), 'lon': _f(p[15]),
            'vr_fpm': _f(p[16]) if len(p) > 16 else math.nan}


def export(session_dir, out_dir=None, warn=print):
    """Czyta sesję i zwraca słownik list wierszy; opcjonalnie zapisuje CSV."""
    d = {k: [] for k in COLS}
    counts = {}
    t_min, t_max = math.inf, -math.inf
    for topic, t, m in bagio.iter_messages(session_dir, warn=warn):
        counts[topic] = counts.get(topic, 0) + 1
        t_min, t_max = min(t_min, t), max(t_max, t)
        if topic == '/aircraft/frames':
            d['ramki'].append({'t_log': t, 'ramka': m.data.strip()})
        elif topic == '/aircraft/raw':
            r = parse_sbs(m.data)
            if r:
                r['t_log'] = t
                d['sbs'].append(r)
        elif topic == '/aircraft/state':
            d['stan'].append({
                't_log': t, 'stamp': bagio.t_of(m.header.stamp),
                'pos_stamp': bagio.t_of(m.position_stamp),
                'time_source': getattr(m, 'time_source', -1),
                'clock_offset': getattr(m, 'clock_offset', math.nan),
                'icao': m.icao, 'znak': m.callsign, 'lat': m.latitude, 'lon': m.longitude,
                'jakosc': m.position_quality, 'alt_m': m.altitude, 'typ_alt': m.altitude_type,
                'alt_baro_m': m.altitude_baro, 'gs': m.ground_speed, 'kurs': m.track,
                'vr': m.vertical_rate, 'odl_pozioma': m.ground_distance,
                'odl_skosna': m.slant_distance, 'azymut': m.azimuth, 'elewacja': m.elevation})
        elif topic == '/gps/fix':
            d['gps_fix'].append({'t_log': t, 'stamp': bagio.t_of(m.header.stamp),
                                 'lat': m.latitude, 'lon': m.longitude, 'alt': m.altitude})
        elif topic == '/gps/time_ref':
            d['czas_gps'].append({'t_log': t, 'stamp': bagio.t_of(m.header.stamp),
                                  'time_ref': bagio.t_of(m.time_ref)})
        elif topic == '/system/cpu_temp':
            d['temp_cpu'].append({'t_log': t, 'stamp': bagio.t_of(m.header.stamp),
                                  'temp': m.temperature})
        elif topic == '/system/undervoltage':
            d['napiecie'].append({'t_log': t, 'niskie': int(bool(m.data))})
    for k in d:
        d[k].sort(key=lambda r: r['t_log'])
    info = bagio.session_info(session_dir)
    info.update({'wiadomosci': counts,
                 't_pierwsza': t_min if t_min < math.inf else math.nan,
                 't_ostatnia': t_max if t_max > -math.inf else math.nan})
    info['czas_trwania_s'] = info['t_ostatnia'] - info['t_pierwsza']
    d['info'] = info
    if out_dir:
        save(d, out_dir)
    return d


def save(d, out_dir):
    common.ensure_dir(out_dir)
    for k, cols in COLS.items():
        common.write_csv(os.path.join(out_dir, k + '.csv'), d[k], cols)
    common.write_json(os.path.join(out_dir, 'info.json'), d['info'])


def load(out_dir):
    """Wczytuje CSV zapisane przez save() (z konwersją typów)."""
    import json
    d = {}
    for k in COLS:
        path = os.path.join(out_dir, k + '.csv')
        rows = common.read_csv(path) if os.path.exists(path) else []
        for r in rows:
            for c in r:
                if c in FLOAT_COLS:
                    r[c] = _f(r[c])
                elif c in INT_COLS:
                    r[c] = int(float(r[c])) if r[c] not in ('', None) else -1
        d[k] = rows
    with open(os.path.join(out_dir, 'info.json'), encoding='utf-8') as f:
        d['info'] = json.load(f)
    return d


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('sesja', help='folder sesji rosbag2 (z plikami .mcap)')
    ap.add_argument('wyjscie', help='folder na pliki CSV')
    a = ap.parse_args()
    d = export(a.sesja, a.wyjscie)
    print(f"Zapisano CSV do {a.wyjscie}")
    for t, n in sorted(d['info']['wiadomosci'].items()):
        print(f'  {t:24s} {n:9d}')


if __name__ == '__main__':
    main()
