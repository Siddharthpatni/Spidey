"""The knowledge graph — Spidey's connected memory.

Everything the platform touches becomes a node (a project, file, skill, paper,
person, company, tool, concept) and relationships become typed edges, so the
assistant can reason over *connections* — "ROS2 →uses→ Python →uses→ OpenCV
→used_in→ Autonomous Driving" — instead of only retrieving text.

Native and offline: nodes/edges live in SQLite (no Neo4j needed), entity
extraction is a curated tech dictionary + capitalized-phrase heuristic, and
co-occurrence builds the edges. Any module can call :func:`ingest_text` to fold
new material in; :func:`upsert_node` / :func:`link` add structure directly;
:func:`neighbors`, :func:`shortest_path` and :func:`subgraph` read it back.
"""

from __future__ import annotations

import re
from collections import deque
from typing import Any, Dict, List, Optional, Tuple

from . import db

# Node types (loosely typed; new ones are fine)
TYPES = ("concept", "skill", "tool", "framework", "language", "project", "file",
         "paper", "person", "company", "topic", "fact", "api", "dataset")

# Curated technical vocabulary → typed nodes. Reuses the job-matching skill set
# and adds relationship-worthy tech so the graph is dense from day one.
TECH_TYPES: Dict[str, str] = {}
for _t in ("python", "javascript", "typescript", "java", "c++", "rust", "go", "kotlin"):
    TECH_TYPES[_t] = "language"
for _t in ("react", "fastapi", "django", "flask", "next.js", "pytorch", "tensorflow",
           "langchain", "langgraph", "ros2", "ros", "opencv", "yolo", "spring", "vue"):
    TECH_TYPES[_t] = "framework"
for _t in ("docker", "kubernetes", "redis", "postgresql", "qdrant", "neo4j", "kafka",
           "celery", "ollama", "vllm", "prometheus", "grafana", "git", "nginx", "minio"):
    TECH_TYPES[_t] = "tool"
for _t in ("machine learning", "deep learning", "computer vision", "nlp", "rag",
           "autonomous driving", "reinforcement learning", "knowledge graph",
           "multi-agent", "fine-tuning", "embeddings", "slam", "sensor fusion"):
    TECH_TYPES[_t] = "concept"

STOP = frozenset("the a an and or of to in on for with is are was were this that "
                 "it its by as at from be we our you your they he she".split())


def _now() -> str:
    return db.now()


# ------------------------------ mutation ------------------------------------ #
def upsert_node(node_type: str, name: str, props: Optional[dict] = None,
                bump: float = 0.0) -> int:
    """Create the node or, if it exists, merge props and add ``bump`` to weight.
    Weight grows each time we see a concept — the graph's sense of importance."""
    name = name.strip()[:120]
    if not name:
        return 0
    row = db.one("SELECT id, props, weight FROM kg_nodes WHERE type=? AND name=?",
                 (node_type, name))
    if row:
        merged = {**db.json_loads(row["props"], {}), **(props or {})}
        db.execute("UPDATE kg_nodes SET props=?, weight=weight+?, updated_at=? WHERE id=?",
                   (db.json_dumps(merged), bump, _now(), row["id"]))
        return row["id"]
    return db.execute(
        "INSERT INTO kg_nodes(type, name, props, weight, created_at, updated_at)"
        " VALUES(?,?,?,?,?,?)",
        (node_type, name, db.json_dumps(props or {}), 1.0 + bump, _now(), _now()))


def link(src: int, dst: int, rel: str = "related_to", weight: float = 1.0) -> None:
    if not src or not dst or src == dst:
        return
    row = db.one("SELECT id FROM kg_edges WHERE src=? AND dst=? AND rel=?", (src, dst, rel))
    if row:
        db.execute("UPDATE kg_edges SET weight=weight+? WHERE id=?", (weight, row["id"]))
    else:
        db.execute("INSERT INTO kg_edges(src, dst, rel, weight, created_at) VALUES(?,?,?,?,?)",
                   (src, dst, rel, weight, _now()))


def relate(a_type: str, a_name: str, rel: str, b_type: str, b_name: str,
           weight: float = 1.0) -> Tuple[int, int]:
    """Convenience: upsert both endpoints and connect them (directed)."""
    a = upsert_node(a_type, a_name)
    b = upsert_node(b_type, b_name)
    link(a, b, rel, weight)
    return a, b


# ------------------------------ extraction ---------------------------------- #
def extract_entities(text: str) -> List[Tuple[str, str]]:
    """Return [(type, name)] found in text: curated tech first, then capitalized
    multi-word proper nouns (people/projects/companies), de-duplicated."""
    found: List[Tuple[str, str]] = []
    seen = set()
    low = " " + re.sub(r"[^\w+#.\- ]", " ", text.lower()) + " "
    for term, typ in TECH_TYPES.items():
        if re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9+#])", low):
            if term not in seen:
                found.append((typ, term))
                seen.add(term)
    # Capitalized phrases (e.g. "Autonomous Driving", "Siddharth Patni").
    for m in re.finditer(r"\b([A-Z][a-zA-Z0-9]+(?:\s+[A-Z][a-zA-Z0-9]+){0,3})\b", text):
        phrase = m.group(1).strip()
        key = phrase.lower()
        if (key in seen or key in STOP or len(phrase) < 4
                or phrase.isupper() and len(phrase) < 5):
            continue
        typ = "person" if re.match(r"^[A-Z][a-z]+\s+[A-Z][a-z]+$", phrase) else "topic"
        found.append((typ, phrase))
        seen.add(key)
    return found[:40]


