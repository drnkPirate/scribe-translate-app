#!/usr/bin/env python3
"""Install the disk image in a temporary folder and check the packaged app."""

import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen


def main():
    image = Path(sys.argv[1]).resolve(strict=True)
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", 43187)) == 0:
            raise RuntimeError("Close the running app before testing the installer")
    with tempfile.TemporaryDirectory(prefix="scribe-translate-smoke-") as temporary:
        root = Path(temporary)
        mount = root / "disk"
        mount.mkdir()
        subprocess.run([
            "hdiutil", "attach", "-nobrowse", "-readonly", "-mountpoint", str(mount), str(image),
        ], check=True)
        app = root / "Scribe Translate.app"
        try:
            subprocess.run(["ditto", str(mount / app.name), str(app)], check=True)
        finally:
            subprocess.run(["hdiutil", "detach", str(mount)], check=True)
        subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)], check=True)
        subprocess.run([
            sys.executable, str(Path(__file__).with_name("check_bundle.py")),
            str(app / "Contents/Resources/sidecar"),
        ], check=True)
        process = subprocess.Popen([
            str(app / "Contents/MacOS/Scribe Translate"), f"--user-data-dir={root / 'profile'}",
        ], start_new_session=True, env={**os.environ, "HF_HOME": str(root / "models")})
        try:
            for _ in range(90):
                if process.poll() is not None:
                    raise RuntimeError(f"The installed app exited with {process.returncode}")
                try:
                    with urlopen("http://127.0.0.1:43187/api/status", timeout=2) as response:
                        status = json.load(response)
                except URLError:
                    time.sleep(1)
                    continue
                assert status["app"] == "scribe-translate", status
                assert status["phase"] == "models_missing", status
                with urlopen("http://127.0.0.1:43187/", timeout=2) as response:
                    assert b'id="download"' in response.read()
                print("Installed macOS app smoke check passed: models_missing")
                return
            raise RuntimeError("The installed app did not start its local service")
        finally:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()


if __name__ == "__main__":
    main()
