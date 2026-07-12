"""LLM Gateway — the Sentinel port: a drop-in endpoint that runs any prompt
through any configured provider and traces every call.

POST /api/llm/chat proxies to Ollama (default) or Claude/Gemini/OpenAI (pass
``provider`` + ``api_key``, or set the standard env var). Each call is logged
with estimated tokens, estimated USD cost (Sentinel's cost tables; $0 on local
models) and latency. /calls browses the trace log, /stats aggregates spend and
reliability per provider/model — your own mini LLM-observability plane, no
external service.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..core import db, llmutil

router = APIRouter(prefix="/api/llm", tags=["LLM Gateway"])


class ChatIn(BaseModel):
    prompt: str
    system: Optional[str] = None
    provider: Optional[str] = Field(default=None,
                                    description="ollama (default) | anthropic | gemini | openai | custom")
    model: Optional[str] = None
    api_key: Optional[str] = Field(default=None,
                                   description="Used for this call only — never stored.")


@router.post("/chat")
def gateway_chat(body: ChatIn) -> dict:
    if not body.prompt.strip():
        raise HTTPException(422, "prompt is required")
    try:
        return llmutil.chat(body.prompt, system=body.system, provider=body.provider,
                            model=body.model, api_key=body.api_key, source="gateway")
    except Exception as e:
        raise HTTPException(502, f"model call failed ({type(e).__name__}): {e} — "
                                 "is Ollama running, or did you pass a valid provider/api_key?")


@router.get("/calls")
def list_calls(limit: int = 50, source: Optional[str] = None) -> list:
    if source:
        return db.query("SELECT id, provider, model, source, status, latency_ms, cost_usd,"
                        " prompt_tokens_est, completion_tokens_est, ts,"
                        " substr(prompt,1,120) AS prompt_preview FROM llm_calls"
                        " WHERE source=? ORDER BY id DESC LIMIT ?", (source, limit))
    return db.query("SELECT id, provider, model, source, status, latency_ms, cost_usd,"
                    " prompt_tokens_est, completion_tokens_est, ts,"
                    " substr(prompt,1,120) AS prompt_preview FROM llm_calls"
                    " ORDER BY id DESC LIMIT ?", (limit,))


@router.get("/calls/{call_id}")
def get_call(call_id: int) -> dict:
    row = db.one("SELECT * FROM llm_calls WHERE id=?", (call_id,))
    if not row:
        raise HTTPException(404, "call not found")
    return row


@router.get("/stats")
def stats() -> dict:
    rows = db.query(
        "SELECT provider, model, COUNT(*) AS calls,"
        " SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) AS errors,"
        " ROUND(AVG(latency_ms),1) AS avg_latency_ms,"
        " ROUND(SUM(cost_usd),6) AS total_cost_usd,"
        " SUM(prompt_tokens_est+completion_tokens_est) AS tokens_est"
        " FROM llm_calls GROUP BY provider, model ORDER BY calls DESC")
    totals = db.one("SELECT COUNT(*) AS calls, ROUND(SUM(cost_usd),6) AS cost_usd,"
                    " SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) AS errors"
                    " FROM llm_calls") or {}
    return {"by_model": rows, "totals": totals}
