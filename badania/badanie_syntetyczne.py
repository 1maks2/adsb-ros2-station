#!/usr/bin/env python3
"""Badania dekodera na danych syntetycznych (scenariusze T1.1-T1.8, T2.1, zegar).

Źródło odniesienia: wygenerowane ramki DF17 ze ZNANĄ trajektorią (lib/cpr_gen.py),
więc błąd pozycji jest liczony dokładnie, a nie względem innego odbiornika.

Co powstaje (domyślnie w wyniki/syntetyczne/):
  tabele/tab_syn_utrata.tex     Tabela A  - wyniki w funkcji utraty ramek p (T1.2)
  tabele/tab_syn_ber.tex        Tabela A2 - przekłamania bitów (T1.3)
  tabele/tab_syn_stacja.tex     Tabela A3 - błędna pozycja stacji (T1.4)
  tabele/tab_syn_zasieg.tex     Tabela A4 - zasięg poprawnego dekodowania lokalnego (T1.5)
  tabele/tab_przypadki.tex      Tabela B  - przypadki brzegowe: oczekiwane / uzyskane
  wykresy/rys_syn_blad.pdf      histogram błędu pozycji (p = 0 i p = 0,3)
  wykresy/rys_syn_t1poz.pdf     czas do 1. pozycji LOCAL i VERIFIED w funkcji p
  wykresy/rys_syn_zasieg.pdf    odsetek błędnych pozycji LOCAL w funkcji odległości
  wykresy/rys_syn_stacja.pdf    błąd azymutu w funkcji błędu pozycji stacji
  csv/*.csv                     dane surowe (do załącznika / własnych wykresów)
  podsumowanie.json             wszystkie liczby w jednym pliku

Uruchomienie (z folderu badania/):
  python3 badanie_syntetyczne.py               # pełne (20 ziaren, ok. 1-2 min)
  python3 badanie_syntetyczne.py --ziarna 5    # szybki podgląd
"""
import argparse
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import cases, common, cpr_gen
from lib.common import dec, fmt

ST = common.STACJA_PRZYKLAD


# --------------------------------------------------------------------------- #
def run_one(seed, p, duration):
    """Jeden losowy lot przy utracie ramek p. Zwraca wskaźniki W1-W3 dla lotu."""
    rng = cpr_gen.make_rng(1000 + seed)
    f = cpr_gen.random_flight(rng, ST)
    r = cases.run_flight(f, duration, seed=seed * 7919 + int(p * 100), loss=p)
    q = r['qualities']
    errs = r['errors']
    # pozycje po pierwszych 30 s śledzenia (próg z metodyki: eta_V >= 90 %)
    t0 = r['t_first_frame']
    n_v = sum(1 for x in q if x == dec.POSITION_VERIFIED)
    return {
        'ziarno': seed, 'p': p, 'pozycje': len(q), 'verified': n_v,
        'eta_V': n_v / len(q) if q else math.nan,
        't1_local': (r['t_first_pos'] - t0) if r['t_first_pos'] is not None else math.nan,
        't1_verified': (r['t_first_verified'] - t0) if r['t_first_verified'] is not None
        else math.nan,
        'blad_sr': common.mean(errs), 'blad_max': max(errs) if errs else math.nan,
        'odrzucone': r['stats']['niezgodne'] + r['stats']['skoki']
        + r['stats']['poza_zasiegiem'],
        '_errors': errs, '_t0': t0,
    }


def eta_after(seed, p, duration, after_s=30.0):
    """eta_V liczone tylko z pozycji po pierwszych `after_s` s śledzenia."""
    rng = cpr_gen.make_rng(1000 + seed)
    f = cpr_gen.random_flight(rng, ST)
    rng2 = cpr_gen.make_rng(seed * 7919 + int(p * 100))
    ev = f.generate(duration, rng2)
    if p > 0:
        ev = cpr_gen.apply_loss(ev, p, rng2)
    d = dec.AdsbDecoder()
    d.set_station(*ST)
    icao = f'{f.icao:06X}'
    t0 = None
    n = nv = 0
    for t, frame, kind, truth in ev:
        if d.process('*' + frame + ';', t) == icao and t0 is None:
            t0 = t
        ac = d.aircraft.get(icao)
        if ac and truth and ac['position_time'] == t and t - t0 > after_s:
            n += 1
            nv += ac['position_quality'] == dec.POSITION_VERIFIED
    return nv / n if n else math.nan


