#!/usr/bin/env python3
"""Analiza jednej sesji pomiarowej (T3.1, T4.1, T5.x, T6.x, T7.1, T8.1; W1-W10).

Wejście: folder sesji rosbag2 (MCAP) skopiowany z RPi - albo folder z CSV
wcześniej zapisanymi przez ten skrypt (szybciej przy kolejnych uruchomieniach).

Co robi skrypt:
 1. Eksportuje nagranie do CSV (bag_to_csv.py).
 2. Wyznacza pozycję stacji (mediana /gps/fix) i KOREKTĘ CZASU:
    delta_k = time_ref - stamp z /gps/time_ref; estymata = mediana z KOŃCA sesji
    (domyślnie ostatnie 10 min - patrz ustalenie F1: czas GPS bywa błędny o pełne
    sekundy przez pierwsze ok. 12,5 min po złapaniu fixa). Wykrywa skoki delta_k.
 3. ODTWARZA dekodowanie: surowe ramki z /aircraft/frames przechodzą przez ten sam
    moduł adsb_decoder.py co na żywo (T4.1). Daje to pełne statystyki (także
    odrzucone pozycje), których nie ma w nagraniu.
 4. Porównuje dekoder z dump1090 (SBS) na tych samych ramkach (W1, W3, W4).
 5. Liczy wskaźniki W2-W10 i zapisuje tabele LaTeX, CSV i wykresy PDF/PNG.

Wyniki: wyniki/<ID>/{dane,csv,tabele,wykresy}/ + podsumowanie.json
(podsumowanie.json czyta porownanie_sesji.py, które buduje Tabelę C).

Przykłady:
  python3 analiza_sesji.py dane/sesja_20261124_123000Z --id R-02
  python3 analiza_sesji.py dane/sesja_20261020_000000Z --id R-04 \\
          --koniec "2026-10-20 00:12:06"        # czas odcięcia zasilania z journalctl
"""
import argparse
import bisect
import math
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bag_to_csv  # noqa: E402
from lib import common, cpr_gen  # noqa: E402
from lib.common import dec, fmt  # noqa: E402

Q_LOCAL, Q_GLOBAL, Q_VER = dec.POSITION_LOCAL, dec.POSITION_GLOBAL, dec.POSITION_VERIFIED


# =========================================================================== #
# 1. Dane
# =========================================================================== #
def load_session(path, out_dir, refresh=False):
    data_dir = os.path.join(out_dir, 'dane')
    if os.path.exists(os.path.join(path, 'info.json')) and not any(
            f.endswith('.mcap') for f in os.listdir(path)):
        return bag_to_csv.load(path)                       # podano folder z CSV
    if not refresh and os.path.exists(os.path.join(data_dir, 'info.json')):
        print(f'Wczytuję CSV z {data_dir} (użyj --odswiez, aby ponownie czytać MCAP)')
        return bag_to_csv.load(data_dir)
    print('Czytam nagranie MCAP...')
    return bag_to_csv.export(path, data_dir)


def station_from_fix(fixes):
    if not fixes:
        return None
    lat = common.percentile([r['lat'] for r in fixes], 50)
    lon = common.percentile([r['lon'] for r in fixes], 50)
    alt = common.percentile([r['alt'] for r in fixes], 50)
    return lat, lon, alt


# =========================================================================== #
# 2. Czas (W9, ustalenie F1)
# =========================================================================== #
def time_analysis(tref, window_min=10.0, step_s=0.5):
    """Przesunięcie zegara RPi względem GPS: seria delta_k, estymata, skoki."""
    if not tref:
        return {'dostepny': False}
    t = [r['t_log'] for r in tref]
    delta = [r['time_ref'] - r['stamp'] for r in tref]
    # skoki: odchylenie od mediany ostatnich 15 próbek, potwierdzone 3 próbkami
    steps, hist, pend = [], [], []
    for ti, d in zip(t, delta):
        med = common.percentile(hist[-15:], 50) if len(hist) >= 5 else None
        if med is not None and abs(d - med) > step_s:
            pend.append((ti, d))
            if len(pend) >= 3:
                if max(p[1] for p in pend) - min(p[1] for p in pend) <= step_s:
                    steps.append({'t_log': pend[0][0], 'od_startu_min': (pend[0][0] - t[0]) / 60,
                                  'skok_s': pend[-1][1] - med})
                    hist = [p[1] for p in pend]
                pend = []
            continue
        pend = []
        hist.append(d)
    # estymata: mediana z końca sesji, ale tylko z próbek PO ostatnim skoku (F1)
    t_end = t[-1]
    t_from = t_end - window_min * 60
    if steps:
        t_from = max(t_from, steps[-1]['t_log'])
    win = [d for ti, d in zip(t, delta) if ti >= t_from]
    d_hat = common.percentile(win, 50)
    return {'dostepny': True, 'delta_hat': d_hat, 'sigma': common.stdev(win),
            'n_okno': len(win), 'okno_min': window_min, 'skoki': steps,
            'delta_pierwsza': delta[0], 'delta_ostatnia': delta[-1],
            't': t, 'delta': delta}


