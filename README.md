# Scribe Translate

A standalone desktop app for live Dutch transcription with French captions. Audio, transcription, and translation stay on the computer.

## Download for Windows

1. Open the [latest release](https://github.com/drnkPirate/scribe-translate-app/releases/latest).
2. Download `Scribe-Translate-<version>-Setup.exe`.
3. Run the installer and open **Scribe Translate**.
4. On first use, select **Download models**. The pinned models require about 1.5 GB.
5. Select a microphone and press **Start**.

Windows may show an unknown-publisher warning because the installer is not yet code-signed. Only use installers downloaded from this repository.

## Use

French captions appear in large text with the recognized Dutch text underneath. **Clear captions** removes the current captions without changing the selected microphone or downloaded models.

The models are stored in the user cache and are not included in Git, the installer, or the app bundle. After the first download, transcription and translation work offline.

## Supported systems

- Windows 11 x64. An NVIDIA GPU is the recommended and tested Photon configuration. The app selects CUDA when available and otherwise falls back to CPU; near-real-time performance without NVIDIA is not guaranteed.
- macOS on Apple silicon. The local build is tested on a MacBook Pro M2 with 32 GB RAM.

The desktop layer permits one app instance at a time. Its service listens only on `127.0.0.1` and accepts requests only from the same local origin.

## Local development

Requirements: Node.js 22+, Python 3.12, and `uv`.

```bash
uv venv --python 3.12
uv pip install --python .venv/bin/python -r requirements.txt
npm install
python3 scripts/create_icon.py
npm test
npm run dev
```

On Windows, use `.venv\\Scripts\\python.exe`.

## Build

macOS Apple Silicon:

```bash
npm run build:mac
```

Windows x64:

```powershell
npm run build:win
```

`build_sidecar.py` packages only the Python runtime. The build fails if `model.safetensors` is accidentally included. GitHub Actions builds and smoke-tests the Windows installer on Windows.

## Models

- ASR: [moondream/parakeet-ultra](https://huggingface.co/moondream/parakeet-ultra), pinned to commit `73175eb7aeb0d82f1e2a6b53b3aabc10a90bcd0b`.
- Translation: [Helsinki-NLP/opus-mt-nl-fr](https://huggingface.co/Helsinki-NLP/opus-mt-nl-fr), pinned to commit `a74137b1148a173261834247de2a17c855e43c20`.
- Local ASR runtime: [Moondream Photon](https://docs.moondream.ai/running-locally/).

The app verifies critical Ultra model files against pinned SHA-256 hashes before loading them.
