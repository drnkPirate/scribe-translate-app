#!/usr/bin/env python3
"""Report bundled runtime size and reject downloaded model weights."""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path


root = Path(sys.argv[1] if len(sys.argv) > 1 else "dist/sidecar")
if not root.is_dir():
    raise SystemExit(f"bundle not found: {root}")

sizes: dict[str, int] = defaultdict(int)
total = 0
model_files = []
for path in root.rglob("*"):
    if not path.is_file() or path.is_symlink():
        continue
    size = path.stat().st_size
    total += size
    relative = path.relative_to(root)
    sizes[relative.parts[1] if relative.parts[0] == "_internal" and len(relative.parts) > 1 else relative.parts[0]] += size
    if size > 10 * 1024 * 1024 and path.suffix.lower() in {".bin", ".ckpt", ".onnx", ".pt", ".pth", ".safetensors"}:
        model_files.append(str(relative))

if model_files:
    raise SystemExit("downloaded model weights entered the bundle: " + ", ".join(model_files))
print(json.dumps({"bundle_bytes": total, "largest": dict(sorted(sizes.items(), key=lambda item: item[1], reverse=True)[:12])}, indent=2))
