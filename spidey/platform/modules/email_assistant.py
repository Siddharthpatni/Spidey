"""Email assistant: sync a mailbox (IMAP — Gmail works with an app password),
auto-categorize, predict priority, draft smart replies, suggest calendar events
and answer questions over your mail with RAG.

Privacy follows Spidey's rules: credentials are used for the one sync call and
never stored; message bodies live only in the local SQLite file. Offline demo
path: POST raw .eml text to /import — every downstream feature works the same.
Categories come from transparent keyword rules with an LLM upgrade when a model
is up; priority is a scored heuristic (deadline words, direct questions,
sender's history, thread heat).
"""

from __future__ import annotations

import email
import email.utils
import imaplib
import re
from datetime import datetime, timedelta
from email.header import decode_header
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..core import db, llmutil
from ..core.text import embed, top_k

CATEGORY_RULES = [
    ("meeting",    r"\b(meeting|calendar|invite|zoom|teams|schedule|call at|termin)\b"),
    ("billing",    r"\b(invoice|payment|receipt|billing|rechnung|due|overdue|paypal)\b"),
    ("recruiting", r"\b(interview|application|position|recruiter|bewerbung|resume|cv)\b"),
    ("newsletter", r"\b(unsubscribe|newsletter|digest|weekly update|view in browser)\b"),
    ("security",   r"\b(verification code|password reset|2fa|sign-?in attempt|otp)\b"),
    ("shipping",   r"\b(shipped|tracking|delivery|paket|order .*(confirm|dispatch))\b"),
]
URGENT_WORDS = r"\b(urgent|asap|today|tomorrow|deadline|eod|immediately|wichtig|dringend)\b"


class SyncIn(BaseModel):
    host: str = Field(examples=["imap.gmail.com"])
    user: str
    password: str = Field(description="Used for this sync only — never stored.")
    folder: str = "INBOX"
    limit: int = Field(default=25, le=200)


class ImportIn(BaseModel):
    raw: str = Field(description="A raw RFC-822 message (.eml contents).")
    folder: str = "imported"


# ------------------------------- ingestion ---------------------------------- #
def _decode(value: Optional[str]) -> str:
    if not value:
        return ""
    parts = []
    for chunk, enc in decode_header(value):
        parts.append(chunk.decode(enc or "utf-8", "replace")
                     if isinstance(chunk, bytes) else chunk)
    return "".join(parts)


def _body_text(msg: email.message.Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode(part.get_content_charset() or "utf-8", "replace")
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                from ..core.text import strip_html
                payload = part.get_payload(decode=True)
                if payload:
                    return strip_html(payload.decode(part.get_content_charset() or "utf-8",
                                                     "replace"))
        return ""
    payload = msg.get_payload(decode=True)
    return payload.decode(msg.get_content_charset() or "utf-8", "replace") if payload else ""


def categorize(subject: str, body: str) -> str:
    text = f"{subject}\n{body[:2000]}".lower()
    for cat, pattern in CATEGORY_RULES:
        if re.search(pattern, text):
            return cat
    llm = llmutil.ask(f"Categorize this email as one word from: meeting, billing, recruiting,"
                      f" newsletter, security, shipping, personal, work, other.\n\n"
                      f"Subject: {subject}\n{body[:1000]}")
    if llm:
        word = llm.strip().split()[0].lower().strip(".,")
        if word in {"meeting", "billing", "recruiting", "newsletter", "security",
                    "shipping", "personal", "work", "other"}:
            return word
    return "other"


def priority_score(sender: str, subject: str, body: str) -> float:
    """0–1: how soon this needs a human."""
    text = f"{subject}\n{body[:2000]}".lower()
    score = 0.2
    if re.search(URGENT_WORDS, text):
        score += 0.35
    if "?" in body[:1500]:
        score += 0.15
    if re.search(r"\b(re:|aw:)", subject.lower()):
        score += 0.1  # ongoing thread
    known = db.one("SELECT COUNT(*) AS n FROM emails WHERE sender=?", (sender,))
    if known and known["n"] > 2:
        score += 0.1  # frequent correspondent
    if re.search(r"\bunsubscribe\b", text):
        score -= 0.25
    return round(max(0.0, min(1.0, score)), 2)


def store_message(raw_bytes: bytes, folder: str, uid: str) -> Optional[int]:
    msg = email.message_from_bytes(raw_bytes)
    sender = _decode(msg.get("From"))
    subject = _decode(msg.get("Subject"))
    date = msg.get("Date", "")
    body = _body_text(msg)[:20000]
    if db.one("SELECT id FROM emails WHERE uid=? AND folder=?", (uid, folder)):
        return None
    return db.execute(
        "INSERT INTO emails(uid, folder, sender, subject, date, body, category, priority,"
        " vec, created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (uid, folder, sender, subject, date, body, categorize(subject, body),
         priority_score(sender, subject, body),
         db.json_dumps(embed(f"{subject}\n{body[:3000]}")), db.now()))


