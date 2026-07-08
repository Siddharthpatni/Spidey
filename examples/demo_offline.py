#!/usr/bin/env python3
"""Run the offline demo directly:  python examples/demo_offline.py

No Ollama, GPU, or network required — it uses Spidey's scripted stub backend.
"""

import pathlib
import sys

# Make the repo root importable when run as a plain script.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from spidey.demo import run_demo  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(run_demo())
