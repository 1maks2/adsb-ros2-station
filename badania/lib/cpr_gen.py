"""Generator syntetycznych ramek ADS-B (DF17) ze znaną trajektorią.

Służy jako źródło odniesienia o ZNANEJ prawdzie (scenariusze T1.x): dekoder
dostaje ramki, a jego wynik porównuje się z dokładną pozycją, którą zakodowano.

Zaimplementowano (na podstawie: J. Sun, The 1090 Megahertz Riddle, 2021):
  - CRC-24 Mode S (wielomian generujący 0x1FFF409),
  - kodowanie CPR pozycji w powietrzu (17 bitów, NZ = 15, ramki parzyste/nieparzyste),
  - kod wysokości barometrycznej z bitem Q = 1 (krok 25 ft),
  - wiadomość prędkości TC 19, podtyp 1 (prędkość względem ziemi),
  - wiadomość identyfikacyjna TC 4 (znak wywoławczy).

Nominalne częstości nadawania (do weryfikacji w Sun 2021, rozdz. 1/3):
pozycja ok. 2 Hz (naprzemiennie parzysta/nieparzysta), prędkość ok. 2 Hz,
identyfikacja ok. 0,2 Hz. Odstępy losowane są z rozkładu jednostajnego.
"""
import math
import random

from . import common

NZ = 15
CRC_POLY = 0x1FFF409
CHARSET = '#ABCDEFGHIJKLMNOPQRSTUVWXYZ#####_###############0123456789######'


# --- CRC-24 ---------------------------------------------------------------- #
def crc24(data88):
    """Reszta z dzielenia 88 bitów danych (przesuniętych o 24) przez wielomian Mode S."""
    v = data88 << 24
    for i in range(111, 23, -1):
        if (v >> i) & 1:
            v ^= CRC_POLY << (i - 24)
    return v & 0xFFFFFF


def crc_ok(frame_hex):
    """True, jeśli 112-bitowa ramka ma poprawną sumę kontrolną (reszta = 0)."""
    try:
        v = int(frame_hex, 16)
    except ValueError:
        return False
    if len(frame_hex) != 28:
        return False
    return crc24(v >> 24) == (v & 0xFFFFFF)


def build_df17(icao, me, ca=5):
    data = ((17 << 3 | ca) << 80) | (icao << 56) | me
    return f'{(data << 24) | crc24(data):028X}'


# --- CPR ------------------------------------------------------------------- #
def nl(lat):
    """Liczba stref długości geograficznej NL(lat)."""
    a = abs(lat)
    if a < 1e-9:
        return 59
    if abs(a - 87.0) < 1e-9:
        return 2
    if a > 87.0:
        return 1
    x = 1 - math.cos(math.pi / (2 * NZ))
    y = math.cos(math.pi / 180.0 * a) ** 2
    return int(math.floor(2 * math.pi / math.acos(1 - x / y)))


def nl_transitions(lat_from, lat_to):
    """Szerokości, na których NL zmienia wartość (do scenariusza T1.7)."""
    out = []
    step = 0.001
    lat = lat_from
    prev = nl(lat)
    while lat < lat_to:
        lat += step
        cur = nl(lat)
        if cur != prev:
            out.append((round(lat, 3), prev, cur))
            prev = cur
    return out


def cpr_encode(lat, lon, odd):
    """Zwraca (YZ, XZ) - 17-bitowe współrzędne CPR dla ramki parzystej (odd=0) lub nieparzystej."""
    i = 1 if odd else 0
    dlat = 360.0 / (4 * NZ - i)
    yz = math.floor(2 ** 17 * ((lat % dlat) / dlat) + 0.5)
    rlat = dlat * (yz / 2 ** 17 + math.floor(lat / dlat))
    nlr = nl(rlat) - i
    dlon = 360.0 / max(nlr, 1)
    xz = math.floor(2 ** 17 * ((lon % dlon) / dlon) + 0.5)
    return yz % 2 ** 17, xz % 2 ** 17


def alt_code_ft(alt_ft):
    """12-bitowy kod wysokości (Q = 1, krok 25 ft, od -1000 ft)."""
    n = int(round((alt_ft + 1000.0) / 25.0))
    n = max(0, min(n, 2 ** 11 - 1))
    return ((n >> 4) << 5) | (1 << 4) | (n & 0xF)


# --- Wiadomości ------------------------------------------------------------ #
def frame_position(icao, lat, lon, alt_ft, odd, tc=11):
    yz, xz = cpr_encode(lat, lon, odd)
    me = (tc << 51) | (0 << 49) | (0 << 48) | (alt_code_ft(alt_ft) << 36) \
        | (0 << 35) | ((1 if odd else 0) << 34) | (yz << 17) | xz
    return build_df17(icao, me)


