"""Download the configured Hugging Face model once into the local HF cache (skips if already present).

Usage: python scripts/download_model.py [--model mlx-community/Qwen3-8B-4bit]
"""
from __future__ import annotations

import argparse
import platform
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import settings  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=settings()["llm"]["model"])
    args = ap.parse_args()
    if not (sys.platform == "darwin" and platform.machine() == "arm64"):
        print("  Live generation uses MLX on Apple Silicon; this machine will run in Cache mode.")
        return 0
    from huggingface_hub import snapshot_download
    try:
        path = snapshot_download(args.model, local_files_only=True)
        print(f"→ Model ready: {args.model}")
        return 0
    except Exception:
        pass
    print(f"→ Downloading {args.model} from Hugging Face (one time, ~2–5 GB)")
    path = snapshot_download(args.model)
    print(f"  saved to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
