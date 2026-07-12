"""API-key auth for the platform's REST surface.

Keys are created via POST /api/keys (or accepted from $SPIDEY_TOKEN, so the
WebSocket token secures REST too). Only SHA-256 hashes are stored; the plain
key is shown exactly once at creation. Enforcement follows Spidey's local-first
stance: with no keys and no token the API is open (bind to 127.0.0.1), the
moment a credential exists every request must present ``X-API-Key``.
"""

from __future__ import annotations

import hashlib
import os
import secrets
from typing import Optional

from fastapi import APIRouter, Header, HTTPException

from . import db


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def create_key(name: str) -> str:
    key = "spk_" + secrets.token_urlsafe(24)
    db.execute("INSERT INTO api_keys(name, key_hash, created_at) VALUES(?,?,?)",
               (name, _hash(key), db.now()))
    return key


def _auth_required() -> bool:
    if os.environ.get("SPIDEY_TOKEN"):
        return True
    return db.one("SELECT id FROM api_keys LIMIT 1") is not None


def verify(key: str) -> bool:
    token = os.environ.get("SPIDEY_TOKEN")
    if token and secrets.compare_digest(key, token):
        return True
    row = db.one("SELECT id FROM api_keys WHERE key_hash=?", (_hash(key),))
    if row:
        db.execute("UPDATE api_keys SET last_used_at=? WHERE id=?", (db.now(), row["id"]))
        return True
    return False


async def require_api_key(x_api_key: Optional[str] = Header(default=None)) -> None:
    if not _auth_required():
        return
    if not x_api_key or not verify(x_api_key):
        raise HTTPException(401, "missing or invalid X-API-Key")


# ------------------------------- REST API ---------------------------------- #
router = APIRouter(prefix="/api/keys", tags=["Auth"])


@router.post("")
def new_key(body: dict) -> dict:
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(422, "name is required")
    key = create_key(name)
    return {"name": name, "key": key,
            "note": "Store this now — only its hash is kept. Send it as X-API-Key."}


@router.get("")
def list_keys() -> list:
    return db.query("SELECT id, name, created_at, last_used_at FROM api_keys ORDER BY id")


@router.delete("/{key_id}")
def revoke(key_id: int) -> dict:
    db.execute("DELETE FROM api_keys WHERE id=?", (key_id,))
    return {"revoked": key_id}
