#!/usr/bin/env python3
"""Porównanie pozycji stacji z niezależnym źródłem (T9.1), np. OpenSky Network.

Wejście:
  1) folder wyników sesji (wyniki/<ID>) z analiza_sesji.py
     - używa csv/pozycje_odtworzone.csv (tylko VERIFIED) i podsumowanie.json (delta),
  2) plik CSV źródła zewnętrznego z kolumnami co najmniej: t_utc, icao, lat, lon
     (format zapisywany przez opensky_zapis.py; inne źródła wystarczy przemapować).

Metoda:
  - czas stacji: t_utc = t_log + delta (korekta zegara z GPS z analizy sesji),
  - dla każdego punktu zewnętrznego pozycja stacji tego samego statku jest
    interpolowana liniowo na chwilę t_utc + tau (przerwa między próbkami <= 5 s),
  - błąd e = odległość po powierzchni Ziemi; liczona dla tau = 0 oraz dla
    przesunięć tau od -5 do +5 s co 0,1 s. Przesunięcie tau*, przy którym mediana
    błędu jest najmniejsza, to niezależna ocena błędu czasu (powinno wyjść ~0 s;
    ok. 2 s oznaczałoby nieskorygowane zjawisko F1).

Uwaga interpretacyjna: OpenSky podaje czas pozycji z dokładnością do 1 s i ma własne
opóźnienia, więc błąd e obejmuje także niedokładność źródła zewnętrznego.

Przykład:
  python3 porownanie_zewnetrzne.py wyniki/R-02 dane/opensky_R-02.csv
  python3 porownanie_zewnetrzne.py wyniki/R-02 dane/opensky_R-02.csv --bez-korekty
"""
import argparse
import bisect
import json
import math
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import common  # noqa: E402
from lib.common import dec, fmt  # noqa: E402


def interp(track, times, t, max_gap=5.0):
    i = bisect.bisect_left(times, t)
    if i == 0 or i >= len(times):
        return None
    a, b = track[i - 1], track[i]
    if b['t'] - a['t'] > max_gap:
        return None
    w = (t - a['t']) / (b['t'] - a['t']) if b['t'] > a['t'] else 0.0
    return a['lat'] + w * (b['lat'] - a['lat']), a['lon'] + w * (b['lon'] - a['lon'])


