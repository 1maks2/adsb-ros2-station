"""Testy jednostkowe adsb_decoder.py (scenariusze T1.1-T1.8, weryfikacja).

Uruchomienie (z folderu badania/):  python -m pytest -v testy/
"""
import pytest

from lib import cases


def _ids(rows):
    return [f"{r['id']} {r['warunek']}" for r in rows]


@pytest.mark.parametrize('case', [
    cases.case_clean_flight, cases.case_bit_errors, cases.case_wrong_station,
    cases.case_range_limit, cases.case_jump_limit, cases.case_nl_crossing,
    cases.case_geometry,
], ids=lambda f: f.__name__)
def test_dekoder(case):
    rows = case()
    bad = [r for r in rows if not r['wynik']]
    assert not bad, '\n'.join(
        f"{r['id']} {r['warunek']}: oczekiwano {r['oczekiwane']}, uzyskano {r['uzyskane']}"
        for r in bad)
