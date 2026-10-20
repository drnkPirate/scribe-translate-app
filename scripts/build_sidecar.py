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
    command = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir",
        "--name", "scribe-translate-server",
        "--distpath", str(WORK / "dist"), "--workpath", str(WORK / "work"),
        "--specpath", str(WORK), "--paths", str(ROOT / "sidecar"),
        "--add-data", f"{ROOT / 'sidecar' / 'web'}{separator}web",
        "--collect-all", "moondream", "--collect-all", "kestrel",
        "--collect-all", "kestrel_native", "--collect-all", "kestrel_kernels",
        "--collect-all", "ctranslate2",
        "--collect-all", "silero_vad", "--collect-all", "sentencepiece",
        str(ROOT / "sidecar" / "server.py"),
    ]
    for package in ("kestrel_mps_torch_ext", "kestrel_cuda"):
        if importlib.util.find_spec(package):
            command[-1:-1] = ["--collect-all", package]
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
