"""Przypadki testowe (brzegowe i strukturalne) - wspólne dla pytest i Tabeli B.

Każda funkcja case_* zwraca listę wierszy:
    {'id', 'scenariusz', 'warunek', 'oczekiwane', 'uzyskane', 'wynik' (bool)}
pytest sprawdza, czy wszystkie mają wynik == True, a badanie_syntetyczne.py
zapisuje je jako tabelę "przypadek - oczekiwane - uzyskane - zaliczony".
Dzięki temu tabela w pracy i testy automatyczne pochodzą z TEGO SAMEGO kodu.
"""
import calendar
import math
import sys
import types

from . import common, cpr_gen
from .common import dec, fmt

ST = common.STACJA_PRZYKLAD


def row(id_, scen, warunek, oczek, uzysk, ok):
    return {'id': id_, 'scenariusz': scen, 'warunek': warunek,
            'oczekiwane': oczek, 'uzyskane': uzysk, 'wynik': bool(ok)}


def run_flight(flight, duration, station=ST, seed=1, loss=0.0, ber=0.0):
    """Przepuszcza wygenerowany lot przez AdsbDecoder. Zwraca słownik z wynikami."""
    rng = cpr_gen.make_rng(seed)
    ev = flight.generate(duration, rng)
    if loss > 0:
        ev = cpr_gen.apply_loss(ev, loss, rng)
    d = dec.AdsbDecoder()
    if station is not None:
        d.set_station(*station)
    icao = f'{flight.icao:06X}'
    out = {'errors': [], 'qualities': [], 't_first_frame': None, 't_first_pos': None,
           't_first_verified': None, 'corrupted': 0, 'corrupted_accepted': 0,
           'local_wrong': 0, 'positions': 0}
    stats_total = dec.AdsbDecoder._empty_stats()
    for t, frame, kind, truth in ev:
        orig = frame
        if ber > 0:
            frame, nbits = cpr_gen.flip_bits(frame, ber, rng)
            if nbits:
                out['corrupted'] += 1
        res = d.process('*' + frame + ';', t)
        if res is not None and frame != orig:
            out['corrupted_accepted'] += 1
        if res == icao and out['t_first_frame'] is None:
            out['t_first_frame'] = t
        ac = d.aircraft.get(icao)
        if ac is not None and truth is not None and ac['position_time'] == t:
            err = dec.ground_distance_m(ac['lat'], ac['lon'], truth[0], truth[1])
            out['errors'].append(err)
            out['qualities'].append(ac['position_quality'])
            out['positions'] += 1
            if ac['position_quality'] == dec.POSITION_LOCAL and err > 1000:
                out['local_wrong'] += 1
            if out['t_first_pos'] is None:
                out['t_first_pos'] = t
            if out['t_first_verified'] is None and ac['position_quality'] == dec.POSITION_VERIFIED:
                out['t_first_verified'] = t
    for k, v in d.stats.items():
        stats_total[k] += v
    out['stats'] = stats_total
    ac = d.aircraft.get(icao)
    out['final_quality'] = ac['position_quality'] if ac else 0
    out['final_err'] = (dec.ground_distance_m(ac['lat'], ac['lon'], ev[-1][3][0], ev[-1][3][1])
                        if ac and ac['position_quality'] and ev[-1][3] else float('nan'))
    out['first_pos_frame_t'] = next((e[0] for e in ev if e[2].startswith('pos')), None)
    return out