def sync_imap(cfg: SyncIn) -> Dict[str, Any]:
    try:
        conn = imaplib.IMAP4_SSL(cfg.host, timeout=30)
        conn.login(cfg.user, cfg.password)
    except (imaplib.IMAP4.error, OSError) as e:
        raise HTTPException(502, f"IMAP connection failed: {e}")
    try:
        conn.select(cfg.folder, readonly=True)
        _, data = conn.search(None, "ALL")
        uids = data[0].split()[-cfg.limit:]
        new = 0
        for uid in uids:
            _, msg_data = conn.fetch(uid, "(RFC822)")
            if msg_data and msg_data[0]:
                if store_message(msg_data[0][1], cfg.folder, uid.decode()):
                    new += 1
        return {"synced": len(uids), "new": new, "folder": cfg.folder}
    finally:
        try:
            conn.logout()
        except Exception:
            pass


# ------------------------------- calendar ------------------------------------ #
DATE_PATTERNS = [
    (r"\b(\d{4}-\d{2}-\d{2})(?:[ T]|\s+(?:at|um)\s+)(\d{1,2}):(\d{2})", "%Y-%m-%d"),
    (r"\b(\d{1,2}[./]\d{1,2}[./]\d{4})\s+(?:(?:at|um)\s+)?(\d{1,2}):(\d{2})", "%d.%m.%Y"),
]


def calendar_suggestions(subject: str, body: str) -> List[Dict[str, str]]:
    found = []
    for pattern, datefmt in DATE_PATTERNS:
        for m in re.finditer(pattern, body[:4000]):
            try:
                day = datetime.strptime(m.group(1).replace("/", "."), datefmt)
                start = day.replace(hour=int(m.group(2)), minute=int(m.group(3)))
            except ValueError:
                continue
            end = start + timedelta(hours=1)
            stamp = "%Y%m%dT%H%M%S"
            found.append({
                "title": subject[:80] or "Meeting", "start": start.isoformat(),
                "ics": ("BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//Spidey//EN\nBEGIN:VEVENT\n"
                        f"DTSTART:{start.strftime(stamp)}\nDTEND:{end.strftime(stamp)}\n"
                        f"SUMMARY:{subject[:80]}\nEND:VEVENT\nEND:VCALENDAR")})
    return found[:5]


# ------------------------------- REST API ---------------------------------- #
router = APIRouter(prefix="/api/email", tags=["Email Assistant"])


@router.post("/sync")
def api_sync(body: SyncIn) -> dict:
    return sync_imap(body)


@router.post("/import")
def api_import(body: ImportIn) -> dict:
    uid = str(abs(hash(body.raw)) % 10**12)
    eid = store_message(body.raw.encode(), body.folder, uid)
    if eid is None:
        return {"id": None, "note": "duplicate — already imported"}
    row = db.one("SELECT category, priority FROM emails WHERE id=?", (eid,))
    return {"id": eid, **row}


@router.get("/messages")
def list_messages(category: Optional[str] = None, limit: int = 50) -> list:
    base = ("SELECT id, sender, subject, date, category, priority FROM emails "
            "{} ORDER BY priority DESC, id DESC LIMIT ?")
    if category:
        return db.query(base.format("WHERE category=?"), (category, limit))
    return db.query(base.format(""), (limit,))


@router.get("/messages/{email_id}")
def get_message(email_id: int) -> dict:
    row = db.one("SELECT id, sender, subject, date, body, category, priority FROM emails"
                 " WHERE id=?", (email_id,))
    if not row:
        raise HTTPException(404, "email not found")
    return row


@router.post("/messages/{email_id}/reply")
def smart_reply(email_id: int, body: Optional[dict] = None) -> dict:
    row = db.one("SELECT * FROM emails WHERE id=?", (email_id,))
    if not row:
        raise HTTPException(404, "email not found")
    tone = (body or {}).get("tone", "friendly, concise")
    llm = llmutil.ask(f"Draft a {tone} reply to this email. Just the reply body.\n\n"
                      f"From: {row['sender']}\nSubject: {row['subject']}\n\n{row['body'][:3000]}")
    templates = {
        "meeting": "Thanks for the invite — that time works for me. See you then!",
        "recruiting": ("Thank you for reaching out. I'd be glad to talk — could you share "
                       "a few time slots that work on your side?"),
        "billing": "Thanks — confirming I've received this. I'll process it shortly.",
    }
    return {"draft": llm or templates.get(row["category"],
                                          "Thanks for your email — I'll get back to you shortly."),
            "mode": "llm" if llm else "template"}


@router.get("/messages/{email_id}/calendar")
def api_calendar(email_id: int) -> list:
    row = db.one("SELECT subject, body FROM emails WHERE id=?", (email_id,))
    if not row:
        raise HTTPException(404, "email not found")
    return calendar_suggestions(row["subject"] or "", row["body"] or "")


@router.post("/ask")
def ask_mail(body: dict) -> dict:
    question = body.get("question", "").strip()
    if not question:
        raise HTTPException(422, "question is required")
    rows = db.query("SELECT id, subject||'\n'||body AS text, vec FROM emails")
    if not rows:
        raise HTTPException(404, "no emails synced or imported yet")
    hits = top_k(question, [(r["id"], r["text"][:2000], db.json_loads(r["vec"], []))
                            for r in rows], 4)
    context = "\n\n---\n\n".join(f"[email {eid}] {text}" for eid, text, _ in hits)
    llm = llmutil.ask(f"Answer from these emails only; cite [email N].\n\n{context}\n\n"
                      f"QUESTION: {question}")
    return {"answer": llm or "No model reachable — closest emails below.",
            "mode": "llm" if llm else "retrieval_only",
            "sources": [{"email": eid, "score": round(s, 3)} for eid, _, s in hits]}
