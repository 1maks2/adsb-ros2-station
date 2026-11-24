# Badania stacji bazowej ADS-B – skrypty i procedury

Ten folder zawiera wszystko, co potrzebne do przeprowadzenia badań z rozdziału 6 pracy
(scenariusze **T1–T9**, wskaźniki **W1–W10** z metodyki badań). Każdy skrypt na końcu
zapisuje **tabele LaTeX** (`\input{...}`), **wykresy PDF** (wektorowe, do pracy), PNG
(podgląd) oraz **CSV/JSON** z danymi surowymi (do załącznika lub własnej analizy).

> Liczby z sesji testowej (`generuj_sesje_testowa.py`) i z danych syntetycznych służą do
> sprawdzenia narzędzi albo do badań weryfikacyjnych (T1). **Wyniki terenowe w pracy
> muszą pochodzić z prawdziwych sesji.**

---

## 1. Zawartość

| Plik | Gdzie uruchamiać | Scenariusze | Co robi |
|---|---|---|---|
| `testy/` (pytest) | laptop lub RPi | T1.1–T1.8, T2.1, Z.1–Z.4 | Automatyczne testy jednostkowe dekodera, NMEA i korekty zegara |
| `badanie_syntetyczne.py` | laptop | T1.1–T1.8, T2.1 | Badanie dekodera na ramkach o znanej trajektorii: Tabela A, A2–A4, Tabela B, 4 wykresy |
| `generuj_sesje_testowa.py` | laptop | – | Sztuczna sesja rosbag2 do próby całego toru analizy |
| `bag_to_csv.py` | laptop | – | Eksport nagrania MCAP do CSV (bez ROS 2) |
| `analiza_sesji.py` | laptop | T4.1, T5.x, T6.x, T7.1, T8.1 | Analiza jednej sesji: wskaźniki W1–W10, tabele, 9 wykresów |
| `porownanie_sesji.py` | laptop | T5.3, T7.1, zestawienia | Tabela C (sesje obok siebie), porównanie zasięgu i temperatury |
| `opensky_zapis.py` | laptop z internetem, **w trakcie sesji** | T9.1 | Zapis pozycji z OpenSky Network jako niezależnego źródła |
| `porownanie_zewnetrzne.py` | laptop | T9.1 | Błąd pozycji względem OpenSky i niezależna ocena błędu czasu |
| `benchmark_dekodera.py` | **RPi** (Docker) i laptop | T3.2 | Czas przetwarzania jednej ramki, warunek czasu rzeczywistego (W8) |
| `rpi/monitor_cpu.py` | **RPi** (host) | T3.2, T7.1 | Obciążenie CPU przez procesy stacji, temperatura, RAM |
| `wykres_obciazenia.py` | laptop | T3.2, T7.1 | Tabela i wykres obciążenia z danych `monitor_cpu.py` |
| `rpi/sprawdz_system.sh` | **RPi** | T3.1 | Test uruchomienia: usługi, węzły, tematy, częstotliwości |
| `rpi/raport_sesji.sh` | **RPi** | T6.2, T6.3 | Przegląd sesji: `metadata.yaml`, rozmiary, czas trwania |
| `rpi/napraw_sesje.sh` | **RPi** | T6.2 | Odzyskanie sesji po nagłym odcięciu zasilania (`ros2 bag reindex`) |
| `sesje.csv` | – | wszystkie terenowe | Katalog sesji (wypełniaj na bieżąco) |
| `lib/` | – | – | Wspólny kod: generator ramek (CPR, CRC-24), odczyt MCAP, tabele, styl wykresów |

Dekoder jest importowany **bezpośrednio z pakietu ROS** (`ros2_ws/src/aircraft_tracker/`),
więc badany jest dokładnie ten sam kod, który działa na stacji.

---

## 2. Przygotowanie

### Laptop (analiza)

```bash
cd ~                                        # albo inny folder roboczy
git clone https://github.com/1maks2/adsb-ros2-station.git     # albo: git pull w istniejącej kopii
cd adsb-ros2-station/badania
python3 -m venv ~/badania-venv              # osobne środowisko Pythona (Ubuntu nie pozwala na pip w systemie)
source ~/badania-venv/bin/activate          # aktywacja - w każdym nowym terminalu
pip install -r requirements.txt
python -m pytest -v testy/                  # sprawdzenie: wszystkie testy PASSED
```

