"""Pinned local Dutch speech recognition and Dutch-to-French translation."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
import unicodedata
from pathlib import Path

import numpy as np


PROCESSING = json.loads((Path(__file__).with_name("web") / "processing.json").read_text())
ASR_MODEL = "moondream/parakeet-ultra"
ASR_REVISION = "73175eb7aeb0d82f1e2a6b53b3aabc10a90bcd0b"
TRANSLATION_MODEL = "Helsinki-NLP/opus-mt-nl-fr"
TRANSLATION_REVISION = "a74137b1148a173261834247de2a17c855e43c20"
ASR_HASHES = {
    "config.json": "e747b85e1bdfd300c8b8ac63bac8dd5221f8fe9bc275b48d06c735fcd6971b6e",
    "model.safetensors": "c9608f36d0ab956c14bfcc525479b0746b3b42a56f6949ec85c14eb7466717dc",
    "tokenizer.json": "bd321b096832a3f270bd3b2a88823957920f1a5c5ada71114a26ea729d0cbe91",
}


def _cache_root() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "scribe-translate"
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "Scribe Translate" / "Cache"
    return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "scribe-translate"


def _verify_asr(path: str | Path) -> None:
    root = Path(path)
    for name, expected in ASR_HASHES.items():
        file = root / name
        if not file.is_file():
            raise ValueError(f"missing model artifact: {name}")
        with file.open("rb") as source:
            actual = hashlib.file_digest(source, "sha256").hexdigest()
        if actual != expected:
            raise ValueError(f"model artifact hash changed: {name}")


def _translation_output() -> Path:
    import ctranslate2

    return _cache_root() / f"opus-ct2-{TRANSLATION_REVISION}-int8-{ctranslate2.__version__}"


def model_paths(*, local_only: bool) -> tuple[str, str]:
    from huggingface_hub import snapshot_download

    asr = snapshot_download(ASR_MODEL, revision=ASR_REVISION, local_files_only=local_only)
    translation = snapshot_download(
        TRANSLATION_MODEL,
        revision=TRANSLATION_REVISION,
        local_files_only=local_only,
        allow_patterns=["*.json", "*.spm", "*.bin", "*.safetensors", "*.txt"],
    )
    _verify_asr(asr)
    return asr, translation


def models_ready() -> bool:
    try:
        model_paths(local_only=True)
        return (_translation_output() / "model.bin").is_file()
    except Exception:
        return False


def download_models() -> None:
    from ctranslate2.converters import TransformersConverter

    _, translation = model_paths(local_only=False)
    output = _translation_output()
    if not (output / "model.bin").is_file():
        output.parent.mkdir(parents=True, exist_ok=True)
        TransformersConverter(translation).convert(str(output), quantization="int8", force=True)


def prepare_audio(audio, vad=None, detect_speech=None):
    audio = np.asarray(audio, dtype=np.float32)
    if audio.ndim != 1 or not 0 < len(audio) <= 30 * 16_000:
        raise ValueError("expected 0-30 seconds of mono 16 kHz audio")
    if not np.isfinite(audio).all() or np.max(np.abs(audio)) > 1.01:
        raise ValueError("invalid audio samples")
    rms = float(np.sqrt(np.mean(audio**2)))
    silent = rms < 0.0001
    gain = min(20.0, 0.05 / rms, 0.95 / float(np.max(np.abs(audio)))) if not silent else 1.0
    prepared = audio * max(1.0, gain)
    if not silent and vad is not None:
        import torch

        speech = detect_speech(
            torch.from_numpy(prepared), vad, sampling_rate=16_000,
            min_speech_duration_ms=100, speech_pad_ms=200,
        )
        if speech:
            prepared = prepared[speech[0]["start"] : speech[-1]["end"]]
        else:
            silent = True
    return prepared, silent, max(1.0, gain)


class Pipeline:
    def __init__(self, *, device="auto"):
        import ctranslate2
        import moondream
        import torch
        from silero_vad import get_speech_timestamps, load_silero_vad
        from transformers import MarianTokenizer

        if device not in {"auto", "cpu", "mps", "cuda"}:
            raise ValueError("invalid device")
        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else (
                "mps" if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available() else "cpu"
            )
        asr_path, translation_path = model_paths(local_only=True)
        output = _translation_output()
        if not (output / "model.bin").is_file():
            raise RuntimeError("translation model is not prepared")

        torch.set_num_threads(min(4, os.cpu_count() or 1))
        self.torch = torch
        self.device = device
        self.photon = moondream.photon(ASR_MODEL, model_path=asr_path, device=device)
        self.tokenizer = MarianTokenizer.from_pretrained(translation_path, local_files_only=True)
        self.translator = ctranslate2.Translator(
            str(output), device="cpu", compute_type="int8", inter_threads=4, intra_threads=1,
        )
        self.vad = load_silero_vad()
        self.detect_speech = get_speech_timestamps

    def warmup(self):
        self.detect_speech(self.torch.zeros(16_000), self.vad, sampling_rate=16_000)
        self._recognize(np.zeros(8_000, dtype=np.float32))
        self.translate("Goedemorgen.", partial=True)

    def _recognize(self, audio):
        result = self.photon.transcribe(
            audio=np.asarray(audio, dtype=np.float32), sample_rate=16_000, timestamps="none",
        )
        if not isinstance(result, dict) or not isinstance(result.get("text"), str):
            raise RuntimeError("invalid transcription response")
        return result["text"].strip()

    def translate(self, text, *, partial=False, quality=PROCESSING["default"]):
        started = time.perf_counter()
        profile = PROCESSING["profiles"][quality]
        text = unicodedata.normalize("NFKC", text).replace("\u2019", "'").replace("\u2018", "'")
        if not text.strip():
            return "", 0.0, {"input_tokens": 0, "output_tokens": 0}
        sentences = re.split(r"(?<=[.!?])\s+(?=[A-ZÀ-ÖØ-Þ])", text)
        sources = [
            self.tokenizer.convert_ids_to_tokens(
                self.tokenizer(sentence, return_tensors="pt", truncation=False).input_ids[0].tolist()
            )
            for sentence in sentences
        ]
        if any(len(source) > 480 for source in sources):
            raise ValueError("translation input exceeds 480 tokens")
        results = self.translator.translate_batch(
            sources, beam_size=profile["partial_beam_size" if partial else "final_beam_size"], max_batch_size=1,
            max_input_length=0, max_decoding_length=128 if partial else 256,
            return_end_token=True,
        )
        tokens = [result.hypotheses[0] for result in results]
        usage = {
            "input_tokens": sum(map(len, sources)),
            "output_tokens": sum(map(len, tokens)),
            "sentence_units": len(sentences),
        }
        if any(not unit or unit[-1] != self.tokenizer.eos_token for unit in tokens):
            if partial:
                return "", time.perf_counter() - started, {**usage, "truncated": True}
            raise RuntimeError("translation truncated")
        translated = [
            self.tokenizer.decode(self.tokenizer.convert_tokens_to_ids(unit), skip_special_tokens=True).strip()
            for unit in tokens
        ]
        if not all(translated):
            raise RuntimeError("empty translation")
        return " ".join(translated), time.perf_counter() - started, usage

    def process(self, audio, *, partial=False, quality=PROCESSING["default"]):
        audio = np.asarray(audio, dtype=np.float32)
        started = time.perf_counter()
        prepared, silent, gain = prepare_audio(audio, self.vad, self.detect_speech)
        dutch = "" if silent else self._recognize(prepared)
        if not any(character.isalnum() for character in dutch):
            dutch = ""
        asr_seconds = time.perf_counter() - started
        french, translation_seconds, usage = self.translate(dutch, partial=partial, quality=quality)
        return {
            "dutch": dutch,
            "french": french,
            "duration_s": len(audio) / 16_000,
            "asr_s": asr_seconds,
            "translation_s": translation_seconds,
            "latency_s": time.perf_counter() - started,
            "model": {"asr": ASR_MODEL, "translation": TRANSLATION_MODEL, "device": self.device},
            "usage": usage,
            "status": "silence" if silent else "ok",
            "gain": gain,
            "partial": partial,
            "quality": quality,
            "translation_pending": bool(usage.get("truncated")),
        }
