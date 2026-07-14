"""Cross-device chat history — conversations persisted to the shared database.

The agent's chat used to live in each browser's localStorage, so opening Spidey
on your phone showed none of the conversations from your laptop. Now every
finished turn is written here, keyed by conversation, so the History drawer on
any device on the network shows the same threads. The server calls
:func:`save_turn` as runs complete; the UI reads the REST endpoints below.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException

from ..core import db

router = APIRouter(prefix="/api/chat", tags=["Chat History"])


def create_conversation(title: str = "New chat", device_id: Optional[str] = None,
                        device_label: Optional[str] = None) -> int:
    return db.execute(
        "INSERT INTO chat_conversations(title, device_id, device_label, created_at,"
        " updated_at) VALUES(?,?,?,?,?)",
        (title[:120] or "New chat", device_id, device_label, db.now(), db.now()))


def save_turn(conversation_id: Optional[int], task: str, answer: str,
              device_id: Optional[str] = None, device_label: Optional[str] = None) -> int:
    """Append a user+assistant turn; create the conversation on the first turn
    (titled from the first user message, attributed to the device). Returns the id."""
    if not conversation_id or not db.one("SELECT id FROM chat_conversations WHERE id=?",
                                         (conversation_id,)):
        conversation_id = create_conversation(task[:60], device_id, device_label)
    with db.connect() as conn:
        conn.executemany(
            "INSERT INTO chat_messages(conversation_id, role, content, ts) VALUES(?,?,?,?)",
            [(conversation_id, "user", task, db.now()),
             (conversation_id, "assistant", answer, db.now())])
        conn.execute("UPDATE chat_conversations SET updated_at=? WHERE id=?",
                     (db.now(), conversation_id))
    return conversation_id


@router.get("/conversations")
def list_conversations(device_id: Optional[str] = None, limit: int = 100) -> list:
    """All conversations (attributed to their device), or just one device's when
    ``device_id`` is given — the device-wise session view for shared instances."""
    where = " WHERE c.device_id=?" if device_id else ""
    params = ((device_id,) if device_id else ()) + (limit,)
    return db.query(
        "SELECT c.id, c.title, c.device_id, c.device_label, c.created_at, c.updated_at,"
        " COUNT(m.id) AS messages FROM chat_conversations c"
        " LEFT JOIN chat_messages m ON m.conversation_id=c.id"
        f"{where} GROUP BY c.id ORDER BY c.updated_at DESC LIMIT ?", params)


@router.get("/devices")
def list_devices() -> list:
    """Who's been using this Spidey — one row per device/person, with counts."""
    return db.query(
        "SELECT COALESCE(device_label, device_id, 'unknown') AS name, device_id,"
        " COUNT(*) AS conversations, MAX(updated_at) AS last_active"
        " FROM chat_conversations GROUP BY device_id ORDER BY last_active DESC")


@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: int) -> dict:
    conv = db.one("SELECT * FROM chat_conversations WHERE id=?", (conversation_id,))
    if not conv:
        raise HTTPException(404, "conversation not found")
    conv["messages"] = db.query(
        "SELECT role, content, ts FROM chat_messages WHERE conversation_id=? ORDER BY id",
        (conversation_id,))
    return conv


@router.delete("/conversations/{conversation_id}")
def delete_conversation(conversation_id: int) -> dict:
    db.execute("DELETE FROM chat_messages WHERE conversation_id=?", (conversation_id,))
    db.execute("DELETE FROM chat_conversations WHERE id=?", (conversation_id,))
    return {"deleted": conversation_id}
