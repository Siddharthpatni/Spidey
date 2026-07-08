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