def utc(t_log, tm):
    return t_log + tm['delta_hat'] if tm.get('dostepny') else t_log


# =========================================================================== #
# 3. Ramki (W5) i odtworzenie dekodowania (T4.1, W2-W7)
# =========================================================================== #
def frame_stats(frames):
    df_count = defaultdict(int)
    n17 = n17_ok = 0
    for r in frames:
        h = r['ramka'].strip().lstrip('*').rstrip(';')
        try:
            df = int(h[:2], 16) >> 3
        except ValueError:
            df_count['błędna'] += 1
            continue
        df_count[df if df < 24 else 24] += 1
        if df == 17 and len(h) == 28:
            n17 += 1
            n17_ok += cpr_gen.crc_ok(h)
    return {'ramki': len(frames), 'df17': n17, 'df17_crc_ok': n17_ok,
            'udzial_df17': n17 / len(frames) if frames else math.nan,
            'udzial_crc_ok': n17_ok / n17 if n17 else math.nan, 'df': dict(df_count)}


def replay(frames, fixes):
    """Przepuszcza nagrane ramki przez AdsbDecoder (jak decoder_node, czas = t_log)."""
    d = dec.AdsbDecoder()
    ev = [(r['t_log'], 0, r) for r in frames] + [(r['t_log'], 1, r) for r in fixes]
    ev.sort(key=lambda e: (e[0], e[1]))
    positions = []
    ac_info = defaultdict(lambda: {'t_ramka': None, 't_local': None, 't_verified': None,
                                   'n_poz': 0, 'n_ver': 0, 't_poz': [], 'znak': ''})
    for t, kind, r in ev:
        if kind == 1:
            d.set_station(r['lat'], r['lon'], r['alt'])
            continue
        icao = d.process(r['ramka'], t)
        if icao is None:
            continue
        a = ac_info[icao]
        if a['t_ramka'] is None:
            a['t_ramka'] = t
        ac = d.aircraft[icao]
        a['znak'] = ac['callsign'] or a['znak']
        if ac['position_time'] == t:
            s = d.state(icao)
            q = s['position_quality']
            a['n_poz'] += 1
            a['t_poz'].append(t)
            if a['t_local'] is None:
                a['t_local'] = t
            if q == Q_VER:
                a['n_ver'] += 1
                if a['t_verified'] is None:
                    a['t_verified'] = t
            e = n = math.nan
            if d.station is not None:
                e, n, _ = common.enu(*d.station, s['latitude'], s['longitude'],
                                     s['altitude'] if not common.isnan(s['altitude']) else 0)
            positions.append({'t_log': t, 'icao': icao, 'lat': s['latitude'],
                              'lon': s['longitude'], 'jakosc': q, 'alt_m': s['altitude'],
                              'odl_pozioma': s['ground_distance'], 'odl_skosna': s['slant_distance'],
                              'azymut': s['azimuth'], 'elewacja': s['elevation'],
                              'e_km': e / 1000, 'n_km': n / 1000})
    return positions, dict(ac_info), d.stats


def sbs_per_aircraft(sbs):
    out = defaultdict(lambda: {'t_msg': None, 't_poz': None, 'n_poz': 0})
    pos = []
    for r in sbs:
        a = out[r['icao']]
        if a['t_msg'] is None:
            a['t_msg'] = r['t_log']
        if r['typ'] == 3 and not common.isnan(r['lat']) and not common.isnan(r['lon']):
            a['n_poz'] += 1
            if a['t_poz'] is None:
                a['t_poz'] = r['t_log']
            pos.append(r)
    return dict(out), pos


def compare_sbs(dec_pos, sbs_pos, max_dt=1.0):
    """Dla każdej pozycji SBS: najbliższa (w metrach) pozycja dekodera tego samego
    statku z okna +/- max_dt s. Ta sama ramka -> różnica ~0 m (spójność dekoderów)."""
    by_icao = defaultdict(list)
    for p in dec_pos:
        by_icao[p['icao']].append(p)
    for v in by_icao.values():
        v.sort(key=lambda p: p['t_log'])
    times = {k: [p['t_log'] for p in v] for k, v in by_icao.items()}
    diffs, unmatched = [], 0
    for s in sbs_pos:
        lst = by_icao.get(s['icao'])
        if not lst:
            unmatched += 1
            continue
        tt = times[s['icao']]
        i0 = bisect.bisect_left(tt, s['t_log'] - max_dt)
        i1 = bisect.bisect_right(tt, s['t_log'] + max_dt)
        if i0 >= i1:
            unmatched += 1
            continue
        best = min(dec.ground_distance_m(s['lat'], s['lon'], p['lat'], p['lon'])
                   for p in lst[i0:i1])
        diffs.append(best)
    return diffs, unmatched


