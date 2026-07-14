"""Knowledge Nexus — a distributed web-intelligence platform.

A mini search-engine that continuously crawls the web, deduplicates, extracts
entities into the knowledge graph, indexes semantic embeddings, and serves
**hybrid search** (BM25 + vector + graph + recency) to Spidey's agents. It is the
knowledge-acquisition layer for the AI's long-term memory: the assistant stops
depending on static documents and builds/updates its own knowledge base.

Runs on Spidey's own core — no Kafka/Neo4j/Elasticsearch/Milvus to stand up. The
mapping is 1:1 with the "real" stack, just sized to run offline on a laptop:

    crawl frontier / queue  →  the platform job queue (Kafka/RabbitMQ)
    knowledge graph         →  kg_nodes / kg_edges (Neo4j)
    vector index            →  nexus_chunks.vec + cosine (Qdrant/Milvus)
    keyword index           →  nexus_postings inverted index + BM25 (Elasticsearch)
    dedup                   →  SimHash + Hamming distance (LSH)
    object store / cache    →  SQLite + WAL (S3/Redis)

Pipeline per URL (a queued job, so retries + backoff come free):
  fetch (robots.txt + rate-limit) → extract main text → SimHash dedup →
  chunk + embed → BM25 index → entity extraction → knowledge graph →
  discover links → enqueue frontier (bounded by depth + domain).
"""

from __future__ import annotations

import math
import re
import time
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse
from urllib import robotparser

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..core import db, graph, metrics
from ..core.text import chunk_text, cosine, embed, strip_html, tokenize
from .webauto import extract_links, fetch

MAX_PAGES_DEFAULT = 25
RATE_LIMIT_S = 1.0            # min seconds between fetches to the same domain
SIMHASH_HAMMING = 6          # <= this bit-distance ⇒ near-duplicate (63-bit hash)
BM25_K1, BM25_B = 1.5, 0.75

_last_fetch: Dict[str, float] = {}   # domain → last fetch epoch (politeness)
_robots: Dict[str, Any] = {}


# ------------------------------ dedup: SimHash ------------------------------ #
def simhash(text: str) -> int:
    """63-bit SimHash of a token bag — near-duplicate pages get near-equal hashes.
    63 bits (not 64) so the value fits SQLite's signed INTEGER without overflow."""
    import hashlib
    BITS = 63
    v = [0] * BITS
    for tok, w in Counter(tokenize(text)).items():
        h = int.from_bytes(hashlib.blake2b(tok.encode(), digest_size=8).digest(), "big")
        for i in range(BITS):
            v[i] += w if (h >> i) & 1 else -w
    out = 0
    for i in range(BITS):
        if v[i] > 0:
            out |= (1 << i)
    return out


def _hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def near_duplicate(sh: int) -> Optional[int]:
    """Return the page id of a near-duplicate already in the index. Includes
    'unchanged' pages — a re-crawled page stays a valid dedup target."""
    for row in db.query("SELECT id, simhash FROM nexus_pages WHERE simhash IS NOT NULL"
                        " AND status IN ('indexed', 'unchanged')"):
        if _hamming(sh, row["simhash"]) <= SIMHASH_HAMMING:
            return row["id"]
    return None


# ------------------------------ politeness ---------------------------------- #
def _allowed(url: str) -> bool:
    p = urlparse(url)
    base = f"{p.scheme}://{p.netloc}"
    rp = _robots.get(base)
    if rp is None:
        rp = robotparser.RobotFileParser()
        try:
            rp.set_url(base + "/robots.txt")
            rp.read()
        except Exception:
            rp = False  # unreadable robots ⇒ be permissive
        _robots[base] = rp
    if rp is False:
        return True
    try:
        return rp.can_fetch("SpideyNexus", url)
    except Exception:
        return True


def _rate_limit(domain: str) -> None:
    last = _last_fetch.get(domain, 0)
    wait = RATE_LIMIT_S - (time.time() - last)
    if wait > 0:
        time.sleep(wait)
    _last_fetch[domain] = time.time()


# ------------------------------ BM25 index ---------------------------------- #
def _index_chunk(chunk_id: int, text: str) -> int:
    toks = tokenize(text)
    tf = Counter(toks)
    with db.connect() as conn:
        conn.executemany("INSERT INTO nexus_postings(term, chunk_id, tf) VALUES(?,?,?)",
                         [(t, chunk_id, c) for t, c in tf.items()])
        for t in tf:
            conn.execute("INSERT INTO nexus_terms(term, df) VALUES(?,1) "
                         "ON CONFLICT(term) DO UPDATE SET df=df+1", (t,))
    return len(toks)


