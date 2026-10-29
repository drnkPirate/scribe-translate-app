#!/usr/bin/env python3
"""Loopback-only HTTP service for Scribe Translate."""

from __future__ import annotations

import argparse
import io
import json
import multiprocessing
import os
import signal
import socket
import threading
import traceback
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import numpy as np
from scipy.signal import resample_poly


MAX_BODY_BYTES = 3 * 1024 * 1024
MAX_AUDIO_SECONDS = 30
WEB_ROOT = Path(__file__).with_name("web")
PROCESSING = json.loads((WEB_ROOT / "processing.json").read_text())
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/en.json": ("en.json", "application/json; charset=utf-8"),
    "/processing.json": ("processing.json", "application/json; charset=utf-8"),
}


class CaptionState:
    def __init__(self, pipeline=None, *, phase="models_missing"):
        self.pipeline = pipeline
        self.phase = phase
        self.error = None
        self.admission = threading.Semaphore(1)
        self.lock = threading.Lock()

    @property
    def ready(self):
        return self.phase == "ready" and self.pipeline is not None


def _local_host(value: str) -> bool:
    try:
        hostname = urlsplit(f"//{value}").hostname
    except ValueError:
        return False
    return hostname in {"127.0.0.1", "localhost", "::1"}


def _request_allowed(host: str | None, origin: str | None) -> bool:
    if not host or not _local_host(host):
        return False
    if origin is None:
        return True
    try:
        parsed = urlsplit(origin)
    except ValueError:
        return False
    return parsed.scheme == "http" and parsed.netloc.lower() == host.lower()


def _decode_wav(body: bytes) -> np.ndarray:
    try:
        with wave.open(io.BytesIO(body), "rb") as source:
            channels = source.getnchannels()
            sample_width = source.getsampwidth()
            sample_rate = source.getframerate()
            frame_count = source.getnframes()
            compression = source.getcomptype()
            frames = source.readframes(frame_count)
    except (EOFError, wave.Error) as error:
        raise ValueError("invalid_audio") from error
    if (
        channels != 1
        or sample_width != 2
        or compression != "NONE"
        or not 8_000 <= sample_rate <= 192_000
        or frame_count < 1
        or frame_count / sample_rate > MAX_AUDIO_SECONDS
        or len(frames) != frame_count * sample_width
    ):
        raise ValueError("invalid_audio")
    audio = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    if sample_rate != 16_000:
        audio = resample_poly(audio, 16_000, sample_rate).astype(np.float32, copy=False)
        np.clip(audio, -1.0, 1.0, out=audio)
    return np.ascontiguousarray(audio, dtype=np.float32)


def create_server(address: tuple[str, int], state: CaptionState) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        server_version = "ScribeTranslate/1"

        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def log_message(self, _format, *args):
            pass

        def _send_json(self, status: int, value: dict):
            body = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _allowed(self) -> bool:
            if _request_allowed(self.headers.get("Host"), self.headers.get("Origin")):
                return True
            self._send_json(403, {"error": "forbidden"})
            return False

        def do_GET(self):
            if not self._allowed():
                return
            path = urlsplit(self.path).path
            if path == "/api/status":
                self._send_json(200, {
                    "app": "scribe-translate",
                    "ready": state.ready,
                    "modelsReady": state.phase in {"warming", "ready"},
                    "phase": state.phase,
                    "error": state.error,
                })
                return
            static = STATIC_FILES.get(path)
            if static is None:
                self._send_json(404, {"error": "not_found"})
                return
            body = (WEB_ROOT / static[0]).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", static[1])
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; connect-src 'self'; "
                "media-src 'self' blob:; style-src 'self' 'unsafe-inline'",
            )
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if not self._allowed():
                return
            path = urlsplit(self.path).path
            if path == "/api/models/download":
                started = start_model_setup(state, download=True)
                self._send_json(202 if started else 200, {"started": started, "phase": state.phase})
                return
            if path != "/api/caption":
                self._send_json(404, {"error": "not_found"})
                return
            if self.headers.get_content_type() not in {"audio/wav", "audio/x-wav"}:
                self._send_json(415, {"error": "unsupported_media_type"})
                return
            partial_header = self.headers.get("X-Caption-Partial")
            if partial_header not in {None, "0", "1"}:
                self._send_json(400, {"error": "invalid_partial"})
                return
            quality = self.headers.get("X-Caption-Quality", PROCESSING["default"])
            if quality not in PROCESSING["profiles"]:
                self._send_json(400, {"error": "invalid_quality"})
                return
            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                length = 0
            if length < 1 or length > MAX_BODY_BYTES:
                self._send_json(413, {"error": "invalid_size"})
                return
            if not state.ready:
                self._send_json(503, {"error": state.error or state.phase})
                return
            if not state.admission.acquire(blocking=False):
                self._send_json(429, {"error": "busy"})
                return
            try:
                body = self.rfile.read(length)
                if len(body) != length:
                    raise ValueError("invalid_audio")
                audio = _decode_wav(body)
                result = state.pipeline.process(audio, partial=partial_header == "1", quality=quality)
                self._send_json(200, result)
            except (TimeoutError, socket.timeout):
                self.close_connection = True
                self._send_json(408, {"error": "request_timeout"})
            except ValueError as error:
                self._send_json(400, {"error": str(error)})
            except Exception:
                traceback.print_exc()
                self._send_json(500, {"error": "processing_failed"})
            finally:
                state.admission.release()

    server = ThreadingHTTPServer(address, Handler)
    server.daemon_threads = True
    return server


def _setup_models(state: CaptionState, download: bool):
    try:
        from engine import Pipeline, download_models

        if download:
            download_models()
        state.phase = "warming"
        pipeline = Pipeline(device=os.environ.get("SCRIBE_TRANSLATE_DEVICE", "auto"))
        pipeline.warmup()
        state.pipeline = pipeline
        state.error = None
        state.phase = "ready"
    except Exception:
        state.error = "startup_failed"
        state.phase = "failed"
        traceback.print_exc()


def start_model_setup(state: CaptionState, *, download: bool) -> bool:
    with state.lock:
        if state.phase in {"downloading", "warming", "ready"}:
            return False
        state.error = None
        state.phase = "downloading" if download else "warming"
        threading.Thread(target=_setup_models, args=(state, download), daemon=True).start()
        return True


def main() -> None:
    multiprocessing.freeze_support()
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=43187)
    args = parser.parse_args()

    from engine import models_ready

    state = CaptionState()
    if models_ready():
        start_model_setup(state, download=False)
    server = create_server(("127.0.0.1", args.port), state)
    print(f"http://127.0.0.1:{args.port}", flush=True)

    def stop(_signum, _frame):
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