# =========================================================================== #
# 4. Wskaźniki
# =========================================================================== #
def compute(d, args):
    info = d['info']
    res = {'id': args.id, 'sesja': info.get('sesja'), 'notatka': args.notatka}
    t0, t1 = info['t_pierwsza'], info['t_ostatnia']
    dur = info['czas_trwania_s']
    res['czas_trwania_h'] = dur / 3600
    res['rozmiar_MB'] = info['rozmiar_MB']
    res['MB_na_h'] = info['rozmiar_MB'] / (dur / 3600) if dur > 0 else math.nan
    res['metadata_yaml'] = info['metadata_yaml']
    res['wiadomosci'] = info['wiadomosci']
    res['czestotliwosc_Hz'] = {k: v / dur for k, v in info['wiadomosci'].items()} if dur else {}

    # T6.1 / T6.2: utracone nagranie po odcięciu zasilania
    if args.koniec:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        tk = datetime.strptime(args.koniec, '%Y-%m-%d %H:%M:%S').replace(
            tzinfo=ZoneInfo(args.strefa)).timestamp()
        res['koniec_zasilania'] = args.koniec
        res['utracone_min'] = (tk - t1) / 60
        res['czas_pracy_h'] = (tk - t0) / 3600

    st = station_from_fix(d['gps_fix'])
    res['stacja_znana'] = st is not None
    res['stacja_alt_m'] = st[2] if st else math.nan

    # W9: czas
    tm = time_analysis(d['czas_gps'], args.okno_czasu)
    res['czas'] = {k: v for k, v in tm.items() if k not in ('t', 'delta')}
    live = [r for r in d['stan'] if r['time_source'] == 1]
    res['stan_z_czasem_gps_proc'] = 100 * len(live) / len(d['stan']) if d['stan'] else math.nan
    if live and tm.get('dostepny'):
        err = [abs(r['clock_offset'] - tm['delta_hat']) for r in live]
        res['korekta_na_zywo_blad_mediana_s'] = common.percentile(err, 50)
        res['korekta_na_zywo_blad_max_s'] = max(err)
        res['korekta_na_zywo_blad_gt_1s_proc'] = 100 * sum(e > 1 for e in err) / len(err)

    # W10: praca w terenie
    temps = [r['temp'] for r in d['temp_cpu']]
    res['temp_max'] = max(temps) if temps else math.nan
    res['temp_sr'] = common.mean(temps)
    uv = d['napiecie']
    res['niskie_napiecie_zdarzenia'] = sum(1 for a, b in zip([{'niskie': 0}] + uv, uv)
                                           if b['niskie'] and not a['niskie'])
    res['niskie_napiecie_s'] = sum(r['niskie'] for r in uv)
    fx = [r['t_log'] for r in d['gps_fix']]
    res['eta_gps_proc'] = 100 * len(fx) / dur if dur else math.nan
    gaps = [b - a for a, b in zip(fx, fx[1:])]
    res['gps_najdluzsza_przerwa_s'] = max(gaps) if gaps else math.nan

    # W5: ramki
    fs = frame_stats(d['ramki'])
    res['ramki'] = fs

    # T4.1: odtworzenie dekodowania
    dec_pos, ac_info, dstats = replay(d['ramki'], d['gps_fix']) if d['ramki'] else ([], {}, {})
    res['dekoder_statystyki'] = dstats
    npoz = len(dec_pos)
    nver = sum(p['jakosc'] == Q_VER for p in dec_pos)
    nodrz = sum(dstats.get(k, 0) for k in ('niezgodne', 'skoki', 'poza_zasiegiem'))
    res['W2_pozycje'] = npoz
    res['W2_eta_V_proc'] = 100 * nver / npoz if npoz else math.nan
    res['W2_eta_R_proc'] = 100 * nodrz / (npoz + nodrz) if npoz + nodrz else math.nan
    res['jakosc_udzialy_proc'] = {common.JAKOSC_NAZWY[q]: 100 * sum(p['jakosc'] == q for p in dec_pos) / npoz
                                  for q in (1, 2, 3)} if npoz else {}
    # spójność odtworzenia z nagranym /aircraft/state
    live_pos = [r for r in d['stan'] if r['jakosc'] > 0 and abs(r['pos_stamp'] - r['stamp']) < 1e-6]
    res['stan_nagrany_pozycje'] = len(live_pos)

    # W3, W4: na statek
    sbs_ac, sbs_pos = sbs_per_aircraft(d['sbs'])
    per_ac = []
    for icao, a in ac_info.items():
        s = sbs_ac.get(icao, {})
        tp = a['t_poz']
        per_ac.append({
            'icao': icao, 'znak': a['znak'], 'pozycje': a['n_poz'], 'verified': a['n_ver'],
            'T1_local_s': (a['t_local'] - a['t_ramka']) if a['t_local'] else math.nan,
            'T1_verified_s': (a['t_verified'] - a['t_ramka']) if a['t_verified'] else math.nan,
            'T1_sbs_s': (s['t_poz'] - a['t_ramka']) if s.get('t_poz') else math.nan,
            'okres_aktualizacji_s': common.percentile([b - x for x, b in zip(tp, tp[1:])], 50),
            'sbs_pozycje': s.get('n_poz', 0)})
    res['statki_df17'] = len(ac_info)
    res['statki_z_pozycja'] = sum(1 for a in ac_info.values() if a['n_poz'])
    res['statki_verified'] = sum(1 for a in ac_info.values() if a['n_ver'])
    res['statki_sbs'] = len(sbs_ac)
    res['statki_sbs_z_pozycja'] = sum(1 for a in sbs_ac.values() if a['n_poz'])
    res['W4_kappa_dek_proc'] = 100 * res['statki_z_pozycja'] / len(ac_info) if ac_info else math.nan
    res['W4_kappa_sbs_proc'] = (100 * sum(1 for i in ac_info if sbs_ac.get(i, {}).get('n_poz'))
                                / len(ac_info)) if ac_info else math.nan
    for k in ('T1_local_s', 'T1_verified_s', 'T1_sbs_s'):
        v = [r[k] for r in per_ac]
        res[f'W3_{k}_mediana'] = common.percentile(v, 50)
        res[f'W3_{k}_p90'] = common.percentile(v, 90)
    res['W6_okres_aktualizacji_mediana_s'] = common.percentile(
        [r['okres_aktualizacji_s'] for r in per_ac], 50)

    # W1: dekoder vs SBS
    diffs, unmatched = compare_sbs(dec_pos, sbs_pos) if dec_pos else ([], len(sbs_pos))
    s1 = common.stats(diffs)
    res['W1_sbs'] = s1
    res['W1_sbs_ponizej_1m_proc'] = 100 * sum(x < 1 for x in diffs) / len(diffs) if diffs else math.nan
    res['W1_sbs_bez_pary'] = unmatched
    res['W1_sbs_pozycje'] = len(sbs_pos)

    # W7: zasięg (pozycje VERIFIED)
    ver = [p for p in dec_pos if p['jakosc'] == Q_VER and not common.isnan(p['odl_pozioma'])]
    rng_km = [p['odl_pozioma'] / 1000 for p in ver]
    res['W7_zasieg_max_km'] = max(rng_km) if rng_km else math.nan
    res['W7_zasieg_p95_km'] = common.percentile(rng_km, 95)
    sectors = [0.0] * 36
    for p in ver:
        k = int((p['azymut'] % 360) // 10)
        sectors[k] = max(sectors[k], p['odl_pozioma'] / 1000)
    res['W7_sektory_km'] = sectors
    res['W7_elewacja_min_deg'] = min((p['elewacja'] for p in ver), default=math.nan)
    return res, tm, dec_pos, per_ac, diffs, st


# =========================================================================== #
# 5. Tabele i wykresy
# =========================================================================== #
def write_tables(out, res):
    T = os.path.join(out, 'tabele')
    rid = res['id']
    tm = res['czas']
    rows = [
        ('Czas trwania sesji [h]', fmt(res['czas_trwania_h'], 2)),
        ('Rozmiar nagrania [MB] / [MB/h]', f"{fmt(res['rozmiar_MB'], 1)} / {fmt(res['MB_na_h'], 1)}"),
        ('Ramki Mode S / ADS-B (DF17)', f"{res['ramki']['ramki']} / {res['ramki']['df17']}"),
        (r'Udział DF17 z poprawnym CRC [\%]', fmt(100 * res['ramki']['udzial_crc_ok'], 1)),
        ('Statki DF17 / z pozycją / VERIFIED',
         f"{res['statki_df17']} / {res['statki_z_pozycja']} / {res['statki_verified']}"),
        (r'Pokrycie $\kappa$ dekoder / dump1090 [\%]',
         f"{fmt(res['W4_kappa_dek_proc'], 1)} / {fmt(res['W4_kappa_sbs_proc'], 1)}"),
        ('Pozycje (odtworzenie)', str(res['W2_pozycje'])),
        (r'$\eta_V$ / $\eta_R$ [\%]', f"{fmt(res['W2_eta_V_proc'], 1)} / {fmt(res['W2_eta_R_proc'], 2)}"),
        ('Mediana T do 1. pozycji: LOCAL / VERIFIED / dump1090 [s]',
         f"{fmt(res['W3_T1_local_s_mediana'], 2)} / {fmt(res['W3_T1_verified_s_mediana'], 1)} / "
         f"{fmt(res['W3_T1_sbs_s_mediana'], 1)}"),
        ('Okres aktualizacji pozycji (mediana) [s]', fmt(res['W6_okres_aktualizacji_mediana_s'], 2)),
        ('Różnica dekoder--dump1090: mediana / P95 [m]',
         f"{fmt(res['W1_sbs']['mediana'], 2)} / {fmt(res['W1_sbs']['p95'], 2)}"),
        ('Zasięg maks. / P95 [km]', f"{fmt(res['W7_zasieg_max_km'], 0)} / {fmt(res['W7_zasieg_p95_km'], 0)}"),
        (r'Przesunięcie zegara $\hat\delta$ [s]', fmt(tm.get('delta_hat'), 3)),
        (r'Rozrzut $\sigma_\delta$ [s]', fmt(tm.get('sigma'), 3)),
        ('Skoki czasu GPS (liczba)', str(len(tm.get('skoki', []))) if tm.get('dostepny') else '--'),
        (r'Czas z fixem GPS $\eta_{\mathrm{GPS}}$ [\%]', fmt(res['eta_gps_proc'], 1)),
        ('Temperatura CPU maks. / śr. [°C]', f"{fmt(res['temp_max'], 1)} / {fmt(res['temp_sr'], 1)}"),
        ('Zdarzenia niskiego napięcia', str(res['niskie_napiecie_zdarzenia'])),
    ]
    if 'utracone_min' in res:
        rows.append(('Utracone nagranie po odcięciu zasilania [min]', fmt(res['utracone_min'], 1)))
        rows.append(('Czas pracy do odcięcia [h]', fmt(res['czas_pracy_h'], 2)))
    common.write_latex_table(
        os.path.join(T, f'tab_sesja_{rid}.tex'), ['Wielkość', 'Wartość'],
        [[a, b] for a, b in rows], f'Podsumowanie sesji pomiarowej {rid}',
        f'tab:sesja_{rid.lower().replace("-", "")}', align='p{9.5cm} r')
    # przy nagłówkach z $...$ escape zepsułby LaTeX - pierwsza kolumna wstawiana surowo:
    _raw_first_col(os.path.join(T, f'tab_sesja_{rid}.tex'), rows)
    common.write_csv(os.path.join(out, 'csv', 'tabela_sesji.csv'),
                     [{'wielkosc': a, 'wartosc': b} for a, b in rows])

    df = res['ramki']['df']
    tot = sum(df.values()) or 1
    common.write_latex_table(
        os.path.join(T, f'tab_df_{rid}.tex'), ['DF', 'Liczba ramek', r'Udział [\%]'],
        [[str(k), str(v), fmt(100 * v / tot, 1)] for k, v in sorted(df.items(), key=lambda x: str(x[0]))],
        f'Rodzaje odebranych ramek Mode S w~sesji {rid}', f'tab:df_{rid.lower().replace("-", "")}')


def _raw_first_col(path, rows):
    """Podmienia zabezpieczone komórki pierwszej kolumny na wersję z matematyką LaTeX."""
    with open(path, encoding='utf-8') as f:
        txt = f.read()
    for a, _ in rows:
        txt = txt.replace(common.latex_escape(a), a)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(txt)


def make_plots(out, res, tm, dec_pos, per_ac, diffs, st, d):
    plt = common.setup_matplotlib()
    import matplotlib.dates as mdates
    from datetime import datetime, timezone
    W = os.path.join(out, 'wykresy')
    rid = res['id']
    snippets = []

    def dt(ts):
        return [datetime.fromtimestamp(utc(x, tm), tz=timezone.utc) for x in ts]

    def tax(ax):
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M', tz=timezone.utc))
        ax.set_xlabel('Czas UTC' + (' (po korekcie z GPS)' if tm.get('dostepny') else ' (zegar RPi)'))

    # 1) mapa śladów (ENU względem stacji - bez ujawniania lokalizacji)
    if dec_pos:
        fig, ax = plt.subplots(figsize=(common.SZER_PELNA, common.SZER_PELNA * 0.8))
        step = max(1, len(dec_pos) // 60000)
        for q, name in ((Q_LOCAL, 'LOCAL'), (Q_GLOBAL, 'GLOBAL'), (Q_VER, 'VERIFIED')):
            pts = [p for p in dec_pos[::step] if p['jakosc'] == q]
            if pts:
                ax.scatter([p['e_km'] for p in pts], [p['n_km'] for p in pts], s=1.5,
                           color=common.KOLORY[name], label=f'{name} ({len(pts)})', rasterized=True)
        for r in (100, 200, 300):
            ax.add_patch(plt.Circle((0, 0), r, fill=False, ls='--', lw=0.6, color='0.5'))
            ax.text(r * 0.707, r * 0.707, f'{r} km', fontsize=7, color='0.4')
        ax.plot(0, 0, marker='^', color='k', ms=7, label='stacja')
        ax.set_aspect('equal')
        ax.set_xlabel('Odległość na wschód od stacji [km]')
        ax.set_ylabel('Odległość na północ od stacji [km]')
        lg = ax.legend(loc='upper right', fontsize=8)
        for h in lg.legend_handles:
            if hasattr(h, 'set_sizes'):
                h.set_sizes([20])
        common.comma_axes(ax)
        common.save_fig(fig, os.path.join(W, f'rys_mapa_{rid}'))
        snippets.append((f'rys_mapa_{rid}', f'Ślady statków powietrznych w~sesji {rid} '
                         'względem stacji bazowej; kolor oznacza jakość pozycji', 'mapa'))

    # 2) zasięg biegunowy
    if res['W7_sektory_km'] and max(res['W7_sektory_km']) > 0:
        import numpy as np
        fig = plt.figure(figsize=(common.SZER_POL * 1.3, common.SZER_POL * 1.3))
        ax = fig.add_subplot(projection='polar')
        ax.set_theta_zero_location('N')
        ax.set_theta_direction(-1)
        th = np.deg2rad(np.arange(0, 370, 10) + 5)
        r = res['W7_sektory_km'] + res['W7_sektory_km'][:1]
        ax.plot(th, r, color=common.KOLORY['akcent'], marker='o', ms=2.5, lw=1)
        ax.fill(th, r, alpha=0.15, color=common.KOLORY['akcent'])
        from matplotlib.ticker import MaxNLocator
        ax.yaxis.set_major_locator(MaxNLocator(4))
        ax.set_rlabel_position(112)
        ax.tick_params(axis='y', labelsize=7)
        ax.set_title('Maks. zasięg [km] w sektorach 10°', fontsize=9, pad=14)
        common.save_fig(fig, os.path.join(W, f'rys_zasieg_bieg_{rid}'))
        snippets.append((f'rys_zasieg_bieg_{rid}', f'Maksymalny zasięg odbioru pozycji '
                         f'potwierdzonych w~sektorach co \\ang{{10}} -- sesja {rid}', 'zasieg_bieg'))

    # 3) zasięg vs wysokość + horyzont radiowy (eq:zasieg)
    ver = [p for p in dec_pos if p['jakosc'] == Q_VER and not common.isnan(p['alt_m'])]
    if ver:
        fig, ax = plt.subplots(figsize=(common.SZER_PELNA, 3.0))
        step = max(1, len(ver) // 30000)
        ax.scatter([p['alt_m'] / 1000 for p in ver[::step]],
                   [p['odl_pozioma'] / 1000 for p in ver[::step]], s=1,
                   color=common.KOLORY['VERIFIED'], label='pozycje VERIFIED', rasterized=True)
        hs = [i * 0.1 for i in range(0, 141)]
        ax.plot(hs, [common.radio_horizon_km(res['stacja_alt_m'] if not common.isnan(res['stacja_alt_m'])
                                             else 0, h * 1000) for h in hs],
                color=common.KOLORY['linia'], lw=1, label='horyzont radiowy, wzór (eq:zasieg)')
        ax.set_xlabel('Wysokość statku powietrznego [km]')
        ax.set_ylabel('Odległość pozioma [km]')
        ax.legend(markerscale=6, fontsize=8)
        common.comma_axes(ax)
        common.save_fig(fig, os.path.join(W, f'rys_zasieg_wys_{rid}'))
        snippets.append((f'rys_zasieg_wys_{rid}', 'Odległość odbioru w~funkcji wysokości '
                         f'statku powietrznego na tle horyzontu radiowego -- sesja {rid}', 'zasieg_wys'))

    # 4) CDF czasu do pierwszej pozycji
    if per_ac:
        fig, ax = plt.subplots(figsize=(common.SZER_PELNA, 2.8))
        for k, name, col in (('T1_local_s', 'dekoder, pierwsza pozycja', common.KOLORY['LOCAL']),
                             ('T1_verified_s', 'dekoder, VERIFIED', common.KOLORY['VERIFIED']),
                             ('T1_sbs_s', 'dump1090 (SBS)', common.KOLORY['SBS'])):
            v = sorted(r[k] for r in per_ac if not common.isnan(r[k]))
            if v:
                ax.step(v, [100 * (i + 1) / len(per_ac) for i in range(len(v))], where='post',
                        color=col, label=f'{name} (n = {len(v)})')
        ax.set_xscale('symlog', linthresh=1)
        ax.set_xlabel('Czas od pierwszej ramki DF17 statku [s]')
        ax.set_ylabel('Statki z pozycją [%]')
        ax.set_ylim(0, 102)
        ax.legend(loc='lower right', fontsize=8)
        common.comma_axes(ax, x=False)
        common.save_fig(fig, os.path.join(W, f'rys_t1poz_{rid}'))
        snippets.append((f'rys_t1poz_{rid}', 'Dystrybuanta czasu od pierwszej ramki DF17 '
                         f'do pierwszej pozycji -- dekoder i~dump1090, sesja {rid}', 't1poz'))

    # 5) różnice dekoder - dump1090
    if diffs:
        fig, ax = plt.subplots(figsize=(common.SZER_PELNA, 2.6))
        ax.hist([min(x, 20) for x in diffs], bins=[i * 0.5 for i in range(41)],
                color=common.KOLORY['akcent'])
        ax.set_yscale('log')
        ax.set_xlabel('Różnica pozycji dekoder -- dump1090 [m] (≥ 20 m w ostatniej klasie)')
        ax.set_ylabel('Liczba pozycji')
        common.comma_axes(ax, y=False)
        common.save_fig(fig, os.path.join(W, f'rys_roznica_sbs_{rid}'))
        snippets.append((f'rys_roznica_sbs_{rid}', 'Rozkład różnic pozycji wyznaczonych przez '
                         f'dekoder i~przez dump1090 dla tych samych ramek -- sesja {rid}', 'roznica_sbs'))

    # 6) liczba statków i 9) ramki na sekundę w czasie
    if d['ramki']:
        tmin = d['ramki'][0]['t_log']
        bins = defaultdict(lambda: [set(), set(), 0, 0])
        for r in d['ramki']:
            b = int((r['t_log'] - tmin) // 60)
            bins[b][2] += 1
            h = r['ramka'].strip().lstrip('*').rstrip(';')
            if len(h) == 28 and h[:2] in ('8D', '8C', '8E', '8F', '8A', '8B', '89', '88'):
                bins[b][3] += 1
                bins[b][0].add(h[2:8])
        for p in dec_pos:
            bins[int((p['t_log'] - tmin) // 60)][1].add(p['icao'])
        ks = sorted(bins)
        tt = dt([tmin + 60 * k + 30 for k in ks])
        fig, ax = plt.subplots(figsize=(common.SZER_PELNA, 2.6))
        ax.step(tt, [len(bins[k][0]) for k in ks], where='mid', color='0.4', label='nadające DF17')
        ax.step(tt, [len(bins[k][1]) for k in ks], where='mid', color=common.KOLORY['VERIFIED'],
                label='z pozycją')
        ax.set_ylabel('Liczba statków (okna 1 min)')
        ax.legend(fontsize=8)
        tax(ax)
        common.save_fig(fig, os.path.join(W, f'rys_liczba_statkow_{rid}'))
        snippets.append((f'rys_liczba_statkow_{rid}', 'Liczba statków powietrznych w~zasięgu '
                         f'w~funkcji czasu (okna 1~min) -- sesja {rid}', 'liczba_statkow'))
        fig, ax = plt.subplots(figsize=(common.SZER_PELNA, 2.6))
        ax.step(tt, [bins[k][2] / 60 for k in ks], where='mid', color='0.4', label='wszystkie ramki')
        ax.step(tt, [bins[k][3] / 60 for k in ks], where='mid', color=common.KOLORY['akcent'],
                label='ramki DF17')
        ax.set_ylabel('Ramki na sekundę [1/s]')
        ax.legend(fontsize=8)
        tax(ax)
        common.comma_axes(ax, x=False)
        common.save_fig(fig, os.path.join(W, f'rys_ramki_{rid}'))
        snippets.append((f'rys_ramki_{rid}', 'Średnia liczba odebranych ramek na sekundę '
                         f'(okna 1~min) -- sesja {rid}', 'ramki'))

    # 7) temperatura CPU
    if d['temp_cpu']:
        fig, ax = plt.subplots(figsize=(common.SZER_PELNA, 2.4))
        ax.plot(dt([r['t_log'] for r in d['temp_cpu']]), [r['temp'] for r in d['temp_cpu']],
                lw=0.8, color=common.KOLORY['LOCAL'])
        ax.axhline(80, ls='--', lw=0.8, color='0.3')
        ax.text(0.01, 80.5, '80 °C', transform=ax.get_yaxis_transform(), fontsize=8)
        ax.set_ylabel('Temperatura CPU [°C]')
        tax(ax)
        common.comma_axes(ax, x=False)
        common.save_fig(fig, os.path.join(W, f'rys_temp_{rid}'))
        snippets.append((f'rys_temp_{rid}', f'Temperatura procesora RPi w~sesji {rid}', 'temp'))

    # 8) przesunięcie zegara (F1)
    if tm.get('dostepny'):
        fig, ax = plt.subplots(figsize=(common.SZER_PELNA, 2.6))
        t0 = tm['t'][0]
        x = [(t - t0) / 60 for t in tm['t']]
        y = [dd - tm['delta_hat'] for dd in tm['delta']]
        ax.plot(x, y, '.', ms=1.5, color=common.KOLORY['akcent'], label=r'$\delta_k - \hat\delta$')
        for s in tm['skoki']:
            ax.axvline(s['od_startu_min'], color=common.KOLORY['LOCAL'], lw=0.8, ls='--')
            ax.text(s['od_startu_min'], ax.get_ylim()[1] * 0.9 if ax.get_ylim()[1] > 0 else 0.5,
                    f" skok {fmt(s['skok_s'], 2)} s", fontsize=8, color=common.KOLORY['LOCAL'])
        ax.set_xlabel('Czas od pierwszego odczytu czasu GPS [min]')
        ax.set_ylabel(r'$\delta_k - \hat\delta$ [s]')
        ax.set_title(r'$\hat\delta$ = ' + fmt(tm['delta_hat'], 3) + ' s (mediana z ostatnich '
                     + fmt(tm['okno_min'], 0) + ' min)', fontsize=9)
        common.comma_axes(ax)
        common.save_fig(fig, os.path.join(W, f'rys_zegar_{rid}'))
        snippets.append((f'rys_zegar_{rid}', 'Odchylenie próbek przesunięcia zegara RPi '
                         f'względem czasu GPS od estymaty końcowej -- sesja {rid}', 'zegar'))

    for name, cap, lab in snippets:
        common.write_figure_snippet(os.path.join(W, name + '.tex'), name, cap,
                                    f'rys:{lab}_{rid.lower().replace("-", "")}')


# =========================================================================== #
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('sesja', help='folder sesji (MCAP) albo folder z CSV')
    ap.add_argument('--id', help='identyfikator sesji, np. R-02 (z sesje.csv)')
    ap.add_argument('--notatka', default='', help='krótki opis (miejsce, antena, pogoda)')
    ap.add_argument('--okno-czasu', type=float, default=10.0,
                    help='z ilu ostatnich minut liczyć przesunięcie zegara [min]')
    ap.add_argument('--koniec', help='chwila odcięcia zasilania "RRRR-MM-DD GG:MM:SS" '
                    '(z journalctl --list-boots, czas lokalny)')
    ap.add_argument('--strefa', default='Europe/Warsaw')
    ap.add_argument('--odswiez', action='store_true', help='ponownie czytaj MCAP')
    a = ap.parse_args()
    a.id = a.id or os.path.basename(os.path.normpath(a.sesja))
    out = common.ensure_dir(os.path.join(common.BADANIA_DIR, 'wyniki', a.id))

    d = load_session(a.sesja, out, a.odswiez)
    print('Liczę wskaźniki (odtwarzanie dekodowania może potrwać 1-3 min)...')
    res, tm, dec_pos, per_ac, diffs, st = compute(d, a)
    common.write_csv(os.path.join(out, 'csv', 'statki.csv'), per_ac)
    common.write_csv(os.path.join(out, 'csv', 'pozycje_odtworzone.csv'), dec_pos)
    if tm.get('dostepny'):
        common.write_csv(os.path.join(out, 'csv', 'zegar.csv'),
                         [{'t_log': t, 'delta': x} for t, x in zip(tm['t'], tm['delta'])])
    write_tables(out, res)
    make_plots(out, res, tm, dec_pos, per_ac, diffs, st, d)
    common.write_json(os.path.join(out, 'podsumowanie.json'), res)

    tmr = res['czas']
    print(f"\n=== Sesja {a.id} ===")
    print(f"czas trwania: {res['czas_trwania_h']:.2f} h, {res['MB_na_h']:.1f} MB/h")
    print(f"ramki: {res['ramki']['ramki']}, DF17: {res['ramki']['df17']}, "
          f"statki DF17/z pozycją/VERIFIED: {res['statki_df17']}/{res['statki_z_pozycja']}/"
          f"{res['statki_verified']}")
    print(f"eta_V = {fmt(res['W2_eta_V_proc'], 1)} %, eta_R = {fmt(res['W2_eta_R_proc'], 2)} %, "
          f"T1 LOCAL/VER/SBS (mediana): {fmt(res['W3_T1_local_s_mediana'], 2)} / "
          f"{fmt(res['W3_T1_verified_s_mediana'], 1)} / {fmt(res['W3_T1_sbs_s_mediana'], 1)} s")
    print(f"dekoder vs dump1090: mediana {fmt(res['W1_sbs']['mediana'], 2)} m, "
          f"<1 m: {fmt(res['W1_sbs_ponizej_1m_proc'], 1)} %")
    print(f"zasięg max/P95: {fmt(res['W7_zasieg_max_km'], 0)} / {fmt(res['W7_zasieg_p95_km'], 0)} km")
    if tmr.get('dostepny'):
        print(f"zegar: delta = {fmt(tmr['delta_hat'], 3)} s, sigma = {fmt(tmr['sigma'], 3)} s, "
              f"skoki: {[(round(s['od_startu_min'], 1), round(s['skok_s'], 2)) for s in tmr['skoki']]}")
    if 'korekta_na_zywo_blad_mediana_s' in res:
        print(f"korekta na żywo vs końcowa: mediana {fmt(res['korekta_na_zywo_blad_mediana_s'], 3)} s, "
              f"> 1 s w {fmt(res['korekta_na_zywo_blad_gt_1s_proc'], 1)} % komunikatów")
    print(f"temperatura max {fmt(res['temp_max'], 1)} °C, fix GPS {fmt(res['eta_gps_proc'], 1)} % czasu")
    print(f"\nWyniki: {out}")


if __name__ == '__main__':
    main()