`venv` to osobny katalog z własnym Pythonem i bibliotekami. Nie zmienia systemu i nie
koliduje z ROS w Dockerze. Po `source .../activate` na początku wiersza poleceń pojawi się
`(badania-venv)`.

### Raspberry Pi

Nic nie trzeba instalować. Skrypty `rpi/*` używają tylko basha i Pythona systemowego,
a `benchmark_dekodera.py` uruchamia się w istniejącym obrazie Dockera stacji.

### Kopiowanie sesji z RPi na laptop

```bash
mkdir -p dane
scp -r maks@<IP-RPi>:~/ros2_sdr/ros2_ws/bags/sesja_20261125_120000Z dane/
```

Foldery `dane/` i `wyniki/` są w `.gitignore`. Nagrania zawierają lokalizację stacji
i **nie mogą trafić do publicznego repozytorium**.

---

## 3. Procedura polowa (wspólna dla T5–T9)

1. Rozstaw stację (antena ADS-B pionowo, moduł GPS z widokiem nieba) i włącz zasilanie.
   Każde włączenie to nowa sesja `sesja_<UTC>`.
2. **Poczekaj ok. 15 min z fixem GPS**, zanim zaczniesz właściwy pomiar (ustalenie F1:
   tani moduł GPS przez pierwsze do 12,5 min po złapaniu fixa może podawać UTC błędny
   o pełne sekundy). Analiza i tak liczy przesunięcie zegara z **końca** sesji.
3. Wpisz sesję do `sesje.csv`: ID (`R-xx`), folder, opis miejsca **bez współrzędnych**,
   antena, obudowa, wentylator, pogoda, stan baterii, NTP (czy RPi miał internet), commit.
4. Nagrywaj co najmniej 60 min (dzień i wieczór osobno).
5. Wyłącz stację przyciskiem (przytrzymaj 2 s), poczekaj na zgaśnięcie diody.
6. Skopiuj sesję na laptop i uruchom `analiza_sesji.py`.

---

## 4. Opis badań

Oznaczenia: **weryfikacja** = szukanie błędów (testy jednostkowe, dane syntetyczne);
**walidacja** = sprawdzenie wymagań w warunkach rzeczywistych (sesje terenowe).

### T1 – dekoder na danych syntetycznych (weryfikacja)

**Cel.** Sprawdzić poprawność i dokładność dekodera przy znanej prawdzie: pozycja
zakodowana w ramce jest znana dokładnie, więc błąd liczy się bez niepewności odniesienia.

**Dane.** Generator `lib/cpr_gen.py` koduje ramki DF17 (CPR 17-bitowy, CRC-24 z wielomianem
`0x1FFF409`, wysokość z bitem Q, prędkość TC 19, identyfikacja TC 4). Częstości:
pozycja i prędkość co 0,4–0,6 s, identyfikacja co 4,8–5,2 s (*nominalne wartości do
potwierdzenia w Sun 2021*). Poprawność generatora sprawdzono: ramka dla przykładu z książki
Suna ma identyczne pole ME (`58C382D690C8AC`).

**Uruchomienie.**
```bash
python -m pytest -v testy/                     # szybki test (zaliczony / niezaliczony)
python badanie_syntetyczne.py                  # pełne badanie, ok. 15 s
```