# --- T1.1 czysty lot ------------------------------------------------------ #
def case_clean_flight():
    f = cpr_gen.Flight(0x4CA123, 'TST123', 50.3, 20.4, 10000, 230, 45, 0, 100)
    r = run_flight(f, 180)
    emax = max(r['errors'])
    t1 = r['t_first_pos'] - r['first_pos_frame_t']
    return [
        row('T1.1a', 'lot syntetyczny bez zakłóceń', 'maks. błąd pozycji',
            '≤ 10 m', f'{fmt(emax, 2)} m', emax <= 10),
        row('T1.1b', 'lot syntetyczny bez zakłóceń',
            'czas od 1. ramki pozycyjnej do 1. pozycji', '0 s (dekodowanie lokalne)',
            f'{fmt(t1, 2)} s', abs(t1) < 1e-9),
        row('T1.1c', 'lot syntetyczny bez zakłóceń', 'osiągnięcie jakości VERIFIED',
            'tak', 'tak' if r['t_first_verified'] is not None else 'nie',
            r['t_first_verified'] is not None),
        row('T1.1d', 'lot syntetyczny bez zakłóceń', 'pozycje odrzucone',
            '0', str(r['stats']['niezgodne'] + r['stats']['skoki']
                     + r['stats']['poza_zasiegiem']),
            r['stats']['niezgodne'] + r['stats']['skoki'] + r['stats']['poza_zasiegiem'] == 0),
    ]


# --- T1.3 przekłamania bitów ----------------------------------------------- #
def case_bit_errors(ber=1e-2):
    f = cpr_gen.Flight(0x4CA124, 'TST124', 50.2, 19.8, 9000, 200, 120, 0, None)
    r = run_flight(f, 300, ber=ber, seed=7)
    return [row('T1.3', f'przekłamania bitów, BER = {ber:g}'.replace('.', ','),
                f'ramki uszkodzone przyjęte jako poprawne (z {r["corrupted"]})',
                '0', str(r['corrupted_accepted']), r['corrupted_accepted'] == 0)]


# --- T1.4 błędna pozycja stacji ------------------------------------------- #
def case_wrong_station(shift_km=500):
    f = cpr_gen.Flight(0x4CA125, 'TST125', 50.3, 20.3, 10000, 230, 90, 0, 100)
    wrong = common.destination(ST[0], ST[1], 0.0, shift_km * 1000) + (ST[2],)
    r = run_flight(f, 180, station=wrong)
    nv = sum(1 for q in r['qualities'] if q == dec.POSITION_VERIFIED)
    ok = r['stats']['niezgodne'] > 0 and nv == 0
    qf, ef = r['final_quality'], r['final_err']
    if shift_km > 450:     # globalna poza filtrem zasięgu względem złej stacji
        exp, ok2 = 'brak pozycji (NONE)', qf == dec.POSITION_NONE
    else:
        exp, ok2 = 'GLOBAL, błąd ≤ 10 m', qf == dec.POSITION_GLOBAL and ef <= 10
    return [row('T1.4', f'stacja przesunięta o {shift_km} km',
                'wykrycie niezgodności metod, brak VERIFIED',
                'niezgodne > 0, VERIFIED = 0',
                f'niezgodne = {r["stats"]["niezgodne"]}, VERIFIED = {nv}', ok),
            row('T1.4b', f'stacja przesunięta o {shift_km} km',
                'pozycja na końcu lotu', exp,
                f'{common.JAKOSC_NAZWY[qf]}' + ('' if common.isnan(ef) else f', {fmt(ef, 1)} m'),
                ok2)]


def case_wrong_station_400():
    return case_wrong_station(400)


# --- T1.5 statek poza zasięgiem jednoznacznego dekodowania lokalnego -------- #
def case_far_aircraft(dist_km=360):
    lat, lon = common.destination(ST[0], ST[1], 0.0, dist_km * 1000)
    f = cpr_gen.Flight(0x4CA127, 'TST127', lat, lon, 11000, 230, 90, 0, 0)
    r = run_flight(f, 120)
    q_end, e_end = r['final_quality'], r['final_err']
    return [row('T1.5c', f'statek {dist_km} km od stacji (poza 180 NM)',
                'pozycja po rozruchu metody globalnej',
                'GLOBAL, błąd ≤ 10 m (zła pozycja LOCAL zastąpiona)',
                f'{common.JAKOSC_NAZWY[q_end]}, {fmt(e_end, 1)} m',
                q_end == dec.POSITION_GLOBAL and e_end <= 10)]


