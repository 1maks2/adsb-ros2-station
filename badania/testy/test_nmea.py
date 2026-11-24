"""Testy sumy kontrolnej i parsowania NMEA w gps_node.py (scenariusz T2.1)."""
from lib import cases


def test_nmea():
    bad = [r for r in cases.case_nmea() if not r['wynik']]
    assert not bad, bad
