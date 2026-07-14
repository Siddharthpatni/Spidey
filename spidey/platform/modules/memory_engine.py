"""Memory Engine — persistent, structured memory for the AI OS.

ChatGPT-style memory, but typed and searchable, spanning the classic memory
hierarchy so the assistant carries context across sessions without retraining:

  * long        — preferences, goals, projects (durable facts about the user)
  * semantic    — facts + relationships (also mirrored into the knowledge graph)
  * episodic     — conversations, actions, mistakes (what happened)
  * procedural  — workflows, repeated actions (how the user likes things done)

Every memory is embedded, so ``recall`` is semantic (cosine) blended with
importance and recency — the assistant retrieves what's *relevant*, not just
recent. ``profile`` assembles a compact context block (who the user is, their
goals, projects, top facts) that a Context Engine can inject into any prompt.
Unifies with Spidey's existing markdown memory + lessons via ``/sync``.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..core import db, graph
from ..core.text import cosine, embed

SCOPES = ("long", "semantic", "episodic", "procedural")
KINDS = ("preference", "goal", "project", "fact", "skill", "workflow", "episode", "mistake")
KIND_SCOPE = {"preference": "long", "goal": "long", "project": "long",
              "fact": "semantic", "skill": "semantic",
              "workflow": "procedural", "episode": "episodic", "mistake": "episodic"}

router = APIRouter(prefix="/api/memory", tags=["Memory Engine"])


class MemoryIn(BaseModel):
    content: str
    kind: str = Field(default="fact", description=f"one of {KINDS}")
    importance: float = 1.0
    source: str = "user"


def remember(content: str, kind: str = "fact", importance: float = 1.0,
             source: str = "user") -> Dict[str, Any]:
    content = content.strip()
    if not content:
        raise HTTPException(422, "content is required")
    if kind not in KINDS:
        raise HTTPException(422, f"kind must be one of {KINDS}")
    scope = KIND_SCOPE.get(kind, "long")
    # de-dupe near-identical memories of the same kind
    existing = db.one("SELECT id FROM memories WHERE kind=? AND lower(content)=lower(?)",
                      (kind, content))
    if existing:
        db.execute("UPDATE memories SET importance=importance+?, last_used_at=? WHERE id=?",
                   (importance, db.now(), existing["id"]))
        return {"id": existing["id"], "deduped": True}
    mid = db.execute(
        "INSERT INTO memories(scope, kind, content, vec, importance, source, created_at)"
        " VALUES(?,?,?,?,?,?,?)",
        (scope, kind, content, db.json_dumps(embed(content)), importance, source, db.now()))
    # semantic memories also become knowledge-graph structure
    if scope == "semantic":
        try:
            graph.ingest_text(content, source="memory", central=("person", "You"),
                             rel="knows")
        except Exception:
            pass
    return {"id": mid, "scope": scope, "kind": kind}


def recall(query: str, k: int = 6, scope: Optional[str] = None) -> List[Dict[str, Any]]:
    """Relevance = semantic similarity, boosted by importance and recency."""
    rows = db.query("SELECT * FROM memories" + (" WHERE scope=?" if scope else ""),
                    (scope,) if scope else ())
    if not rows:
        return []
    qv = embed(query)
    now = datetime.now(timezone.utc)
    scored = []
    for r in rows:
        sim = cosine(qv, db.json_loads(r["vec"], []))
        try:
            age = (now - datetime.fromisoformat(r["created_at"])).days
        except ValueError:
            age = 0
        recency = math.exp(-age / 60.0)
        score = 0.7 * sim + 0.2 * min(1.0, r["importance"] / 5.0) + 0.1 * recency
        scored.append({"id": r["id"], "kind": r["kind"], "scope": r["scope"],
                       "content": r["content"], "score": round(score, 4)})
    scored.sort(key=lambda x: x["score"], reverse=True)
    top = scored[:k]
    for m in top:
        db.execute("UPDATE memories SET uses=uses+1, last_used_at=? WHERE id=?",
                   (db.now(), m["id"]))
    return top


# ------------------------------- REST API ---------------------------------- #
@router.post("/remember")
def api_remember(body: MemoryIn) -> dict:
    return remember(body.content, body.kind, body.importance, body.source)


@router.get("/recall")
def api_recall(q: str, k: int = 6, scope: Optional[str] = None) -> dict:
    if not q.strip():
        raise HTTPException(422, "q is required")
    return {"query": q, "memories": recall(q, k, scope)}


@router.get("/all")
def list_all(kind: Optional[str] = None, scope: Optional[str] = None, limit: int = 100) -> list:
    where, params = [], []
    if kind:
        where.append("kind=?"); params.append(kind)
    if scope:
        where.append("scope=?"); params.append(scope)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    return db.query("SELECT id, scope, kind, content, importance, uses, created_at FROM"
                    f" memories{clause} ORDER BY importance DESC, id DESC LIMIT ?",
                    (*params, limit))


@router.get("/profile")
def profile() -> dict:
    """A compact context block — who the user is — for prompt injection."""
    out: Dict[str, Any] = {}
    for kind in ("preference", "goal", "project", "skill", "workflow"):
        rows = db.query("SELECT content FROM memories WHERE kind=? ORDER BY importance DESC"
                        " LIMIT 8", (kind,))
        if rows:
            out[kind + "s"] = [r["content"] for r in rows]
    counts = {r["scope"]: r["n"] for r in db.query(
        "SELECT scope, COUNT(*) AS n FROM memories GROUP BY scope")}
    out["counts"] = counts
    out["total"] = sum(counts.values())
    return out


@router.post("/sync")
def sync() -> dict:
    """Fold Spidey's markdown memory (~/.spidey/memory.md) and lessons into the
    typed store, so the engine and the agent's memory stay one brain."""
    from ...memory import LESSONS_FILE, MEMORY_FILE
    added = 0
    for path_, kind in [(MEMORY_FILE, "fact"), (LESSONS_FILE, "mistake")]:
        try:
            for line in path_.read_text().splitlines():
                line = line.strip("- ").strip()
                line = line.split("] ", 1)[-1] if line.startswith("[") else line
                if len(line) >= 8:
                    remember(line, kind=kind, source=path_.name)
                    added += 1
        except OSError:
            continue
    return {"synced": added, **profile()}


@router.delete("/{memory_id}")
def forget(memory_id: int) -> dict:
    db.execute("DELETE FROM memories WHERE id=?", (memory_id,))
    return {"forgotten": memory_id}
