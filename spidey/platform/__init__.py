"""Spidey Platform — the capability layer on top of the agent.

Eleven production-style modules (web automation, file pipeline, analytics, fleet,
resume matching, research, code assistant, email, driving data, multi-agent team,
LLM gateway) share one small core: a SQLite store with migrations, a retrying job queue, a
scheduler, API-key auth, Prometheus metrics and webhook notifications.

Everything runs on the standard library + ``requests``. Heavier abilities
(Playwright rendering, OCR, OpenCV, PDF parsing) switch on automatically when
their optional package is installed — and every AI-assisted feature degrades to
a deterministic heuristic when no model is reachable, so the platform works
fully offline.

``mount_platform(app)`` wires the whole thing into the FastAPI app.
"""

from __future__ import annotations

from typing import Any


def mount_platform(app: Any) -> None:
    """Attach all platform routers, the dashboard, /metrics and /api/health."""
    from fastapi import Depends
    from fastapi.responses import HTMLResponse, PlainTextResponse

    from .core import auth, db, metrics, queue, scheduler
    from .core.queue import default_queue
    from .dashboard import DASHBOARD_HTML
    from .modules import (analytics, brain, codeassist, docgen, driving,
                          email_assistant, filepipe, fleet, jobs, llmgateway,
                          media, research, sessions, team, webauto)

    db.init()

    guarded = [Depends(auth.require_api_key)]
    for mod in (webauto, filepipe, analytics, fleet, jobs, research,
                codeassist, email_assistant, driving, team, llmgateway,
                docgen, sessions, brain, media):
        app.include_router(mod.router, dependencies=guarded)
        register = getattr(mod, "register_jobs", None)
        if register:
            register(default_queue())
    app.include_router(queue.router, dependencies=guarded)
    app.include_router(scheduler.router, dependencies=guarded)
    app.include_router(auth.router, dependencies=guarded)

    @app.get("/api/health", tags=["Platform"])
    async def health() -> dict:
        return {
            "status": "ok",
            "modules": ["webauto", "files", "analytics", "fleet", "jobs",
                        "research", "code", "email", "driving", "team", "llm",
                        "docgen", "sessions", "brain", "media"],
            "queue": default_queue().stats(),
            "optional": _optional_features(),
        }

    @app.get("/metrics", response_class=PlainTextResponse, tags=["Platform"])
    async def prometheus_metrics() -> str:
        return metrics.render()

    @app.get("/platform", response_class=HTMLResponse, include_in_schema=False)
    async def dashboard() -> str:
        # Prefer the React Studio (same bundle as the agent chat). If the web app
        # isn't built, fall back to the self-contained HTML dashboard so the
        # platform UI still works from a bare `pip install`.
        from pathlib import Path
        index = Path(__file__).resolve().parent.parent / "server" / "static" / "index.html"
        if index.is_file():
            return index.read_text()
        return DASHBOARD_HTML

    @app.on_event("startup")
    async def _start_platform() -> None:
        default_queue().start()
        scheduler.start()

    @app.on_event("shutdown")
    async def _stop_platform() -> None:
        scheduler.stop()
        default_queue().stop()


def _optional_features() -> dict:
    """Which optional abilities are unlocked in this install."""
    feats = {}
    for feat, module in [("playwright", "playwright"), ("bs4", "bs4"),
                         ("ocr", "pytesseract"), ("opencv", "cv2"),
                         ("pdf", "pypdf"), ("rosbags", "rosbags")]:
        try:
            __import__(module)
            feats[feat] = True
        except Exception:
            feats[feat] = False
    # Image generation is a reachable local service, not a Python import.
    try:
        import os
        import requests
        sd = os.environ.get("SPIDEY_SD_URL", "http://localhost:7860").rstrip("/")
        feats["image_gen"] = requests.get(f"{sd}/sdapi/v1/sd-models", timeout=1).ok
    except Exception:
        feats["image_gen"] = False
    return feats