# --- Atrapy pyModeS do testów strukturalnych (T1.5, T1.6) ------------------ #
class _FakePipe:
    """Udaje pyModeS.PipeDecoder: zwraca podany słownik (np. pozycję globalną)."""

    def __init__(self):
        self.next = {}

    def decode(self, hexmsg, timestamp=None):
        base = {'crc_valid': True, 'icao': 'ABC123', 'bds': '0,5', 'typecode': 11,
                'altitude': 30000}
        base.update(self.next)
        return base


class _patched_local:
    """Kontekst podmieniający dekodowanie lokalne (pyModeS.decode w adsb_decoder)."""

    def __init__(self, func):
        self.func = func

    def __enter__(self):
        self.orig = dec.pyModeS.decode
        dec.pyModeS.decode = self.func
        return self

    def __exit__(self, *a):
        dec.pyModeS.decode = self.orig


_ANY_FRAME = '*' + cpr_gen.frame_position(0xABC123, 50.0, 20.0, 30000, 0) + ';'


def case_range_limit():
    rows = []
    for dist_km, accept in ((449.0, True), (451.0, False)):
        lat, lon = common.destination(ST[0], ST[1], 90.0, dist_km * 1000)
        d = dec.AdsbDecoder()
        d.set_station(*ST)
        d.pipe = _FakePipe()
        d.pipe.next = {'latitude': lat, 'longitude': lon}
        with _patched_local(lambda *a, **k: {}):   # brak wyniku lokalnego
            d.process(_ANY_FRAME, 0.0)
        got = d.aircraft['ABC123']['position_quality'] == dec.POSITION_GLOBAL
        rows.append(row('T1.5', f'pozycja globalna {fmt(dist_km, 0)} km od stacji',
                        'filtr zasięgu 450 km', 'przyjęta' if accept else 'odrzucona',
                        'przyjęta' if got else 'odrzucona', got == accept))
    return rows


def case_jump_limit():
    """Granica kontroli skoku: 600 m/s * dt + 1000 m (dt = 10 s -> 7000 m)."""
    rows = []
    for dist_m, accept in ((6900.0, True), (7100.0, False)):
        p0 = common.destination(ST[0], ST[1], 0.0, 20000)
        p1 = common.destination(p0[0], p0[1], 90.0, dist_m)
        seq = [p0, p1]
        d = dec.AdsbDecoder()
        d.set_station(*ST)
        d.pipe = _FakePipe()

        def local(*a, **k):
            p = seq.pop(0)
            return {'latitude': p[0], 'longitude': p[1]}
        with _patched_local(local):
            d.process(_ANY_FRAME, 0.0)
            d.process(_ANY_FRAME, 10.0)
        got = d.aircraft['ABC123']['position_time'] == 10.0
        rows.append(row('T1.6', f'skok o {fmt(dist_m, 0)} m po 10 s (LOCAL)',
                        'kontrola skoku (granica 7000 m)',
                        'przyjęta' if accept else 'odrzucona',
                        'przyjęta' if got else 'odrzucona', got == accept))
    return rows


# --- T1.7 przejście przez granicę stref NL --------------------------------- #
def case_nl_crossing():
    trans = cpr_gen.nl_transitions(ST[0], ST[0] + 1.0)
    lat_t = trans[0][0]
    start = (lat_t - 0.15, ST[1])           # 0,15 deg na południe od granicy
    f = cpr_gen.Flight(0x4CA126, 'TST126', start[0], start[1], 10000, 230, 0, 0, None)
    r = run_flight(f, 180)
    emax = max(r['errors'])
    bad = r['stats']['niezgodne'] + r['stats']['skoki']
    return [row('T1.7', f'przelot przez granicę NL {trans[0][1]}→{trans[0][2]} '
                f'({fmt(lat_t, 3)}°)', 'maks. błąd i odrzucenia',
                '≤ 10 m, 0 odrzuceń', f'{fmt(emax, 2)} m, {bad} odrzuceń',
                emax <= 10 and bad == 0)]


