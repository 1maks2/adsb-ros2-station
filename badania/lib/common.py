"""Wspólne narzędzia dla skryptów badawczych.

- ścieżki (import adsb_decoder.py / clock_offset.py z pakietu ROS bez ROS),
- styl wykresów zgodny z pracą (krój szeryfowy podobny do Times, przecinek
  dziesiętny, szerokość pod \\textwidth = 16 cm),
- zapis tabel do CSV i LaTeX (booktabs),
- funkcje geometryczne (ENU) i statystyczne.
"""
import csv
import json
import math
import os
import sys

# --- Ścieżki --------------------------------------------------------------- #
BADANIA_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_DIR = os.path.dirname(BADANIA_DIR)
PKG_DIR = os.path.join(REPO_DIR, 'ros2_ws', 'src', 'aircraft_tracker')
if PKG_DIR not in sys.path:
    sys.path.insert(0, PKG_DIR)

# Teraz można: from aircraft_tracker.adsb_decoder import AdsbDecoder
from aircraft_tracker import adsb_decoder as dec  # noqa: E402

NAN = float('nan')

# Stacja przykładowa do symulacji (zaokrąglona, NIE prawdziwa lokalizacja stacji)
STACJA_PRZYKLAD = (50.0, 20.0, 250.0)

JAKOSC_NAZWY = {0: 'brak', 1: 'LOCAL', 2: 'GLOBAL', 3: 'VERIFIED'}


# --- Liczby i tekst -------------------------------------------------------- #
def isnan(x):
    try:
        return x is None or math.isnan(x)
    except TypeError:
        return False


def fmt(x, digits=1):
    """Liczba z przecinkiem dziesiętnym (jak w pracy); NaN/None -> '--'."""
    if isinstance(x, str):
        return x
    if isnan(x):
        return '--'
    if isinstance(x, bool):
        return 'tak' if x else 'nie'
    if isinstance(x, int):
        return f'{x:d}'
    return f'{x:.{digits}f}'.replace('.', ',')


def percentile(values, p):
    """Percentyl p (0-100) z interpolacją liniową; pusta lista -> NaN."""
    v = sorted(x for x in values if not isnan(x))
    if not v:
        return NAN
    k = (len(v) - 1) * p / 100.0
    f = math.floor(k)
    c = min(f + 1, len(v) - 1)
    return v[f] + (v[c] - v[f]) * (k - f)


def mean(values):
    v = [x for x in values if not isnan(x)]
    return sum(v) / len(v) if v else NAN


def rms(values):
    v = [x for x in values if not isnan(x)]
    return math.sqrt(sum(x * x for x in v) / len(v)) if v else NAN


def stdev(values):
    v = [x for x in values if not isnan(x)]
    if len(v) < 2:
        return NAN
    m = sum(v) / len(v)
    return math.sqrt(sum((x - m) ** 2 for x in v) / (len(v) - 1))


def stats(values):
    """Zestaw statystyk używany w tabelach błędów (W1)."""
    v = [x for x in values if not isnan(x)]
    return {
        'n': len(v),
        'srednia': mean(v),
        'mediana': percentile(v, 50),
        'rms': rms(v),
        'p95': percentile(v, 95),
        'max': max(v) if v else NAN,
    }


# --- Geometria ------------------------------------------------------------- #
def enu(st_lat, st_lon, st_alt, lat, lon, alt):
    """Wschód, północ, góra [m] punktu względem stacji (ten sam model co w dekoderze)."""
    sx, sy, sz = dec.geodetic_to_ecef(st_lat, st_lon, st_alt)
    ax, ay, az = dec.geodetic_to_ecef(lat, lon, alt)
    dx, dy, dz = ax - sx, ay - sy, az - sz
    la, lo = math.radians(st_lat), math.radians(st_lon)
    e = -math.sin(lo) * dx + math.cos(lo) * dy
    n = (-math.sin(la) * math.cos(lo) * dx - math.sin(la) * math.sin(lo) * dy
         + math.cos(la) * dz)
    u = (math.cos(la) * math.cos(lo) * dx + math.cos(la) * math.sin(lo) * dy
         + math.sin(la) * dz)
    return e, n, u


def destination(lat, lon, bearing_deg, dist_m):
    """Punkt odległy o dist_m w kierunku bearing_deg (sfera o promieniu dekodera)."""
    r = dec.EARTH_R
    p1, l1, b = math.radians(lat), math.radians(lon), math.radians(bearing_deg)
    d = dist_m / r
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(b))
    l2 = l1 + math.atan2(math.sin(b) * math.sin(d) * math.cos(p1),
                         math.cos(d) - math.sin(p1) * math.sin(p2))
    return math.degrees(p2), (math.degrees(l2) + 540.0) % 360.0 - 180.0


def radio_horizon_km(h_station_m, h_aircraft_m, r_km=6371.0):
    """Wzór (eq:zasieg) z rozdziału 2: d = R(acos(R/(R+hr)) + acos(R/(R+ht)))."""
    hr, ht = h_station_m / 1000.0, h_aircraft_m / 1000.0
    a = math.acos(r_km / (r_km + max(hr, 0.0)))
    b = math.acos(r_km / (r_km + max(ht, 0.0)))
    return r_km * (a + b)


