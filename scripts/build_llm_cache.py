"""Pre-build the grounded answer cache with the Hugging Face model, for every demo state.

Covers the reset state and each single scenario: all screen narratives (EN, plus ES/PT briefing) and the scripted
Copilot questions. After this, Cache mode answers the whole presenter script with no model loaded.

Usage: python scripts/build_llm_cache.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.copilot import SUGGESTIONS, answer  # noqa: E402
from backend.hub import hub  # noqa: E402
from backend.llm import GATEWAY  # noqa: E402
from backend.narratives import narrative  # noqa: E402
from backend.state import SCENARIOS, STATE  # noqa: E402

STATES = [()] + [(s,) for s in SCENARIOS]


def main():
    GATEWAY.mode = "auto"
    GATEWAY.load_async()
    for _ in range(240):
        if GATEWAY.status in ("ready", "missing", "error"):
            break
        time.sleep(0.5)
    if GATEWAY.status != "ready":
        print("Model not available:", GATEWAY.status, GATEWAY.error)
        return 1
    h = hub()
    t0 = time.time()
    for st in STATES:
        STATE.reset()
        for s in st:
            STATE.inject(s)
        h.signals()
        jobs = [("briefing", "en"), ("briefing", "es"), ("briefing", "pt"), ("pricing", "en"), ("forecast", "en"), ("inventory", "en"), ("routes", "en")]
        for task, lang in jobs:
            narrative(task, lang)
        for q in SUGGESTIONS:
            answer(q)
        print(f"  state {st or '(reset)'}: done · cache {len(GATEWAY.cache)} entries · {time.time() - t0:.0f}s")
    STATE.reset()
    print("Stats:", GATEWAY.stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())