# --- T1.8 geometria -------------------------------------------------------- #
def case_geometry():
    rows = []
    lat0, lon0, h0 = ST

    def chk(id_, opis, lat, lon, alt, exp_az, exp_el, tol_az=0.05, tol_el=0.01):
        s, az, el = dec.look_angles(lat0, lon0, h0, lat, lon, alt)
        ok_el = abs(el - exp_el) <= tol_el
        ok_az = exp_az is None or min(abs(az - exp_az), 360 - abs(az - exp_az)) <= tol_az
        exp = (f'az {fmt(exp_az, 1)}°, ' if exp_az is not None else '') + f'el {fmt(exp_el, 3)}°'
        got = (f'az {fmt(az, 2)}°, ' if exp_az is not None else '') + f'el {fmt(el, 3)}°'
        rows.append(row(id_, 'geometria stacja–statek', opis, exp, got, ok_el and ok_az))

    chk('T1.8a', 'statek 10 km nad stacją', lat0, lon0, h0 + 10000, None, 90.0)
    n = common.destination(lat0, lon0, 0, 10000)
    chk('T1.8b', '10 km na północ, wys. stacji', n[0], n[1], h0, 0.0, -0.045, 0.05, 0.005)
    e = common.destination(lat0, lon0, 90, 10000)
    chk('T1.8c', '10 km na wschód, wys. stacji', e[0], e[1], h0, 90.0, -0.045, 0.1, 0.005)
    far = common.destination(lat0, lon0, 180, 100000)
    exp_el = -math.degrees(100000 / (2 * 6371000.0))
    chk('T1.8d', '100 km na południe (krzywizna)', far[0], far[1], h0, 180.0, exp_el, 0.1, 0.01)
    return rows


# --- T2.1 sumy kontrolne NMEA ---------------------------------------------- #
def nmea(body):
    x = 0
    for ch in body:
        x ^= ord(ch)
    return f'${body}*{x:02X}'


def _import_gps_node():
    """Import gps_node.py bez ROS i pyserial (atrapy modułów)."""
    try:
        import rclpy  # noqa: F401
        has_ros = True
    except ImportError:
        has_ros = False
    if not has_ros:
        class _Node:
            def __init__(self, *a, **k):
                pass

        def mod(name, **kw):
            m = types.ModuleType(name)
            m.__dict__.update(kw)
            sys.modules.setdefault(name, m)
        mod('rclpy')
        mod('rclpy.node', Node=_Node)
        mod('rclpy.executors', ExternalShutdownException=Exception)
        mod('sensor_msgs')
        mod('sensor_msgs.msg', NavSatFix=object, NavSatStatus=object, TimeReference=object)
    if 'serial' not in sys.modules:
        try:
            import serial  # noqa: F401
        except ImportError:
            sys.modules['serial'] = types.ModuleType('serial')
    from aircraft_tracker import gps_node
    return gps_node


