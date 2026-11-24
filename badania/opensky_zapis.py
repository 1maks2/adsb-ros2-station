#!/usr/bin/env python3
"""Zapis danych odniesienia z OpenSky Network w trakcie sesji (scenariusz T9.1).

Uruchom na LAPTOPIE z internetem w tym samym czasie, w którym stacja nagrywa.
Co `--okres` sekund pobiera wektory stanu statków z prostokąta wokół stacji
i dopisuje je do pliku CSV w formacie używanym przez porownanie_zewnetrzne.py:
  t_utc, t_kontakt, icao, znak, lat, lon, alt_geo_m, alt_baro_m, gs_mps, kurs, zrodlo

Ograniczenia (dokumentacja OpenSky, sprawdź aktualne przed badaniem:
https://openskynetwork.github.io/opensky-api/rest.html):
  - bez konta: 400 kredytów API na dobę i rozdzielczość czasu 10 s,
  - zapytanie o mały obszar kosztuje mniej kredytów (dlatego prostokąt wokół stacji),
  - z kontem: logowanie przez OAuth2 (client credentials). Utwórz "API client" na stronie
    konta i ustaw zmienne środowiskowe OPENSKY_CLIENT_ID i OPENSKY_CLIENT_SECRET.
Dane OpenSky służą tu jako NIEZALEŻNE źródło (inne odbiorniki, inny zegar) - ich
własna dokładność czasu i pozycji jest ograniczona (t_utc = time_position, 1 s).

Przykład (stacja ok. 50,0 N 20,0 E, kwadrat +/- 2 stopnie, co 10 s przez 60 min):
  python3 opensky_zapis.py --lat 50.0 --lon 20.0 --minuty 60 --wyjscie dane/opensky_R-02.csv
"""
import argparse
import csv
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

API = 'https://opensky-network.org/api/states/all'
TOKEN_URL = ('https://auth.opensky-network.org/auth/realms/opensky-network/'
             'protocol/openid-connect/token')
COLS = ['t_utc', 't_kontakt', 'icao', 'znak', 'lat', 'lon', 'alt_geo_m', 'alt_baro_m',
        'gs_mps', 'kurs', 'zrodlo']


class Token:
    def __init__(self):
        self.cid = os.environ.get('OPENSKY_CLIENT_ID')
        self.sec = os.environ.get('OPENSKY_CLIENT_SECRET')
        self.tok, self.exp = None, 0.0

    def header(self):
        if not self.cid:
            return {}
        if time.time() > self.exp - 60:
            body = urllib.parse.urlencode({'grant_type': 'client_credentials',
                                           'client_id': self.cid,
                                           'client_secret': self.sec}).encode()
            req = urllib.request.Request(TOKEN_URL, data=body, headers={
                'Content-Type': 'application/x-www-form-urlencoded'})
            with urllib.request.urlopen(req, timeout=20) as r:
                j = json.load(r)
            self.tok, self.exp = j['access_token'], time.time() + j.get('expires_in', 1800)
        return {'Authorization': f'Bearer {self.tok}'}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--lat', type=float, required=True)
    ap.add_argument('--lon', type=float, required=True)
    ap.add_argument('--polbok', type=float, default=2.0, help='pół boku prostokąta [stopnie]')
    ap.add_argument('--okres', type=float, default=10.0, help='co ile sekund [s]')
    ap.add_argument('--minuty', type=float, default=60.0)
    ap.add_argument('--wyjscie', required=True)
    a = ap.parse_args()
    q = urllib.parse.urlencode({'lamin': a.lat - a.polbok, 'lamax': a.lat + a.polbok,
                                'lomin': a.lon - a.polbok, 'lomax': a.lon + a.polbok})
    tok = Token()
    new = not os.path.exists(a.wyjscie)
    os.makedirs(os.path.dirname(a.wyjscie) or '.', exist_ok=True)
    f = open(a.wyjscie, 'a', newline='', encoding='utf-8')
    w = csv.writer(f)
    if new:
        w.writerow(COLS)
    t_end = time.time() + a.minuty * 60
    n = 0
    print(f"Zapis do {a.wyjscie} ({'konto OAuth2' if tok.cid else 'anonimowo'}), Ctrl+C = koniec")
    while time.time() < t_end:
        t_req = time.time()
        try:
            req = urllib.request.Request(f'{API}?{q}', headers=tok.header())
            with urllib.request.urlopen(req, timeout=20) as r:
                left = r.headers.get('X-Rate-Limit-Remaining')
                j = json.load(r)
            for s in j.get('states') or []:
                # indeksy wg dokumentacji: 0 icao24, 1 callsign, 3 time_position, 4 last_contact,
                # 5 lon, 6 lat, 7 baro_altitude, 9 velocity, 10 true_track, 13 geo_altitude
                if s[5] is None or s[6] is None or s[3] is None:
                    continue
                w.writerow([s[3], s[4], s[0].upper(), (s[1] or '').strip(), s[6], s[5],
                            s[13], s[7], s[9], s[10], 'opensky'])
                n += 1
            f.flush()
            print(f"\r{time.strftime('%H:%M:%S')}  wierszy: {n}  kredyty: {left}", end='')
        except urllib.error.HTTPError as e:
            if e.code == 429:
                print('\nWyczerpany limit zapytań (HTTP 429) - przerywam.')
                break
            print(f'\nBłąd HTTP {e.code}, ponawiam')
        except Exception as e:  # sieć
            print(f'\nBłąd: {e}, ponawiam')
        time.sleep(max(0.0, a.okres - (time.time() - t_req)))
    f.close()
    print(f'\nZapisano {n} wierszy.')


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nPrzerwano.')
