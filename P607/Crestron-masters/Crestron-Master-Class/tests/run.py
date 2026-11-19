"""Run every test: python tests/run.py"""

import sys
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
sys.path[:0] = [str(TESTS.parent)]
suite = unittest.defaultTestLoader.discover(str(TESTS), top_level_dir=str(TESTS))
sys.exit(not unittest.TextTestRunner(verbosity=1).run(suite).wasSuccessful())
