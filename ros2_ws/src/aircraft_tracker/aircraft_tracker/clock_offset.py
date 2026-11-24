#!/usr/bin/env python3
"""Wyznaczanie przesunięcia zegara RPi względem czasu GPS.

Ten moduł NIE korzysta z ROS - da się go testować osobno.

Raspberry Pi nie ma zegara RTC. W terenie, bez internetu (NTP), zegar
systemowy po starcie może się mylić nawet o kilka dni. Odbiornik GPS
podaje dokładny czas UTC, więc z każdej pary:
    t_gps  - czas UTC z GPS (zdanie RMC, temat /gps/time_ref, pole time_ref),
    t_sys  - czas zegara RPi w chwili odczytu zdania (header.stamp),
liczymy jedną próbkę przesunięcia:
    delta_k = t_gps - t_sys + gps_delay
Poprawiony czas dowolnego zdarzenia: t_poprawiony = t_sys + delta.

gps_delay [s] - opóźnienie między początkiem sekundy GPS a odczytem zdania
przez gps_node (transmisja 9600 bit/s + odpytywanie portu co 100 ms).
Domyślnie 0; można je zmierzyć, gdy zegar RPi jest zsynchronizowany przez
NTP (wtedy średnio delta_k = -gps_delay) - test T8.1.

Estymata = MEDIANA z ostatnich próbek (odporna na pojedyncze spóźnione
odczyty). Jeśli zegar RPi zostanie nagle przestawiony (np. NTP po
podłączeniu internetu), kolejne próbki przesuną się skokowo - po kilku
zgodnych "nowych" próbkach estymata zaczyna się od nowa.
"""
from collections import deque
import statistics


class ClockOffset:
    def __init__(self, window=60, min_samples=3, jump_threshold=1.0,
                 jump_confirm=3, gps_delay=0.0):
        self.samples = deque(maxlen=window)  # zaakceptowane próbki delta_k [s]
        self.min_samples = min_samples        # ile próbek, zanim zaczniemy poprawiać czas
        self.jump_threshold = jump_threshold  # [s] różnica uznawana za skok zegara
        self.jump_confirm = jump_confirm      # ile zgodnych próbek potwierdza skok
        self.gps_delay = gps_delay            # [s] opóźnienie odczytu zdania NMEA
        self.pending = []                     # próbki odstające (kandydaci na skok)
        self.last_sample_sys = None           # czas RPi ostatniej próbki [s]
        self.jumps = 0                        # ile razy wykryto przestawienie zegara
        self.outliers = 0                     # ile próbek odrzucono jako odstające

    # ------------------------------------------------------------------ #
    def add(self, t_gps, t_sys):
        """Dodaje próbkę (czas GPS, czas RPi) w sekundach.

        Zwraca True, jeśli wykryto i przyjęto skok zegara RPi.
        """
        d = t_gps - t_sys + self.gps_delay
        self.last_sample_sys = t_sys
        est = self.offset()

        # Za mało próbek albo próbka zgodna z dotychczasową estymatą -> przyjmujemy
        if est is None or abs(d - est) <= self.jump_threshold:
            self.samples.append(d)
            self.pending.clear()
            return False

        # Próbka odstająca: pojedyncza = błąd odczytu, kilka zgodnych = skok zegara
        self.pending.append(d)
        if len(self.pending) >= self.jump_confirm:
            if max(self.pending) - min(self.pending) <= self.jump_threshold:
                self.samples.clear()
                self.samples.extend(self.pending)
                self.pending.clear()
                self.jumps += 1
                return True
            self.pending.pop(0)    # niezgodne między sobą - zapominamy najstarszą
        self.outliers += 1
        return False

    def offset(self):
        """Aktualne przesunięcie zegara [s] (GPS - RPi) albo None, gdy za mało danych."""
        if len(self.samples) < self.min_samples:
            return None
        return statistics.median(self.samples)

    def spread(self):
        """Rozrzut próbek w oknie [s] (odchylenie standardowe), albo None."""
        if len(self.samples) < 2:
            return None
        return statistics.stdev(self.samples)

    def age(self, now_sys):
        """Ile sekund minęło od ostatniej próbki z GPS (None, jeśli nie było żadnej)."""
        if self.last_sample_sys is None:
            return None
        return now_sys - self.last_sample_sys