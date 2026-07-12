"""Document Studio, deep-research papers, sessions, and file uploads —
through the real API. Renderers are validated by cracking the actual bytes
(zip structure for OOXML, %PDF header), not just asserting non-empty."""

import io
import zipfile

from tests.conftest import wait_for_job


# ------------------------------ document studio ------------------------------ #
def test_docgen_all_formats_are_real_files(client):
    md_kinds = client.get("/api/docgen/kinds").json()
    assert "resume" in [k["kind"] for k in md_kinds["kinds"]]
    assert set(md_kinds["formats"]) >= {"docx", "pptx", "pdf", "html", "md", "txt"}

    for fmt in ("md", "txt", "html", "docx", "pptx", "pdf"):
        doc = client.post("/api/docgen/create", json={
            "kind": "resume", "format": fmt, "title": f"Test {fmt}",
            "prompt": "Backend engineer, Python, FastAPI, Docker."}).json()
        assert doc["format"] == fmt and doc["size"] > 0
        raw = client.get(doc["download_url"]).content
        assert len(raw) == doc["size"]
        if fmt in ("docx", "pptx"):
            zf = zipfile.ZipFile(io.BytesIO(raw))   # must be a valid OOXML zip
            names = zf.namelist()
            assert "[Content_Types].xml" in names
            if fmt == "docx":
                assert "word/document.xml" in names
            else:
                assert any(n.startswith("ppt/slides/slide") for n in names)
        elif fmt == "pdf":
            assert raw[:5] == b"%PDF-" and b"%%EOF" in raw[-1024:]
        elif fmt == "html":
            assert b"<html" in raw.lower()


def test_docgen_pptx_slides_from_markdown():
    from spidey.platform.modules.docgen import render_pptx, slides_from_markdown
    md = "# Deck\n## Slide One\n- a\n- b\n## Slide Two\n- c"
    slides = slides_from_markdown(md, "Deck")
    assert slides[0]["title"] == "Deck"                     # title slide
    assert any(s["title"] == "Slide One" and s["bullets"] == ["a", "b"] for s in slides)
    raw = render_pptx(md, "Deck")
    names = zipfile.ZipFile(io.BytesIO(raw)).namelist()
    # title slide + 2 content slides = 3 slide parts
    assert sum(n.startswith("ppt/slides/slide") and n.endswith(".xml") for n in names) == 3


def test_docgen_render_own_markdown(client):
    r = client.post("/api/docgen/render", json={
        "markdown": "# Hello\n\nSome **bold** text.\n\n- one\n- two",
        "format": "pdf", "title": "mine"}).json()
    assert r["size"] > 0
    assert client.get(r["download_url"]).content[:5] == b"%PDF-"


def test_docgen_template_fallback_when_no_model(client):
    # conftest points the model at a nonexistent one → template mode, still a file
    doc = client.post("/api/docgen/create", json={
        "kind": "report", "format": "docx", "prompt": "Q3 sales analysis"}).json()
    assert doc["mode"] == "template"
    assert "Q3 sales" in doc["markdown"]


# ---------------------------- deep-research paper ---------------------------- #
def test_paper_pipeline_fails_cleanly_without_model(client, monkeypatch):
    # No sources fetched (offline) + no model → the job must fail with a clear message,
    # and the run row must reflect it. We stub the fetch to stay offline/fast.
    import spidey.platform.modules.docgen as dg
    monkeypatch.setattr(dg, "_fetch_sources", lambda topic: [])
    run = client.post("/api/docgen/paper", json={"topic": "test topic", "format": "md"}).json()
    assert run["status"] == "queued"
    jobs = client.get("/api/queue/jobs?limit=20").json()
    job_id = next(j["id"] for j in jobs if j["kind"] == "docgen.paper")
    wait_for_job(client, job_id)
    status = client.get(f"/api/docgen/paper/{run['id']}").json()
    assert status["status"] == "failed"
    assert "model" in (status["error"] or "")


# --------------------------------- sessions --------------------------------- #
def test_sessions_persist_actions(client):
    s = client.post("/api/sessions", json={"name": "Test session"}).json()
    client.post(f"/api/sessions/{s['id']}/items",
                json={"module": "docgen", "action": "create", "input": "resume",
                      "output": "ok", "ref_id": 7})
    client.post(f"/api/sessions/{s['id']}/items",
                json={"module": "llm", "action": "chat", "output": "hi"})
    items = client.get(f"/api/sessions/{s['id']}/items").json()
    assert len(items) == 2 and items[0]["module"] == "llm"   # newest first
    assert items[1]["ref_id"] == 7
    listed = client.get("/api/sessions").json()
    assert any(x["id"] == s["id"] and x["items"] == 2 for x in listed)


# ------------------------------- file uploads -------------------------------- #
def test_research_upload_indexes_text(client):
    content = ("Attention Is All You Need. The Transformer uses self-attention. "
               "Self-attention relates positions of a single sequence.").encode()
    r = client.put("/api/research/docs/upload?title=paper.txt", content=content).json()
    assert r["chunks"] >= 1 and r["chars"] > 0
    ans = client.post("/api/research/ask",
                      json={"question": "what does the transformer use?", "doc_id": r["id"]}).json()
    assert "self-attention" in ans["answer"].lower()


def test_resume_upload_extracts_skills(client):
    content = b"Jane Dev. Python, FastAPI, Docker, Kubernetes, PyTorch engineer."
    r = client.put("/api/match/resumes/upload?name=jane.txt", content=content).json()
    assert "python" in r["skills"] and "kubernetes" in r["skills"]
    assert r["chars"] > 0


# ------------------------------- media studio -------------------------------- #
def test_media_status_is_honest(client):
    st = client.get("/api/media/status").json()
    assert "image" in st and "url" in st["image"]
    assert "Ollama" in st["note"]  # honest note that Ollama ≠ image gen


def test_media_image_without_backend_explains_how(client):
    # No Stable Diffusion running in CI → 501 with install instructions, not a crash.
    r = client.post("/api/media/image", json={"prompt": "a red spider"})
    assert r.status_code == 501
    assert "Stable Diffusion" in r.json()["detail"]
