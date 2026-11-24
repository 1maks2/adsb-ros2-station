#!/usr/bin/env python3
"""Tabela i wykres obciążenia RPi (T3.2, T7.1) z plików monitor_cpu.py i benchmark.

Przykład:
  python3 wykres_obciazenia.py wyniki/rpi/cpu_20261125_1200Z.csv \\
          --benchmark wyniki/rpi/benchmark_rpi.json --id R-02
Wyniki: wyniki/<ID>/obciazenie/ (tab_obciazenie_<ID>.tex, rys_obciazenie_<ID>.pdf)
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import common  # noqa: E402
from lib.common import fmt  # noqa: E402

GRUPY = ['dump1090', 'sdr_node', 'decoder_node', 'display_node', 'gps_node',
         'power_monitor_node', 'rosbag2']


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('csv', help='plik z rpi/monitor_cpu.py')
    ap.add_argument('--benchmark', help='JSON z benchmark_dekodera.py (uruchomionego na RPi)')
    ap.add_argument('--id', default='rpi')
    a = ap.parse_args()
    rows = common.read_csv(a.csv)
    out = common.ensure_dir(os.path.join(common.BADANIA_DIR, 'wyniki', a.id, 'obciazenie'))
    col = {k: [float(r[k]) for r in rows] for k in rows[0]}
    tab = [[g, fmt(common.mean(col[g]), 1), fmt(common.percentile(col[g], 95), 1),
            fmt(max(col[g]), 1)] for g in GRUPY if g in col]
    tab.append(['RPi razem (4 rdzenie = 100 %)', fmt(common.mean(col['cpu_calk_proc']), 1),
                fmt(common.percentile(col['cpu_calk_proc'], 95), 1), fmt(max(col['cpu_calk_proc']), 1)])
    tab.append(['Temperatura CPU [°C]', fmt(common.mean(col['temp_C']), 1),
                fmt(common.percentile(col['temp_C'], 95), 1), fmt(max(col['temp_C']), 1)])
    tab.append(['Pamięć RAM zajęta [MB]', fmt(common.mean(col['ram_MB']), 0),
                fmt(common.percentile(col['ram_MB'], 95), 0), fmt(max(col['ram_MB']), 0)])
    note = None
    if a.benchmark:
        with open(a.benchmark, encoding='utf-8') as f:
            b = json.load(f)
        s = b['czas_ramki_us']
        note = (f"Czas przetwarzania jednej ramki przez dekoder ({b['platforma']}): "
                f"średnio {fmt(s['srednia'], 1)}~\\textmu s, P99 {fmt(b['p99_us'], 1)}~\\textmu s; "
                f"w~szczycie {fmt(b['szczyt_ramek_na_s'], 0)} ramek/s odstęp wynosi "
                f"{fmt(b['odstep_w_szczycie_us'], 0)}~\\textmu s.")
    common.write_latex_table(os.path.join(out, f'tab_obciazenie_{a.id}.tex'),
                             ['Proces', r'Średnio [\%]', r'P95 [\%]', r'Maks. [\%]'], tab,
                             f'Obciążenie procesora RPi (w~\\% jednego rdzenia) -- {a.id}',
                             f'tab:obciazenie_{a.id.lower().replace("-", "")}', note=note)
    common.write_csv(os.path.join(out, f'obciazenie_{a.id}.csv'),
                     [dict(zip(['proces', 'srednio', 'p95', 'max'], r)) for r in tab])

    plt = common.setup_matplotlib()
    t0 = col['t_utc'][0]
    x = [(t - t0) / 60 for t in col['t_utc']]
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(common.SZER_PELNA, 4.2), sharex=True)
    for g in GRUPY:
        if g in col and max(col[g]) > 0.5:
            ax1.plot(x, col[g], lw=0.8, label=g)
    ax1.set_ylabel('CPU [% rdzenia]')
    if ax1.get_legend_handles_labels()[0]:
        ax1.legend(fontsize=7, ncol=3)
    ax2.plot(x, col['temp_C'], lw=0.8, color=common.KOLORY['LOCAL'])
    ax2.set_ylabel('Temperatura [°C]')
    ax2.set_xlabel('Czas od początku pomiaru [min]')
    for ax in (ax1, ax2):
        common.comma_axes(ax)
    common.save_fig(fig, os.path.join(out, f'rys_obciazenie_{a.id}'))
    common.write_figure_snippet(os.path.join(out, f'rys_obciazenie_{a.id}.tex'),
                                f'rys_obciazenie_{a.id}', 'Obciążenie procesora przez procesy '
                                f'stacji i~temperatura CPU -- {a.id}',
                                f'rys:obciazenie_{a.id.lower().replace("-", "")}')
    print(f'Zapisano w {out}')


if __name__ == '__main__':
    main()
