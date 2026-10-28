"""Run the complete automated suite; skipped checks cannot produce a green gate."""
from pathlib import Path
import sys
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if __name__ == '__main__':
    suite = unittest.defaultTestLoader.discover(str(ROOT/'tests'))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.skipped:
        print('Skipped checks are not accepted by the development gate:', result.skipped)
    raise SystemExit(0 if result.wasSuccessful() and not result.skipped else 1)
