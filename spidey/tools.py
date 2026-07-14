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


def _path_allowed(ctx: "Context", path: Path) -> bool:
    """Full-disk by default; only enforce the workdir sandbox when the safety
    config asks for it (``confine_to_workdir=True``)."""
    if not getattr(ctx.safety, "confine_to_workdir", False):
        return True
    return within_workdir(ctx.workdir, path)


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
    if not _path_allowed(ctx, path):
        return f"ERROR: file access blocked by confine_to_workdir: {rel}"
    if not path.exists():
        return f"ERROR: file not found: {rel}"
    if path.is_dir():
        return f"ERROR: {rel} is a directory (use list_directory)"
    return path.read_text(errors="replace")


def _write_file(ctx: Context, args: Dict[str, Any]) -> str:
    rel = args["path"]
    content = args.get("content", "")
    path = (ctx.workdir / rel)
    if not _path_allowed(ctx, path):
        return f"ERROR: file access blocked by confine_to_workdir: {rel}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return f"Wrote {len(content)} bytes to {rel}"


def _list_directory(ctx: Context, args: Dict[str, Any]) -> str:
    rel = args.get("path", ".")
    path = (ctx.workdir / rel)
    if not _path_allowed(ctx, path):
        return f"ERROR: listing blocked by confine_to_workdir: {rel}"
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
    if not _path_allowed(ctx, root):
        return f"ERROR: search blocked by confine_to_workdir: {rel}"
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


def _plan(ctx: Context, args: Dict[str, Any]) -> str:
    # The plan lives in the transcript/graph; the agent follows it from there.
    return "Plan recorded. Follow it step by step — and revise it if reality disagrees."


def _remember(ctx: Context, args: Dict[str, Any]) -> str:
    from .memory import add_memory
    result = add_memory(args["fact"])
    # Mirror the fact into the knowledge graph so remembered things connect to
    # everything else Spidey knows (the self-building brain).
    try:
        from .platform.modules.brain import learn_fact
        learn_fact(args["fact"])
    except Exception:
        pass
    return result


def _search_notes(ctx: Context, args: Dict[str, Any]) -> str:
    from .memory import search_knowledge
    return search_knowledge(args["query"])


