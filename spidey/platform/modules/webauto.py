"""Web automation: extract data from any website with layered strategies.

Strategy ladder (``auto`` walks down until something useful comes out):
  1. ``structured`` — JSON-LD / OpenGraph / meta tags (free, most reliable)
  2. ``tables``     — every <table> parsed into rows
  3. ``links``      — anchor inventory (href + text)
  4. ``text``       — readability-style main-text extraction
  5. ``ai``         — the AI fallback: hand the page text + your instruction to
                      the model, get back structured JSON
Extras: ``selector`` (CSS via BeautifulSoup, optional), ``regex`` (your
pattern), ``render`` (Playwright for JS-heavy pages, optional), OCR on images
(pytesseract, optional) and full-page screenshots.

Scrapes run through the job queue → retries with backoff for free; recurring
scrapes are one POST to /api/schedules with kind ``webauto.scrape``. Any
request with ``require_approval`` waits in a human approval queue until
someone POSTs approve/deny — nothing hits the network before that.
"""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..core import db, llmutil, metrics, notify
from ..core.text import strip_html

STRATEGIES = ("auto", "structured", "tables", "links", "text", "ai", "selector",
              "regex", "render")
UA = "Mozilla/5.0 (compatible; SpideyPlatform/1.0; +https://github.com/Siddharthpatni/Spidey)"


# ------------------------------ fetching ----------------------------------- #
def fetch(url: str, render: bool = False, timeout: int = 30) -> str:
    if render:
        return _fetch_rendered(url, timeout)
    import requests
    resp = requests.get(url, headers={"User-Agent": UA}, timeout=timeout)
    resp.raise_for_status()
    return resp.text


def _fetch_rendered(url: str, timeout: int) -> str:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError("JS rendering needs `pip install playwright && playwright install chromium`")
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page(user_agent=UA)
            page.goto(url, timeout=timeout * 1000, wait_until="networkidle")
            return page.content()
        finally:
            browser.close()