def errors_for_shift(tracks, times, ext, tau):
    out = []
    for e in ext:
        tr = tracks.get(e['icao'])
        if not tr:
            continue
        p = interp(tr, times[e['icao']], e['t'] + tau)
        if p:
            out.append(dec.ground_distance_m(p[0], p[1], e['lat'], e['lon']))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('wyniki_sesji')
    ap.add_argument('zewnetrzne', help='CSV: t_utc, icao, lat, lon, ...')
    ap.add_argument('--bez-korekty', action='store_true', help='nie dodawaj delta (porównawczo)')
    ap.add_argument('--nazwa', default='opensky')
    a = ap.parse_args()
    with open(os.path.join(a.wyniki_sesji, 'podsumowanie.json'), encoding='utf-8') as f:
        summ = json.load(f)
    rid = summ['id']
    delta = summ['czas'].get('delta_hat') if summ['czas'].get('dostepny') else 0.0
    if a.bez_korekty:
        delta = 0.0
    tracks = defaultdict(list)
    for r in common.read_csv(os.path.join(a.wyniki_sesji, 'csv', 'pozycje_odtworzone.csv')):
        if int(r['jakosc']) == dec.POSITION_VERIFIED:
            tracks[r['icao']].append({'t': float(r['t_log']) + delta,
                                      'lat': float(r['lat']), 'lon': float(r['lon'])})
    for v in tracks.values():
        v.sort(key=lambda x: x['t'])
    times = {k: [x['t'] for x in v] for k, v in tracks.items()}
    ext = []
    for r in common.read_csv(a.zewnetrzne):
        try:
            ext.append({'t': float(r['t_utc']), 'icao': r['icao'].strip().upper(),
                        'lat': float(r['lat']), 'lon': float(r['lon'])})
        except (ValueError, KeyError):
            continue
    ext.sort(key=lambda x: x['t'])

    e0 = errors_for_shift(tracks, times, ext, 0.0)
    taus = [round(-5 + 0.1 * i, 1) for i in range(101)]
    med = [common.percentile(errors_for_shift(tracks, times, ext, t), 50) for t in taus]
    valid = [(m, t) for m, t in zip(med, taus) if not math.isnan(m)]
    best_m, best_t = min(valid) if valid else (math.nan, math.nan)
    s0 = common.stats(e0)
    n_ac = len({e['icao'] for e in ext if e['icao'] in tracks})

    out = common.ensure_dir(os.path.join(common.BADANIA_DIR, 'wyniki', rid, a.nazwa))
    res = {'id': rid, 'zrodlo': a.nazwa, 'korekta_czasu_s': delta, 'punkty': s0['n'],
           'statki': n_ac, 'blad_tau0': s0, 'tau_opt_s': best_t, 'mediana_tau_opt_m': best_m}
    common.write_json(os.path.join(out, 'porownanie.json'), res)
    common.write_csv(os.path.join(out, 'mediana_od_tau.csv'),
                     [{'tau_s': t, 'mediana_m': m} for t, m in zip(taus, med)])
    common.write_latex_table(
        os.path.join(out, f'tab_{a.nazwa}_{rid}.tex'),
        ['Wielkość', 'Wartość'],
        [['Punkty porównania / statki', f"{s0['n']} / {n_ac}"],
         ['Błąd: mediana / P95 / maks. [m]',
          f"{fmt(s0['mediana'], 0)} / {fmt(s0['p95'], 0)} / {fmt(s0['max'], 0)}"],
         ['Przesunięcie czasu minimalizujące błąd [s]', fmt(best_t, 1)],
         ['Mediana błędu przy tym przesunięciu [m]', fmt(best_m, 0)]],
        f'Porównanie pozycji stacji z~danymi {a.nazwa} -- sesja {rid}',
        f'tab:{a.nazwa}_{rid.lower().replace("-", "")}', align='p{8cm} r')

    plt = common.setup_matplotlib()
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(common.SZER_PELNA, 2.6))
    if e0:
        ax1.hist([min(x, 1000) for x in e0], bins=40, color=common.KOLORY['akcent'])
    ax1.set_xlabel('Błąd pozycji [m] (≥ 1000 m w ostatniej klasie)')
    ax1.set_ylabel('Liczba punktów')
    ax2.plot(taus, med, '.', ms=3, color=common.KOLORY['VERIFIED'])
    ax2.axvline(0, color='0.5', lw=0.6)
    ax2.set_xlabel(r'Przesunięcie czasu $\tau$ [s]')
    ax2.set_ylabel('Mediana błędu [m]')
    for ax in (ax1, ax2):
        common.comma_axes(ax)
    fig.tight_layout()
    common.save_fig(fig, os.path.join(out, f'rys_{a.nazwa}_{rid}'))
    common.write_figure_snippet(os.path.join(out, f'rys_{a.nazwa}_{rid}.tex'),
                                f'rys_{a.nazwa}_{rid}',
                                f'Porównanie z~danymi {a.nazwa}: rozkład błędu pozycji (z~lewej) '
                                'i~mediana błędu w~funkcji przesunięcia czasu (z~prawej) -- sesja '
                                f'{rid}', f'rys:{a.nazwa}_{rid.lower().replace("-", "")}')
    print(f"Punkty: {s0['n']} ({n_ac} statków); mediana błędu {fmt(s0['mediana'], 0)} m; "
          f"tau* = {fmt(best_t, 1)} s (mediana {fmt(best_m, 0)} m). Wyniki: {out}")


if __name__ == '__main__':
    main()