def _bm25(query_terms: List[str]) -> Dict[int, float]:
    """BM25 score per chunk for the query terms (classic Okapi BM25)."""
    stats = db.one("SELECT COUNT(*) AS n, AVG(ntokens) AS avg FROM nexus_chunks") or {}
    N = stats.get("n") or 0
    avgdl = stats.get("avg") or 1
    if not N:
        return {}
    scores: Dict[int, float] = {}
    for term in set(query_terms):
        row = db.one("SELECT df FROM nexus_terms WHERE term=?", (term,))
        if not row or not row["df"]:
            continue
        idf = math.log(1 + (N - row["df"] + 0.5) / (row["df"] + 0.5))
        for p in db.query("SELECT p.chunk_id, p.tf, c.ntokens FROM nexus_postings p"
                          " JOIN nexus_chunks c ON c.id=p.chunk_id WHERE p.term=?", (term,)):
            dl = p["ntokens"] or 1
            denom = p["tf"] + BM25_K1 * (1 - BM25_B + BM25_B * dl / avgdl)
            scores[p["chunk_id"]] = scores.get(p["chunk_id"], 0) + idf * (p["tf"] * (BM25_K1 + 1)) / denom
    return scores


# ------------------------------ the crawl job ------------------------------- #
def _now() -> str:
    return db.now()