def _control_app(ctx: Context, args: Dict[str, Any]) -> str:
    """Drive native macOS apps (Notes, Reminders, Calendar, Mail, Music, Safari)
    via AppleScript. Powerful — so every script needs the user's approval."""
    import platform

    if platform.system() != "Darwin":
        return "ERROR: control_app drives macOS apps and this isn't a Mac."
    script = args["script"]
    if not ctx.approve(f"Run AppleScript?\n    {script[:400]}"):
        return "DENIED: the user declined this app action."
    proc = subprocess.run(["osascript", "-e", script],
                          capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:
        return f"ERROR from AppleScript: {proc.stderr.strip()[:400]}"
    return proc.stdout.strip() or "Done (no output)."


def _scrape_page(ctx: Context, args: Dict[str, Any]) -> str:
    """Fetch a live web page through the platform's extraction ladder."""
    from .platform.modules.webauto import scrape

    url = args["url"]
    if not url.startswith(("http://", "https://")):
        return "ERROR: url must start with http:// or https://"
    if not ctx.approve(f"Fetch this web page?\n    {url}"):
        return "DENIED: the user declined the web request."
    try:
        result = scrape(url, strategy=args.get("strategy", "auto"),
                        instruction=args.get("instruction", ""))
    except Exception as e:
        return f"ERROR fetching {url}: {type(e).__name__}: {e}"
    import json as _json
    return f"[{result['strategy']}] " + _json.dumps(result["data"], ensure_ascii=False)[:7000]


def _knowledge_search(ctx: Context, args: Dict[str, Any]) -> str:
    """Search Spidey's own crawled knowledge base (Knowledge Nexus) with hybrid
    BM25 + vector + graph ranking. Optionally crawl a seed URL first."""
    from .platform.modules.nexus import hybrid_search, crawl_one
    from urllib.parse import urlparse

    seed = args.get("crawl")
    crawled = ""
    if seed:
        if not seed.startswith(("http://", "https://")):
            return "ERROR: 'crawl' must be an http(s) URL"
        try:
            r = crawl_one(seed, depth=int(args.get("depth", 1)),
                          max_pages=int(args.get("max_pages", 15)),
                          domain_lock=urlparse(seed).netloc)
            crawled = f"(crawled {seed}: {r.get('status')}, discovered {r.get('discovered', 0)} links)\n"
        except Exception as e:
            crawled = f"(crawl of {seed} failed: {e})\n"
    query = args.get("query", "")
    if not query.strip():
        return crawled + "Provide a 'query' to search the knowledge base."
    hits = hybrid_search(query, k=int(args.get("k", 6)))
    if not hits:
        return crawled + "No results — the knowledge base is empty. Pass a 'crawl' URL to fill it."
    lines = [f"[{h['score']}] {h['title'] or h['url']} — {h['url']}\n    {h['snippet']}"
             for h in hits]
    return crawled + "\n".join(lines)


def _team_status(ctx: Context, args: Dict[str, Any]) -> str:
    """Peek at the platform: queue depth, recent jobs, unacked alerts."""
    from .platform.core import db as pdb
    from .platform.core.queue import default_queue

    stats = default_queue().stats()
    alerts = pdb.query("SELECT source, message FROM alerts WHERE acked=0"
                       " ORDER BY id DESC LIMIT 5")
    lines = ["queue: " + (", ".join(f"{k}={v}" for k, v in stats.items()) or "empty")]
    lines += [f"alert[{a['source']}]: {a['message']}" for a in alerts] or ["no active alerts"]
    return "\n".join(lines)


def _http_request(ctx: Context, args: Dict[str, Any]) -> str:
    """Call any HTTP API: GET/POST/PUT/PATCH/DELETE with optional headers + body."""
    import json as _json

    import requests

    method = (args.get("method") or "GET").upper()
    url = args["url"]
    if not url.startswith(("http://", "https://")):
        return "ERROR: url must start with http:// or https://"
    headers = args.get("headers") or {}
    if isinstance(headers, str):
        headers = _json.loads(headers) if headers.strip() else {}
    body = args.get("body")
    kwargs: Dict[str, Any] = {"headers": headers, "timeout": 30}
    if body is not None:
        if isinstance(body, (dict, list)):
            kwargs["json"] = body
        else:
            kwargs["data"] = body
    try:
        resp = requests.request(method, url, **kwargs)
    except Exception as e:
        return f"ERROR calling {url}: {type(e).__name__}: {e}"
    ct = resp.headers.get("content-type", "")
    preview = resp.text[:6000]
    return (f"{method} {url} -> {resp.status_code} ({ct})\n{preview}"
            + ("\n...[truncated]" if len(resp.text) > 6000 else ""))


def _generate_image(ctx: Context, args: Dict[str, Any]) -> str:
    """Generate an image from a text prompt via a local Stable Diffusion backend."""
    from .platform.modules.media import ImageIn, generate_image
    from fastapi import HTTPException

    prompt = args.get("prompt", "")
    if not prompt.strip():
        return "ERROR: 'prompt' is required"
    try:
        img = generate_image(ImageIn(prompt=prompt, negative_prompt=args.get("negative_prompt", ""),
                                     width=int(args.get("width", 512)),
                                     height=int(args.get("height", 512)),
                                     title=args.get("title", "")))
    except HTTPException as e:
        return f"IMAGE BACKEND UNAVAILABLE: {e.detail}"
    except Exception as e:
        return f"ERROR generating image: {type(e).__name__}: {e}"
    return (f"Generated image '{img['title']}' ({img['size']} bytes). "
            f"Download at {img['download_url']}.")


def _create_document(ctx: Context, args: Dict[str, Any]) -> str:
    """Generate a real downloadable document (résumé, CV, slides, report, HTML
    canvas...) via the platform's Document Studio."""
    from .platform.modules.docgen import KINDS, FORMATS, create_document

    kind = args.get("kind", "custom")
    fmt = args.get("format", "docx")
    if kind not in KINDS:
        return f"ERROR: kind must be one of {list(KINDS)}"
    if fmt not in FORMATS:
        return f"ERROR: format must be one of {FORMATS}"
    prompt = args.get("prompt") or args.get("brief") or ""
    if not prompt.strip():
        return "ERROR: 'prompt' (what the document should contain) is required"
    try:
        doc = create_document(kind, fmt, args.get("title", "").strip() or KINDS[kind]["label"],
                              prompt, args.get("details", ""))
    except Exception as e:
        return f"ERROR generating document: {type(e).__name__}: {e}"
    return (f"Created '{doc['title']}' ({doc['format'].upper()}, {doc['size']} bytes, "
            f"{doc['mode']} mode). Download it at {doc['download_url']} "
            f"(open http://localhost:8000{doc['download_url']} in the browser, or find it "
            f"under History in the Studio).")


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
        "plan",
        "Team-Leader hat: lay out 2-6 numbered steps BEFORE starting any multi-step task. "
        "Keeps the whole run organized and visible to the user.",
        {"type": "object",
         "properties": {"steps": {"type": "string",
                                  "description": "Numbered steps, e.g. '1. read X 2. change Y 3. verify'."}},
         "required": ["steps"]},
        _plan,
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
        "control_app",
        "Control the user's Mac apps with AppleScript — create Notes, add Reminders, "
        "read/add Calendar events, draft Mail, control Music, open Safari tabs. The apps "
        "already sync the user's accounts, so this reaches their real data. Every script "
        "is shown to the user for approval first. Write minimal, single-purpose scripts.",
        {"type": "object",
         "properties": {"script": {"type": "string",
                                   "description": "A short AppleScript, e.g. 'tell application "
                                                  "\"Reminders\" to make new reminder with "
                                                  "properties {name:\"buy milk\"}'."}},
         "required": ["script"]},
        _control_app,
    ))
    reg.register(Tool(
        "search_notes",
        "Search the user's personal knowledge base — documents they fed Spidey "
        "(`spidey learn <file>`), remembered facts, and lessons from past jobs. Use it "
        "when a question is about THEIR life, projects, or notes rather than this folder.",
        {"type": "object",
         "properties": {"query": {"type": "string", "description": "A few key words."}},
         "required": ["query"]},
        _search_notes,
    ))
    reg.register(Tool(
        "scrape_page",
        "Fetch a live web page and extract its data (structured metadata, tables, links "
        "or readable text — pass an 'instruction' to get AI-extracted JSON). Use this "
        "when the task needs information from the internet.",
        {"type": "object",
         "properties": {"url": {"type": "string", "description": "Full http(s) URL."},
                        "strategy": {"type": "string",
                                     "description": "auto (default), structured, tables, "
                                                    "links, text or ai."},
                        "instruction": {"type": "string",
                                        "description": "What to extract, e.g. "
                                                       "'product names and prices'."}},
         "required": ["url"]},
        _scrape_page,
    ))
    reg.register(Tool(
        "platform_status",
        "Check Spidey's platform: background job queue depth and any active alerts "
        "(analytics thresholds, fleet maintenance). Use when asked how the system is doing.",
        {"type": "object", "properties": {}},
        _team_status,
    ))
    reg.register(Tool(
        "knowledge_search",
        "Search Spidey's own continuously-crawled knowledge base (Knowledge Nexus) with "
        "hybrid BM25 + semantic + graph ranking — its long-term web memory. Pass a 'crawl' "
        "URL to fetch + index a site first, then 'query' to search it. Use for research "
        "that should persist and improve over time, not one-off fetches.",
        {"type": "object",
         "properties": {
            "query": {"type": "string", "description": "What to search for."},
            "crawl": {"type": "string", "description": "Optional seed URL to crawl+index first."},
            "depth": {"type": "integer", "description": "Link-follow depth when crawling (default 1)."},
            "max_pages": {"type": "integer"}},
         "required": ["query"]},
        _knowledge_search,
    ))
    reg.register(Tool(
        "http_request",
        "Make an HTTP request to any API or URL and return the response. Use for "
        "calling REST APIs, webhooks, downloading JSON/text, or checking a service. "
        "Supports GET/POST/PUT/PATCH/DELETE with headers and a JSON or text body.",
        {"type": "object",
         "properties": {
            "url": {"type": "string", "description": "Full http(s) URL."},
            "method": {"type": "string", "description": "GET (default), POST, PUT, PATCH, DELETE."},
            "headers": {"type": "object", "description": "Optional request headers."},
            "body": {"description": "Optional request body — a JSON object/array (sent as "
                                    "JSON) or a string (sent raw)."}},
         "required": ["url"]},
        _http_request,
    ))
    reg.register(Tool(
        "generate_image",
        "Generate an image from a text prompt (uses a local Stable Diffusion backend). "
        "Use when the user asks for a picture, illustration, logo, or artwork. Returns a "
        "download link; if no image backend is installed, it says exactly how to add one.",
        {"type": "object",
         "properties": {
            "prompt": {"type": "string", "description": "What to draw, in detail."},
            "negative_prompt": {"type": "string", "description": "What to avoid (optional)."},
            "width": {"type": "integer"}, "height": {"type": "integer"},
            "title": {"type": "string"}},
         "required": ["prompt"]},
        _generate_image,
    ))
    reg.register(Tool(
        "create_document",
        "Generate a real, downloadable document and return its link. Use whenever the "
        "user wants a résumé, CV, cover letter, slide deck / presentation (PPT), report, "
        "letter, README, proposal, or a visual HTML 'canvas' — instead of pasting a long "
        "document into chat.",
        {"type": "object",
         "properties": {
            "kind": {"type": "string",
                     "description": "resume | cv | cover_letter | presentation | report | "
                                    "letter | readme | proposal | meeting_minutes | "
                                    "ieee_paper | custom"},
            "format": {"type": "string",
                       "description": "docx | pptx | pdf | html | md | txt. Use pptx for "
                                      "slide decks, html for a visual canvas, docx/pdf for "
                                      "résumés and reports."},
            "title": {"type": "string"},
            "prompt": {"type": "string",
                       "description": "What the document should contain, in detail."},
            "details": {"type": "string",
                        "description": "Optional source facts to use verbatim (the user's "
                                       "real experience, data, notes) — never invented."}},
         "required": ["kind", "format", "prompt"]},
        _create_document,
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
