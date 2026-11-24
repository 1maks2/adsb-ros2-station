#!/usr/bin/env python3
"""Zestawienie kilku sesji (Tabela C / D) i wykresy porównawcze (T5.3, T7.1, T8.1).

Wejście: foldery wyników z analiza_sesji.py (każdy ma podsumowanie.json).
Opcjonalnie sesje.csv - katalog sesji (opis miejsca, anteny, wentylatora...).

Przykłady:
  python3 porownanie_sesji.py wyniki/R-02 wyniki/R-03 wyniki/R-04
  python3 porownanie_sesji.py wyniki/R-05 wyniki/R-06 --nazwa antena    # T5.3: w/poza obudową
  python3 porownanie_sesji.py wyniki/R-07 wyniki/R-08 --nazwa wentylator # T7.1

Wyniki: wyniki/porownanie_<nazwa>/  (tabele/tab_sesje_<nazwa>.tex, wykresy, CSV)
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import common  # noqa: E402
from lib.common import fmt  # noqa: E402

WIERSZE = [  # (etykieta LaTeX, funkcja -> tekst)
    ('Data / opis', lambda r, k: k.get('opis', '') or r.get('notatka', '')),
    ('Czas trwania [h]', lambda r, k: fmt(r['czas_trwania_h'], 2)),
    ('Dane [MB/h]', lambda r, k: fmt(r['MB_na_h'], 1)),
    ('Ramki / ramki DF17', lambda r, k: f"{r['ramki']['ramki']} / {r['ramki']['df17']}"),
    ('Statki DF17 / z pozycją', lambda r, k: f"{r['statki_df17']} / {r['statki_z_pozycja']}"),
    (r'$\kappa$ dekoder / dump1090 [\%]',
     lambda r, k: f"{fmt(r['W4_kappa_dek_proc'], 1)} / {fmt(r['W4_kappa_sbs_proc'], 1)}"),
    (r'$\eta_V$ [\%]', lambda r, k: fmt(r['W2_eta_V_proc'], 1)),
    (r'$\eta_R$ [\%]', lambda r, k: fmt(r['W2_eta_R_proc'], 2)),
    ('Niezgodności metod', lambda r, k: str(r.get('W2_niezgodne', '--'))),
    (r'$\tilde T_{\mathrm{L}}$ / $\tilde T_{\mathrm{V}}$ / $\tilde T_{\mathrm{SBS}}$ [s]',
     lambda r, k: f"{fmt(r['W3_T1_local_s_mediana'], 2)} / {fmt(r['W3_T1_verified_s_mediana'], 1)}"
                  f" / {fmt(r['W3_T1_sbs_s_mediana'], 1)}"),
    ('Dekoder--dump1090, mediana [m]', lambda r, k: fmt(r['W1_sbs']['mediana'], 2)),
    ('Zasięg maks. / P95 [km]',
     lambda r, k: f"{fmt(r['W7_zasieg_max_km'], 0)} / {fmt(r['W7_zasieg_p95_km'], 0)}"),
    (r'$\hat\delta$ / $\sigma_\delta$ [s]',
     lambda r, k: f"{fmt(r['czas'].get('delta_hat'), 3)} / {fmt(r['czas'].get('sigma'), 3)}"
     if r['czas'].get('dostepny') else '--'),
    ('Skoki czasu GPS', lambda r, k: str(len(r['czas'].get('skoki', [])))
     if r['czas'].get('dostepny') else '--'),
    (r'$\eta_{\mathrm{GPS}}$ [\%]', lambda r, k: fmt(r['eta_gps_proc'], 1)),
    ('Temp. CPU maks. / śr. [°C]', lambda r, k: f"{fmt(r['temp_max'], 1)} / {fmt(r['temp_sr'], 1)}"),
    ('Niskie napięcie (zdarzenia)', lambda r, k: str(r['niskie_napiecie_zdarzenia'])),
    ('Utracone nagranie [min]', lambda r, k: fmt(r.get('utracone_min'), 1)),
    ('Plik metadata.yaml', lambda r, k: 'tak' if r['metadata_yaml'] else 'nie'),
]


def load_catalog(path):
    if not path or not os.path.exists(path):
        return {}
    return {r['id']: r for r in common.read_csv(path)}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('wyniki', nargs='+', help='foldery wyniki/<ID> z analiza_sesji.py')
    ap.add_argument('--nazwa', default='sesje', help='nazwa zestawienia (część nazw plików)')
    ap.add_argument('--katalog', default=os.path.join(common.BADANIA_DIR, 'sesje.csv'))
    a = ap.parse_args()
    out = common.ensure_dir(os.path.join(common.BADANIA_DIR, 'wyniki', f'porownanie_{a.nazwa}'))
    kat = load_catalog(a.katalog)
    res = []
    for p in a.wyniki:
        with open(os.path.join(p, 'podsumowanie.json'), encoding='utf-8') as f:
            res.append(json.load(f))
    ids = [r['id'] for r in res]

    rows = [[lab] + [fn(r, kat.get(r['id'], {})) for r in res] for lab, fn in WIERSZE]
    common.write_csv(os.path.join(out, 'csv', f'sesje_{a.nazwa}.csv'),
                     [dict(zip(['wielkosc'] + ids, r)) for r in rows], ['wielkosc'] + ids)
    path = os.path.join(out, 'tabele', f'tab_sesje_{a.nazwa}.tex')
    common.write_latex_table(path, ['Wielkość'] + ids, rows,
                             'Zestawienie sesji pomiarowych', f'tab:sesje_{a.nazwa}',
                             align='l' + 'r' * len(ids))
    with open(path, encoding='utf-8') as f:            # matematyka w 1. kolumnie bez escape
        txt = f.read()
    for lab, _ in WIERSZE:
        txt = txt.replace(common.latex_escape(lab), lab)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(txt)

    plt = common.setup_matplotlib()
    import numpy as np
    W = os.path.join(out, 'wykresy')
    markers = ['o', 's', '^', 'D', 'v', 'P']
    # zasięg biegunowy (T5.3: antena w obudowie / na zewnątrz, wysokość)
    fig = plt.figure(figsize=(common.SZER_POL * 1.4, common.SZER_POL * 1.4))
    ax = fig.add_subplot(projection='polar')
    ax.set_theta_zero_location('N')
    ax.set_theta_direction(-1)
    th = np.deg2rad(np.arange(0, 370, 10) + 5)
    for i, r in enumerate(res):
        s = r.get('W7_sektory_km') or []
        if s and max(s) > 0:
            ax.plot(th, s + s[:1], marker=markers[i % 6], ms=2.5, lw=1,
                    label=f"{r['id']} {kat.get(r['id'], {}).get('opis', '')}".strip())
    ax.legend(loc='lower left', bbox_to_anchor=(-0.15, -0.25), fontsize=8)
    ax.tick_params(axis='y', labelsize=7)
    ax.set_title('Maks. zasięg [km] w sektorach 10°', fontsize=9, pad=14)
    common.save_fig(fig, os.path.join(W, f'rys_zasieg_{a.nazwa}'))
    common.write_figure_snippet(os.path.join(W, f'rys_zasieg_{a.nazwa}.tex'),
                                f'rys_zasieg_{a.nazwa}', 'Porównanie maksymalnego zasięgu '
                                'odbioru w~sektorach co \\ang{10}', f'rys:zasieg_{a.nazwa}')
    # temperatura w funkcji czasu od startu (T7.1)
    fig, ax = plt.subplots(figsize=(common.SZER_PELNA, 2.6))
    any_t = False
    for i, (p, r) in enumerate(zip(a.wyniki, res)):
        f = os.path.join(p, 'dane', 'temp_cpu.csv')
        if os.path.exists(f):
            rows_t = common.read_csv(f)
            if rows_t:
                t0 = float(rows_t[0]['t_log'])
                ax.plot([(float(x['t_log']) - t0) / 3600 for x in rows_t],
                        [float(x['temp']) for x in rows_t], lw=0.7,
                        label=f"{r['id']} {kat.get(r['id'], {}).get('opis', '')}".strip())
                any_t = True
    if any_t:
        ax.axhline(80, ls='--', lw=0.8, color='0.3')
        ax.set_xlabel('Czas od uruchomienia [h]')
        ax.set_ylabel('Temperatura CPU [°C]')
        ax.legend(fontsize=8)
        common.comma_axes(ax)
        common.save_fig(fig, os.path.join(W, f'rys_temp_{a.nazwa}'))
        common.write_figure_snippet(os.path.join(W, f'rys_temp_{a.nazwa}.tex'),
                                    f'rys_temp_{a.nazwa}', 'Temperatura procesora RPi '
                                    'w~porównywanych sesjach', f'rys:temp_{a.nazwa}')
    print(f'Zapisano zestawienie {len(res)} sesji w {out}')


if __name__ == '__main__':
    main()
