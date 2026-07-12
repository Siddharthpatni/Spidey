"""Text + vector utilities shared by every RAG-flavored module.

Embeddings are hashed TF vectors (the "hashing trick"): tokenize, hash each
token into a fixed number of buckets, log-weight the counts, L2-normalize.
No model download, deterministic, fast — and cosine similarity over them is
plenty for ranking resumes against jobs or retrieving chunks. If
``sentence-transformers`` is installed we upgrade to real embeddings
automatically; nothing else changes because both sides go through
:func:`embed` / :func:`cosine`.
"""

from __future__ import annotations

import math
import re
import zlib
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

DIM = 384

STOPWORDS = frozenset("""a an and are as at be by for from has have i in is it its of on or
that the this to was were will with you your we our they he she them his her not no do does
did been being than then there their so if but about into over under up down out own same
""".split())

_st_model = None
_st_checked = False


def tokenize(text: str) -> List[str]:
    return [t for t in re.findall(r"[a-zA-Z][a-zA-Z0-9+#.\-]{1,30}", text.lower())
            if t not in STOPWORDS]


def _sentence_transformer():
    global _st_model, _st_checked
    if not _st_checked:
        _st_checked = True
        try:
            from sentence_transformers import SentenceTransformer
            _st_model = SentenceTransformer("all-MiniLM-L6-v2")
        except Exception:
            _st_model = None
    return _st_model


def embed(text: str) -> List[float]:
    model = _sentence_transformer()
    if model is not None:
        return [float(x) for x in model.encode(text[:4000])]
    vec = [0.0] * DIM
    for tok in tokenize(text):
        vec[zlib.crc32(tok.encode()) % DIM] += 1.0
    vec = [math.log1p(v) for v in vec]
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def match_score(sim: float) -> int:
    """Map cosine (~0.2–0.7 typical) to a friendly 0–100 scale (ported from jobflow)."""
    return max(0, min(100, round(sim * 140)))


def chunk_text(text: str, size: int = 1200, overlap: int = 150) -> List[str]:
    """Paragraph-aware chunks of roughly ``size`` chars with a little overlap."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: List[str] = []
    buf = ""
    for p in paras:
        if len(buf) + len(p) + 2 <= size:
            buf = f"{buf}\n\n{p}" if buf else p
            continue
        if buf:
            chunks.append(buf)
        while len(p) > size:  # single huge paragraph — hard split
            chunks.append(p[:size])
            p = p[size - overlap:]
        buf = p
    if buf:
        chunks.append(buf)
    return chunks


def top_k(query: str, rows: Sequence[Tuple[int, str, Sequence[float]]],
          k: int = 5) -> List[Tuple[int, str, float]]:
    """Rank ``(id, text, vec)`` rows against a query; returns (id, text, score)."""
    qv = embed(query)
    scored = [(rid, text, cosine(qv, vec)) for rid, text, vec in rows]
    scored.sort(key=lambda x: x[2], reverse=True)
    return scored[:k]


def sentences(text: str) -> List[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if len(s.strip()) > 20]


def extractive_summary(text: str, max_sentences: int = 6) -> str:
    """Classic frequency-based summarizer — the zero-model fallback."""
    sents = sentences(text)
    if len(sents) <= max_sentences:
        return " ".join(sents)
    freq: dict = {}
    for tok in tokenize(text):
        freq[tok] = freq.get(tok, 0) + 1
    scored = sorted(
        ((sum(freq.get(t, 0) for t in tokenize(s)) / (len(tokenize(s)) or 1), i, s)
         for i, s in enumerate(sents)), reverse=True)[:max_sentences]
    return " ".join(s for _, _, s in sorted(scored, key=lambda x: x[1]))


# ------------------------- document text extraction ------------------------- #
def extract_text(path: str) -> str:
    """Best-effort text from txt/md/html/pdf/docx. PDF prefers pypdf, then PyMuPDF."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(path)
    suffix = p.suffix.lower()
    if suffix == ".pdf":
        return _pdf_text(p)
    if suffix == ".docx":
        return _docx_text(p)
    raw = p.read_text(errors="replace")
    if suffix in (".html", ".htm"):
        return strip_html(raw)
    return raw


def _pdf_text(p: Path) -> str:
    try:
        from pypdf import PdfReader
        return "\n\n".join((page.extract_text() or "") for page in PdfReader(str(p)).pages)
    except ImportError:
        pass
    try:
        import fitz  # PyMuPDF
        with fitz.open(str(p)) as doc:
            return "\n\n".join(page.get_text() for page in doc)
    except ImportError:
        raise RuntimeError("PDF support needs `pip install pypdf` (or PyMuPDF)")


def _docx_text(p: Path) -> str:
    import zipfile
    with zipfile.ZipFile(p) as z:
        xml = z.read("word/document.xml").decode(errors="replace")
    xml = re.sub(r"</w:p>", "\n\n", xml)
    return re.sub(r"<[^>]+>", "", xml)


def strip_html(html: str) -> str:
    html = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</h[1-6]>", "\n", html)
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"&nbsp;|&#160;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)
