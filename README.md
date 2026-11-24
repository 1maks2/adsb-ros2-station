# adsb-ros2-station

Przenośna stacja bazowa ADS-B w ROS 2 – część projektu dyplomowego
*„Przenośny system logowania pozycji statków powietrznych w ROS 2.0 na podstawie transponderów ADS-B”* (AGH, WEAIiIB, Automatyka i Robotyka).

Stacja odbiera sygnały ADS-B (1090 MHz), w czasie rzeczywistym wyznacza pozycje statków powietrznych
względem własnej pozycji z GPS i publikuje je jako komunikaty ROS 2. Wszystkie dane są nagrywane (rosbag2, MCAP)
jako dane referencyjne, np. do oceny algorytmów detekcji statków powietrznych z kamery.

## Sprzęt
- Raspberry Pi 4B (Ubuntu, system na pendrive USB 64 GB)
- RTL-SDR Blog V3 + antena dipolowa λ/4, montowana pionowo
- moduł GPS na UART (`/dev/ttyAMA0`, 9600 bit/s, NMEA GGA/RMC)
- wyświetlacz TFT 2,4" ILI9341 (SPI)
- przycisk wyłączania (GPIO3) i dioda stanu (GPIO17)
- zasilanie z powerbanku USB-C, obudowa drukowana 3D

## Działanie w skrócie
- `dump1090` (host) demoduluje sygnał z RTL-SDR i udostępnia ramki przez TCP (30002 – surowe ramki, 30003 – SBS).
- Węzły ROS 2 Jazzy działają w kontenerze Docker uruchamianym przez systemd zaraz po włączeniu zasilania.
- `decoder_node` dekoduje ramki DF17 dwiema niezależnymi metodami CPR (lokalną z pozycją stacji i globalną z par ramek).
  Zgodne wyniki dostają jakość VERIFIED.
- Znaczniki czasu są poprawiane do UTC na podstawie czasu z GPS (Raspberry Pi nie ma zegara RTC).
- Nagrywanie startuje automatycznie: każde włączenie stacji tworzy nową sesję `sesja_<UTC>Z`, plik `.mcap` co 10 min.

## Węzły i tematy
| Węzeł | Publikuje |
|---|---|
| `sdr_radar_node` | `/aircraft/raw` (linie SBS), `/aircraft/frames` (surowe ramki AVR) |
| `gps_node` | `/gps/fix` (pozycja stacji), `/gps/time_ref` (czas UTC z GPS) |
| `decoder_node` | `/aircraft/state` (`aircraft_interfaces/AircraftState`: pozycja, jakość, wysokość, prędkość, odległość, azymut, elewacja) |
| `power_monitor_node` | `/system/undervoltage`, `/system/cpu_temp` |
| `display_node` | – (wyświetla stan na TFT) |
| `rosbag2_recorder` | nagrywa wszystkie 7 tematów |

## Uruchomienie i obsługa
- Włączenie zasilania = start systemu i nagrywania. Po około 1–2 min na wyświetlaczu pojawia się `REC`.
- Wyłączenie: przytrzymaj przycisk 2 s i poczekaj, aż zgaśnie dioda. Dopiero wtedy odłącz zasilanie.
- Uwaga o czasie GPS: tani moduł GPS przez pierwsze minuty po złapaniu sygnału może podawać czas o 2 s za wcześnie.
  Gdy moduł to poprawi, `decoder_node` zapisze w logu komunikat „Skok czasu GPS…”. Pomiary, w których liczy się dokładny czas,
  najlepiej zaczynać dopiero po tym komunikacie.

## Przydatne polecenia

Na Raspberry Pi (przez SSH):
- `journalctl -u ros2-adsb.service -f` – podgląd na żywo komunikatów wszystkich węzłów (wyjście: Ctrl+C)
- `sudo systemctl restart ros2-adsb.service` – restart całego oprogramowania stacji (zaczyna też nową sesję nagrania)
- `docker exec -it ros2_jazzy_lpa bash` – wejście do kontenera z ROS 2

W kontenerze (najpierw `source /ros2_ws/install/setup.bash`, żeby ROS znał typ `AircraftState`):
- `ros2 node list` – lista działających węzłów (powinno być 5 + `rosbag2_recorder`)
- `ros2 topic list` – lista tematów
- `ros2 topic hz /aircraft/frames` – ile ramek na sekundę przychodzi z odbiornika (wyjście: Ctrl+C)
- `ros2 topic echo /aircraft/state --once` – jeden komunikat ze stanem statku powietrznego
- `ros2 bag info /ros2_ws/bags/<sesja>` – podsumowanie nagranej sesji (czas trwania, liczba wiadomości)

## Struktura repozytorium
- `ros2_ws/src/aircraft_tracker/` – węzły ROS 2 (Python) oraz moduły `adsb_decoder.py` i `clock_offset.py`, oba bez zależności od ROS
- `ros2_ws/src/aircraft_interfaces/` – własny typ komunikatu `AircraftState`
- `ros2_ws/start_nodes.sh` – skrypt startowy kontenera (budowanie, węzły, nagrywanie, poprawne zamykanie)
- `Dockerfile`, `docker-composer.yml` – obraz i kontener (ROS 2 Jazzy)
- `system/` – kopia plików konfiguracyjnych systemu (usługi systemd, `config.txt`, skrypt przycisku) i stanu systemu
- `badania/` – testy i skrypty analizy wyników (instrukcja w `badania/README.md`)
- `backup_system.sh` – kopia zapasowa konfiguracji i kodu do tego repozytorium

## Odtworzenie stacji od zera (skrót)
1. Zainstaluj Ubuntu na RPi i sklonuj repozytorium do `~/ros2_sdr`.
2. Zainstaluj pakiety: `sudo apt install $(cat system/state/apt-packages-manual.txt)`.
3. Skopiuj `system/files/*` do `/`, potem `sudo systemctl daemon-reload` i włącz usługi z `system/state/enabled-services.txt`.
4. Zbuduj obraz: `docker compose -f docker-composer.yml build`.
5. Uruchom ponownie RPi.

## Licencja
MIT – patrz `LICENSE`.