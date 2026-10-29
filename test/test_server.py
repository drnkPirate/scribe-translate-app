import http.client
import importlib.util
import io
import json
import threading
import unittest
import wave
from pathlib import Path

import numpy as np


MODULE_PATH = Path(__file__).parents[1] / "sidecar" / "server.py"
SPEC = importlib.util.spec_from_file_location("scribe_translate_server", MODULE_PATH)
server_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(server_module)


def wav(samples, rate=8_000):
    output = io.BytesIO()
    with wave.open(output, "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(rate)
        target.writeframes(np.asarray(samples, dtype="<i2").tobytes())
    return output.getvalue()


class FakePipeline:
    def __init__(self):
        self.audio = []

    def process(self, audio, partial=False, quality="fast"):
        self.audio.append(audio)
        return {"dutch": "goed", "french": "bien", "duration_s": 0.1, "partial": partial, "quality": quality}


class ServerTest(unittest.TestCase):
    def setUp(self):
        self.pipeline = FakePipeline()
        self.state = server_module.CaptionState(self.pipeline, phase="ready")
        self.server = server_module.create_server(("127.0.0.1", 0), self.state)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        data = response.read()
        connection.close()
        return response.status, json.loads(data), dict(response.headers)

    def test_caption_resamples_and_keeps_partial_flag(self):
        body = wav([0, 16_384, -16_384, 0] * 200)
        status, result, _ = self.request(
            "POST", "/api/caption", body,
            {"Content-Type": "audio/wav", "X-Caption-Partial": "1"},
        )
        self.assertEqual((status, result["dutch"], result["french"], result["partial"]), (200, "goed", "bien", True))
        self.assertEqual(self.pipeline.audio[0].dtype, np.float32)
        self.assertEqual(self.pipeline.audio[0].shape, (1600,))
        self.assertEqual(result["quality"], "fast")

    def test_processing_modes_are_available_and_validated_before_inference(self):
        status, settings, _ = self.request("GET", "/processing.json")
        self.assertEqual(status, 200)
        self.assertEqual(list(settings["profiles"]), ["fast", "balanced", "thorough"])
        for quality in ("fast", "balanced", "thorough"):
            with self.subTest(quality=quality):
                status, result, _ = self.request(
                    "POST", "/api/caption", wav([100, -100] * 200),
                    {"Content-Type": "audio/wav", "X-Caption-Quality": quality},
                )
                self.assertEqual((status, result["quality"]), (200, quality))
        for quality in ("unknown", "", "__proto__"):
            status, result, _ = self.request(
                "POST", "/api/caption", wav([100, -100] * 200),
                {"Content-Type": "audio/wav", "X-Caption-Quality": quality},
            )
            self.assertEqual((status, result), (400, {"error": "invalid_quality"}))
        self.assertEqual(len(self.pipeline.audio), 3)

    def test_status_identifies_the_local_service(self):
        status, result, headers = self.request("GET", "/api/status")
        self.assertEqual(status, 200)
        self.assertEqual((result["app"], result["phase"], result["ready"]), ("scribe-translate", "ready", True))
        self.assertEqual(headers["Cache-Control"], "no-store")

    def test_model_download_endpoint_starts_setup(self):
        self.state.pipeline = None
        self.state.phase = "models_missing"
        original = server_module.start_model_setup
        calls = []

        def start(state, *, download):
            calls.append(download)
            state.phase = "downloading"
            return True

        server_module.start_model_setup = start
        try:
            status, result, _ = self.request("POST", "/api/models/download")
        finally:
            server_module.start_model_setup = original
        self.assertEqual((status, result, calls), (202, {"started": True, "phase": "downloading"}, [True]))

    def test_cross_origin_and_invalid_audio_are_rejected(self):
        status, result, _ = self.request(
            "POST", "/api/caption", wav([1, 2, 3]),
            {"Content-Type": "audio/wav", "Origin": "http://example.test"},
        )
        self.assertEqual((status, result), (403, {"error": "forbidden"}))
        status, result, _ = self.request("POST", "/api/caption", b"no", {"Content-Type": "audio/wav"})
        self.assertEqual((status, result), (400, {"error": "invalid_audio"}))


if __name__ == "__main__":
    unittest.main()
