#!/usr/bin/env python3
"""Build the model runtime without embedding downloaded model files."""

from __future__ import annotations

import os
import filecmp
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "build" / "pyinstaller"
OUTPUT = ROOT / "dist" / "sidecar"


def main():
    shutil.rmtree(WORK, ignore_errors=True)
    shutil.rmtree(OUTPUT, ignore_errors=True)
    separator = os.pathsep
    silero = (
        Path(importlib.util.find_spec("silero_vad").submodule_search_locations[0])
        / "data"
        / "silero_vad.jit"
    )
    transformer_models = Path(
        importlib.util.find_spec("transformers.models").submodule_search_locations[0]
    )
    required_transformer_models = {"auto", "encoder_decoder", "marian"}
    assert all((transformer_models / name).is_dir() for name in required_transformer_models)
    command = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir",
        "--name", "scribe-translate-server",
        "--distpath", str(WORK / "dist"), "--workpath", str(WORK / "work"),
        "--specpath", str(WORK), "--paths", str(ROOT / "sidecar"),
        "--add-data", f"{ROOT / 'sidecar' / 'web'}{separator}web",
        "--add-data", f"{silero}{separator}silero_vad/data",
        "--copy-metadata", "moondream",
        "--hidden-import", "kestrel.models.parakeet_tdt.registration",
        "--collect-all", "kestrel_kernels", "--collect-all", "sentencepiece",
        "--exclude-module", "torch.onnx",
        "--exclude-module", "torch.utils.tensorboard",
        str(ROOT / "sidecar" / "server.py"),
    ]
    for package in ("kestrel_mps_torch_ext", "kestrel_cuda"):
        if importlib.util.find_spec(package):
            command[-1:-1] = ["--collect-all", package]
    for model in transformer_models.iterdir():
        if (
            model.is_dir()
            and model.name not in required_transformer_models
            and (model / "__init__.py").is_file()
        ):
            command[-1:-1] = ["--exclude-module", f"transformers.models.{model.name}"]
    subprocess.run(command, cwd=ROOT, check=True)
    shutil.copytree(WORK / "dist" / "scribe-translate-server", OUTPUT)
    shutil.copy2(ROOT / "sidecar" / "web" / "en.json", OUTPUT / "en.json")
    if os.name != "nt":
        library_dir = OUTPUT / "_internal" / "torch" / "lib"
        for library in library_dir.glob("*"):
            duplicate = OUTPUT / "_internal" / library.name
            if duplicate.is_file() and filecmp.cmp(library, duplicate, shallow=False):
                duplicate.unlink()
                duplicate.symlink_to(Path("torch") / "lib" / library.name)
    assert not any(path.name == "model.safetensors" for path in OUTPUT.rglob("*")), "model weights entered the app bundle"
    print(OUTPUT)


if __name__ == "__main__":
    main()
