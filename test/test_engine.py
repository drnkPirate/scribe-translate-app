import importlib.util
import unittest
from pathlib import Path

import numpy as np


MODULE_PATH = Path(__file__).parents[1] / "sidecar" / "engine.py"
SPEC = importlib.util.spec_from_file_location("scribe_translate_engine", MODULE_PATH)
engine = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(engine)


class EngineTest(unittest.TestCase):
    def test_audio_validation_and_gain(self):
        prepared, silent, gain = engine.prepare_audio(np.full(16_000, 0.002, dtype=np.float32))
        self.assertFalse(silent)
        self.assertGreater(gain, 1)
        self.assertAlmostEqual(float(np.max(prepared)), 0.04, places=3)
        with self.assertRaises(ValueError):
            engine.prepare_audio(np.zeros((2, 10), dtype=np.float32))


if __name__ == "__main__":
    unittest.main()
