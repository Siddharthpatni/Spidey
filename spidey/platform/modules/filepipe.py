"""Distributed file processing: upload → queue → workers → process → store → notify.

Uploads are raw request bodies (no multipart dependency): content-addressed
into ``~/.spidey/platform/files/<sha256>/<name>``, recorded, then processed by
the queue workers with type-specific processors — text stats + preview, CSV
column profiling, JSON shape, zip inventories, image dimensions (header parse,
no imaging library), PDF page text when pypdf is present. Results land back on
the row; ``file.processed`` fires to webhooks.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import struct
import zipfile
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from ..core import db, notify
from ..core.text import extract_text

TEXT_SUFFIXES = {".txt", ".md", ".log", ".py", ".js", ".ts", ".html", ".xml", ".yaml", ".yml"}


# ------------------------------- processors --------------------------------- #
def _process_text(path: Path) -> Dict[str, Any]:
    text = path.read_text(errors="replace")
    lines = text.splitlines()
    return {"kind": "text", "chars": len(text), "words": len(text.split()),
            "lines": len(lines), "preview": text[:800]}


def _process_csv(path: Path) -> Dict[str, Any]:
    with path.open(newline="", errors="replace") as f:
        reader = csv.reader(f)
        rows = list(reader)
    if not rows:
        return {"kind": "csv", "rows": 0}
    header, body = rows[0], rows[1:]
    profile = {}
    for i, col in enumerate(header[:50]):
        values = [r[i] for r in body if len(r) > i and r[i] != ""]
        numeric = []
        for v in values:
            try:
                numeric.append(float(v))
            except ValueError:
                break
        stats: Dict[str, Any] = {"non_empty": len(values)}
        if numeric and len(numeric) == len(values):
            stats.update({"min": min(numeric), "max": max(numeric),
                          "mean": round(sum(numeric) / len(numeric), 4)})
        profile[col or f"col_{i}"] = stats
    return {"kind": "csv", "rows": len(body), "columns": header, "profile": profile}


def _process_json(path: Path) -> Dict[str, Any]:
    data = json.loads(path.read_text(errors="replace"))
    if isinstance(data, list):
        return {"kind": "json", "type": "array", "items": len(data),
                "sample": data[0] if data else None}
    if isinstance(data, dict):
        return {"kind": "json", "type": "object", "keys": list(data)[:50]}
    return {"kind": "json", "type": type(data).__name__}


def _process_zip(path: Path) -> Dict[str, Any]:
    with zipfile.ZipFile(path) as z:
        infos = z.infolist()
        return {"kind": "zip", "entries": len(infos),
                "files": [{"name": i.filename, "size": i.file_size} for i in infos[:100]],
                "total_uncompressed": sum(i.file_size for i in infos)}


def _image_dimensions(path: Path) -> Optional[Dict[str, int]]:
    """PNG/GIF/JPEG dimensions straight from the header bytes."""
    with path.open("rb") as f:
        head = f.read(26)
        if head.startswith(b"\x89PNG") and len(head) >= 24:
            w, h = struct.unpack(">II", head[16:24])
            return {"width": w, "height": h}
        if head[:6] in (b"GIF87a", b"GIF89a"):
            w, h = struct.unpack("<HH", head[6:10])
            return {"width": w, "height": h}
        if head.startswith(b"\xff\xd8"):  # JPEG: walk segments to SOFn
            f.seek(2)
            while True:
                marker = f.read(2)
                if len(marker) < 2 or marker[0] != 0xFF:
                    return None
                (length,) = struct.unpack(">H", f.read(2))
                if 0xC0 <= marker[1] <= 0xCF and marker[1] not in (0xC4, 0xC8, 0xCC):
                    f.read(1)
                    h, w = struct.unpack(">HH", f.read(4))
                    return {"width": w, "height": h}
                f.seek(length - 2, io.SEEK_CUR)
    return None


def process_file(path: Path) -> Dict[str, Any]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return _process_csv(path)
    if suffix == ".json":
        return _process_json(path)
    if suffix == ".zip":
        return _process_zip(path)
    if suffix in (".png", ".gif", ".jpg", ".jpeg"):
        dims = _image_dimensions(path)
        return {"kind": "image", **(dims or {"note": "unrecognized image header"})}
    if suffix == ".pdf":
        text = extract_text(str(path))
        return {"kind": "pdf", "chars": len(text), "preview": text[:800]}
    if suffix in TEXT_SUFFIXES:
        return _process_text(path)
    return {"kind": "binary", "note": f"no specific processor for '{suffix or 'no extension'}'"}


def _job_process(payload: Dict[str, Any]) -> Dict[str, Any]:
    file_id = payload["file_id"]
    row = db.one("SELECT * FROM files WHERE id=?", (file_id,))
    if not row:
        raise RuntimeError(f"file row {file_id} vanished")
    try:
        result = process_file(Path(row["path"]))
        db.execute("UPDATE files SET status='done', result=? WHERE id=?",
                   (db.json_dumps(result), file_id))
        notify.emit("file.processed", {"file_id": file_id, "name": row["name"],
                                       "kind": result.get("kind")})
        return result
    except Exception as e:
        db.execute("UPDATE files SET status='failed', error=? WHERE id=?", (str(e), file_id))
        raise


def register_jobs(queue) -> None:
    queue.register("files.process", _job_process)


# ------------------------------- REST API ---------------------------------- #
router = APIRouter(prefix="/api/files", tags=["File Pipeline"])
MAX_UPLOAD = 100 * 1024 * 1024


@router.put("/upload")
async def upload(request: Request, name: str) -> dict:
    """Raw-body upload: ``curl -T report.csv '<host>/api/files/upload?name=report.csv'``"""
    body = await request.body()
    if not body:
        raise HTTPException(422, "empty body")
    if len(body) > MAX_UPLOAD:
        raise HTTPException(413, f"file exceeds {MAX_UPLOAD} bytes")
    safe = Path(name).name or "upload.bin"
    sha = hashlib.sha256(body).hexdigest()
    dest = db.data_dir() / "files" / sha[:16]
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / safe
    path.write_bytes(body)
    fid = db.execute(
        "INSERT INTO files(name, path, size, sha256, content_type, created_at)"
        " VALUES(?,?,?,?,?,?)",
        (safe, str(path), len(body), sha,
         request.headers.get("content-type", ""), db.now()))
    from ..core.queue import default_queue
    default_queue().enqueue("files.process", {"file_id": fid})
    return {"id": fid, "name": safe, "sha256": sha, "size": len(body), "status": "queued"}


@router.get("")
def list_files(limit: int = 50) -> list:
    return db.query("SELECT id, name, size, sha256, status, created_at FROM files"
                    " ORDER BY id DESC LIMIT ?", (limit,))


@router.get("/{file_id}")
def get_file(file_id: int) -> dict:
    row = db.one("SELECT * FROM files WHERE id=?", (file_id,))
    if not row:
        raise HTTPException(404, "file not found")
    row["result"] = db.json_loads(row["result"])
    return row