def study_loss(seeds, duration, losses=(0.0, 0.1, 0.3, 0.5)):
    runs, summary, errs_by_p = [], [], {}
    for p in losses:
        rr = [run_one(s, p, duration) for s in range(seeds)]
        eta30 = [eta_after(s, p, duration) for s in range(seeds)]
        allerr = [e for r in rr for e in r['_errors']]
        errs_by_p[p] = allerr
        st = common.stats(allerr)
        summary.append({
            'p': p, 'loty': seeds, 'pozycje': sum(r['pozycje'] for r in rr),
            'eta_V_proc': 100 * common.mean([r['eta_V'] for r in rr]),
            'eta_V30_proc': 100 * common.mean(eta30),
            't1_local_sr': common.mean([r['t1_local'] for r in rr]),
            't1_local_std': common.stdev([r['t1_local'] for r in rr]),
            't1_verified_sr': common.mean([r['t1_verified'] for r in rr]),
            't1_verified_std': common.stdev([r['t1_verified'] for r in rr]),
            't1_verified_max': max(r['t1_verified'] for r in rr),
            'blad_sr': st['srednia'], 'blad_p95': st['p95'], 'blad_max': st['max'],
            'odrzucone': sum(r['odrzucone'] for r in rr),
        })
        for r in rr:
            runs.append({k: v for k, v in r.items() if not k.startswith('_')})
    return summary, runs, errs_by_p


def study_ber(bers=(1e-4, 1e-3, 1e-2)):
    out = []
    for ber in bers:
        f = cpr_gen.Flight(0x4CA200, 'TST200', 50.2, 19.8, 9000, 200, 120, 0, None)
        r = cases.run_flight(f, 600, ber=ber, seed=11)
        out.append({'ber': ber, 'ramki_uszkodzone': r['corrupted'],
                    'przyjete_uszkodzone': r['corrupted_accepted'],
                    'pozycje': r['positions'], 'blad_max': max(r['errors'])})
    return out


def study_station(offsets_km=(0, 1, 5, 50, 150, 250, 350, 500), duration=240):
    """T1.4: stacja ustawiona w złym miejscu (przesunięta na północ o d km)."""
    out = []
    for off in offsets_km:
        wrong = common.destination(ST[0], ST[1], 0.0, off * 1000.0) + (ST[2],) \
            if off else ST
        f = cpr_gen.Flight(0x4CA300, 'TST300', 50.25, 20.35, 10000, 230, 60, 0, 100)
        rng = cpr_gen.make_rng(5)
        ev = f.generate(duration, rng)
        d = dec.AdsbDecoder()
        d.set_station(*wrong)
        icao = f'{f.icao:06X}'
        n = nv = wrong_local = 0
        az_err, el_err, pos_err = [], [], []
        for t, frame, kind, truth in ev:
            d.process('*' + frame + ';', t)
            ac = d.aircraft.get(icao)
            if ac and truth and ac['position_time'] == t:
                n += 1
                e = dec.ground_distance_m(ac['lat'], ac['lon'], truth[0], truth[1])
                pos_err.append(e)
                if ac['position_quality'] == dec.POSITION_VERIFIED:
                    nv += 1
                elif e > 1000:
                    wrong_local += 1
                _, az_w, el_w = dec.look_angles(*wrong, ac['lat'], ac['lon'], truth[2])
                _, az_t, el_t = dec.look_angles(*ST, truth[0], truth[1], truth[2])
                da = abs(az_w - az_t)
                az_err.append(min(da, 360 - da))
                el_err.append(abs(el_w - el_t))
        out.append({'przesuniecie_km': off, 'pozycje': n, 'verified': nv,
                    'niezgodne': d.stats['niezgodne'], 'local_bledne': wrong_local,
                    'blad_poz_max_m': max(pos_err) if pos_err else math.nan,
                    'blad_az_max_deg': max(az_err) if az_err else math.nan,
                    'blad_el_max_deg': max(el_err) if el_err else math.nan})
    return out