| Scenariusz | Co się dzieje | Wynik (plik) | Wskaźnik / próg z metodyki |
|---|---|---|---|
| T1.1 | czysty lot 180 s | `tab_przypadki.tex` | błąd maks. ≤ 10 m; 1. pozycja od razu z 1. ramki pozycyjnej |
| T1.2 | utrata ramek p = 0/10/30/50 %, 20 lotów losowych na wartość p | `tab_syn_utrata.tex`, `rys_syn_t1poz`, `rys_syn_blad` | W1, W2 (η_V ≥ 90 % po 30 s), W3 |
| T1.3 | przekłamania bitów BER 10⁻⁴…10⁻² | `tab_syn_ber.tex` | 100 % uszkodzonych ramek odrzuconych |
| T1.4 | stacja przesunięta o 0…500 km | `tab_syn_stacja.tex`, `rys_syn_stacja` | wykrycie złej stacji; wpływ na azymut/elewację |
| T1.5 | statek 100…440 km od stacji (N i E); filtr 450 km | `tab_syn_zasieg.tex`, `rys_syn_zasieg` | granica poprawnego dekodowania lokalnego |
| T1.6 | skok pozycji tuż poniżej/powyżej 600 m/s·dt + 1000 m | `tab_przypadki.tex` | przyjęty / odrzucony |
| T1.7 | przelot przez granicę stref NL (ok. 50,672°) | `tab_przypadki.tex` | błąd ≤ 10 m, 0 odrzuceń |
| T1.8 | geometria: nad stacją, 10 km N/E, 100 km S | `tab_przypadki.tex` | el = 90°, az = 0°/90°/180°, el ≈ −0,45° (krzywizna) |

**Interpretacja (wyniki z próby w sandboksie, przed badaniem na Twoim laptopie):**
- Błąd pozycji to 0–3,7 m, czyli rozdzielczość CPR, i nie zależy od utraty ramek.
- Czas do pierwszej pozycji LOCAL jest prawie zerowy. Czas do VERIFIED rośnie z utratą ramek (ok. 2,6 s → 6,8 s),
  bo dekodowanie globalne potrzebuje par ramek parzysta/nieparzysta.
- **T1.5 – ważne ustalenie:** dekodowanie lokalne z pozycją stacji jest poprawne do ok.
  **330 km** (kierunek N) / **340 km** (E), zgodnie z granicą 180 NM. Dalej pierwsze pozycje
  LOCAL są błędne o ok. 700 km (zła strefa CPR). **Poprawka z 2026-11-24:** przy niezgodności
  metod wygrywa metoda globalna (PipeDecoder wypuszcza ją dopiero po kilku zgodnych parach
  ramek), więc po kilku sekundach statek dostaje poprawną pozycję **GLOBAL** (błąd ok. 3 m,
  kolumna $e_{\mathrm{kon}}$ w `tab_syn_zasieg.tex`). Gdy także pozycja globalna jest
  odrzucona (np. stacja przesunięta o > 450 km), pozycja statku jest **unieważniana** (NONE)
  zamiast publikować znaną błędną. Wniosek do pracy: jako dane referencyjne używać
  **VERIFIED**, ewentualnie GLOBAL; pozycje LOCAL z pierwszych sekund śledzenia dalekich
  statków mogą być błędne.
- T1.4: niewielki błąd pozycji stacji nie psuje pozycji samolotu (dekodowanie lokalne
  toleruje setki km), ale **psuje kierunek**: 1 km błędu stacji daje do ok. 1° błędu azymutu
  dla bliskiego statku. To argument za GPS w stacji.

### T2.1 – sumy kontrolne i parsowanie NMEA (weryfikacja)

Część `pytest` i Tabeli B (`tab_przypadki.tex`): poprawne GGA/RMC, zmieniona cyfra, ucięte
zdanie, brak `*`, suma nieszesnastkowa, GGA bez fixa, RMC ze statusem V. Zdania testowe mają
zaokrąglone współrzędne (50,0° N, 20,0° E), a nie lokalizację stacji.

### Z.1–Z.4 – korekta zegara `clock_offset.py` (weryfikacja)

Zegar RPi o 3 doby do tyłu, pojedynczy błędny odczyt (+5 s), przestawienie zegara przez NTP,
kompensacja `gps_delay`. Wyniki są w Tabeli B.

### T3.1 – test uruchomienia (integracja, RPi)

Gdy stacja działa ≥ 2 min:
```bash
bash ~/ros2_sdr/badania/rpi/sprawdz_system.sh
```
Skrypt sprawdza usługi systemd, kontener, 5 węzłów i `/rosbag2_recorder`, stan rekordera
(`S`) oraz częstotliwości 7 tematów. Raport trafia do `wyniki/rpi/T3_1_*.txt` z wynikiem
ZALICZONY/NIEZALICZONY. Oczekiwane: `/gps/fix` i `/gps/time_ref` ≈ 1 Hz, `/system/*` 1 Hz,
`/aircraft/*` zależnie od ruchu.

