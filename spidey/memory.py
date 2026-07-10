"""Spidey's long-term memory: what it knows about its person, across sessions.

A personal assistant that forgets you every run is a search box, not a friend.
This is a deliberately simple, deliberately local store: one markdown file of
dated one-line facts at ``~/.spidey/memory.md``. The agent reads it at the start
of every run (injected into the system prompt) and appends to it through the
``remember`` tool when the user shares something worth keeping.

Plain text on purpose: the user can open it, edit it, or delete lines — it's
*their* memory of themselves. Nothing here ever leaves the machine.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

MEMORY_FILE = Path.home() / ".spidey" / "memory.md"
KNOWLEDGE_DIR = Path.home() / ".spidey" / "knowledge"   # docs fed via `spidey learn`
LESSONS_FILE = Path.home() / ".spidey" / "lessons.md"   # what past mistakes taught it
MAX_INJECT_CHARS = 2500   # newest memories win if the file outgrows the prompt
MAX_FACT_CHARS = 300


def load_memories() -> str:
    """Memory block for the system prompt — newest lines kept if too long."""
    try:
        lines = [l for l in MEMORY_FILE.read_text().splitlines() if l.strip()]
    except OSError:
        return ""
    out: list[str] = []
    size = 0
    for line in reversed(lines):
        size += len(line) + 1
        if size > MAX_INJECT_CHARS:
            break
        out.append(line)
    return "\n".join(reversed(out))


def add_lesson(lesson: str) -> None:
    """Self-learning journal: when a run goes wrong and gets corrected, the
    correction is written down and injected into future runs. Mistakes teach."""
    lesson = " ".join(lesson.split())[:200]
    if not lesson:
        return
    LESSONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    existing = LESSONS_FILE.read_text() if LESSONS_FILE.exists() else ""
    if lesson.lower() in existing.lower():
        return
    with open(LESSONS_FILE, "a") as f:
        f.write(f"- [{date.today().isoformat()}] {lesson}\n")


def load_lessons(max_chars: int = 800) -> str:
    try:
        lines = [l for l in LESSONS_FILE.read_text().splitlines() if l.strip()]
    except OSError:
        return ""
    out: list[str] = []
    size = 0
    for line in reversed(lines):
        size += len(line) + 1
        if size > max_chars:
            break
        out.append(line)
    return "\n".join(reversed(out))


def search_knowledge(query: str, max_hits: int = 12) -> str:
    """Grep the personal knowledge base (docs fed via `spidey learn`, memories,
    lessons). Plain substring/word matching — offline, instant, no embeddings."""
    words = [w for w in query.lower().split() if len(w) > 2]
    if not words:
        return "ERROR: give a couple of meaningful words to search for."
    files = [MEMORY_FILE, LESSONS_FILE]
    if KNOWLEDGE_DIR.is_dir():
        files += sorted(p for p in KNOWLEDGE_DIR.rglob("*")
                        if p.suffix.lower() in (".md", ".txt") and p.is_file())
    hits: list[str] = []
    for path in files:
        try:
            for n, line in enumerate(path.read_text(errors="ignore").splitlines(), 1):
                lowered = line.lower()
                if any(w in lowered for w in words):
                    hits.append(f"{path.name}:{n}: {line.strip()[:160]}")
                    if len(hits) >= max_hits:
                        return "\n".join(hits)
        except OSError:
            continue
    return "\n".join(hits) if hits else (
        "No matches in the knowledge base. Feed documents with: spidey learn <file>")


def learn(source: str) -> str:
    """Feed Spidey knowledge: a .md/.txt file is copied into the knowledge base;
    anything else is saved as a dated note."""
    import shutil

    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
    p = Path(source).expanduser()
    if p.is_file():
        if p.suffix.lower() not in (".md", ".txt"):
            return f"ERROR: only .md/.txt for now — convert {p.suffix} to text first."
        dest = KNOWLEDGE_DIR / p.name
        shutil.copy(p, dest)
        return f"Learned {p.name} ({dest.stat().st_size} bytes) → {dest}"
    notes = KNOWLEDGE_DIR / "notes.md"
    with open(notes, "a") as f:
        f.write(f"\n## {date.today().isoformat()}\n{source}\n")
    return f"Noted → {notes}"


def add_memory(fact: str) -> str:
    fact = " ".join(fact.split())[:MAX_FACT_CHARS]
    if not fact:
        return "ERROR: nothing to remember."
    MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    existing = MEMORY_FILE.read_text() if MEMORY_FILE.exists() else ""
    if fact.lower() in existing.lower():
        return f"Already remembered: {fact}"
    with open(MEMORY_FILE, "a") as f:
        f.write(f"- [{date.today().isoformat()}] {fact}\n")
    return f"Remembered: {fact}"
