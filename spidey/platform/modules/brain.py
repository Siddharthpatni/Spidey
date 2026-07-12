"""The Brain — Spidey's knowledge graph, exposed and self-building.

Feed it anything (notes, papers, repos, resumes, remembered facts) and it grows
a connected map of your engineering world: concepts, tools, frameworks, papers,
people — linked by how they co-occur and relate. Then reason over it: a concept's
neighbors, the shortest path between two ideas, the whole subgraph to draw.

Other modules call :func:`spidey.platform.core.graph.ingest_text` when they take
in material, so the graph fills itself as you use the platform — the "learns on
its own, never forgets" loop. It also mirrors the agent's markdown memory
(``~/.spidey/memory.md``) and lessons, so what the assistant learns about *you*
becomes graph nodes too.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..core import db, graph

router = APIRouter(prefix="/api/brain", tags=["Knowledge Graph"])


class IngestIn(BaseModel):
    text: str
    source: str = ""
    title: Optional[str] = None   # if given, becomes a central node everything hangs off


class RelateIn(BaseModel):
    src: str
    rel: str = "related_to"
    dst: str
    src_type: str = "concept"
    dst_type: str = "concept"


@router.post("/ingest")
def ingest(body: IngestIn) -> dict:
    if not body.text.strip():
        raise HTTPException(422, "text is required")
    central = ("topic", body.title) if body.title else None
    return graph.ingest_text(body.text, source=body.source, central=central)


@router.post("/relate")
def relate(body: RelateIn) -> dict:
    a, b = graph.relate(body.src_type, body.src, body.rel, body.dst_type, body.dst)
    return {"src_id": a, "dst_id": b, "rel": body.rel}


@router.get("/graph")
def get_graph(limit: int = 120) -> dict:
    return graph.subgraph(limit)


@router.get("/stats")
def get_stats() -> dict:
    return graph.stats()


@router.get("/node/{name}")
def node_neighbors(name: str, limit: int = 25) -> dict:
    result = graph.neighbors(name, limit)
    if not result["found"]:
        raise HTTPException(404, f"'{name}' is not in the graph yet")
    return result


@router.get("/path")
def path(from_: str, to: str) -> dict:
    """How are two concepts connected? e.g. /api/brain/path?from_=ROS2&to=YOLO"""
    return graph.shortest_path(from_, to)


@router.post("/sync-memory")
def sync_memory() -> dict:
    """Fold the agent's markdown memory + lessons into the graph as nodes, so
    what Spidey remembers about you is connected to everything else it knows."""
    from ...memory import LESSONS_FILE, MEMORY_FILE

    added = 0
    for path_, kind, rel in [(MEMORY_FILE, "fact", "remembers"),
                             (LESSONS_FILE, "fact", "learned")]:
        try:
            for line in path_.read_text().splitlines():
                line = line.strip("- ").strip()
                if len(line) < 8:
                    continue
                graph.ingest_text(line, source=path_.name,
                                  central=("person", "You"), rel=rel)
                added += 1
        except OSError:
            continue
    return {"lines_ingested": added, **graph.stats()}


def learn_fact(fact: str) -> None:
    """Called by the agent's ``remember`` tool: mirror the fact into the graph."""
    try:
        graph.ingest_text(fact, source="memory", central=("person", "You"),
                          rel="remembers")
    except Exception:
        pass  # graph is additive; never block a remember