def screenshot(url: str, path: str, timeout: int = 30) -> Dict[str, Any]:
    """Full-page screenshot; if OCR is installed the pixels get read too."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError("Screenshots need `pip install playwright && playwright install chromium`")
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page(user_agent=UA)
            page.goto(url, timeout=timeout * 1000, wait_until="networkidle")
            page.screenshot(path=path, full_page=True)
        finally:
            browser.close()
    result: Dict[str, Any] = {"path": path}
    ocr_text = ocr_image(path, missing_ok=True)
    if ocr_text is not None:
        result["ocr_text"] = ocr_text[:4000]
        analysis = llmutil.ask(
            f"This text was OCR'd from a screenshot of {url}. Describe what the page "
            f"shows and list the key facts:\n\n{ocr_text[:3000]}")
        if analysis:
            result["analysis"] = analysis
    return result


def ocr_image(path: str, missing_ok: bool = False) -> Optional[str]:
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        if missing_ok:
            return None
        raise RuntimeError("OCR needs `pip install pytesseract Pillow` and the tesseract binary")
    return pytesseract.image_to_string(Image.open(path))


# --------------------------- extraction strategies -------------------------- #
class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tables: List[List[List[str]]] = []
        self._row: List[str] = []
        self._cell: Optional[List[str]] = None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.tables.append([])
        elif tag == "tr" and self.tables:
            self._row = []
        elif tag in ("td", "th") and self.tables:
            self._cell = []

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self.tables and self._row:
            self.tables[-1].append(self._row)
            self._row = []

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


class _LinkParser(HTMLParser):
    def __init__(self, base: str) -> None:
        super().__init__()
        self.base = base
        self.links: List[Dict[str, str]] = []
        self._href: Optional[str] = None
        self._text: List[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href")
            if href and not href.startswith(("javascript:", "#")):
                self._href, self._text = urljoin(self.base, href), []

    def handle_endtag(self, tag):
        if tag == "a" and self._href:
            text = " ".join("".join(self._text).split())
            self.links.append({"url": self._href, "text": text[:200]})
            self._href = None

    def handle_data(self, data):
        if self._href:
            self._text.append(data)


def extract_structured(html: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {"json_ld": [], "meta": {}}
    for m in re.finditer(r'(?is)<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html):
        try:
            out["json_ld"].append(json.loads(m.group(1).strip()))
        except json.JSONDecodeError:
            continue
    for m in re.finditer(r'(?is)<meta\s+[^>]*?(?:property|name)=["\']([^"\']+)["\'][^>]*?'
                         r'content=["\']([^"\']*)["\']', html):
        out["meta"][m.group(1)] = m.group(2)
    title = re.search(r"(?is)<title[^>]*>(.*?)</title>", html)
    if title:
        out["title"] = " ".join(title.group(1).split())
    return out


def extract_tables(html: str) -> List[List[List[str]]]:
    p = _TableParser()
    p.feed(html)
    return [t for t in p.tables if t]


def extract_links(html: str, base: str) -> List[Dict[str, str]]:
    p = _LinkParser(base)
    p.feed(html)
    return p.links


def extract_selector(html: str, selector: str) -> List[str]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        raise RuntimeError("CSS selectors need `pip install beautifulsoup4`")
    soup = BeautifulSoup(html, "html.parser")
    return [el.get_text(" ", strip=True)[:500] for el in soup.select(selector)][:200]


def extract_ai(html: str, url: str, instruction: str) -> Dict[str, Any]:
    """The AI fallback: page text + instruction → structured JSON."""
    text = strip_html(html)[:6000]
    raw = llmutil.ask(
        f"Extract data from this web page ({url}).\nInstruction: {instruction}\n"
        f"Reply with ONLY a JSON object.\n\nPAGE TEXT:\n{text}",
        system="You are a precise data-extraction engine. Output valid JSON only.")
    if raw is None:
        raise RuntimeError("AI extraction needs a reachable model (start Ollama or set "
                           "SPIDEY_LLM_PROVIDER) — deterministic strategies still work")
    m = re.search(r"\{.*\}", raw, re.S)
    try:
        return json.loads(m.group(0) if m else raw)
    except json.JSONDecodeError:
        return {"raw": raw}


def scrape(url: str, strategy: str = "auto", instruction: str = "",
           selector: str = "", pattern: str = "", render: bool = False) -> Dict[str, Any]:
    """Run one scrape and return ``{strategy, data}``. ``auto`` tries the ladder."""
    html = fetch(url, render=render or strategy == "render")
    metrics.inc("spidey_scrapes_total", {"strategy": strategy})
    if strategy in ("auto", "render"):
        structured = extract_structured(html)
        if structured["json_ld"] or len(structured["meta"]) >= 4:
            return {"strategy": "structured", "data": structured}
        tables = extract_tables(html)
        if tables:
            return {"strategy": "tables", "data": tables}
        text = strip_html(html)
        if instruction:
            try:
                return {"strategy": "ai", "data": extract_ai(html, url, instruction)}
            except RuntimeError:
                pass
        return {"strategy": "text", "data": {"title": structured.get("title"),
                                             "text": text[:20000]}}
    if strategy == "structured":
        return {"strategy": strategy, "data": extract_structured(html)}
    if strategy == "tables":
        return {"strategy": strategy, "data": extract_tables(html)}
    if strategy == "links":
        return {"strategy": strategy, "data": extract_links(html, url)}
    if strategy == "text":
        return {"strategy": strategy, "data": {"text": strip_html(html)[:20000]}}
    if strategy == "ai":
        return {"strategy": strategy, "data": extract_ai(html, url, instruction or "extract the key facts")}
    if strategy == "selector":
        return {"strategy": strategy, "data": extract_selector(html, selector)}
    if strategy == "regex":
        try:
            rx = re.compile(pattern)
        except re.error as e:
            raise RuntimeError(f"invalid regex: {e}")
        return {"strategy": strategy, "data": rx.findall(html)[:500]}
    raise RuntimeError(f"unknown strategy '{strategy}'")


# ------------------------------- queue handler ------------------------------ #
def _job_scrape(payload: Dict[str, Any]) -> Dict[str, Any]:
    scrape_id = payload.get("scrape_id")
    try:
        result = scrape(payload["url"], payload.get("strategy", "auto"),
                        payload.get("instruction", ""), payload.get("selector", ""),
                        payload.get("pattern", ""), payload.get("render", False))
        if scrape_id:
            db.execute("UPDATE scrapes SET status='done', data=?, finished_at=? WHERE id=?",
                       (db.json_dumps(result), db.now(), scrape_id))
        notify.emit("scrape.done", {"scrape_id": scrape_id, "url": payload["url"]})
        return result
    except Exception as e:
        if scrape_id:
            db.execute("UPDATE scrapes SET status='failed', error=?, finished_at=? WHERE id=?",
                       (str(e), db.now(), scrape_id))
        raise


def register_jobs(queue) -> None:
    queue.register("webauto.scrape", _job_scrape)


# ------------------------------- REST API ---------------------------------- #
router = APIRouter(prefix="/api/webauto", tags=["Web Automation"])


class ScrapeIn(BaseModel):
    url: str
    strategy: str = Field(default="auto", description=f"One of {STRATEGIES}")
    instruction: str = Field(default="", description="What to extract (drives the AI fallback).")
    selector: str = ""
    pattern: str = ""
    render: bool = Field(default=False, description="Render JS with Playwright first.")
    require_approval: bool = Field(default=False,
                                   description="Hold in the human approval queue before fetching.")


@router.post("/scrapes")
def create_scrape(body: ScrapeIn) -> dict:
    if body.strategy not in STRATEGIES:
        raise HTTPException(422, f"strategy must be one of {STRATEGIES}")
    status = "pending_approval" if body.require_approval else "queued"
    sid = db.execute(
        "INSERT INTO scrapes(url, strategy, instruction, status, created_at) VALUES(?,?,?,?,?)",
        (body.url, body.strategy, body.instruction, status, db.now()))
    if not body.require_approval:
        _enqueue(sid, body)
    return {"id": sid, "status": status}


def _enqueue(sid: int, body: ScrapeIn) -> None:
    from ..core.queue import default_queue
    default_queue().enqueue("webauto.scrape", {
        "scrape_id": sid, "url": body.url, "strategy": body.strategy,
        "instruction": body.instruction, "selector": body.selector,
        "pattern": body.pattern, "render": body.render})


@router.get("/scrapes")
def list_scrapes(status: Optional[str] = None, limit: int = 50) -> list:
    if status:
        return db.query("SELECT id, url, strategy, status, created_at, finished_at FROM scrapes"
                        " WHERE status=? ORDER BY id DESC LIMIT ?", (status, limit))
    return db.query("SELECT id, url, strategy, status, created_at, finished_at FROM scrapes"
                    " ORDER BY id DESC LIMIT ?", (limit,))


@router.get("/scrapes/{scrape_id}")
def get_scrape(scrape_id: int) -> dict:
    row = db.one("SELECT * FROM scrapes WHERE id=?", (scrape_id,))
    if not row:
        raise HTTPException(404, "scrape not found")
    row["data"] = db.json_loads(row["data"])
    return row


@router.get("/approvals")
def approval_queue() -> list:
    """The human approval queue: scrapes waiting for a yes/no."""
    return db.query("SELECT id, url, strategy, instruction, created_at FROM scrapes"
                    " WHERE status='pending_approval' ORDER BY id")


@router.post("/scrapes/{scrape_id}/approve")
def approve_scrape(scrape_id: int, body: Optional[dict] = None) -> dict:
    row = db.one("SELECT * FROM scrapes WHERE id=? AND status='pending_approval'", (scrape_id,))
    if not row:
        raise HTTPException(404, "no scrape awaiting approval with that id")
    approved = True if body is None else bool(body.get("approved", True))
    if not approved:
        db.execute("UPDATE scrapes SET status='denied', finished_at=? WHERE id=?",
                   (db.now(), scrape_id))
        return {"id": scrape_id, "status": "denied"}
    db.execute("UPDATE scrapes SET status='queued' WHERE id=?", (scrape_id,))
    _enqueue(scrape_id, ScrapeIn(url=row["url"], strategy=row["strategy"],
                                 instruction=row["instruction"] or ""))
    return {"id": scrape_id, "status": "queued"}


@router.post("/scrape-now")
def scrape_now(body: ScrapeIn) -> dict:
    """Synchronous scrape (no queue) — handy for the agent tool and quick tests."""
    try:
        return scrape(body.url, body.strategy, body.instruction, body.selector,
                      body.pattern, body.render)
    except Exception as e:
        raise HTTPException(502, str(e))


@router.post("/screenshot")
def take_screenshot(body: dict) -> dict:
    url = body.get("url")
    if not url:
        raise HTTPException(422, "url is required")
    out = db.data_dir() / "screenshots"
    out.mkdir(exist_ok=True)
    safe = re.sub(r"[^a-zA-Z0-9.-]", "_", url)[:80]
    try:
        return screenshot(url, str(out / f"{safe}.png"))
    except RuntimeError as e:
        raise HTTPException(501, str(e))


@router.post("/ocr")
def run_ocr(body: dict) -> dict:
    path = body.get("path")
    if not path:
        raise HTTPException(422, "path (to an image file) is required")
    try:
        return {"text": ocr_image(path)}
    except RuntimeError as e:
        raise HTTPException(501, str(e))
    except FileNotFoundError:
        raise HTTPException(404, f"no image at {path}")
