"""Research assistant: feed it papers/PDFs/notes, then summarize, take notes,
drill flashcards, ask questions with citations, and compare documents.

Ingestion chunks each document and embeds every chunk into the shared vector
store. Q&A retrieves top chunks and answers with the model (citing chunk ids);
without a model the answer is extractive — the most relevant sentences, still
cited. Summaries, notes and flashcards have the same two paths, so the whole
module works offline.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..core import db, llmutil
from ..core.text import (chunk_text, cosine, embed, extract_text,
                         extractive_summary, sentences, tokenize, top_k)


class DocIn(BaseModel):
    title: str
    text: Optional[str] = None
    path: Optional[str] = None  # pdf/docx/html/txt on disk


class AskIn(BaseModel):
    question: str
    doc_id: Optional[int] = None  # restrict to one document; default: whole corpus


def ingest(title: str, text: str, kind: str, source: str = "") -> int:
    doc_id = db.execute("INSERT INTO docs(title, kind, source, created_at) VALUES(?,?,?,?)",
                        (title, kind, source, db.now()))
    with db.connect() as conn:
        conn.executemany(
            "INSERT INTO doc_chunks(doc_id, seq, text, vec) VALUES(?,?,?,?)",
            [(doc_id, i, c, db.json_dumps(embed(c)))
             for i, c in enumerate(chunk_text(text))])
    # Fold the document into the knowledge graph (self-building brain).
    try:
        from ..core import graph
        graph.ingest_text(text[:8000], source=f"doc:{title}",
                          central=("paper", title), rel="covers")
    except Exception:
        pass
    return doc_id


def _chunks(doc_id: Optional[int]) -> List[tuple]:
    if doc_id:
        rows = db.query("SELECT id, text, vec FROM doc_chunks WHERE doc_id=?", (doc_id,))
    else:
        rows = db.query("SELECT id, text, vec FROM doc_chunks")
    return [(r["id"], r["text"], db.json_loads(r["vec"], [])) for r in rows]


def _doc_text(doc_id: int) -> str:
    rows = db.query("SELECT text FROM doc_chunks WHERE doc_id=? ORDER BY seq", (doc_id,))
    if not rows:
        raise HTTPException(404, "document not found")
    return "\n\n".join(r["text"] for r in rows)


def answer(question: str, doc_id: Optional[int] = None) -> Dict[str, Any]:
    hits = top_k(question, _chunks(doc_id), k=4)
    if not hits:
        raise HTTPException(404, "no documents ingested yet")
    context = "\n\n".join(f"[chunk {cid}] {text}" for cid, text, _ in hits)
    llm = llmutil.ask(
        f"Answer using ONLY the excerpts below; cite the [chunk N] ids you used.\n\n"
        f"{context}\n\nQUESTION: {question}")
    if llm:
        return {"answer": llm, "mode": "llm",
                "citations": [{"chunk": cid, "score": round(s, 3)} for cid, _, s in hits]}
    # Extractive fallback: most question-relevant sentences from the top chunks.
    qv = embed(question)
    best = sorted(((cosine(qv, embed(s)), cid, s)
                   for cid, text, _ in hits for s in sentences(text)), reverse=True)[:3]
    return {"answer": " ".join(f"{s} [chunk {cid}]" for _, cid, s in best),
            "mode": "extractive",
            "citations": [{"chunk": cid, "score": round(sc, 3)} for cid, _, sc in hits]}


def flashcards(doc_id: int, count: int = 8) -> List[Dict[str, str]]:
    text = _doc_text(doc_id)
    llm = llmutil.ask(f"Create {count} flashcards (Q:/A: pairs, one line each) from:\n\n"
                      f"{text[:6000]}")
    if llm:
        cards = re.findall(r"Q[:.]\s*(.+?)\s*\n\s*A[:.]\s*(.+)", llm)
        if cards:
            return [{"q": q.strip(), "a": a.strip()} for q, a in cards[:count]]
    # Heuristic: definition-shaped sentences become "What is X?" cards.
    cards = []
    for s in sentences(text):
        m = re.match(r"^([A-Z][A-Za-z0-9 \-]{2,40}?)\s+(?:is|are|means|refers to)\s+(.{20,200})",
                     s)
        if m:
            cards.append({"q": f"What is {m.group(1).strip()}?", "a": s})
        if len(cards) >= count:
            break
    return cards


def compare(doc_a: int, doc_b: int) -> Dict[str, Any]:
    ta, tb = _doc_text(doc_a), _doc_text(doc_b)
    tok_a, tok_b = set(tokenize(ta)), set(tokenize(tb))
    llm = llmutil.ask("Compare these two documents: methods, findings, disagreements. "
                      f"Be concrete.\n\nDOC A:\n{ta[:4000]}\n\nDOC B:\n{tb[:4000]}")
    return {"similarity": round(cosine(embed(ta[:8000]), embed(tb[:8000])), 3),
            "shared_terms": sorted(tok_a & tok_b, key=len, reverse=True)[:25],
            "only_in_a": sorted(tok_a - tok_b, key=len, reverse=True)[:15],
            "only_in_b": sorted(tok_b - tok_a, key=len, reverse=True)[:15],
            "llm_comparison": llm}


# ------------------------------- REST API ---------------------------------- #
router = APIRouter(prefix="/api/research", tags=["Research"])


@router.post("/docs")
def add_doc(body: DocIn) -> dict:
    text, kind, source = body.text, "text", ""
    if not text and body.path:
        try:
            text = extract_text(body.path)
            kind, source = "file", body.path
        except (FileNotFoundError, RuntimeError) as e:
            raise HTTPException(422, str(e))
    if not text or not text.strip():
        raise HTTPException(422, "provide 'text' or a readable 'path'")
    doc_id = ingest(body.title, text, kind, source)
    n = db.one("SELECT COUNT(*) AS n FROM doc_chunks WHERE doc_id=?", (doc_id,))["n"]
    return {"id": doc_id, "title": body.title, "chunks": n}


@router.put("/docs/upload")
async def upload_doc(request: Request, title: str = "") -> dict:
    """Raw-body document upload (PDF/DOCX/HTML/TXT/MD): the file is saved, its
    text extracted, chunked and embedded — ready for /ask, /summary, /analyze."""
    body = await request.body()
    if not body:
        raise HTTPException(422, "empty body — send the file as the request body")
    name = Path(title).name or "upload.txt"
    dest = db.data_dir() / "research"
    dest.mkdir(exist_ok=True)
    path = dest / name
    path.write_bytes(body)
    try:
        text = extract_text(str(path))
    except RuntimeError as e:
        raise HTTPException(422, str(e))
    if not text.strip():
        raise HTTPException(422, f"no extractable text in {name}")
    doc_id = ingest(Path(name).stem, text, "file", str(path))
    n = db.one("SELECT COUNT(*) AS n FROM doc_chunks WHERE doc_id=?", (doc_id,))["n"]
    return {"id": doc_id, "title": Path(name).stem, "chunks": n, "chars": len(text)}


@router.get("/docs")
def list_docs() -> list:
    return db.query(
        "SELECT d.id, d.title, d.kind, d.created_at, COUNT(c.id) AS chunks FROM docs d"
        " LEFT JOIN doc_chunks c ON c.doc_id=d.id GROUP BY d.id ORDER BY d.id")


@router.post("/ask")
def ask_docs(body: AskIn) -> dict:
    return answer(body.question, body.doc_id)


@router.get("/docs/{doc_id}/summary")
def summarize(doc_id: int) -> dict:
    text = _doc_text(doc_id)
    llm = llmutil.ask(f"Summarize this document in one tight paragraph plus 3-6 bullet "
                      f"key findings:\n\n{text[:8000]}")
    return {"summary": llm or extractive_summary(text),
            "mode": "llm" if llm else "extractive"}


@router.get("/docs/{doc_id}/notes")
def notes(doc_id: int) -> dict:
    """Structured notes: an outline from the document's own signposts."""
    text = _doc_text(doc_id)
    headings = [ln.strip() for ln in text.splitlines()
                if re.match(r"^(#+\s|\d+[\.\)]\s|[A-Z][A-Z &\-]{4,60}$)", ln.strip())][:30]
    return {"outline": headings, "key_points": extractive_summary(text, 8).split(". ")}


