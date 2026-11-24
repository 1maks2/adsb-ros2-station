"""Konfiguracja pytest: dostęp do badania/lib i do pakietu aircraft_tracker."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib import common  # noqa: E402,F401  (ustawia ścieżkę do aircraft_tracker)
