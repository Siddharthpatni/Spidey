"""Media Studio — generate images (and, when you install the tools, audio) locally.

Honest about the stack: Ollama runs text models, not image/audio/video ones, so
this module talks to the real local generators when they're present:

  * Images → Stable Diffusion via an AUTOMATIC1111-compatible API
    (``$SPIDEY_SD_URL``, default http://localhost:7860). Install one of:
      - AUTOMATIC1111 stable-diffusion-webui (run with ``--api``)
      - ComfyUI with the a1111-style API, or SD.Next
  * Audio/music → a local server exposing ``$SPIDEY_TTS_URL`` / ``$SPIDEY_MUSIC_URL``
    (e.g. a small AudioCraft/MusicGen or Piper/Bark wrapper). Optional.

Every result is stored in ``generated_docs`` and downloadable through the same
``/api/docgen/files/{id}/download`` endpoint as documents. When no backend is
reachable, the endpoints return 501 with the exact install command — nothing
pretends to work that isn't actually installed.
"""

from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..core import db

router = APIRouter(prefix="/api/media", tags=["Media Studio"])


def _sd_url() -> str:
    return os.environ.get("SPIDEY_SD_URL", "http://localhost:7860").rstrip("/")


def _store(kind: str, fmt: str, title: str, prompt: str, data: bytes) -> Dict[str, Any]:
    out_dir = db.data_dir() / "generated"
    out_dir.mkdir(exist_ok=True)
    import re
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", title).strip("-").lower()[:60] or kind
    doc_id = db.execute(
        "INSERT INTO generated_docs(kind, title, format, path, size, prompt, markdown,"
        " mode, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (kind, title, fmt, "", len(data), prompt[:1000], "", "generated", db.now()))
    path = out_dir / f"{doc_id:04d}-{slug}.{fmt}"
    path.write_bytes(data)
    db.execute("UPDATE generated_docs SET path=? WHERE id=?", (str(path), doc_id))
    return {"id": doc_id, "title": title, "format": fmt, "size": len(data),
            "download_url": f"/api/docgen/files/{doc_id}/download"}


class ImageIn(BaseModel):
    prompt: str
    negative_prompt: str = ""
    width: int = 512
    height: int = 512
    steps: int = 25
    title: str = ""


def generate_image(body: ImageIn) -> Dict[str, Any]:
    import requests

    payload = {"prompt": body.prompt, "negative_prompt": body.negative_prompt,
               "width": body.width, "height": body.height, "steps": body.steps}
    try:
        r = requests.post(f"{_sd_url()}/sdapi/v1/txt2img", json=payload, timeout=300)
        r.raise_for_status()
        images = r.json().get("images") or []
    except requests.exceptions.RequestException:
        raise HTTPException(501,
            "No Stable Diffusion backend reachable at " + _sd_url() + ". Install one and "
            "run it with the API on:\n"
            "  • AUTOMATIC1111: ./webui.sh --api   (or --api --listen)\n"
            "  • ComfyUI / SD.Next with the a1111 API enabled\n"
            "Then set SPIDEY_SD_URL if it's not on :7860. (Ollama does not generate images.)")
    if not images:
        raise HTTPException(502, "the image backend returned no image")
    data = base64.b64decode(images[0].split(",", 1)[-1])
    return _store("image", "png", body.title or body.prompt[:40], body.prompt, data)


@router.post("/image")
def api_image(body: ImageIn) -> dict:
    if not body.prompt.strip():
        raise HTTPException(422, "prompt is required")
    return generate_image(body)


@router.get("/status")
def status() -> dict:
    """Which media backends are reachable right now."""
    import requests
    def reachable(url: str) -> bool:
        try:
            return requests.get(url, timeout=2).status_code < 500
        except Exception:
            return False
    return {
        "image": {"backend": "stable-diffusion (a1111 API)", "url": _sd_url(),
                  "available": reachable(f"{_sd_url()}/sdapi/v1/sd-models")},
        "note": "Ollama runs text models only; image/audio/video use separate local "
                "tools. Install Stable Diffusion for images; ask to wire MusicGen/Bark "
                "for audio and AnimateDiff for video.",
    }


class AudioIn(BaseModel):
    prompt: str
    seconds: int = 8
    title: str = ""
    kind: str = "music"   # music | speech


@router.post("/audio")
def api_audio(body: AudioIn) -> dict:
    """Generate music/speech via a local server if one is configured.
    Set SPIDEY_MUSIC_URL (MusicGen/AudioCraft) or SPIDEY_TTS_URL (Bark/Piper)."""
    import requests
    url = os.environ.get("SPIDEY_MUSIC_URL" if body.kind == "music" else "SPIDEY_TTS_URL")
    if not url:
        raise HTTPException(501,
            f"No {body.kind} backend configured. Local audio generation needs a separate "
            "model server (MusicGen/AudioCraft for music, Bark/Piper for speech). Install "
            "one, expose an HTTP endpoint returning audio bytes, and set "
            f"{'SPIDEY_MUSIC_URL' if body.kind == 'music' else 'SPIDEY_TTS_URL'}. "
            "(Ollama does not generate audio.)")
    try:
        r = requests.post(url, json={"prompt": body.prompt, "seconds": body.seconds}, timeout=300)
        r.raise_for_status()
    except requests.exceptions.RequestException as e:
        raise HTTPException(502, f"audio backend error: {e}")
    fmt = "wav" if r.headers.get("content-type", "").endswith("wav") else "mp3"
    return _store(body.kind, fmt, body.title or body.prompt[:40], body.prompt, r.content)
