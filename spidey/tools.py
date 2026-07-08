"""The tools Spidey can call, plus a tiny registry that exposes them to the model.

Each tool has a JSON-Schema ``parameters`` block (this is what the model sees and
fills in) and a Python function that actually does the work. File tools are
confined to the working directory; ``run_command`` goes through the safety layer.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List

from .safety import SafetyConfig, check_command, within_workdir

MAX_OUTPUT = 8000  # cap observation size so a huge file doesn't blow up the context


@dataclass
class Context:
    """Runtime handles passed to every tool call."""

    workdir: Path
    safety: SafetyConfig
    approve: Callable[[str], bool]


@dataclass
class Tool:
    name: str
    description: str
    parameters: Dict[str, Any]
    func: Callable[[Context, Dict[str, Any]], str]


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def specs(self) -> List[Dict[str, Any]]:
        """Normalized specs handed to the LLM backend."""
        return [
            {"name": t.name, "description": t.description, "parameters": t.parameters}
            for t in self._tools.values()
        ]

    def names(self) -> List[str]:
        return list(self._tools)

    def call(self, name: str, args: Dict[str, Any], ctx: Context) -> str:
        if name not in self._tools:
            return f"ERROR: unknown tool '{name}'. Available: {', '.join(self._tools)}"
        try:
            return _truncate(self._tools[name].func(ctx, args or {}))
        except KeyError as e:
            return f"ERROR: missing required argument {e} for tool '{name}'"
        except Exception as e:  # tools must never crash the loop
            return f"ERROR while running {name}: {type(e).__name__}: {e}"


def _truncate(text: Any) -> str:
    s = text if isinstance(text, str) else str(text)
    if len(s) <= MAX_OUTPUT:
        return s
    return s[:MAX_OUTPUT] + f"\n...[truncated {len(s) - MAX_OUTPUT} chars]"


# --------------------------------------------------------------------------- #
# Tool implementations
# --------------------------------------------------------------------------- #
def _read_file(ctx: Context, args: Dict[str, Any]) -> str:
    rel = args["path"]
    path = (ctx.workdir / rel)
    if not within_workdir(ctx.workdir, path):
        return f"ERROR: refusing to read outside the working directory: {rel}"
    if not path.exists():
        return f"ERROR: file not found: {rel}"
    if path.is_dir():
        return f"ERROR: {rel} is a directory (use list_directory)"
    return path.read_text(errors="replace")


def _write_file(ctx: Context, args: Dict[str, Any]) -> str:
    rel = args["path"]
    content = args.get("content", "")
    path = (ctx.workdir / rel)
    if not within_workdir(ctx.workdir, path):
        return f"ERROR: refusing to write outside the working directory: {rel}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return f"Wrote {len(content)} bytes to {rel}"


def _list_directory(ctx: Context, args: Dict[str, Any]) -> str:
    rel = args.get("path", ".")
    path = (ctx.workdir / rel)
    if not within_workdir(ctx.workdir, path):
        return f"ERROR: refusing to list outside the working directory: {rel}"
    if not path.exists():
        return f"ERROR: not found: {rel}"
    rows = []
    for p in sorted(path.iterdir(), key=lambda x: (x.is_file(), x.name)):
        rows.append(("[dir]  " if p.is_dir() else "       ") + p.name)
    return "\n".join(rows) or "(empty directory)"


def _search_code(ctx: Context, args: Dict[str, Any]) -> str:
    pattern = args["pattern"]
    rel = args.get("path", ".")
    root = (ctx.workdir / rel)
    if not within_workdir(ctx.workdir, root):
        return f"ERROR: refusing to search outside the working directory: {rel}"
    try:
        rx = re.compile(pattern)
    except re.error as e:
        return f"ERROR: invalid regex: {e}"

    skip = {".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache", "dist", "build"}
    hits: List[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip]
        for fn in filenames:
            fp = Path(dirpath) / fn
            try:
                text = fp.read_text(errors="ignore")
            except (OSError, UnicodeDecodeError):
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                if rx.search(line):
                    hits.append(f"{fp.relative_to(ctx.workdir)}:{lineno}: {line.strip()[:200]}")
                    if len(hits) >= 200:
                        hits.append("...[stopped at 200 matches]")
                        return "\n".join(hits)
    return "\n".join(hits) or "No matches found."


def _run_command(ctx: Context, args: Dict[str, Any]) -> str:
    cmd = args["command"]
    verdict, reason = check_command(cmd, ctx.safety)
    if verdict == "deny":
        return f"BLOCKED by safety policy ({reason}). Command not run."
    if verdict == "ask":
        if not ctx.approve(f"Run shell command?\n    $ {cmd}\n    (flagged: {reason})"):
            return "DENIED by user. Command not run."
    try:
        proc = subprocess.run(
            cmd, shell=True, cwd=str(ctx.workdir),
            capture_output=True, text=True, timeout=ctx.safety.command_timeout,
        )
    except subprocess.TimeoutExpired:
        return f"ERROR: command timed out after {ctx.safety.command_timeout}s"
    body = (proc.stdout or "")
    if proc.stderr:
        body += ("\n[stderr]\n" + proc.stderr)
    return f"exit_code={proc.returncode}\n{body}".strip()


def _remember(ctx: Context, args: Dict[str, Any]) -> str:
    from .memory import add_memory
    return add_memory(args["fact"])


def _finish(ctx: Context, args: Dict[str, Any]) -> str:
    # The agent intercepts calls to `finish` by name; this is only a fallback.
    return args.get("summary", "")


def default_registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(Tool(
        "read_file",
        "Read a UTF-8 text file inside the working directory and return its contents.",
        {"type": "object",
         "properties": {"path": {"type": "string", "description": "Path relative to the working directory."}},
         "required": ["path"]},
        _read_file,
    ))
    reg.register(Tool(
        "write_file",
        "Create or overwrite a text file inside the working directory.",
        {"type": "object",
         "properties": {"path": {"type": "string"},
                        "content": {"type": "string", "description": "Full file contents to write."}},
         "required": ["path", "content"]},
        _write_file,
    ))
    reg.register(Tool(
        "list_directory",
        "List the files and folders at a path (defaults to the working directory root).",
        {"type": "object",
         "properties": {"path": {"type": "string", "description": "Defaults to '.'"}}},
        _list_directory,
    ))
    reg.register(Tool(
        "search_code",
        "Regex-search file contents under a path. Returns matching 'file:line: text' rows.",
        {"type": "object",
         "properties": {"pattern": {"type": "string", "description": "A Python regular expression."},
                        "path": {"type": "string", "description": "Where to search. Defaults to '.'"}},
         "required": ["pattern"]},
        _search_code,
    ))
    reg.register(Tool(
        "run_command",
        "Run a shell command in the working directory. Subject to the safety policy; "
        "destructive commands are blocked or require approval.",
        {"type": "object",
         "properties": {"command": {"type": "string"}},
         "required": ["command"]},
        _run_command,
    ))
    reg.register(Tool(
        "remember",
        "Save a lasting fact about the user — their name, preferences, projects, goals, "
        "important dates. Use it whenever they share something a good friend would remember. "
        "One short sentence per fact.",
        {"type": "object",
         "properties": {"fact": {"type": "string",
                                 "description": "The fact, phrased to be useful later, e.g. "
                                                "'Siddharth prefers short answers.'"}},
         "required": ["fact"]},
        _remember,
    ))
    reg.register(Tool(
        "finish",
        "Call this when the task is complete. Provide a concise summary of what you did.",
        {"type": "object",
         "properties": {"summary": {"type": "string"}},
         "required": ["summary"]},
        _finish,
    ))
    return reg