# --- Zapis wyników --------------------------------------------------------- #
def ensure_dir(path):
    os.makedirs(path, exist_ok=True)
    return path


def write_csv(path, rows, columns=None):
    """Zapisuje listę słowników do CSV (kropka dziesiętna - do dalszej obróbki)."""
    ensure_dir(os.path.dirname(path) or '.')
    if columns is None:
        columns = list(rows[0].keys()) if rows else []
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction='ignore')
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return path


def read_csv(path):
    with open(path, newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def write_json(path, obj):
    ensure_dir(os.path.dirname(path) or '.')

    def default(o):
        if isinstance(o, float) and math.isnan(o):
            return None
        return str(o)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(obj, f, indent=2, ensure_ascii=False, default=default)
    return path


def latex_escape(s):
    rep = {'\\': r'\textbackslash{}', '&': r'\&', '%': r'\%', '$': r'\$',
           '#': r'\#', '_': r'\_', '{': r'\{', '}': r'\}', '~': r'\textasciitilde{}',
           '^': r'\^{}'}
    return ''.join(rep.get(c, c) for c in str(s))


def write_latex_table(path, header, rows, caption, label, align=None, note=None):
    """Tabela w stylu booktabs, podpis NAD tabelą (zasady pracy).

    header - lista nagłówków (surowy LaTeX, np. r'$e_{\\max}$ [m]'),
    rows   - lista list komórek (tekst już sformatowany funkcją fmt; zostanie
             zabezpieczony przed znakami specjalnymi LaTeX-a).
    """
    ensure_dir(os.path.dirname(path) or '.')
    if align is None:
        align = 'l' + 'r' * (len(header) - 1)
    lines = [
        '% Wygenerowano automatycznie (badania/). Wklej przez \\input{...}.',
        '% Wymaga pakietu booktabs (jest w preambule pracy).',
        '\\begin{table}[!htb]',
        '  \\centering',
        f'  \\caption{{{caption}}}',
        f'  \\label{{{label}}}',
        f'  \\begin{{tabular}}{{{align}}}',
        '    \\toprule',
        '    ' + ' & '.join(header) + ' \\\\',
        '    \\midrule',
    ]
    for r in rows:
        lines.append('    ' + ' & '.join(latex_escape(c) for c in r) + ' \\\\')
    lines += ['    \\bottomrule', '  \\end{tabular}']
    if note:
        lines.append(f'  \\par\\smallskip\\footnotesize {note}')
    lines.append('\\end{table}')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    return path


# --- Wykresy --------------------------------------------------------------- #
SZER_PELNA = 16.0 / 2.54   # \textwidth pracy = 16 cm
SZER_POL = 7.8 / 2.54

KOLORY = {  # paleta czytelna także dla osób z zaburzeniami widzenia barw
    'VERIFIED': '#1b9e77', 'LOCAL': '#d95f02', 'GLOBAL': '#7570b3', 'brak': '#999999',
    'SBS': '#e7298a', 'linia': '#333333', 'akcent': '#1f78b4',
}


def setup_matplotlib():
    """Konfiguruje matplotlib: bez okna (Agg), krój STIX ~ Times, rozmiary jak w pracy."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({
        'font.family': 'STIXGeneral',
        'mathtext.fontset': 'stix',
        'font.size': 10,
        'axes.labelsize': 10,
        'axes.titlesize': 10,
        'legend.fontsize': 9,
        'xtick.labelsize': 9,
        'ytick.labelsize': 9,
        'axes.grid': True,
        'grid.alpha': 0.3,
        'figure.dpi': 120,
        'savefig.dpi': 300,
        'savefig.bbox': 'tight',
        'axes.spines.top': False,
        'axes.spines.right': False,
        'pdf.fonttype': 42,
    })
    return plt


def comma_axes(ax, x=True, y=True):
    """Przecinek dziesiętny na osiach liniowych."""
    from matplotlib.ticker import FuncFormatter

    def f(v, _pos):
        s = f'{v:g}'
        return s.replace('.', ',').replace('-', '\u2212')
    if x and ax.get_xscale() == 'linear':
        ax.xaxis.set_major_formatter(FuncFormatter(f))
    if y and ax.get_yscale() == 'linear':
        ax.yaxis.set_major_formatter(FuncFormatter(f))


def save_fig(fig, path_no_ext):
    """Zapis PDF (wektor - do pracy) i PNG (podgląd)."""
    ensure_dir(os.path.dirname(path_no_ext) or '.')
    fig.savefig(path_no_ext + '.pdf')
    fig.savefig(path_no_ext + '.png')
    import matplotlib.pyplot as plt
    plt.close(fig)
    return path_no_ext + '.pdf'


def write_figure_snippet(path, pdf_name, caption, label, width='\\textwidth'):
    """Gotowy fragment LaTeX z rysunkiem (podpis POD rysunkiem)."""
    with open(path, 'w', encoding='utf-8') as f:
        f.write('% Wygenerowano automatycznie. Skopiuj PDF do img/ w Overleaf.\n'
                '\\begin{figure}[!htb]\n  \\centering\n'
                f'  \\includegraphics[width={width}]{{{pdf_name}}}\n'
                f'  \\caption{{{caption}}}\n  \\label{{{label}}}\n\\end{{figure}}\n')
