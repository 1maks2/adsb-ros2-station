"""Czytanie sesji rosbag2 (MCAP) BEZ instalacji ROS 2.

Wykorzystuje biblioteki `mcap` i `mcap-ros2-support` (pip). Format MCAP
przechowuje schemat każdej wiadomości, więc także własny typ AircraftState
da się odczytać bez budowania pakietu aircraft_interfaces.

Sesja = folder sesja_YYYYMMDD_HHMMSSZ z plikami *_0.mcap, *_1.mcap, ...
Ostatni plik po nagłym zaniku zasilania bywa niekompletny - czytamy go
sekwencyjnie i zatrzymujemy się na pierwszym uszkodzonym fragmencie.
"""
import glob
import os
import re
import sys

TOPICS = ['/aircraft/raw', '/aircraft/frames', '/aircraft/state', '/gps/fix',
          '/gps/time_ref', '/system/undervoltage', '/system/cpu_temp']


def session_files(session_dir):
    files = glob.glob(os.path.join(session_dir, '*.mcap'))

    def idx(p):
        m = re.search(r'_(\d+)\.mcap$', p)
        return int(m.group(1)) if m else 0
    return sorted(files, key=idx)


def t_of(stamp):
    """builtin_interfaces/Time -> sekundy (float)."""
    return stamp.sec + stamp.nanosec * 1e-9


def iter_messages(session_dir, topics=None, warn=print):
    """Zwraca kolejno (topic, log_time_s, msg) ze wszystkich plików sesji.

    log_time_s = czas zapisu przez rosbag2 (zegar RPi, bez korekty).
    """
    try:
        from mcap.reader import NonSeekingReader
        from mcap_ros2.decoder import DecoderFactory
    except ImportError:
        sys.exit('Brak bibliotek: pip install mcap mcap-ros2-support')
    topics = set(topics or TOPICS)
    files = session_files(session_dir)
    if not files:
        sys.exit(f'Brak plików .mcap w {session_dir}')
    for path in files:
        n = 0
        try:
            with open(path, 'rb') as f:
                reader = NonSeekingReader(f, decoder_factories=[DecoderFactory()])
                for schema, channel, message, msg in reader.iter_decoded_messages():
                    if channel.topic in topics:
                        n += 1
                        yield channel.topic, message.log_time * 1e-9, msg
        except Exception as e:  # uszkodzony koniec pliku (np. odcięcie zasilania)
            warn(f'UWAGA: {os.path.basename(path)}: przerwano odczyt po {n} '
                 f'wiadomościach ({type(e).__name__}: {e})')


def session_info(session_dir):
    files = session_files(session_dir)
    return {
        'sesja': os.path.basename(os.path.normpath(session_dir)),
        'pliki_mcap': len(files),
        'rozmiar_MB': sum(os.path.getsize(p) for p in files) / 1e6,
        'metadata_yaml': os.path.exists(os.path.join(session_dir, 'metadata.yaml')),
        'ostatni_plik_B': os.path.getsize(files[-1]) if files else 0,
    }
