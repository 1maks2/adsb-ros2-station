#!/usr/bin/env python3
"""Dekodowanie ramek ADS-B i geometria samolot-stacja.

Ten moduł NIE korzysta z ROS - dzięki temu da się go testować osobno
(np. na laptopie). Węzeł decoder_node.py tylko przekazuje mu ramki
i publikuje wyniki.

Pozycja samolotu jest wyznaczana dwiema niezależnymi metodami:
  1. LOKALNIE - z jednej ramki, z pozycją stacji (GPS) jako odniesieniem.
     Działa od pierwszej odebranej ramki pozycyjnej.
  2. GLOBALNIE - z pary ramek parzysta/nieparzysta (pyModeS.PipeDecoder),
     bez żadnej wiedzy o stacji. PipeDecoder wypuszcza pozycję dopiero
     po zebraniu kilku wzajemnie zgodnych wyników (ochrona przed błędami).
Jeśli obie metody dają ten sam wynik -> pozycja POTWIERDZONA.
"""
import math

import pyModeS

# --- Przeliczniki jednostek lotniczych na SI ---
FT_TO_M = 0.3048            # stopa -> metr
KT_TO_MS = 1852.0 / 3600.0  # węzeł -> m/s
FPM_TO_MS = 0.3048 / 60.0   # stopy na minutę -> m/s

# --- Jakość pozycji (te same wartości co stałe w AircraftState.msg) ---
POSITION_NONE = 0
POSITION_LOCAL = 1
POSITION_GLOBAL = 2
POSITION_VERIFIED = 3

# --- Rodzaj wysokości (jak w AircraftState.msg) ---
ALTITUDE_UNKNOWN = 0
ALTITUDE_BARO = 1
ALTITUDE_GEOMETRIC = 2

# --- Parametry kontroli poprawności ---
AGREE_TOLERANCE_M = 1000.0   # maks. różnica pozycji lokalnej i globalnej, by uznać je za zgodne
MAX_SPEED_MS = 600.0         # maks. realna prędkość samolotu (~1170 węzłów) - do wykrywania skoków
JUMP_MARGIN_M = 1000.0       # zapas na niedokładność przy sprawdzaniu skoków
MAX_RANGE_M = 450000.0       # dalej odbiornik naziemny nie "widzi" samolotów (horyzont radiowy)
STATE_TTL_S = 300.0          # po tylu sekundach ciszy zapominamy samolot

NAN = float('nan')

# --- Elipsoida WGS84 (ta sama, której używa GPS) ---
WGS84_A = 6378137.0                 # półoś równikowa [m]
WGS84_E2 = 6.69437999014e-3         # kwadrat mimośrodu
EARTH_R = 6371008.8                 # średni promień Ziemi [m] (do odległości po powierzchni)


def geodetic_to_ecef(lat_deg, lon_deg, h_m):
    """Szerokość/długość/wysokość -> współrzędne kartezjańskie ECEF [m].

    ECEF = układ o środku w środku Ziemi; w nim odległość 3D to zwykły Pitagoras.
    """
    lat = math.radians(lat_deg)
    lon = math.radians(lon_deg)
    n = WGS84_A / math.sqrt(1.0 - WGS84_E2 * math.sin(lat) ** 2)
    x = (n + h_m) * math.cos(lat) * math.cos(lon)
    y = (n + h_m) * math.cos(lat) * math.sin(lon)
    z = (n * (1.0 - WGS84_E2) + h_m) * math.sin(lat)
    return x, y, z


