# Stan statku powietrznego wyznaczony z ramek ADS-B przez decoder_node.
# Jednostki SI: metry, m/s, stopnie. Wartosci nieznane = NaN.

# --- Stale: jakosc pozycji ---
uint8 POSITION_NONE=0       # brak pozycji
uint8 POSITION_LOCAL=1      # z jednej ramki, odniesienie = pozycja stacji z GPS
uint8 POSITION_GLOBAL=2     # z pary ramek parzysta/nieparzysta (bez pozycji stacji)
uint8 POSITION_VERIFIED=3   # obie metody daly zgodny wynik

# --- Stale: rodzaj wysokosci ---
uint8 ALTITUDE_UNKNOWN=0
uint8 ALTITUDE_BARO=1       # barometryczna (wzgledem cisnienia standardowego 1013,25 hPa)
uint8 ALTITUDE_GEOMETRIC=2  # geometryczna (z GNSS samolotu)

std_msgs/Header header      # stamp = czas odebrania ostatniej ramki (zegar RPi)

string icao                 # adres ICAO transpondera, np. "4D22BF"
string callsign             # znak wywolawczy (pusty, jesli jeszcze nieznany)

# --- Pozycja ---
float64 latitude            # [deg] WGS84
float64 longitude           # [deg] WGS84
uint8 position_quality      # jedna ze stalych POSITION_*
builtin_interfaces/Time position_stamp  # kiedy odebrano ramke, z ktorej pochodzi pozycja

# --- Wysokosc ---
float64 altitude            # [m] najlepsza dostepna wysokosc (rodzaj w altitude_type)
uint8 altitude_type         # jedna ze stalych ALTITUDE_*
float64 altitude_baro       # [m] wysokosc barometryczna

# --- Ruch ---
float64 ground_speed        # [m/s] predkosc wzgledem ziemi
float64 track               # [deg] kurs, 0 = polnoc, 90 = wschod
float64 vertical_rate       # [m/s] dodatnia = wznoszenie

# --- Geometria wzgledem stacji (NaN, jesli brak pozycji samolotu lub stacji) ---
float64 ground_distance     # [m] odleglosc po powierzchni Ziemi
float64 slant_distance      # [m] odleglosc w linii prostej (3D)
float64 azimuth             # [deg] kierunek do samolotu, 0 = polnoc, 90 = wschod
float64 elevation           # [deg] kat nad horyzontem stacji
