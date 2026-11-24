#!/usr/bin/env python3
"""Generuje SZTUCZNĄ sesję rosbag2 (MCAP) do sprawdzenia toru analizy.

Po co: zanim zbierzesz dane w terenie, możesz sprawdzić, że analiza_sesji.py
działa i jak wyglądają tabele/wykresy. Wyniki z takiej sesji NIE są wynikami
badań - nie wolno ich wstawiać do pracy jako pomiarów.

Symulowane są (z prawdą znaną z generatora):
  - kilka statków powietrznych (ramki DF17 z utratą 20 %) + krótkie ramki Mode S,
  - wyjście SBS dump1090 (pozycja dopiero z pary ramek, jak bez --lat/--lon),
  - /aircraft/state z dekodera i korektą czasu (jak decoder_node),
  - zegar RPi przesunięty o 3 doby (brak NTP) i moduł GPS podający czas
    o 2 s za wcześnie przez pierwsze 13 min (zjawisko F1), opóźnienie zdań 0,16 s,
  - przerwa w fixie GPS, temperatura CPU, jedno zdarzenie niskiego napięcia.

Uruchomienie:
  python3 generuj_sesje_testowa.py dane/sesja_TEST  [--minuty 30]
"""
import argparse
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import common, cpr_gen  # noqa: E402
from lib.common import dec  # noqa: E402

TIME = 'int32 sec\nuint32 nanosec'
HEADER = 'builtin_interfaces/Time stamp\nstring frame_id'
SEP = '\n' + '=' * 80 + '\n'


def msgdef(main, deps):
    return main + ''.join(f'{SEP}MSG: {name}\n{body}' for name, body in deps)


DEFS = {
    'std_msgs/msg/String': 'string data',
    'std_msgs/msg/Bool': 'bool data',
    'sensor_msgs/msg/NavSatFix': msgdef(
        'std_msgs/Header header\nsensor_msgs/NavSatStatus status\nfloat64 latitude\n'
        'float64 longitude\nfloat64 altitude\nfloat64[9] position_covariance\n'
        'uint8 position_covariance_type',
        [('std_msgs/Header', HEADER), ('builtin_interfaces/Time', TIME),
         ('sensor_msgs/NavSatStatus', 'int8 status\nuint16 service')]),
    'sensor_msgs/msg/TimeReference': msgdef(
        'std_msgs/Header header\nbuiltin_interfaces/Time time_ref\nstring source',
        [('std_msgs/Header', HEADER), ('builtin_interfaces/Time', TIME)]),
    'sensor_msgs/msg/Temperature': msgdef(
        'std_msgs/Header header\nfloat64 temperature\nfloat64 variance',
        [('std_msgs/Header', HEADER), ('builtin_interfaces/Time', TIME)]),
}


def aircraft_state_def():
    path = os.path.join(common.REPO_DIR, 'ros2_ws', 'src', 'aircraft_interfaces', 'msg',
                        'AircraftState.msg')
    with open(path, encoding='utf-8') as f:
        body = f.read()
    return msgdef(body, [('std_msgs/Header', HEADER), ('builtin_interfaces/Time', TIME)])


def tmsg(t):
    s = int(math.floor(t))
    return {'sec': s, 'nanosec': int(round((t - s) * 1e9)) % 1000000000}