def ground_distance_m(lat1, lon1, lat2, lon2):
    """Odległość po powierzchni Ziemi (wzór haversine) [m]."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2.0 * EARTH_R * math.asin(min(1.0, math.sqrt(a)))


def look_angles(st_lat, st_lon, st_alt, ac_lat, ac_lon, ac_alt):
    """Kierunek ze stacji do samolotu.

    Zwraca (odległość skośna [m], azymut [deg], elewacja [deg]).
    Liczone w lokalnym układzie ENU stacji (East-North-Up), więc
    krzywizna Ziemi jest uwzględniona - daleki samolot "chowa się" za horyzont.
    """
    sx, sy, sz = geodetic_to_ecef(st_lat, st_lon, st_alt)
    ax, ay, az = geodetic_to_ecef(ac_lat, ac_lon, ac_alt)
    dx, dy, dz = ax - sx, ay - sy, az - sz

    lat = math.radians(st_lat)
    lon = math.radians(st_lon)
    # Obrót wektora ECEF do osi: wschód, północ, góra (w miejscu stacji)
    east = -math.sin(lon) * dx + math.cos(lon) * dy
    north = (-math.sin(lat) * math.cos(lon) * dx
             - math.sin(lat) * math.sin(lon) * dy
             + math.cos(lat) * dz)
    up = (math.cos(lat) * math.cos(lon) * dx
          + math.cos(lat) * math.sin(lon) * dy
          + math.sin(lat) * dz)

    slant = math.sqrt(dx * dx + dy * dy + dz * dz)
    azimuth = math.degrees(math.atan2(east, north)) % 360.0
    elevation = math.degrees(math.atan2(up, math.hypot(east, north)))
    return slant, azimuth, elevation


def _new_aircraft():
    return {
        'callsign': '',
        'lat': NAN, 'lon': NAN,
        'position_quality': POSITION_NONE,
        'position_time': NAN,       # czas ramki, z której pochodzi pozycja [s]
        'alt_baro_ft': None,        # z ramek pozycyjnych TC 9-18
        'alt_gnss_ft': None,        # z ramek pozycyjnych TC 20-22
        'geo_minus_baro_ft': None,  # z ramek prędkości (różnica GNSS - baro)
        'speed_kt': None,
        'track': None,
        'vrate_fpm': None,
        'last_seen': 0.0,
    }


class AdsbDecoder:
    """Przechowuje stan wszystkich samolotów i aktualizuje go ramka po ramce."""

    def __init__(self):
        self.pipe = pyModeS.PipeDecoder()   # dekoder globalny (pary ramek)
        self.aircraft = {}                  # ICAO -> słownik ze stanem
        self.station = None                 # (lat, lon, alt) stacji z GPS
        self.stats = self._empty_stats()

    @staticmethod
    def _empty_stats():
        return {'ramki': 0, 'adsb': 0, 'bledne': 0, 'pozycje': 0,
                'potwierdzone': 0, 'niezgodne': 0, 'skoki': 0, 'poza_zasiegiem': 0}

    def reset_stats(self):
        s = self.stats
        self.stats = self._empty_stats()
        return s

    def set_station(self, lat, lon, alt):
        self.station = (lat, lon, alt)

    # ------------------------------------------------------------------ #
    def process(self, frame, t):
        """Przetwarza jedną ramkę AVR (np. '*8D4D22BF...;') odebraną w chwili t [s].

        Zwraca ICAO samolotu, którego stan się zmienił, albo None.
        """
        self.stats['ramki'] += 1
        hexmsg = frame.strip().lstrip('*').rstrip(';')

        # Bierzemy tylko długie ramki DF17 = ADS-B z transpondera.
        # Mają adres ICAO zapisany wprost i są chronione sumą CRC.
        # (Krótkie ramki Mode S i DF20/21 nie zawierają pozycji, a adres
        # odczytany z nich bywa przekłamany.)
        if len(hexmsg) != 28:
            return None
        try:
            if int(hexmsg[:2], 16) >> 3 != 17:
                return None
        except ValueError:
            self.stats['bledne'] += 1
            return None

        try:
            g = self.pipe.decode(hexmsg, timestamp=t)
        except Exception:    # uszkodzona ramka - pyModeS rzuca różne wyjątki
            self.stats['bledne'] += 1
            return None
        if not g.get('crc_valid') or 'error' in g:
            self.stats['bledne'] += 1
            return None

        self.stats['adsb'] += 1
        icao = g['icao']
        ac = self.aircraft.setdefault(icao, _new_aircraft())
        ac['last_seen'] = t

        bds = g.get('bds')
        tc = g.get('typecode') or 0

        # --- Identyfikacja (znak wywoławczy), TC 1-4 ---
        if g.get('callsign'):
            ac['callsign'] = g['callsign'].replace('_', '').strip()

        # --- Prędkość, TC 19 ---
        if g.get('groundspeed') is not None:
            ac['speed_kt'] = g['groundspeed']
        if g.get('track') is not None:
            ac['track'] = g['track']
        if g.get('vertical_rate') is not None:
            ac['vrate_fpm'] = g['vertical_rate']
        if g.get('geo_minus_baro') is not None:
            ac['geo_minus_baro_ft'] = g['geo_minus_baro']

        # --- Pozycja (BDS 0,5 w powietrzu; BDS 0,6 na ziemi) ---
        if bds in ('0,5', '0,6'):
            if bds == '0,5' and g.get('altitude') is not None:
                if 9 <= tc <= 18:
                    ac['alt_baro_ft'] = g['altitude']
                elif 20 <= tc <= 22:
                    ac['alt_gnss_ft'] = g['altitude']
            self._update_position(ac, hexmsg, g, bds, t)

        return icao

    def _update_position(self, ac, hexmsg, g, bds, t):
        # Metoda 1: lokalnie, z jednej ramki, odniesienie = stacja
        local = None
        if self.station is not None:
            ref = (self.station[0], self.station[1])
            try:
                if bds == '0,5':
                    r = pyModeS.decode(hexmsg, reference=ref)
                else:
                    r = pyModeS.decode(hexmsg, surface_ref=ref)
                if r.get('latitude') is not None and r.get('longitude') is not None:
                    local = (r['latitude'], r['longitude'])
            except Exception:
                local = None

        # Metoda 2: globalnie (PipeDecoder już policzył przy decode())
        glob = None
        if g.get('latitude') is not None and g.get('longitude') is not None:
            glob = (g['latitude'], g['longitude'])

        if local and glob:
            if ground_distance_m(*local, *glob) <= AGREE_TOLERANCE_M:
                pos, quality = local, POSITION_VERIFIED
            else:
                # Metody się nie zgadzają - nie ufamy żadnej z nich
                self.stats['niezgodne'] += 1
                return
        elif local:
            pos, quality = local, POSITION_LOCAL
        elif glob:
            pos, quality = glob, POSITION_GLOBAL
        else:
            return

        # Kontrola zasięgu: odbiornik naziemny nie słyszy samolotów dalej niż ~450 km
        if self.station is not None:
            if ground_distance_m(self.station[0], self.station[1], *pos) > MAX_RANGE_M:
                self.stats['poza_zasiegiem'] += 1
                return

        # Kontrola skoku: czy samolot mógł tak szybko przelecieć od poprzedniej pozycji?
        if not math.isnan(ac['lat']):
            dt = max(0.0, t - ac['position_time'])
            jump = ground_distance_m(ac['lat'], ac['lon'], *pos)
            if jump > MAX_SPEED_MS * dt + JUMP_MARGIN_M:
                self.stats['skoki'] += 1
                # Pozycja potwierdzona obiema metodami wygrywa ze starą
                # (stara mogła być błędna); inne odrzucamy.
                if quality != POSITION_VERIFIED:
                    return

        ac['lat'], ac['lon'] = pos
        ac['position_quality'] = quality
        ac['position_time'] = t
        self.stats['pozycje'] += 1
        if quality == POSITION_VERIFIED:
            self.stats['potwierdzone'] += 1

    # ------------------------------------------------------------------ #
    def state(self, icao):
        """Zwraca słownik z pełnym stanem samolotu w jednostkach SI."""
        ac = self.aircraft[icao]

        # Wysokość: najlepiej geometryczna (GNSS), bo GPS stacji też ją tak mierzy.
        # Jeśli jej nie ma, ale znamy różnicę GNSS-baro z ramek prędkości - poprawiamy baro.
        alt_baro = ac['alt_baro_ft'] * FT_TO_M if ac['alt_baro_ft'] is not None else NAN
        if ac['alt_gnss_ft'] is not None:
            alt, alt_type = ac['alt_gnss_ft'] * FT_TO_M, ALTITUDE_GEOMETRIC
        elif ac['alt_baro_ft'] is not None and ac['geo_minus_baro_ft'] is not None:
            alt = (ac['alt_baro_ft'] + ac['geo_minus_baro_ft']) * FT_TO_M
            alt_type = ALTITUDE_GEOMETRIC
        elif ac['alt_baro_ft'] is not None:
            alt, alt_type = alt_baro, ALTITUDE_BARO
        else:
            alt, alt_type = NAN, ALTITUDE_UNKNOWN

        s = {
            'icao': icao,
            'callsign': ac['callsign'],
            'latitude': ac['lat'],
            'longitude': ac['lon'],
            'position_quality': ac['position_quality'],
            'position_time': ac['position_time'],
            'altitude': alt,
            'altitude_type': alt_type,
            'altitude_baro': alt_baro,
            'ground_speed': ac['speed_kt'] * KT_TO_MS if ac['speed_kt'] is not None else NAN,
            'track': ac['track'] if ac['track'] is not None else NAN,
            'vertical_rate': (ac['vrate_fpm'] * FPM_TO_MS
                              if ac['vrate_fpm'] is not None else NAN),
            'ground_distance': NAN,
            'slant_distance': NAN,
            'azimuth': NAN,
            'elevation': NAN,
        }

        if self.station is not None and not math.isnan(ac['lat']):
            st_lat, st_lon, st_alt = self.station
            s['ground_distance'] = ground_distance_m(st_lat, st_lon, ac['lat'], ac['lon'])
            if not math.isnan(alt):
                slant, az, el = look_angles(st_lat, st_lon, st_alt,
                                            ac['lat'], ac['lon'], alt)
                s['slant_distance'], s['azimuth'], s['elevation'] = slant, az, el
        return s

    def prune(self, now):
        """Usuwa samoloty, od których dawno nic nie przyszło."""
        old = [k for k, v in self.aircraft.items() if now - v['last_seen'] > STATE_TTL_S]
        for k in old:
            del self.aircraft[k]
        return len(old)