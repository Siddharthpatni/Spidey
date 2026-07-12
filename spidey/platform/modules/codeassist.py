"""Coding assistant: index a repository, then chat with it, review PRs, hunt
bugs, generate unit tests and draw architecture diagrams.

Indexing chunks source files (~60 lines each) into the shared vector store →
RAG. Static analysis is AST-based and needs no model: mutable default args,
bare excepts, ``== None``, unclosed files, debug prints, TODO/FIXME density,
oversized functions. Test generation reads real signatures with ``inspect``-
grade fidelity (via ``ast``) and emits runnable pytest skeletons. Diagrams are
Mermaid graphs of the intra-project import structure.
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..core import db, llmutil
from ..core.text import embed, top_k

CODE_SUFFIXES = {".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java", ".kt",
                 ".c", ".h", ".cpp", ".cs", ".rb", ".php", ".swift", ".sql", ".sh",
                 ".yaml", ".yml", ".toml", ".md"}
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build",
             ".mypy_cache", "target", ".next"}
CHUNK_LINES = 60


class IndexIn(BaseModel):
    path: str  # repository root on disk


class AskRepoIn(BaseModel):
    repo: str
    question: str


class CodeIn(BaseModel):
    path: Optional[str] = None
    code: Optional[str] = None


def _resolve_repo(path: str) -> Path:
    root = Path(path).expanduser().resolve()
    if not root.is_dir():
        raise HTTPException(404, f"not a directory: {path}")
    return root


# ------------------------------- indexing / RAG ------------------------------ #
def index_repo(root: Path) -> Dict[str, Any]:
    repo = str(root)
    db.execute("DELETE FROM repo_chunks WHERE repo=?", (repo,))
    files = chunks = 0
    rows = []
    for p in sorted(root.rglob("*")):
        if (not p.is_file() or p.suffix.lower() not in CODE_SUFFIXES
                or any(part in SKIP_DIRS for part in p.parts)):
            continue
        try:
            lines = p.read_text(errors="replace").splitlines()
        except OSError:
            continue
        files += 1
        rel = str(p.relative_to(root))
        for start in range(0, len(lines), CHUNK_LINES):
            block = "\n".join(lines[start:start + CHUNK_LINES])
            if not block.strip():
                continue
            text = f"// {rel}:{start + 1}\n{block}"
            rows.append((repo, rel, start + 1, text, db.json_dumps(embed(text))))
            chunks += 1
    with db.connect() as conn:
        conn.executemany("INSERT INTO repo_chunks(repo, path, start_line, text, vec)"
                         " VALUES(?,?,?,?,?)", rows)
    return {"repo": repo, "files": files, "chunks": chunks}


def ask_repo(repo: str, question: str) -> Dict[str, Any]:
    rows = db.query("SELECT id, text, vec FROM repo_chunks WHERE repo=?",
                    (str(Path(repo).expanduser().resolve()),))
    if not rows:
        raise HTTPException(404, "repo not indexed — POST /api/code/index first")
    hits = top_k(question, [(r["id"], r["text"], db.json_loads(r["vec"], [])) for r in rows], 5)
    context = "\n\n---\n\n".join(text for _, text, _ in hits)
    llm = llmutil.ask(f"Answer about this codebase using the excerpts (cite file:line "
                      f"headers).\n\n{context}\n\nQUESTION: {question}")
    return {"answer": llm or "No model reachable — here are the most relevant chunks.",
            "mode": "llm" if llm else "retrieval_only",
            "chunks": [{"text": t[:600], "score": round(s, 3)} for _, t, s in hits]}


# ------------------------------- static analysis ------------------------------ #
def find_bugs(code: str, filename: str = "<code>") -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []

    def add(node, kind, msg):
        findings.append({"file": filename, "line": getattr(node, "lineno", 0),
                         "kind": kind, "message": msg})

    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return [{"file": filename, "line": e.lineno or 0, "kind": "syntax-error",
                 "message": str(e.msg)}]
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for d in node.args.defaults:
                if isinstance(d, (ast.List, ast.Dict, ast.Set)):
                    add(d, "mutable-default", f"mutable default argument in {node.name}()")
            body_len = (node.body[-1].end_lineno or 0) - node.lineno
            if body_len > 80:
                add(node, "long-function", f"{node.name}() spans ~{body_len} lines — split it")
        elif isinstance(node, ast.ExceptHandler) and node.type is None:
            add(node, "bare-except", "bare `except:` swallows KeyboardInterrupt/SystemExit")
        elif isinstance(node, ast.Compare):
            if any(isinstance(op, (ast.Eq, ast.NotEq)) for op in node.ops) and any(
                    isinstance(c, ast.Constant) and c.value is None
                    for c in [*node.comparators, node.left]):
                add(node, "none-comparison", "use `is None` / `is not None`, not ==/!=")
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
              and node.func.id == "open"):
            parent_withs = [n for n in ast.walk(tree) if isinstance(n, ast.With)
                            and node in ast.walk(n)]
            if not parent_withs:
                add(node, "unclosed-file", "open() outside a `with` block may leak the handle")
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
              and node.func.id == "print"):
            add(node, "debug-print", "print() in library code — use logging")
    for i, line in enumerate(code.splitlines(), 1):
        if "TODO" in line or "FIXME" in line:
            findings.append({"file": filename, "line": i, "kind": "todo",
                             "message": line.strip()[:120]})
    return findings


def review_diff(repo: Path, base: str = "HEAD") -> Dict[str, Any]:
    proc = subprocess.run(["git", "diff", base, "--", "."], cwd=str(repo),
                          capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:
        raise HTTPException(422, f"git diff failed: {proc.stderr.strip()[:200]}")
    diff = proc.stdout
    if not diff.strip():
        return {"diff_stats": "clean working tree", "findings": [], "llm_review": None}
    added = [ln[1:] for ln in diff.splitlines() if ln.startswith("+") and not ln.startswith("++")]
    findings = find_bugs("\n".join(added), "<added lines>")
    llm = llmutil.ask("Review this diff like a senior engineer: correctness bugs first, "
                      f"then design. Be specific, cite hunks.\n\n{diff[:8000]}")
    return {"diff_stats": f"{len(added)} added lines", "findings": findings,
            "llm_review": llm}


# ------------------------------- test generation ------------------------------ #
def generate_tests(code: str, module_name: str = "module") -> str:
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        raise HTTPException(422, f"can't parse: {e}")
    lines = [f'"""Auto-generated pytest skeletons for {module_name} — fill in the asserts."""',
             "", "import pytest", "", f"from {module_name} import *  # noqa: F401,F403", ""]
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
            args = [a.arg for a in node.args.args if a.arg not in ("self", "cls")]
            call = f"{node.name}({', '.join(f'{a}=...' for a in args)})"
            lines += [f"def test_{node.name}():",
                      f"    result = {call}",
                      "    assert result is not None  # TODO: real expectation", "",
                      f"def test_{node.name}_invalid_input():",
                      "    with pytest.raises(Exception):  # TODO: narrow the exception",
                      f"        {node.name}({', '.join('None' for _ in args) or ''})", ""]
        elif isinstance(node, ast.ClassDef):
            methods = [m.name for m in node.body
                       if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
                       and not m.name.startswith("_")]
            if methods:
                lines += [f"class Test{node.name}:",
                          "    @pytest.fixture",
                          "    def instance(self):",
                          f"        return {node.name}()  # TODO: constructor args", ""]
                for m in methods:
                    lines += [f"    def test_{m}(self, instance):",
                              f"        assert instance.{m} is not None  # TODO", ""]
    return "\n".join(lines)


# ------------------------------- architecture diagram -------------------------- #
def import_diagram(root: Path) -> str:
    """Mermaid graph of intra-project Python imports."""
    modules: Dict[str, set] = {}
    py_files = [p for p in root.rglob("*.py")
                if not any(part in SKIP_DIRS for part in p.parts)]
    names = {p.stem for p in py_files} | {p.parent.name for p in py_files}
    for p in py_files:
        mod = str(p.relative_to(root).with_suffix("")).replace("/", ".")
        try:
            tree = ast.parse(p.read_text(errors="replace"))
        except (SyntaxError, OSError):
            continue
        deps = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                deps |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                deps.add(node.module.split(".")[0])
        modules[mod] = {d for d in deps if d in names}
    lines = ["graph TD"]
    for mod, deps in sorted(modules.items()):
        safe = mod.replace(".", "_")
        for d in sorted(deps):
            if d != mod.split(".")[0]:
                lines.append(f"    {safe}[{mod}] --> {d}[{d}]")
    return "\n".join(lines) if len(lines) > 1 else "graph TD\n    A[no internal imports found]"


# ------------------------------- REST API ---------------------------------- #
router = APIRouter(prefix="/api/code", tags=["Code Assistant"])


@router.post("/index")
def api_index(body: IndexIn) -> dict:
    return index_repo(_resolve_repo(body.path))


@router.post("/ask")
def api_ask(body: AskRepoIn) -> dict:
    return ask_repo(body.repo, body.question)


def _read_code(body: CodeIn) -> tuple:
    if body.code:
        return body.code, "<inline>"
    if body.path:
        p = Path(body.path).expanduser()
        if not p.is_file():
            raise HTTPException(404, f"no file at {body.path}")
        return p.read_text(errors="replace"), p.name
    raise HTTPException(422, "provide 'code' or 'path'")


@router.post("/explain")
def api_explain(body: CodeIn) -> dict:
    code, name = _read_code(body)
    llm = llmutil.ask(f"Explain this code to a new teammate: what it does, how, and any "
                      f"sharp edges.\n\n{code[:8000]}")
    tree_summary = []
    try:
        for node in ast.parse(code).body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                doc = ast.get_docstring(node)
                tree_summary.append({"name": node.name, "kind": type(node).__name__,
                                     "line": node.lineno, "doc": (doc or "")[:150]})
    except SyntaxError:
        pass
    return {"file": name, "explanation": llm, "structure": tree_summary,
            "mode": "llm" if llm else "structure_only"}


@router.post("/bugs")
def api_bugs(body: CodeIn) -> dict:
    code, name = _read_code(body)
    return {"file": name, "findings": find_bugs(code, name)}


@router.post("/review")
def api_review(body: dict) -> dict:
    repo = _resolve_repo(body.get("repo", "."))
    return review_diff(repo, body.get("base", "HEAD"))


@router.post("/gen-tests")
def api_gen_tests(body: CodeIn) -> dict:
    code, name = _read_code(body)
    module = Path(name).stem if name != "<inline>" else "module"
    return {"file": name, "tests": generate_tests(code, module)}


@router.get("/diagram")
def api_diagram(path: str) -> dict:
    return {"mermaid": import_diagram(_resolve_repo(path))}