### T3.2 – czas rzeczywisty i obciążenie (RPi, W8)

Dwa pomiary, najlepiej w czasie dziennej sesji z dużym ruchem:
```bash
# 1) czas przetwarzania ramki - w obrazie stacji, obok działającego systemu
docker run --rm --user $(id -u):$(id -g) -v ~/ros2_sdr:/repo ros2_sdr-ros2client \
    python3 /repo/badania/benchmark_dekodera.py --syntetyczne 10 \
    --wyjscie /repo/badania/wyniki/rpi/benchmark_rpi.json
# 2) obciążenie procesów stacji przez 60 min
python3 ~/ros2_sdr/badania/rpi/monitor_cpu.py --minuty 60 \
    --wyjscie ~/ros2_sdr/badania/wyniki/rpi/cpu_$(date -u +%Y%m%d_%H%M)Z.csv
```
Na laptopie (po skopiowaniu `wyniki/rpi/`):
```bash
python wykres_obciazenia.py wyniki/rpi/cpu_<...>.csv --benchmark wyniki/rpi/benchmark_rpi.json --id R-02
```
**Warunek czasu rzeczywistego:** czas na ramkę (P99) ≪ odstęp między ramkami w szczycie
(np. 70 ramek/s → 14 ms). Próg z metodyki: ≤ 1 ms na ramkę. Benchmark można też uruchomić
na ramkach z nagrania (`--ramki wyniki/R-02/dane/ramki.csv`).

### T4.1 – odtworzenie nagrania i porównanie z dump1090 (integracja)

Robi to `analiza_sesji.py`. Ramki z `/aircraft/frames` przechodzą ponownie przez
`adsb_decoder.py` (ten sam kod co na żywo), więc są dostępne także statystyki odrzuceń
(η_R). Następnie dla każdej pozycji SBS z dump1090 wyszukiwana jest pozycja dekodera
tego samego statku z okna ±1 s.
- **Interpretacja:** oba dekodery dostają te same ramki, więc różnica powinna być ≈ 0 m.
  dump1090 podaje współrzędne z 5 miejscami po przecinku, co daje ok. 1 m rozdzielczości,
  dlatego kryterium to „< 1 m”. Mediana ≤ 10 m to próg z metodyki.
- W3: mediana czasu od pierwszej ramki DF17 statku do pierwszej pozycji: dekoder (LOCAL,
  VERIFIED) i dump1090. To pokazuje przewagę dekodowania lokalnego z GPS stacji.
- W4: pokrycie κ, czyli jaka część statków nadających DF17 ma pozycję w każdym z dekoderów.

### T5.1–T5.3 – sesje terenowe (walidacja)

```bash
python analiza_sesji.py dane/sesja_<UTC>Z --id R-02 --notatka "dzień, balkon"
python porownanie_sesji.py wyniki/R-02 wyniki/R-03                 # Tabela C
python porownanie_sesji.py wyniki/R-05 wyniki/R-06 --nazwa antena  # T5.3: antena w/poza obudową
```
Wyniki dla sesji (`wyniki/R-02/`):

| Wykres | Treść | Wskaźnik |
|---|---|---|
| `rys_mapa_*` | ślady statków względem stacji [km], kolor = jakość | – |
| `rys_zasieg_bieg_*` | maks. zasięg w sektorach 10° | W7 |
| `rys_zasieg_wys_*` | odległość vs wysokość + horyzont radiowy (wzór `eq:zasieg`) | W7 |
| `rys_t1poz_*` | dystrybuanta czasu do 1. pozycji: LOCAL, VERIFIED, dump1090 | W3 |
| `rys_roznica_sbs_*` | rozkład różnic dekoder – dump1090 | W1 |
| `rys_liczba_statkow_*` | liczba statków w czasie (okna 1 min) | – |
| `rys_ramki_*` | ramki/s w czasie (obciążenie wejścia) | W5 |
| `rys_temp_*` | temperatura CPU w czasie | W10 |
| `rys_zegar_*` | δ_k − δ̂ w czasie, zaznaczone skoki czasu GPS | W9, F1 |