def study_local_range(dists_km=(100, 200, 300, 320, 330, 340, 350, 360, 380, 400, 440),
                      bearings=(0.0, 90.0), duration=120):
    """T1.5: do jakiej odległości dekodowanie lokalne z pozycją stacji jest poprawne.

    Statek leci prostopadle do kierunku na stację (odległość prawie stała),
    na wysokości 11 km. Liczony jest odsetek pozycji LOCAL z błędem > 1 km.
    """
    out = []
    for b in bearings:
        for dk in dists_km:
            lat, lon = common.destination(ST[0], ST[1], b, dk * 1000.0)
            f = cpr_gen.Flight(0x4CA400, 'TST400', lat, lon, 11000, 230, (b + 90) % 360, 0, 0)
            rng = cpr_gen.make_rng(int(dk) + int(b))
            ev = f.generate(duration, rng)
            d = dec.AdsbDecoder()
            d.set_station(*ST)
            icao = f'{f.icao:06X}'
            n_local = n_local_bad = n_ver = 0
            first_local_err = math.nan
            for t, frame, kind, truth in ev:
                d.process('*' + frame + ';', t)
                ac = d.aircraft.get(icao)
                if ac and truth and ac['position_time'] == t:
                    e = dec.ground_distance_m(ac['lat'], ac['lon'], truth[0], truth[1])
                    if ac['position_quality'] == dec.POSITION_LOCAL:
                        n_local += 1
                        n_local_bad += e > 1000
                        if math.isnan(first_local_err):
                            first_local_err = e
                    elif ac['position_quality'] == dec.POSITION_VERIFIED:
                        n_ver += 1
            ac = d.aircraft.get(icao, {})
            out.append({'kierunek_deg': b, 'odleglosc_km': dk, 'local': n_local,
                        'local_bledne': n_local_bad, 'verified': n_ver,
                        'niezgodne': d.stats['niezgodne'],
                        'blad_1_local_km': first_local_err / 1000.0,
                        'jakosc_koncowa': common.JAKOSC_NAZWY.get(
                            ac.get('position_quality', 0), '?')})
    return out


# --------------------------------------------------------------------------- #
def make_plots(out, loss_summary, errs_by_p, local_range, station):
    plt = common.setup_matplotlib()
    W = os.path.join(out, 'wykresy')

    # 1) histogram błędu pozycji
    fig, ax = plt.subplots(figsize=(common.SZER_PELNA, 2.6))
    bins = [i * 0.25 for i in range(0, 25)]
    for p, col in ((0.0, common.KOLORY['VERIFIED']), (0.3, common.KOLORY['LOCAL'])):
        if p in errs_by_p:
            ax.hist([min(e, 6.0) for e in errs_by_p[p]], bins=bins, alpha=0.6, color=col,
                    label=f'p = {fmt(p, 1)}', density=True)
    ax.set_xlabel('Błąd pozycji $e$ [m]')
    ax.set_ylabel('Gęstość [1/m]')
    ax.legend()
    common.comma_axes(ax)
    common.save_fig(fig, os.path.join(W, 'rys_syn_blad'))

    # 2) czas do pierwszej pozycji vs utrata ramek
    fig, ax = plt.subplots(figsize=(common.SZER_PELNA, 2.8))
    ps = [s['p'] * 100 for s in loss_summary]
    ax.errorbar([x - 0.6 for x in ps], [s['t1_local_sr'] for s in loss_summary],
                yerr=[s['t1_local_std'] for s in loss_summary], fmt='o', capsize=3,
                color=common.KOLORY['LOCAL'], label='pierwsza pozycja (LOCAL)')
    ax.errorbar([x + 0.6 for x in ps], [s['t1_verified_sr'] for s in loss_summary],
                yerr=[s['t1_verified_std'] for s in loss_summary], fmt='s', capsize=3,
                color=common.KOLORY['VERIFIED'], label='pierwsza pozycja VERIFIED')
    ax.set_xticks(ps)
    ax.set_xlabel('Utrata ramek $p$ [%]')
    ax.set_ylabel('Czas od 1. ramki [s]')
    ax.legend(loc='upper left')
    common.comma_axes(ax)
    common.save_fig(fig, os.path.join(W, 'rys_syn_t1poz'))

    # 3) zasięg dekodowania lokalnego
    fig, ax = plt.subplots(figsize=(common.SZER_PELNA, 2.8))
    for b, mk, dx, col, nazwa in ((0.0, 'o', -2.0, common.KOLORY['akcent'], 'kierunek N'),
                                  (90.0, 's', 2.0, common.KOLORY['LOCAL'], 'kierunek E')):
        rows = [r for r in local_range if r['kierunek_deg'] == b]
        ax.plot([r['odleglosc_km'] + dx for r in rows],
                [100 * r['local_bledne'] / r['local'] if r['local'] else 0 for r in rows],
                mk, label=nazwa, linestyle='none', mfc='none', mec=col, mew=1.3)
    ax.axvline(333.4, color=common.KOLORY['linia'], ls='--', lw=0.8)
    ax.text(336, 50, '180 NM', fontsize=8)
    ax.set_xlabel('Odległość statku od stacji [km]')
    ax.set_ylabel('Błędne pozycje LOCAL [%]')
    ax.set_ylim(-5, 105)
    ax.legend(loc='center left')
    common.comma_axes(ax)
    common.save_fig(fig, os.path.join(W, 'rys_syn_zasieg'))

    # 4) błąd kierunku vs błąd pozycji stacji
    fig, ax = plt.subplots(figsize=(common.SZER_PELNA, 2.6))
    rows = [r for r in station if 0 < r['przesuniecie_km'] <= 250]
    ax.plot([r['przesuniecie_km'] for r in rows], [r['blad_az_max_deg'] for r in rows],
            'o', color=common.KOLORY['akcent'], label='azymut')
    ax.plot([r['przesuniecie_km'] for r in rows], [r['blad_el_max_deg'] for r in rows],
            's', color=common.KOLORY['LOCAL'], label='elewacja')
    ax.set_xscale('log')
    ax.set_yscale('log')
    ax.set_xlabel('Błąd pozycji stacji [km]')
    ax.set_ylabel('Maks. błąd kąta [°]')
    ax.legend()
    common.save_fig(fig, os.path.join(W, 'rys_syn_stacja'))

    snippets = [
        ('rys_syn_blad', 'Rozkład błędu pozycji wyznaczonej przez dekoder dla lotów '
         'syntetycznych bez utraty ramek i~przy utracie 30\\% ramek', 'rys:syn_blad'),
        ('rys_syn_t1poz', 'Czas od pierwszej odebranej ramki do pierwszej pozycji '
         '(LOCAL) i~do pierwszej pozycji potwierdzonej (VERIFIED) w~funkcji utraty ramek; '
         'punkty -- średnia, odcinki -- odchylenie standardowe', 'rys:syn_t1poz'),
        ('rys_syn_zasieg', 'Odsetek błędnych pozycji wyznaczonych lokalnie w~funkcji '
         'odległości statku powietrznego od stacji', 'rys:syn_zasieg'),
        ('rys_syn_stacja', 'Maksymalny błąd azymutu i~elewacji w~funkcji błędu położenia '
         'stacji bazowej', 'rys:syn_stacja'),
    ]
    for name, cap, lab in snippets:
        common.write_figure_snippet(os.path.join(W, name + '.tex'), name, cap, lab)