class SessionWriter:
    """Zapis w kawałkach po 10 min, jak rosbag2 z --max-bag-duration 600."""

    def __init__(self, folder, t0, split_s=600):
        from mcap_ros2.writer import Writer
        self.Writer = Writer
        self.folder = folder
        self.name = os.path.basename(os.path.normpath(folder))
        self.t0, self.split = t0, split_s
        self.idx = -1
        self.w = None
        os.makedirs(folder, exist_ok=True)

    def _open(self, idx):
        if self.w:
            self.w.finish()
            self.f.close()
        self.idx = idx
        self.f = open(os.path.join(self.folder, f'{self.name}_{idx}.mcap'), 'wb')
        self.w = self.Writer(self.f)
        self.schemas = {k: self.w.register_msgdef(k, v) for k, v in DEFS.items()}
        self.schemas['aircraft_interfaces/msg/AircraftState'] = self.w.register_msgdef(
            'aircraft_interfaces/msg/AircraftState', aircraft_state_def())

    def write(self, topic, dtype, msg, t_log):
        idx = int((t_log - self.t0) // self.split)
        if idx != self.idx:
            self._open(idx)
        ns = int(t_log * 1e9)
        self.w.write_message(topic, self.schemas[dtype], msg, log_time=ns, publish_time=ns)

    def close(self):
        if self.w:
            self.w.finish()
            self.f.close()
        with open(os.path.join(self.folder, 'metadata.yaml'), 'w') as f:
            f.write('rosbag2_bagfile_information:\n  version: 9\n  storage_identifier: mcap\n'
                    '  # plik testowy z generuj_sesje_testowa.py\n')


def sbs_line(kind, icao, d):
    f = ['MSG', str(kind), '1', '1', icao, '1', '', '', '', '', '', '', '', '', '', '', '',
         '', '', '', '', '0']
    if kind == 1:
        f[10] = d.get('callsign', '')
    if kind == 3:
        f[11] = str(d.get('alt', ''))
        f[14], f[15] = f"{d['lat']:.5f}", f"{d['lon']:.5f}"
    if kind == 4:
        f[12], f[13] = str(d.get('gs', '')), str(d.get('trk', ''))
        f[16] = str(d.get('vr', ''))
    return ','.join(f)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('folder')
    ap.add_argument('--minuty', type=float, default=30.0)
    ap.add_argument('--statki', type=int, default=8)
    ap.add_argument('--ziarno', type=int, default=42)
    a = ap.parse_args()
    import pyModeS
    from aircraft_tracker.clock_offset import ClockOffset

    rng = random.Random(a.ziarno)
    st = common.STACJA_PRZYKLAD
    T = a.minuty * 60.0
    TRUE0 = 1795521600.0            # prawdziwy UTC startu (2026-11-24 12:00)
    RPI_OFF = -3 * 86400.0          # zegar RPi spóźniony o 3 doby (brak NTP)
    LAT = 0.16                      # opóźnienie zdania RMC

    # Statki: jeden daleki (ok. 360 km) do pokazania problemu dekodowania lokalnego
    events = []
    for k in range(a.statki):
        far = (k == 0)
        f = cpr_gen.random_flight(rng, st, (355, 365) if far else (15, 280),
                                  icao=0x480000 + k * 0x111)
        if far:
            f.track = (f.track + 90) % 360
        t_start = rng.uniform(0, T * 0.5)
        dur = rng.uniform(600, T - t_start) if T - t_start > 600 else T - t_start
        evs = f.generate(dur, rng, t0=t_start)
        events += cpr_gen.apply_loss(evs, 0.2, rng)
    # krótkie ramki Mode S (DF4/5/11/20/21) jako tło - losowa treść
    t = 0.0
    while t < T:
        df = rng.choice([4, 5, 11, 11, 20, 21])
        nbits = 56 if df in (4, 5, 11) else 112
        v = (df << (nbits - 5)) | rng.getrandbits(nbits - 5)
        events.append((t, f'{v:0{nbits // 4}X}', 'modes', None))
        t += rng.expovariate(15.0)
    events.sort(key=lambda e: e[0])

    w = SessionWriter(a.folder, TRUE0 + RPI_OFF)
    d = dec.AdsbDecoder()
    clk = ClockOffset(gps_delay=0.150)   # jak w start_nodes.sh
    sbs_pipe = pyModeS.PipeDecoder()
    next_gps = 0.0
    ei = 0
    while next_gps < T or ei < len(events):
        if ei < len(events) and (next_gps >= T or events[ei][0] < next_gps):
            t, frame, kind, _ = events[ei]
            ei += 1
            t_rpi = TRUE0 + t + RPI_OFF + 0.002
            w.write('/aircraft/frames', 'std_msgs/msg/String', {'data': f'*{frame};'}, t_rpi)
            if kind != 'modes':
                g = sbs_pipe.decode(frame, timestamp=TRUE0 + t)
                icao = g.get('icao')
                if g.get('latitude') is not None:
                    w.write('/aircraft/raw', 'std_msgs/msg/String', {'data': sbs_line(
                        3, icao, {'lat': g['latitude'], 'lon': g['longitude'],
                                  'alt': g.get('altitude', '')})}, t_rpi + 0.001)
                elif g.get('callsign'):
                    w.write('/aircraft/raw', 'std_msgs/msg/String',
                            {'data': sbs_line(1, icao, {'callsign': g['callsign']})}, t_rpi)
                elif g.get('groundspeed') is not None:
                    w.write('/aircraft/raw', 'std_msgs/msg/String', {'data': sbs_line(
                        4, icao, {'gs': g['groundspeed'], 'trk': round(g['track'], 1),
                                  'vr': g.get('vertical_rate', '')})}, t_rpi)
            icao = d.process(f'*{frame};', t_rpi)
            if icao:
                s = d.state(icao)
                off = clk.offset()
                o = off if off is not None else 0.0
                m = {'header': {'stamp': tmsg(t_rpi + o), 'frame_id': 'gps_link'},
                     'time_source': 1 if off is not None else 0,
                     'clock_offset': off if off is not None else math.nan,
                     'icao': icao, 'callsign': s['callsign'], 'latitude': s['latitude'],
                     'longitude': s['longitude'], 'position_quality': s['position_quality'],
                     'position_stamp': tmsg(s['position_time'] + o)
                     if not math.isnan(s['position_time']) else tmsg(0),
                     'altitude': s['altitude'], 'altitude_type': s['altitude_type'],
                     'altitude_baro': s['altitude_baro'], 'ground_speed': s['ground_speed'],
                     'track': s['track'], 'vertical_rate': s['vertical_rate'],
                     'ground_distance': s['ground_distance'],
                     'slant_distance': s['slant_distance'], 'azimuth': s['azimuth'],
                     'elevation': s['elevation']}
                w.write('/aircraft/state', 'aircraft_interfaces/msg/AircraftState', m,
                        t_rpi + 0.003)
        else:
            t = next_gps
            next_gps += 1.0
            gap = 600 <= t < 720          # 2 min bez fixa
            t_read = TRUE0 + t + LAT + rng.uniform(0, 0.1) + RPI_OFF
            if not gap:
                label = TRUE0 + t + (2.0 if t < 13 * 60 else 0.0)
                w.write('/gps/time_ref', 'sensor_msgs/msg/TimeReference',
                        {'header': {'stamp': tmsg(t_read), 'frame_id': ''},
                         'time_ref': tmsg(label), 'source': 'gps'}, t_read + 0.001)
                clk.add(label, t_read)
                fix = {'header': {'stamp': tmsg(t_read + 0.1), 'frame_id': 'gps_link'},
                       'status': {'status': 0, 'service': 1},
                       'latitude': st[0] + rng.gauss(0, 1e-5),
                       'longitude': st[1] + rng.gauss(0, 1e-5),
                       'altitude': st[2] + rng.gauss(0, 2), 'position_covariance': [0.0] * 9,
                       'position_covariance_type': 0}
                w.write('/gps/fix', 'sensor_msgs/msg/NavSatFix', fix, t_read + 0.101)
                d.set_station(fix['latitude'], fix['longitude'], fix['altitude'])
            temp = 58 + 4 * math.sin(t / 900.0) + rng.gauss(0, 0.5)
            w.write('/system/cpu_temp', 'sensor_msgs/msg/Temperature',
                    {'header': {'stamp': tmsg(TRUE0 + t + RPI_OFF), 'frame_id': 'cpu'},
                     'temperature': temp, 'variance': 0.0}, TRUE0 + t + RPI_OFF)
            w.write('/system/undervoltage', 'std_msgs/msg/Bool',
                    {'data': 900 <= t < 905}, TRUE0 + t + RPI_OFF)
    w.close()
    print(f'Zapisano sztuczną sesję: {a.folder} ({w.idx + 1} plików MCAP)')


if __name__ == '__main__':
    main()
