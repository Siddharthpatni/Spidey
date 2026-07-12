"""Event notifications: every meaningful platform event is logged to the
``notifications`` table and POSTed (best-effort, fire-and-forget) to any
registered webhook whose ``event`` matches — exact name or ``*`` wildcard."""

from __future__ import annotations

import threading
from typing import Any, Dict, List

from . import db, metrics


def register_webhook(event: str, url: str) -> int:
    return db.execute("INSERT INTO webhooks(event, url, created_at) VALUES(?,?,?)",
                      (event, url, db.now()))


def list_webhooks() -> List[dict]:
    return db.query("SELECT * FROM webhooks ORDER BY id")


def delete_webhook(webhook_id: int) -> None:
    db.execute("DELETE FROM webhooks WHERE id=?", (webhook_id,))


def emit(event: str, payload: Dict[str, Any]) -> None:
    """Log the event and deliver it to matching webhooks off-thread."""
    db.execute("INSERT INTO notifications(event, payload, ts) VALUES(?,?,?)",
               (event, db.json_dumps(payload), db.now()))
    metrics.inc("spidey_events_emitted_total", {"event": event})
    hooks = db.query("SELECT url FROM webhooks WHERE event=? OR event='*'", (event,))
    if hooks:
        threading.Thread(target=_deliver, args=(event, payload, [h["url"] for h in hooks]),
                         daemon=True).start()


def _deliver(event: str, payload: Dict[str, Any], urls: List[str]) -> None:
    import requests

    for url in urls:
        try:
            requests.post(url, json={"event": event, "payload": payload}, timeout=10)
            metrics.inc("spidey_webhook_deliveries_total", {"status": "ok"})
        except Exception:
            metrics.inc("spidey_webhook_deliveries_total", {"status": "error"})


def recent(limit: int = 50) -> List[dict]:
    rows = db.query("SELECT * FROM notifications ORDER BY id DESC LIMIT ?", (limit,))
    for r in rows:
        r["payload"] = db.json_loads(r["payload"], {})
    return rows
