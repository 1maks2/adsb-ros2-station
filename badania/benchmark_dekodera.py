#!/usr/bin/env python3
"""Pomiar czasu przetwarzania jednej ramki przez dekoder (T3.2, wskaźnik W8).

Mierzy dokładnie to, co robi decoder_node na każdą ramkę: AdsbDecoder.process()
i - jeśli stan statku się zmienił - AdsbDecoder.state() (geometria ENU).
Działa bez ROS i bez matplotlib (tylko biblioteka standardowa + pyModeS), więc
można go uruchomić NA RASPBERRY PI w obrazie Dockera stacji:

  docker run --rm --user $(id -u):$(id -g) -v ~/ros2_sdr:/repo ros2_sdr-ros2client \\
      python3 /repo/badania/benchmark_dekodera.py --syntetyczne 10 \\
      --wyjscie /repo/badania/wyniki/rpi/benchmark_rpi.json

(uruchomiony obok działającej stacji = pomiar w warunkach rzeczywistego obciążenia)

Źródło ramek:
  --syntetyczne N   N minut ruchu syntetycznego (20 statków + krótkie ramki Mode S),
  --ramki PLIK      ramki z nagrania: ramki.csv z bag_to_csv.py (kolumny t_log, ramka).

Warunek czasu rzeczywistego: czas przetwarzania << odstęp między ramkami
w szczycie ruchu (szczyt liczony z nagrania albo podany --szczyt [ramki/s]).
"""
import argparse
import csv
import os
import platform
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import common, cpr_gen  # noqa: E402
from lib.common import dec  # noqa: E402


def synthetic_frames(minutes, seed=1):
    rng = random.Random(seed)
    T = minutes * 60
    ev = []
    for k in range(20):
        f = cpr_gen.random_flight(rng, common.STACJA_PRZYKLAD, icao=0x480000 + k)
        ev += [(t, '*' + fr + ';') for t, fr, _, _ in f.generate(T, rng)]
    t = 0.0
    while t < T:
        df = rng.choice([4, 5, 11, 20, 21])
        nb = 56 if df in (4, 5, 11) else 112
        ev.append((t, f'*{(df << (nb - 5)) | rng.getrandbits(nb - 5):0{nb // 4}X};'))
        t += rng.expovariate(30.0)
    ev.sort()
    return ev


def load_frames(path):
    with open(path, newline='', encoding='utf-8') as f:
        return [(float(r['t_log']), r['ramka']) for r in csv.DictReader(f)]


def peak_rate(ev):
    """Największa liczba ramek w oknie 1 s."""
    best, j = 0, 0
    for i in range(len(ev)):
        while ev[i][0] - ev[j][0] > 1.0:
            j += 1
        best = max(best, i - j + 1)
    return best


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--syntetyczne', type=float, metavar='MINUTY')
    g.add_argument('--ramki', metavar='CSV')
    ap.add_argument('--szczyt', type=float, help='szczytowa liczba ramek/s (gdy brak nagrania)')
    ap.add_argument('--wyjscie', default=os.path.join(common.BADANIA_DIR, 'wyniki', 'benchmark.json'))
    a = ap.parse_args()
    ev = synthetic_frames(a.syntetyczne) if a.syntetyczne else load_frames(a.ramki)
    d = dec.AdsbDecoder()
    d.set_station(*common.STACJA_PRZYKLAD)
    for t, fr in ev[:500]:                       # rozgrzewka (import, pamięć podręczna)
        d.process(fr, t)
    d = dec.AdsbDecoder()
    d.set_station(*common.STACJA_PRZYKLAD)
    t_all, t_adsb = [], []
    pc = time.perf_counter_ns
    for t, fr in ev:
        t0 = pc()
        icao = d.process(fr, t)
        if icao is not None:
            d.state(icao)
        dt = (pc() - t0) / 1000.0               # mikrosekundy
        t_all.append(dt)
        if icao is not None:
            t_adsb.append(dt)
    peak = a.szczyt or peak_rate(ev)
    st_all, st_adsb = common.stats(t_all), common.stats(t_adsb)
    budget_us = 1e6 / peak if peak else float('nan')
    res = {
        'platforma': f'{platform.machine()} {platform.system()} {platform.release()}',
        'python': platform.python_version(), 'zrodlo': 'syntetyczne' if a.syntetyczne else a.ramki,
        'ramki': len(ev), 'ramki_adsb': len(t_adsb),
        'czas_ramki_us': st_all, 'czas_ramki_adsb_us': st_adsb,
        'p99_us': common.percentile(t_all, 99),
        'szczyt_ramek_na_s': peak, 'odstep_w_szczycie_us': budget_us,
        'wykorzystanie_w_szczycie_proc': 100 * peak * st_all['srednia'] / 1e6 if peak else None,
        'przepustowosc_max_ramek_na_s': 1e6 / st_all['srednia'],
    }
    common.write_json(a.wyjscie, res)
    common.write_csv(os.path.splitext(a.wyjscie)[0] + '_czasy.csv',
                     [{'czas_us': x} for x in t_all])
    print(f"Platforma: {res['platforma']}, Python {res['python']}")
    print(f"Ramki: {len(ev)} (zdekodowane ADS-B: {len(t_adsb)})")
    print(f"Czas na ramkę [us]: średnio {st_all['srednia']:.1f}, mediana {st_all['mediana']:.1f}, "
          f"P95 {st_all['p95']:.1f}, P99 {res['p99_us']:.1f}, maks. {st_all['max']:.0f}")
    print(f"Szczyt: {peak:.0f} ramek/s -> odstęp {budget_us:.0f} us; "
          f"dekoder zajmuje ok. {res['wykorzystanie_w_szczycie_proc']:.1f} % jednego rdzenia")
    print(f'Zapisano: {a.wyjscie}')


if __name__ == '__main__':
    main()