@router.get("/docs/{doc_id}/flashcards")
def get_flashcards(doc_id: int, count: int = 8) -> list:
    return flashcards(doc_id, count)


@router.get("/docs/{doc_id}/citations")
def citations(doc_id: int) -> dict:
    """References the document itself cites (heuristic: bracketed + author-year)."""
    text = _doc_text(doc_id)
    numbered = re.findall(r"\[(\d{1,3})\]\s*([A-Z][^\n\[]{15,160})", text)
    author_year = re.findall(r"\(([A-Z][A-Za-z\-]+(?: et al\.?)?),?\s+(19|20)\d{2}\)", text)
    return {"numbered": [{"n": n, "ref": r.strip()} for n, r in numbered[:50]],
            "author_year": sorted({f"{a} {y}" for a, (y) in
                                   [(m[0], m[1]) for m in author_year]})[:50]}


@router.get("/compare")
def compare_docs(a: int, b: int) -> dict:
    return compare(a, b)


@router.post("/deep")
def deep_research(body: dict) -> dict:
    """Deep research a question: web-search it, fetch + read the top pages, then
    synthesize a cited answer. Real sources, not just what's already uploaded."""
    question = (body.get("question") or body.get("query") or "").strip()
    if not question:
        raise HTTPException(422, "question is required")
    from ..core.websearch import search
    from .webauto import fetch
    from ..core.text import strip_html
    results = search(question, limit=int(body.get("sources", 5)),
                     scholarly=bool(body.get("scholarly", True)))
    if not results:
        raise HTTPException(502, "no web results — check connectivity")
    passages = []
    for r in results:
        text = r.get("snippet") or ""
        if not text and r["url"].startswith("http"):
            try:
                text = strip_html(fetch(r["url"]))[:2500]
            except Exception:
                text = ""
        if text:
            passages.append((r, text))
    context = "\n\n".join(f"[{i+1}] {r['title']} ({r['url']})\n{t[:1500]}"
                          for i, (r, t) in enumerate(passages))
    llm = llmutil.ask(
        f"Research question: {question}\n\nUsing ONLY these sources, write a thorough, "
        f"cited answer (use [n]); note any disagreements between sources.\n\n{context}",
        system="You are a rigorous research assistant. Cite sources as [n]; never invent facts.")
    return {"question": question,
            "answer": llm or "No model reachable — sources below.",
            "mode": "llm" if llm else "sources_only",
            "sources": [{"n": i + 1, "title": r["title"], "url": r["url"],
                         "source": r["source"]} for i, (r, _) in enumerate(passages)]}