Tabele: `tab_sesja_<ID>.tex` (podsumowanie, wszystkie wskaźniki) i `tab_df_<ID>.tex`
(udziały rodzajów ramek DF). Mapa jest rysowana **w km względem stacji**, więc nie ujawnia
lokalizacji.

**Interpretacja:**
- Zasięg rośnie z wysokością statku (horyzont radiowy), a maleje przy przesłoniętym horyzoncie
  i antenie w obudowie (T5.3).
- Liczba statków i ramek zależy od pory dnia. Wpływa to na rozmiar danych [MB/h] i obciążenie.
- η_V niższe od 100 % na początku śledzenia każdego statku to efekt rozruchu metody globalnej.

### T6.1 – czas pracy na baterii

Naładuj powerbank do 100 %, uruchom stację i zostaw do samoczynnego wyłączenia. Potem:
```bash
journalctl --list-boots | tail -3        # na RPi: koniec poprzedniego uruchomienia = chwila odcięcia
```
Na laptopie podaj tę chwilę (czas lokalny z `journalctl`):
```bash
python analiza_sesji.py dane/sesja_<UTC>Z --id R-04 --koniec "2026-11-26 07:41:12"
```
W tabeli pojawi się czas pracy [h] i utracone nagranie [min]. Próg: T_bat ≥ 8 h. Wzór na
średnią moc (`eq:t_bat`, `eq:p_sr` w rozdz. 6) wymaga pojemności powerbanku.

### T6.2 – nagłe odcięcie zasilania

Wyciągnij kabel zasilania w trakcie nagrywania. Po ponownym uruchomieniu:
```bash
bash ~/ros2_sdr/badania/rpi/raport_sesji.sh        # sesja bez metadata.yaml = NIE
bash ~/ros2_sdr/badania/rpi/napraw_sesje.sh sesja_<UTC>Z
```
Utracone nagranie liczy `analiza_sesji.py --koniec ...`. Próg: ≤ 10 min (jeden plik MCAP).

### T6.3 – wyłączenie przyciskiem

Przytrzymaj przycisk 2 s, a po ponownym uruchomieniu wykonaj `raport_sesji.sh`. Sesja musi mieć
`metadata.yaml = tak`, a w `analiza_sesji.py` brak ostrzeżeń o przerwanym pliku.

### T7.1 – temperatura w obudowie (z wentylatorem / bez)

Dwie sesje po ≥ 60 min w tych samych warunkach (wpisz w `sesje.csv` kolumnę `wentylator`),
najlepiej z równoległym `monitor_cpu.py`. Porównanie:
```bash
python porownanie_sesji.py wyniki/R-07 wyniki/R-08 --nazwa wentylator
```
Próg: maks. < 80 °C (*wartość progu dławienia RPi 4 sprawdź w dokumentacji Raspberry Pi*).

### T8.1 – przesunięcie zegara (z NTP / bez NTP) i ustalenie F1

Analiza czasu jest w każdej sesji (wykres `rys_zegar_*`, wiersze δ̂, σ_δ, skoki).
- **Z NTP** (RPi z internetem): zegar RPi jest poprawny, więc δ̂ ≈ 0 s, jeśli `gps_delay` jest
  dobrze dobrany. `gps_delay` = opóźnienie zdania RMC; zmierzone 2026-11-24: **0,150 s**, ustawione
  w `start_nodes.sh` (`--ros-args -p gps_delay:=0.150`). Analiza używa tej samej wartości
  (`analiza_sesji.py --gps-delay 0.150`, domyślnie). Jeśli przy NTP δ̂ wyraźnie różni się od 0,
  zmierz ponownie i popraw obie wartości.
- **Bez NTP** (teren): δ̂ może wynosić godziny lub dni. Sprawdzamy, czy korekta na żywo
  (`time_source = 1` w `/aircraft/state`) zgadza się z korektą końcową (wiersz w wydruku
  „korekta na żywo vs końcowa”).
