"""Testy estymatora przesunięcia zegara (clock_offset.py): Z.1-Z.4."""
from lib import cases


def test_zegar():
    bad = [r for r in cases.case_clock() if not r['wynik']]
    assert not bad, bad