def case_nmea():
    g = _import_gps_node()
    ok_fn = g.nmea_checksum_ok
    gga = nmea('GPGGA,120000.00,5000.00000,N,02000.00000,E,1,09,1.00,250.0,M,40.0,M,,')
    rmc = nmea('GPRMC,123519.00,A,5000.00000,N,02000.00000,E,0.10,,241126,,,A')
    rmc_v = nmea('GPRMC,123519.00,V,,,,,,,241126,,,N')
    gga_0 = nmea('GPGGA,120000.00,,,,,0,00,99.99,,,,,,')
    altered = gga.replace('5000.00000', '5000.00001')
    cases = [
        ('poprawne GGA', gga, True), ('poprawne RMC', rmc, True),
        ('zmieniona cyfra', altered, False), ('ucięte zdanie', gga[:40], False),
        ('brak znaku *', gga.split('*')[0], False), ('suma nie-szesnastkowa', gga[:-2] + 'ZZ', False),
    ]
    rows = [row('T2.1', 'suma kontrolna NMEA', opis, 'przyjęte' if exp else 'odrzucone',
                'przyjęte' if ok_fn(s) else 'odrzucone', ok_fn(s) == exp)
            for opis, s, exp in cases]
    # Parsowanie
    pos = g.GPSNode.parse_nmea_gga(None, gga)
    rows.append(row('T2.1', 'parsowanie GGA', 'szer./dł./wys.', '50,0 / 20,0 / 250,0',
                    ' / '.join(fmt(v, 1) for v in pos) if pos else 'brak',
                    pos is not None and abs(pos[0] - 50) < 1e-9 and abs(pos[1] - 20) < 1e-9
                    and abs(pos[2] - 250) < 1e-9))
    rows.append(row('T2.1', 'parsowanie GGA bez fixa', 'jakość 0', 'brak pozycji',
                    'brak pozycji' if g.GPSNode.parse_nmea_gga(None, gga_0) is None else 'pozycja',
                    g.GPSNode.parse_nmea_gga(None, gga_0) is None))
    t = g.GPSNode.parse_nmea_rmc(None, rmc)
    exp_t = calendar.timegm((2026, 11, 24, 12, 35, 19))
    rows.append(row('T2.1', 'parsowanie RMC', 'czas UTC', str(exp_t),
                    str(t[0]) if t else 'brak', t is not None and t[0] == exp_t and t[1] == 0))
    rows.append(row('T2.1', 'RMC ze statusem V', 'czas nieważny', 'brak czasu',
                    'brak czasu' if g.GPSNode.parse_nmea_rmc(None, rmc_v) is None else 'czas',
                    g.GPSNode.parse_nmea_rmc(None, rmc_v) is None))
    return rows


# --- Korekta zegara (clock_offset.py) -------------------------------------- #
def case_clock():
    from aircraft_tracker.clock_offset import ClockOffset
    rng = cpr_gen.make_rng(3)
    true_off = 3 * 86400 + 0.5
    c = ClockOffset()
    for k in range(30):
        tg = 1.795e9 + k
        lat = 0.15 + rng.random() * 0.1
        ts = tg - true_off + lat
        if k == 12:
            ts += 5.0                # pojedynczy błędny odczyt
        c.add(tg, ts)
    err = c.offset() - (true_off - 0.2)   # średnie opóźnienie 0,2 s
    rows = [row('Z.1', 'korekta zegara RPi', 'zegar RPi o 3 doby do tyłu',
                'błąd ≤ 0,1 s (bez gps_delay)', f'{fmt(err, 3)} s', abs(err) <= 0.1),
            row('Z.2', 'korekta zegara RPi', 'pojedyncza próbka +5 s',
                'odrzucona', f'odrzuconych: {c.outliers}', c.outliers == 1)]
    jumped = False
    for k in range(30, 34):
        jumped |= c.add(1.795e9 + k, 1.795e9 + k + 0.2)
    rows.append(row('Z.3', 'korekta zegara RPi', 'przestawienie zegara (NTP)',
                    'wykryte, nowe przesunięcie ≈ −0,2 s',
                    f'{"wykryte" if jumped else "nie"}, {fmt(c.offset(), 3)} s',
                    jumped and abs(c.offset() + 0.2) < 0.05))
    c2 = ClockOffset(gps_delay=0.16)
    for k in range(5):
        c2.add(100.0 + k, 100.0 + k + 0.16)
    rows.append(row('Z.4', 'korekta zegara RPi', 'kompensacja gps_delay = 0,16 s',
                    '0,000 s', f'{fmt(c2.offset(), 3)} s', abs(c2.offset()) < 1e-6))
    return rows


ALL_CASES = [case_clean_flight, case_bit_errors, case_wrong_station, case_wrong_station_400,
             case_far_aircraft,
             case_range_limit,
             case_jump_limit, case_nl_crossing, case_geometry, case_nmea, case_clock]


def all_rows():
    out = []
    for f in ALL_CASES:
        out.extend(f())
    return out