- **F1:** jeśli moduł GPS po złapaniu fixa podaje UTC o 2 s za wcześnie, na `rys_zegar_*`
  widać skok o ok. −2 s po ≤ 12,5 min. Skrypt podaje czas i wielkość skoku.

### T9.1 – porównanie z OpenSky Network (walidacja, niezależne źródło)

W trakcie sesji, na laptopie z internetem:
```bash
python opensky_zapis.py --lat <szer.> --lon <dł.> --minuty 60 --wyjscie dane/opensky_R-02.csv
```
Bez konta OpenSky daje 400 kredytów API na dobę i rozdzielczość czasu 10 s, co wystarcza
na ok. 60 min przy zapytaniu co 10 s. Z kontem trzeba ustawić `OPENSKY_CLIENT_ID`
i `OPENSKY_CLIENT_SECRET` (OAuth2). Potem:
```bash
python porownanie_zewnetrzne.py wyniki/R-02 dane/opensky_R-02.csv
```
Skrypt liczy rozkład błędu pozycji przy τ = 0 oraz przesunięcie czasu τ*, przy którym mediana
błędu jest najmniejsza. **τ* ≈ 0** oznacza zgodność czasu stacji z niezależnym źródłem.
|τ*| ≈ 2 s wskazuje na nieskorygowane F1. τ* < 0 oznacza, że czas źródła zewnętrznego jest
późniejszy niż czas stacji. Błąd obejmuje też niedokładność OpenSky (czas pozycji co 1 s,
własne opóźnienia), więc oczekiwane są dziesiątki metrów, a nie metry.

---

## 5. Wstawianie wyników do pracy (Overleaf)

1. Skopiuj potrzebne pliki `.pdf` z `wyniki/.../wykresy/` do folderu `img/` w Overleaf.
2. Obok każdego wykresu jest plik `.tex` z gotowym środowiskiem `figure`. Podpis i etykieta są
   propozycją, więc zmień je na własne słowa.
3. Tabele `.tex` wstaw poleceniem `\input{tables/tab_...}` (folder `tables/` w Overleaf).
   Wymagają pakietu `booktabs` (jest w preambule). Liczby mają już przecinek dziesiętny.
4. **Każdy rysunek i tabelę trzeba przywołać w tekście i omówić**, czyli wyjaśnić zależności, a nie
   tylko je pokazać. Tych samych danych nie pokazuje się jednocześnie w tabeli i na wykresie.
5. Dane surowe (CSV) mogą trafić do załącznika albo do repozytorium po usunięciu lokalizacji.

---

## 6. Próba całego toru bez prawdziwych danych

```bash
python generuj_sesje_testowa.py dane/sesja_TEST --minuty 30
python analiza_sesji.py dane/sesja_TEST --id TEST
```
Sztuczna sesja zawiera 8 statków (w tym jeden ok. 360 km od stacji, co pokazuje problem
z T1.5), zegar RPi przesunięty o 3 doby, skok czasu GPS o 2 s po 13 min (F1), przerwę w fixie
i zdarzenie niskiego napięcia. **To nie są wyniki badań.**

---

## 7. Rozwiązywanie problemów

| Objaw | Przyczyna / rozwiązanie |
|---|---|
| `ModuleNotFoundError: mcap` | nie aktywowano venv: `source ~/badania-venv/bin/activate` |
| `UWAGA: ..._N.mcap: przerwano odczyt` | ostatni plik po odcięciu zasilania; dane do tego miejsca są wczytane |
| Ponowna analiza nie widzi zmian w nagraniu | dodaj `--odswiez` (skrypt pamięta CSV w `wyniki/<ID>/dane/`) |
| W tabeli `--` | brak danych (np. sesja bez `/aircraft/frames` jak R-01: działa tylko część SBS/GPS/system) |
| `sprawdz_system.sh`: brak tematów `/gps/*` | GPS bez fixa (w pomieszczeniu) |
| `Permission denied` przy `wyniki/rpi` | katalog utworzył root: `sudo chown -R maks:maks ~/ros2_sdr/badania/wyniki` |