def make_tables(out, loss_summary, ber, station, local_range, case_rows):
    T = os.path.join(out, 'tabele')
    common.write_latex_table(
        os.path.join(T, 'tab_syn_utrata.tex'),
        [r'$p$ [\%]', 'Pozycje', r'$\eta_V$ [\%]', r'$\eta_{V,30}$ [\%]',
         r'$\bar T_{\mathrm{L}}$ [s]', r'$\bar T_{\mathrm{V}}$ [s]', r'$T_{\mathrm{V,max}}$ [s]',
         r'$\bar e$ [m]', r'$e_{95}$ [m]', r'$e_{\max}$ [m]'],
        [[fmt(s['p'] * 100, 0), str(s['pozycje']), fmt(s['eta_V_proc'], 1),
          fmt(s['eta_V30_proc'], 1), fmt(s['t1_local_sr'], 2), fmt(s['t1_verified_sr'], 1),
          fmt(s['t1_verified_max'], 1), fmt(s['blad_sr'], 2), fmt(s['blad_p95'], 2),
          fmt(s['blad_max'], 2)] for s in loss_summary],
        'Wyniki dekodera dla lotów syntetycznych w~funkcji utraty ramek',
        'tab:syn_utrata',
        note=r'$T_{\mathrm{L}}$, $T_{\mathrm{V}}$ -- czas od pierwszej ramki do pierwszej '
             r'pozycji LOCAL i~VERIFIED; $\eta_{V,30}$ -- udział pozycji VERIFIED po '
             r'pierwszych 30~s śledzenia.')
    common.write_latex_table(
        os.path.join(T, 'tab_syn_ber.tex'),
        ['BER [--]', 'Ramki uszkodzone', 'Przyjęte uszkodzone', 'Pozycje', r'$e_{\max}$ [m]'],
        [[f"{b['ber']:.0e}".replace('e-0', 'e-'), str(b['ramki_uszkodzone']),
          str(b['przyjete_uszkodzone']), str(b['pozycje']), fmt(b['blad_max'], 2)]
         for b in ber],
        'Odporność dekodera na przekłamania bitów', 'tab:syn_ber')
    common.write_latex_table(
        os.path.join(T, 'tab_syn_stacja.tex'),
        ['Błąd stacji [km]', 'Pozycje', 'VERIFIED', 'Niezgodne', 'Błędne LOCAL',
         r'$e_{\max}$ [km]', r'$\Delta A_{\max}$ [°]', r'$\Delta E_{\max}$ [°]'],
        [[fmt(r['przesuniecie_km'], 0), str(r['pozycje']), str(r['verified']),
          str(r['niezgodne']), str(r['local_bledne']), fmt(r['blad_poz_max_m'] / 1000, 3),
          fmt(r['blad_az_max_deg'], 2), fmt(r['blad_el_max_deg'], 2)] for r in station],
        'Wpływ błędnej pozycji stacji na pozycje i~kierunek do statku powietrznego',
        'tab:syn_stacja')
    common.write_latex_table(
        os.path.join(T, 'tab_syn_zasieg.tex'),
        ['Kierunek', 'Odległość [km]', 'LOCAL', 'Błędne LOCAL', 'VERIFIED', 'Niezgodne',
         'Jakość końcowa'],
        [['N' if r['kierunek_deg'] == 0 else 'E', fmt(r['odleglosc_km'], 0), str(r['local']),
          str(r['local_bledne']), str(r['verified']), str(r['niezgodne']),
          r['jakosc_koncowa']] for r in local_range],
        'Poprawność dekodowania lokalnego w~funkcji odległości od stacji', 'tab:syn_zasieg')
    common.write_latex_table(
        os.path.join(T, 'tab_przypadki.tex'),
        ['Id', 'Warunek', 'Oczekiwane', 'Uzyskane', 'Wynik'],
        [[r['id'], r['warunek'], r['oczekiwane'], r['uzyskane'],
          'zaliczony' if r['wynik'] else 'NIE'] for r in case_rows],
        'Przypadki brzegowe i~strukturalne -- wyniki testów', 'tab:przypadki',
        align='l p{5.2cm} p{3.2cm} p{3.2cm} l')


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--ziarna', type=int, default=20, help='liczba lotów na wartość p')
    ap.add_argument('--czas', type=float, default=300.0, help='czas lotu [s]')
    ap.add_argument('--wyniki', default=os.path.join(common.BADANIA_DIR, 'wyniki', 'syntetyczne'))
    a = ap.parse_args()
    out = common.ensure_dir(a.wyniki)

    print('Przypadki brzegowe (Tabela B)...')
    case_rows = cases.all_rows()
    n_ok = sum(r['wynik'] for r in case_rows)
    print(f'  zaliczone {n_ok}/{len(case_rows)}')
    print(f'Utrata ramek (Tabela A), {a.ziarna} lotów x 4 wartości p...')
    loss_summary, runs, errs_by_p = study_loss(a.ziarna, a.czas)
    print('Przekłamania bitów (T1.3)...')
    ber = study_ber()
    print('Błędna pozycja stacji (T1.4)...')
    station = study_station()
    print('Zasięg dekodowania lokalnego (T1.5)...')
    local_range = study_local_range()

    C = os.path.join(out, 'csv')
    common.write_csv(os.path.join(C, 'utrata_podsumowanie.csv'), loss_summary)
    common.write_csv(os.path.join(C, 'utrata_loty.csv'), runs)
    common.write_csv(os.path.join(C, 'ber.csv'), ber)
    common.write_csv(os.path.join(C, 'stacja.csv'), station)
    common.write_csv(os.path.join(C, 'zasieg_lokalny.csv'), local_range)
    common.write_csv(os.path.join(C, 'przypadki.csv'), case_rows)
    make_tables(out, loss_summary, ber, station, local_range, case_rows)
    make_plots(out, loss_summary, errs_by_p, local_range, station)
    common.write_json(os.path.join(out, 'podsumowanie.json'), {
        'przypadki_zaliczone': n_ok, 'przypadki_wszystkie': len(case_rows),
        'utrata': loss_summary, 'ber': ber, 'stacja': station, 'zasieg_lokalny': local_range})

    print('\nTabela A (skrót):')
    for s in loss_summary:
        print(f"  p={s['p']:.1f}: eta_V={s['eta_V_proc']:.1f}%  eta_V30={s['eta_V30_proc']:.1f}%  "
              f"T_L={s['t1_local_sr']:.2f}s  T_V={s['t1_verified_sr']:.1f}s  "
              f"e_max={s['blad_max']:.2f} m")
    print(f'\nWyniki zapisano w: {out}')


if __name__ == '__main__':
    main()
