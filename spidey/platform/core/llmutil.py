"""Optional LLM bridge for platform modules — with built-in observability.

``ask()`` sends one prompt through Spidey's normal backend stack (Ollama by
default, or whatever $SPIDEY_LLM_PROVIDER / $SPIDEY_LLM_MODEL says) and returns
the text — or ``None`` if no model is reachable. Callers must treat ``None``
as "fall back to the deterministic path", which is what keeps the whole
platform functional on a machine with nothing installed but Python.

Every call — from modules or from the /api/llm gateway — is recorded to the
``llm_calls`` table with estimated tokens, estimated cost (the Sentinel cost
tables, ported) and latency, plus an analytics event and Prometheus counters.
Local models cost $0; the estimates make BYOK usage visible.
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, Optional

_DEFAULT_MODEL = "gemma4:12b"

# USD per 1M tokens: (prompt, completion). Ported from Sentinel's cost tables,
# trimmed to model families Spidey's backends actually reach. Unknown hosted
# models get DEFAULT_COST; anything served by Ollama/custom is $0 (your metal).
COST_TABLE: Dict[str, tuple] = {
    "gpt-4o": (2.50, 10.00), "gpt-4o-mini": (0.15, 0.60),
    "gpt-4.1": (2.00, 8.00), "gpt-4.1-mini": (0.40, 1.60), "gpt-4.1-nano": (0.10, 0.40),
    "o3": (10.00, 40.00), "o3-mini": (1.10, 4.40), "o4-mini": (1.10, 4.40),
    "claude-opus-4-8": (15.00, 75.00), "claude-sonnet-5": (3.00, 15.00),
    "claude-sonnet-4-20250514": (3.00, 15.00), "claude-opus-4-20250514": (15.00, 75.00),
    "claude-3-5-haiku-20241022": (0.80, 4.00), "claude-haiku-4-5-20251001": (1.00, 5.00),
    "gemini-2.5-pro": (1.25, 10.00), "gemini-2.5-flash": (0.30, 2.50),
}
DEFAULT_COST = (1.00, 3.00)
FREE_PROVIDERS = {"ollama", "custom", "stub"}


def estimate_tokens(text: str) -> int:
    return max(1, len(text or "") // 4)


def estimate_cost(provider: str, model: str, prompt_tokens: int,
                  completion_tokens: int) -> float:
    if provider in FREE_PROVIDERS:
        return 0.0
    p, c = COST_TABLE.get(model, DEFAULT_COST)
    return round((prompt_tokens * p + completion_tokens * c) / 1_000_000, 6)


def record_call(provider: str, model: str, prompt: str, response: str,
                latency_ms: float, ok: bool, source: str = "internal") -> float:
    """Persist one model call (Sentinel-style tracing). Returns the cost estimate.
    Observability must never break the call it observes — failures are swallowed."""
    pt, ct = estimate_tokens(prompt), estimate_tokens(response)
    cost = estimate_cost(provider, model, pt, ct)
    try:
        from . import db, metrics
        status = "ok" if ok else "error"
        metrics.inc("spidey_llm_calls_total", {"provider": provider, "status": status})
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO llm_calls(provider, model, source, prompt, response,"
                " prompt_tokens_est, completion_tokens_est, cost_usd, latency_ms, status, ts)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (provider, model, source, (prompt or "")[:2000], (response or "")[:2000],
                 pt, ct, cost, round(latency_ms, 1), status, db.now()))
            conn.execute("INSERT INTO events(name, value, props, ts) VALUES(?,?,?,?)",
                         ("llm.latency_ms", round(latency_ms, 1),
                          db.json_dumps({"provider": provider, "model": model,
                                         "status": status}), db.now()))
    except Exception:
        pass
    return cost


def chat(prompt: str, system: Optional[str] = None, provider: Optional[str] = None,
         model: Optional[str] = None, api_key: Optional[str] = None,
         source: str = "internal") -> Dict[str, Any]:
    """One traced chat call. Raises on failure (the gateway wants the error);
    use :func:`ask` for the swallow-and-fallback behavior modules rely on."""
    from ...llm import build_backend

    provider = provider or os.environ.get("SPIDEY_LLM_PROVIDER", "ollama")
    model = model or os.environ.get("SPIDEY_LLM_MODEL", _DEFAULT_MODEL)
    t0 = time.time()
    try:
        backend = build_backend(provider, model=model, api_key=api_key)
        messages = ([{"role": "system", "content": system}] if system else [])
        messages.append({"role": "user", "content": prompt})
        reply = backend.chat(messages, tools=[])
        content = (reply.content or "").strip()
    except Exception:
        record_call(provider, model, prompt, "", (time.time() - t0) * 1000,
                    ok=False, source=source)
        raise
    latency_ms = (time.time() - t0) * 1000
    cost = record_call(provider, model, prompt, content, latency_ms,
                       ok=bool(content), source=source)
    return {"response": content, "provider": provider, "model": model,
            "latency_ms": round(latency_ms, 1), "cost_usd": cost,
            "prompt_tokens_est": estimate_tokens(prompt),
            "completion_tokens_est": estimate_tokens(content)}


def ask(prompt: str, system: Optional[str] = None, timeout_hint: int = 120) -> Optional[str]:
    try:
        result = chat(prompt, system=system, source="internal")
        return result["response"] or None
    except Exception:
        return None


def available() -> bool:
    """Cheap reachability probe for the default provider (Ollama)."""
    try:
        import requests
        base = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        return requests.get(f"{base}/api/tags", timeout=2).ok
    except Exception:
        return False