# ------- document analyzer (ported from the author's vergabepilot-ai) -------- #
# German day-first DD.MM.YYYY and ISO YYYY-MM-DD, optional ", HH:MM[:SS] Uhr".
_DMY = re.compile(r"\b(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{2,4})"
                  r"(?:[,\sT]+(?:um\s+)?(\d{1,2}):(\d{2})(?::(\d{2}))?)?")
_ISO = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})"
                  r"(?:[,\sT]+(\d{1,2}):(\d{2})(?::(\d{2}))?)?")
_MONEY = re.compile(r"(?:€\s?|EUR\s?)(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})?)"
                    r"|(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})?)\s?(?:€|EUR)")
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b")
_PHONE = re.compile(r"(?:\+\d{1,3}[\s\-/]?)?(?:\(?\d{2,5}\)?[\s\-/]?)\d{3,}[\s\-/]?\d{2,}")
_REQ_WORDS = re.compile(r"\b(must|shall|required|mandatory|muss|müssen|zwingend|"
                        r"erforderlich|verpflichtend|spätestens|deadline|frist)\b", re.I)


def parse_deadline_dates(text: str) -> List[Dict[str, Any]]:
    """All recognizable dates, parsed. No time → end-of-day (a deadline due
    'today' stays open until midnight, not expired at 00:00) — vergabepilot's rule."""
    from datetime import datetime
    found = []
    for rx, order in ((_ISO, "ymd"), (_DMY, "dmy")):
        for m in rx.finditer(text):
            try:
                if order == "ymd":
                    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
                else:
                    d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
                    if y < 100:
                        y += 2000
                hh = int(m.group(4)) if m.group(4) else 23
                mm = int(m.group(5)) if m.group(5) else 59
                ss = int(m.group(6)) if m.group(6) else (0 if m.group(4) else 59)
                dt = datetime(y, mo, d, hh, mm, ss)
            except ValueError:
                continue
            found.append({"raw": m.group(0).strip(), "parsed": dt.isoformat(),
                          "is_future": dt > datetime.now()})
    seen, unique = set(), []
    for f in found:
        if f["parsed"] not in seen:
            seen.add(f["parsed"])
            unique.append(f)
    return unique[:30]


@router.get("/docs/{doc_id}/analyze")
def analyze_document(doc_id: int) -> dict:
    """Field extraction for contracts/tenders/specs: deadlines (German + ISO
    formats), money amounts, contacts, and requirement sentences (must/shall/
    muss/erforderlich...). Pure regex — no model needed, works offline."""
    text = _doc_text(doc_id)
    deadlines = parse_deadline_dates(text)
    requirements = [s for s in sentences(text) if _REQ_WORDS.search(s)][:25]
    amounts = []
    for m in _MONEY.finditer(text):
        amounts.append((m.group(1) or m.group(2)) + " EUR")
    upcoming = sorted((d for d in deadlines if d["is_future"]), key=lambda d: d["parsed"])
    return {"deadlines": deadlines,
            "next_deadline": upcoming[0] if upcoming else None,
            "amounts": amounts[:15],
            "contacts": {"emails": sorted(set(_EMAIL.findall(text)))[:10],
                         "phones": [p.strip() for p in _PHONE.findall(text)][:5]},
            "requirements": requirements}
