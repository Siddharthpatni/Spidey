"""Workspaces: every action in the studio is recorded to the database and
restorable — open the dashboard tomorrow and your history is still there.

The dashboard creates one session per browser (id in localStorage) and posts an
item after every successful tool call: which module, what went in, what came
out (truncated), and any referenced artifact id. GET /items replays it.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..core import db

router = APIRouter(prefix="/api/sessions", tags=["Sessions"])


class ItemIn(BaseModel):
    module: str
    action: str
    input: str = ""
    output: str = ""
    ref_id: Optional[int] = None


@router.post("")
def create_session(body: Optional[dict] = None) -> dict:
    name = ((body or {}).get("name") or "").strip() or f"Session {db.now()[:16]}"
    sid = db.execute("INSERT INTO sessions(name, created_at, last_active_at) VALUES(?,?,?)",
                     (name, db.now(), db.now()))
    return {"id": sid, "name": name}


@router.get("")
def list_sessions(limit: int = 20) -> list:
    return db.query(
        "SELECT s.*, COUNT(i.id) AS items FROM sessions s"
        " LEFT JOIN session_items i ON i.session_id=s.id"
        " GROUP BY s.id ORDER BY s.last_active_at DESC LIMIT ?", (limit,))


@router.post("/{session_id}/items")
def add_item(session_id: int, body: ItemIn) -> dict:
    if not db.one("SELECT id FROM sessions WHERE id=?", (session_id,)):
        raise HTTPException(404, "session not found — create one with POST /api/sessions")
    item_id = db.execute(
        "INSERT INTO session_items(session_id, module, action, input, output, ref_id, ts)"
        " VALUES(?,?,?,?,?,?,?)",
        (session_id, body.module[:40], body.action[:80], body.input[:2000],
         body.output[:4000], body.ref_id, db.now()))
    db.execute("UPDATE sessions SET last_active_at=? WHERE id=?", (db.now(), session_id))
    return {"id": item_id}


@router.get("/{session_id}/items")
def list_items(session_id: int, limit: int = 100) -> list:
    if not db.one("SELECT id FROM sessions WHERE id=?", (session_id,)):
        raise HTTPException(404, "session not found")
    return db.query("SELECT * FROM session_items WHERE session_id=?"
                    " ORDER BY id DESC LIMIT ?", (session_id, limit))


@router.delete("/{session_id}")
def delete_session(session_id: int) -> dict:
    db.execute("DELETE FROM session_items WHERE session_id=?", (session_id,))
    db.execute("DELETE FROM sessions WHERE id=?", (session_id,))
    return {"deleted": session_id}
