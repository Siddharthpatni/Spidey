"""The Web — Spidey's dispatch layer.

In auto mode, every task is classified and sent to the Spider best suited to
solve it *efficiently*: coding and data work swings to Miles Morales
(qwen2.5-coder — specialist, and the fastest quality model on 16 GB machines),
while deep reasoning, file organization, research, security judgment and
personal conversations stay with Peter Parker (Gemma 4 — the leader).

Routing is deliberately deterministic keyword classification, not an extra LLM
call: it costs zero latency, can't hallucinate, and only ever dispatches to
models that are actually installed (checked against Ollama's tag list, with a
sensible fallback chain).
"""

from __future__ import annotations

from typing import Set, Tuple

from .agent import SPECIALIST_HATS

# Which body of the Spider-Verse runs which brain (kept in sync with the web
# picker in web/src/Settings.jsx).
SPIDER_MODELS = {
    "peter": "gemma4:12b",
    "miles": "qwen2.5-coder:7b",
    "gwen": "gemma4:e4b",
    "noir": "llama3.1:8b",
    "2099": "gemma4:26b",
    "ham": "qwen2.5-coder:1.5b",
}

# Specialist hat -> the Spider that wears it best. Anything unlisted (or no
# hat at all) goes to the leader.
_HAT_TO_SPIDER = {
    "CODING": "miles",
    "DATA ANALYST": "miles",
}

# If the ideal Spider's model isn't downloaded, walk down this chain.
_FALLBACK = ["peter", "miles", "noir", "gwen", "ham"]


def installed_models(base_url: str = "http://localhost:11434") -> Set[str]:
    import requests

    try:
        resp = requests.get(f"{base_url.rstrip('/')}/api/tags", timeout=3)
        return {m["name"] for m in resp.json().get("models", [])}
    except Exception:
        return set()


def route_task(task: str, base_url: str = "http://localhost:11434") -> Tuple[str, str, str]:
    """Classify ``task`` -> (spider, model, human-readable reason)."""
    lowered = task.lower()
    hats = [name for name, (keys, _) in SPECIALIST_HATS.items()
            if any(k in lowered for k in keys)]
    ideal = next((_HAT_TO_SPIDER[h] for h in hats if h in _HAT_TO_SPIDER), "peter")
    kind = hats[0] if hats else "GENERAL"

    tags = installed_models(base_url)
    chain = [ideal] + [s for s in _FALLBACK if s != ideal]
    for spider in chain:
        if not tags or SPIDER_MODELS[spider] in tags:
            model = SPIDER_MODELS[spider]
            names = {"peter": "Peter Parker", "miles": "Miles Morales", "gwen": "Spider-Gwen",
                     "noir": "Spider-Man Noir", "2099": "Miguel O'Hara", "ham": "Spider-Ham"}
            reason = (f"{kind} job → {names[spider]} takes it ({model})"
                      + ("" if spider == ideal else " — first pick isn't downloaded"))
            return spider, model, reason
    return "peter", SPIDER_MODELS["peter"], "GENERAL job → Peter Parker takes it"