def crawl_one(url: str, depth: int, max_pages: int, domain_lock: Optional[str]) -> Dict[str, Any]:
    domain = urlparse(url).netloc
    if not _allowed(url):
        db.execute("INSERT OR IGNORE INTO nexus_pages(url, domain, status, fetched_at)"
                   " VALUES(?,?,?,?)", (url, domain, "failed", _now()))
        return {"url": url, "status": "blocked_by_robots"}
    _rate_limit(domain)
    metrics.inc("spidey_nexus_fetches_total", {"domain": domain})
    html = fetch(url)
    text = strip_html(html)
    sha = __import__("hashlib").sha256(text.encode()).hexdigest()
    title = (re.search(r"(?is)<title[^>]*>(.*?)</title>", html) or [None, ""])[1]
    title = " ".join(title.split())[:200]

    existing = db.one("SELECT id, sha256 FROM nexus_pages WHERE url=?", (url,))
    if existing and existing["sha256"] == sha:
        db.execute("UPDATE nexus_pages SET status='unchanged', revisits=revisits+1,"
                   " fetched_at=? WHERE id=?", (_now(), existing["id"]))
        return {"url": url, "status": "unchanged"}  # incremental: skip re-index

    sh = simhash(text)
    dup = near_duplicate(sh)
    if dup and not existing:
        db.execute("INSERT INTO nexus_pages(url, domain, title, sha256, simhash, depth,"
                   " status, dup_of, fetched_at) VALUES(?,?,?,?,?,?,?,?,?)",
                   (url, domain, title, sha, sh, depth, "duplicate", dup, _now()))
        metrics.inc("spidey_nexus_duplicates_total")
        return {"url": url, "status": "duplicate", "dup_of": dup}

    # upsert the page, then (re)build its index
    if existing:
        page_id = existing["id"]
        db.execute("DELETE FROM nexus_postings WHERE chunk_id IN"
                   " (SELECT id FROM nexus_chunks WHERE page_id=?)", (page_id,))
        db.execute("DELETE FROM nexus_chunks WHERE page_id=?", (page_id,))
        db.execute("UPDATE nexus_pages SET title=?, sha256=?, simhash=?, status='indexed',"
                   " changed_at=?, fetched_at=?, revisits=revisits+1 WHERE id=?",
                   (title, sha, sh, _now(), _now(), page_id))
    else:
        page_id = db.execute(
            "INSERT INTO nexus_pages(url, domain, title, sha256, simhash, depth, status,"
            " fetched_at, changed_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (url, domain, title, sha, sh, depth, "indexed", _now(), _now()))

    chunks = chunk_text(text)
    for i, c in enumerate(chunks):
        cid = db.execute("INSERT INTO nexus_chunks(page_id, seq, text, vec, ntokens)"
                         " VALUES(?,?,?,?,?)", (page_id, i, c, db.json_dumps(embed(c)), 0))
        n = _index_chunk(cid, c)
        db.execute("UPDATE nexus_chunks SET ntokens=? WHERE id=?", (n, cid))
    metrics.inc("spidey_nexus_pages_indexed_total")

    # entity extraction → knowledge graph (the page node links to what it mentions)
    try:
        pnode = graph.upsert_node("paper", title or url, {"url": url}, bump=1.0)
        for typ, name in graph.extract_entities(text[:6000]):
            graph.link(pnode, graph.upsert_node(typ, name, bump=0.5), "mentions", 1.0)
    except Exception:
        pass

    # discover + enqueue the frontier (bounded)
    discovered = 0
    if depth > 0:
        from ..core.queue import default_queue
        indexed = db.one("SELECT COUNT(*) AS n FROM nexus_pages WHERE status='indexed'")["n"]
        for link in extract_links(html, url)[:40]:
            lu = link["url"].split("#")[0]
            ld = urlparse(lu).netloc
            if domain_lock and ld != domain_lock:
                continue
            if indexed + discovered >= max_pages:
                break
            if not lu.startswith(("http://", "https://")):
                continue
            if db.one("SELECT id FROM nexus_pages WHERE url=?", (lu,)):
                continue
            default_queue().enqueue("nexus.crawl", {"url": lu, "depth": depth - 1,
                                                    "max_pages": max_pages,
                                                    "domain_lock": domain_lock})
            discovered += 1
    return {"url": url, "status": "indexed", "chunks": len(chunks), "discovered": discovered}


def _job_crawl(payload: Dict[str, Any]) -> Dict[str, Any]:
    return crawl_one(payload["url"], payload.get("depth", 0),
                     payload.get("max_pages", MAX_PAGES_DEFAULT), payload.get("domain_lock"))


def register_jobs(queue) -> None:
    queue.register("nexus.crawl", _job_crawl)


# ------------------------------ hybrid search ------------------------------- #
def _recency_boost(fetched_at: Optional[str]) -> float:
    if not fetched_at:
        return 0.0
    try:
        age_days = (datetime.now(timezone.utc) - datetime.fromisoformat(fetched_at)).days
    except ValueError:
        return 0.0
    return math.exp(-age_days / 30.0)  # 1.0 today → ~0.37 at 30 days


def hybrid_search(query: str, k: int = 8) -> List[Dict[str, Any]]:
    """Blend BM25 (keyword) + vector (semantic) + graph + recency + authority.

    score = 0.35·semantic + 0.25·keyword + 0.20·freshness + 0.10·authority + 0.10·graph
    """
    qterms = tokenize(query)
    bm = _bm25(qterms)
    qvec = embed(query)
    # candidate chunks: everything the keyword index hit, plus a vector sweep
    cand = set(bm.keys())
    for r in db.query("SELECT id FROM nexus_chunks ORDER BY id DESC LIMIT 400"):
        cand.add(r["id"])
    if not cand:
        return []
    bm_max = max(bm.values()) if bm else 1.0
    # graph signal: does the query name a known concept?
    graph_hit = {n.lower() for (_, n) in graph.extract_entities(query)}

    rows = db.query(
        "SELECT c.id, c.text, c.vec, p.url, p.title, p.fetched_at, p.authority, p.domain"
        " FROM nexus_chunks c JOIN nexus_pages p ON p.id=c.page_id"
        " WHERE c.id IN (%s)" % ",".join("?" * len(cand)), tuple(cand))
    scored = []
    for r in rows:
        sem = cosine(qvec, db.json_loads(r["vec"], []))
        kw = (bm.get(r["id"], 0) / bm_max) if bm_max else 0
        fresh = _recency_boost(r["fetched_at"])
        auth = min(1.0, (r["authority"] or 0) / 10.0)
        gboost = 1.0 if any(g in (r["text"] or "").lower() for g in graph_hit) else 0.0
        score = 0.35 * sem + 0.25 * kw + 0.20 * fresh + 0.10 * auth + 0.10 * gboost
        scored.append({"chunk_id": r["id"], "url": r["url"], "title": r["title"],
                       "domain": r["domain"], "snippet": (r["text"] or "")[:280],
                       "score": round(score, 4),
                       "signals": {"semantic": round(sem, 3), "keyword": round(kw, 3),
                                   "freshness": round(fresh, 3)}})
    scored.sort(key=lambda x: x["score"], reverse=True)
    metrics.inc("spidey_nexus_searches_total")
    return scored[:k]


# ------------------------------- REST API ---------------------------------- #
router = APIRouter(prefix="/api/nexus", tags=["Knowledge Nexus"])


class CrawlIn(BaseModel):
    url: str
    depth: int = 1                 # link-following depth (0 = just this page)
    max_pages: int = MAX_PAGES_DEFAULT
    same_domain: bool = True       # stay on the seed's domain


@router.post("/crawl")
def start_crawl(body: CrawlIn) -> dict:
    if not body.url.startswith(("http://", "https://")):
        raise HTTPException(422, "url must start with http:// or https://")
    lock = urlparse(body.url).netloc if body.same_domain else None
    from ..core.queue import default_queue
    default_queue().enqueue("nexus.crawl", {"url": body.url, "depth": body.depth,
                                            "max_pages": body.max_pages, "domain_lock": lock})
    return {"status": "crawling", "seed": body.url, "max_pages": body.max_pages,
            "note": "distributed across the queue workers — poll GET /api/nexus/status"}


@router.post("/crawl-search")
def crawl_from_search(body: dict) -> dict:
    """Research a *topic* (not a URL): web-search it, then crawl the top results
    into the index. Turns 'index everything about the Inspire RH56 hand' into one call."""
    query = body.get("query", "")
    if not query.strip():
        raise HTTPException(422, "query is required")
    from ..core.websearch import search
    from ..core.queue import default_queue
    results = search(query, limit=int(body.get("max_pages", 6)),
                     scholarly=bool(body.get("scholarly", False)))
    seeds = [r["url"] for r in results if r["url"].startswith(("http://", "https://"))]
    for url in seeds:
        default_queue().enqueue("nexus.crawl", {"url": url, "depth": 0,
                                                "max_pages": 1, "domain_lock": None})
    return {"query": query, "queued": len(seeds), "seeds": seeds}


@router.post("/crawl-now")
def crawl_now(body: CrawlIn) -> dict:
    """Crawl the seed synchronously (one page) — handy for tests/quick indexing."""
    lock = urlparse(body.url).netloc if body.same_domain else None
    try:
        return crawl_one(body.url, body.depth, body.max_pages, lock)
    except Exception as e:
        raise HTTPException(502, f"{type(e).__name__}: {e}")


@router.get("/search")
def search(q: str, k: int = 8) -> dict:
    if not q.strip():
        raise HTTPException(422, "q is required")
    return {"query": q, "results": hybrid_search(q, k)}


@router.get("/answer")
def answer(q: str, k: int = 5) -> dict:
    """RAG over the crawled corpus: retrieve, then answer with the model (cited)."""
    from ..core import llmutil
    hits = hybrid_search(q, k)
    if not hits:
        raise HTTPException(404, "nothing indexed yet — crawl some pages first")
    context = "\n\n".join(f"[{i+1}] ({h['url']}) {h['snippet']}" for i, h in enumerate(hits))
    llm = llmutil.ask(f"Answer using ONLY these web excerpts; cite [n].\n\n{context}\n\n"
                      f"QUESTION: {q}")
    return {"answer": llm or "No model reachable — top results below.",
            "mode": "llm" if llm else "retrieval_only", "sources": hits}


@router.get("/status")
def status() -> dict:
    counts = {r["status"]: r["n"] for r in db.query(
        "SELECT status, COUNT(*) AS n FROM nexus_pages GROUP BY status")}
    totals = db.one("SELECT (SELECT COUNT(*) FROM nexus_chunks) AS chunks,"
                    " (SELECT COUNT(*) FROM nexus_terms) AS vocab,"
                    " (SELECT COUNT(DISTINCT domain) FROM nexus_pages) AS domains") or {}
    from ..core.queue import default_queue
    # "in the index" = freshly indexed + re-crawled-unchanged (both are searchable)
    return {"pages": counts,
            "indexed": counts.get("indexed", 0) + counts.get("unchanged", 0),
            "duplicates_removed": counts.get("duplicate", 0),
            "chunks": totals.get("chunks", 0), "vocabulary": totals.get("vocab", 0),
            "domains": totals.get("domains", 0), "queue": default_queue().stats(),
            "kg": graph.stats()}


@router.get("/pages")
def list_pages(limit: int = 50) -> list:
    return db.query("SELECT id, url, title, domain, status, depth, fetched_at FROM"
                    " nexus_pages ORDER BY id DESC LIMIT ?", (limit,))


@router.post("/feedback")
def feedback(body: dict) -> dict:
    """Learning-to-rank signal: which result the user actually clicked."""
    db.execute("INSERT INTO nexus_feedback(query, chunk_id, clicked, ts) VALUES(?,?,?,?)",
               (body.get("query"), body.get("chunk_id"), int(bool(body.get("clicked", True))),
                db.now()))
    # reward the source page's authority so good pages rank higher next time
    if body.get("chunk_id"):
        db.execute("UPDATE nexus_pages SET authority=authority+1 WHERE id="
                   "(SELECT page_id FROM nexus_chunks WHERE id=?)", (body["chunk_id"],))
    return {"ok": True}