def ingest_text(text: str, source: str = "", central: Optional[Tuple[str, str]] = None,
                rel: str = "mentions") -> Dict[str, Any]:
    """Fold text into the graph: extract entities as nodes, connect co-occurring
    ones, and (optionally) hang them off a central node (e.g. the document)."""
    entities = extract_entities(text)
    ids = [upsert_node(t, n, {"source": source} if source else None, bump=0.5)
           for t, n in entities]
    # Co-occurrence: link consecutive distinct entities (a light "related_to" web).
    for a, b in zip(ids, ids[1:]):
        link(a, b, "related_to", 0.5)
    if central:
        cid = upsert_node(central[0], central[1], {"source": source})
        for nid in ids:
            link(cid, nid, rel, 1.0)
    return {"entities": len(ids), "nodes": [{"type": t, "name": n} for t, n in entities]}


# ------------------------------ reading ------------------------------------- #
def _node(name: str) -> Optional[dict]:
    return db.one("SELECT * FROM kg_nodes WHERE name=? COLLATE NOCASE ORDER BY weight DESC",
                  (name,))


def neighbors(name: str, limit: int = 25) -> Dict[str, Any]:
    node = _node(name)
    if not node:
        return {"found": False, "name": name}
    out = db.query(
        "SELECT e.rel, e.weight, n.id, n.name, n.type FROM kg_edges e"
        " JOIN kg_nodes n ON n.id=e.dst WHERE e.src=? ORDER BY e.weight DESC LIMIT ?",
        (node["id"], limit))
    incoming = db.query(
        "SELECT e.rel, e.weight, n.id, n.name, n.type FROM kg_edges e"
        " JOIN kg_nodes n ON n.id=e.src WHERE e.dst=? ORDER BY e.weight DESC LIMIT ?",
        (node["id"], limit))
    return {"found": True, "node": {"id": node["id"], "name": node["name"],
                                    "type": node["type"], "weight": node["weight"]},
            "out": out, "in": incoming}


def shortest_path(a: str, b: str, max_depth: int = 6) -> Dict[str, Any]:
    """BFS over undirected edges — how are two concepts connected?"""
    na, nb = _node(a), _node(b)
    if not na or not nb:
        return {"found": False, "reason": "one or both nodes are unknown"}
    if na["id"] == nb["id"]:
        return {"found": True, "path": [na["name"]]}
    adj: Dict[int, List[Tuple[int, str]]] = {}
    for e in db.query("SELECT src, dst, rel FROM kg_edges"):
        adj.setdefault(e["src"], []).append((e["dst"], e["rel"]))
        adj.setdefault(e["dst"], []).append((e["src"], e["rel"]))
    q = deque([(na["id"], [(na["id"], "")])])
    seen = {na["id"]}
    while q:
        cur, path = q.popleft()
        if len(path) > max_depth:
            continue
        for nxt, rel in adj.get(cur, []):
            if nxt in seen:
                continue
            new = path + [(nxt, rel)]
            if nxt == nb["id"]:
                names = {r["id"]: r["name"] for r in db.query(
                    "SELECT id, name FROM kg_nodes WHERE id IN (%s)" %
                    ",".join(str(i) for i, _ in new))}
                return {"found": True, "hops": len(new) - 1,
                        "path": [{"name": names.get(i, "?"), "via": rel} for i, rel in new]}
            seen.add(nxt)
            q.append((nxt, new))
    return {"found": False, "reason": f"no path within {max_depth} hops"}


def subgraph(limit: int = 120) -> Dict[str, Any]:
    """The most important slice of the graph, for visualization."""
    nodes = db.query("SELECT id, name, type, weight FROM kg_nodes"
                     " ORDER BY weight DESC LIMIT ?", (limit,))
    ids = {n["id"] for n in nodes}
    edges = [e for e in db.query(
        "SELECT src, dst, rel, weight FROM kg_edges ORDER BY weight DESC LIMIT ?",
        (limit * 4,)) if e["src"] in ids and e["dst"] in ids]
    return {"nodes": nodes, "edges": edges}


def stats() -> Dict[str, Any]:
    by_type = db.query("SELECT type, COUNT(*) AS n FROM kg_nodes GROUP BY type ORDER BY n DESC")
    totals = db.one("SELECT (SELECT COUNT(*) FROM kg_nodes) AS nodes,"
                    " (SELECT COUNT(*) FROM kg_edges) AS edges") or {}
    top = db.query("SELECT name, type, weight FROM kg_nodes ORDER BY weight DESC LIMIT 10")
    return {"nodes": totals.get("nodes", 0), "edges": totals.get("edges", 0),
            "by_type": by_type, "top_concepts": top}
