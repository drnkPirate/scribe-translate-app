import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np


MODULE_PATH = Path(__file__).parents[1] / "sidecar" / "engine.py"
SPEC = importlib.util.spec_from_file_location("scribe_translate_engine", MODULE_PATH)
engine = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(engine)


class EngineTest(unittest.TestCase):
    def test_processing_effort_reaches_partial_and_final_translation(self):
        class Tokenizer:
            eos_token = "</s>"

            def __call__(self, *args, **kwargs):
                return SimpleNamespace(input_ids=[SimpleNamespace(tolist=lambda: ["goed", "</s>"])])

            def convert_ids_to_tokens(self, tokens):
                return tokens

            def convert_tokens_to_ids(self, tokens):
                return tokens

            def decode(self, tokens, **kwargs):
                return " ".join(tokens[:-1])

        pipeline = engine.Pipeline.__new__(engine.Pipeline)
        pipeline.tokenizer = Tokenizer()
        pipeline.translator = SimpleNamespace(translate_batch=lambda sources, **options: [
            SimpleNamespace(hypotheses=[[f"beam-{options['beam_size']}", "</s>"]]) for _ in sources
        ])
        pipeline.photon = SimpleNamespace(transcribe=lambda **kwargs: {"text": "Goedemorgen."})
        pipeline.vad = pipeline.detect_speech = None
        pipeline.device = "cpu"
        for quality, partial_beam, final_beam in (("fast", 1, 4), ("balanced", 2, 6), ("thorough", 4, 8)):
            for partial, expected in ((True, partial_beam), (False, final_beam)):
                with self.subTest(quality=quality, partial=partial):
                    result = pipeline.process(np.full(16_000, 0.002), partial=partial, quality=quality)
                    self.assertEqual((result["french"], result["quality"]), (f"beam-{expected}", quality))
                    self.assertEqual((result["dutch"], result["partial"]), ("Goedemorgen.", partial))
        self.assertEqual(pipeline.process(np.full(16_000, 0.002))["french"], "beam-4")

    def test_audio_validation_and_gain(self):
        prepared, silent, gain = engine.prepare_audio(np.full(16_000, 0.002, dtype=np.float32))
        self.assertFalse(silent)
        self.assertGreater(gain, 1)
        self.assertAlmostEqual(float(np.max(prepared)), 0.04, places=3)
        with self.assertRaises(ValueError):
            engine.prepare_audio(np.zeros((2, 10), dtype=np.float32))


if __name__ == "__main__":
    unittest.main()