def frame_velocity(icao, gs_kt, track_deg, vr_fpm=0.0, geo_minus_baro_ft=None):
    tr = math.radians(track_deg)
    vew = gs_kt * math.sin(tr)
    vns = gs_kt * math.cos(tr)
    s_ew, v_ew = (1 if vew < 0 else 0), min(int(round(abs(vew))) + 1, 1023)
    s_ns, v_ns = (1 if vns < 0 else 0), min(int(round(abs(vns))) + 1, 1023)
    s_vr, vr = (1 if vr_fpm < 0 else 0), min(int(round(abs(vr_fpm) / 64.0)) + 1, 511)
    if geo_minus_baro_ft is None:
        s_dif, dif = 0, 0
    else:
        s_dif = 1 if geo_minus_baro_ft < 0 else 0
        dif = min(int(round(abs(geo_minus_baro_ft) / 25.0)) + 1, 127)
    me = (19 << 51) | (1 << 48) | (0 << 47) | (0 << 46) | (0 << 43) \
        | (s_ew << 42) | (v_ew << 32) | (s_ns << 31) | (v_ns << 21) \
        | (0 << 20) | (s_vr << 19) | (vr << 10) | (0 << 8) | (s_dif << 7) | dif
    return build_df17(icao, me)


def frame_ident(icao, callsign, category=3):
    cs = (callsign.upper() + '________')[:8].replace(' ', '_')
    chars = 0
    for c in cs:
        idx = CHARSET.find(c)
        if idx < 0:
            idx = 32
        chars = (chars << 6) | idx
    me = (4 << 51) | (category << 48) | chars
    return build_df17(icao, me)


def flip_bits(frame_hex, ber, rng):
    """Przekłamuje każdy z 112 bitów z prawdopodobieństwem ber. Zwraca (ramka, liczba_bitów)."""
    v = int(frame_hex, 16)
    n = 0
    for i in range(112):
        if rng.random() < ber:
            v ^= 1 << i
            n += 1
    return f'{v:028X}', n


# --- Trajektoria i harmonogram nadawania ----------------------------------- #
class Flight:
    """Lot po ortodromie ze stałą prędkością, kursem i prędkością pionową."""

    def __init__(self, icao, callsign, lat, lon, alt_m, gs_ms, track_deg,
                 vr_ms=0.0, geo_minus_baro_m=None):
        self.icao = icao
        self.callsign = callsign
        self.lat0, self.lon0 = lat, lon
        self.alt0 = alt_m
        self.gs = gs_ms
        self.track = track_deg
        self.vr = vr_ms
        self.gmb = geo_minus_baro_m

    def at(self, t):
        """Prawdziwa pozycja (lat, lon, wysokość baro [m]) w chwili t [s] od startu."""
        lat, lon = common.destination(self.lat0, self.lon0, self.track, self.gs * t)
        return lat, lon, self.alt0 + self.vr * t

    def generate(self, duration_s, rng, t0=0.0):
        """Lista zdarzeń (t, ramka, rodzaj, prawda) w kolejności czasu.

        rodzaj: 'pos_even', 'pos_odd', 'vel', 'id'; prawda: (lat, lon, alt_m) dla pozycji.
        """
        ev = []
        t = rng.uniform(0.0, 0.5)
        odd = rng.random() < 0.5
        while t < duration_s:
            lat, lon, alt = self.at(t)
            fr = frame_position(self.icao, lat, lon, alt / common.dec.FT_TO_M, odd)
            ev.append((t0 + t, fr, 'pos_odd' if odd else 'pos_even', (lat, lon, alt)))
            odd = not odd
            t += rng.uniform(0.4, 0.6)
        t = rng.uniform(0.0, 0.5)
        while t < duration_s:
            gmb_ft = None if self.gmb is None else self.gmb / common.dec.FT_TO_M
            fr = frame_velocity(self.icao, self.gs / common.dec.KT_TO_MS, self.track,
                                self.vr / common.dec.FPM_TO_MS, gmb_ft)
            ev.append((t0 + t, fr, 'vel', None))
            t += rng.uniform(0.4, 0.6)
        t = rng.uniform(0.0, 5.0)
        while t < duration_s:
            ev.append((t0 + t, frame_ident(self.icao, self.callsign), 'id', None))
            t += rng.uniform(4.8, 5.2)
        ev.sort(key=lambda e: e[0])
        return ev


def random_flight(rng, station, dist_range_km=(20, 250), icao=None):
    """Losowy lot w zasięgu stacji (do badań statystycznych, T1.2)."""
    st_lat, st_lon, _ = station
    d = rng.uniform(*dist_range_km) * 1000.0
    lat, lon = common.destination(st_lat, st_lon, rng.uniform(0, 360), d)
    if icao is None:
        icao = rng.randrange(0x400000, 0x4FFFFF)
    cs = 'TST' + str(rng.randrange(100, 999))
    return Flight(icao, cs, lat, lon, rng.uniform(3000, 12000), rng.uniform(120, 250),
                  rng.uniform(0, 360), rng.choice([0.0, 0.0, 5.0, -5.0]),
                  rng.uniform(-150, 150))


def apply_loss(events, p, rng):
    """Usuwa każdą ramkę niezależnie z prawdopodobieństwem p (utrata w kanale)."""
    return [e for e in events if rng.random() >= p]


def make_rng(seed):
    return random.Random(seed)
