"""Test package for querybloom.

By default, unittest test discovery discovers tests in tests/unit.
"""

from __future__ import annotations

import os
from unittest import TestSuite


def load_tests(loader, standard_tests, pattern):
    unit_dir = os.path.join(os.path.dirname(__file__), "unit")
    unit_suite = loader.discover(start_dir=unit_dir, pattern=pattern or "test_*.py")
    suite = TestSuite()
    suite.addTests(unit_suite)
    return suite
