"""Resume + job matching: resume → embedding → matching → skill gap →
learning roadmap → interview questions.

The ranking is the pipeline from the author's jobflow project (embed profile
once, embed each job once, cosine-rank, map to a 0–100 score) running on the
platform's offline embeddings. Skills are recognized against a curated tech
dictionary; the roadmap and interview questions use the model when one is
reachable and a solid static generator when not.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..core import db, llmutil
from ..core.text import cosine, embed, extract_text, match_score

SKILLS = sorted({
    "python", "java", "javascript", "typescript", "c", "c++", "c#", "go", "rust",
    "kotlin", "swift", "sql", "html", "css", "bash", "matlab", "r", "scala", "dart",
    "react", "vue", "angular", "next.js", "node", "node.js", "django", "flask",
    "fastapi", "spring", "spring boot", "express", ".net", "flutter", "react native",
    "postgresql", "mysql", "sqlite", "mongodb", "redis", "elasticsearch", "kafka",
    "rabbitmq", "celery", "qdrant", "neo4j",
    "docker", "kubernetes", "terraform", "ansible", "jenkins", "github actions",
    "ci/cd", "aws", "gcp", "azure", "linux", "git", "nginx", "grafana", "prometheus",
    "pytorch", "tensorflow", "keras", "scikit-learn", "pandas", "numpy", "opencv",
    "nlp", "computer vision", "deep learning", "machine learning", "llm", "langchain",
    "langgraph", "rag", "transformers", "hugging face", "ollama", "fine-tuning",
    "reinforcement learning", "mlops", "yolo", "whisper",
    "ros", "ros2", "autonomous driving", "slam", "sensor fusion", "can bus", "carla",
    "rest", "graphql", "grpc", "websockets", "microservices", "oauth", "jwt",
    "unit testing", "pytest", "selenium", "playwright", "agile", "scrum",
})


def extract_skills(text: str) -> List[str]:
    low = " " + re.sub(r"[,;/()|\n\t]", " ", text.lower()) + " "
    found = [s for s in SKILLS
             if re.search(r"(?<![a-z0-9])" + re.escape(s) + r"(?![a-z0-9+#])", low)]
    return sorted(found)


ROADMAP_RESOURCES = {
    "docker": "Docker's official Get Started guide, then containerize one of your own projects",
    "kubernetes": "kubernetes.io tutorials + run a local cluster with kind/minikube",
    "react": "react.dev tutorial, then rebuild one of your UIs in it",
    "fastapi": "FastAPI's tutorial (fastapi.tiangolo.com) — build a small CRUD API",
    "pytorch": "PyTorch 60-minute blitz, then reimplement a paper you like",
    "aws": "AWS Cloud Practitioner path + deploy a side project on ECS/Lambda",
    "kafka": "Confluent's Kafka 101 course, then wire a producer/consumer demo",
    "ros2": "The official ROS 2 tutorials (turtlesim → nav2), then replay a rosbag",
}


class ResumeIn(BaseModel):
    name: str
    text: Optional[str] = None
    path: Optional[str] = None  # .pdf/.docx/.txt on disk — parsed server-side


class JobPostIn(BaseModel):
    title: str
    company: Optional[str] = None
    description: str


# ------------------------------- pipeline ----------------------------------- #
def rank_jobs(resume: dict, posts: List[dict], top_k: int = 20) -> List[dict]:
    rvec = db.json_loads(resume["vec"], [])
    rskills = set(db.json_loads(resume["skills"], []))
    scored = []
    for p in posts:
        sim = cosine(rvec, db.json_loads(p["vec"], []))
        pskills = set(db.json_loads(p["skills"], []))
        overlap = len(rskills & pskills) / len(pskills) if pskills else 0
        # blend semantic similarity with hard skill overlap
        score = round(0.6 * match_score(sim) + 0.4 * 100 * overlap)
        scored.append({"id": p["id"], "title": p["title"], "company": p["company"],
                       "match": min(100, score),
                       "matching_skills": sorted(rskills & pskills),
                       "missing_skills": sorted(pskills - rskills)})
    scored.sort(key=lambda x: x["match"], reverse=True)
    return scored[:top_k]


def learning_roadmap(missing: List[str], job_title: str) -> Dict[str, Any]:
    llm = llmutil.ask(
        f"Create a compact learning roadmap (ordered steps, ~1 line each) for a candidate "
        f"missing these skills for a '{job_title}' role: {', '.join(missing)}. "
        f"Order by dependency, note roughly how many weeks each takes.")
    steps = [{"skill": s,
              "resource": ROADMAP_RESOURCES.get(
                  s, f"official {s} docs/tutorial, then use {s} in a small project"),
              "weeks": 2 if s in ROADMAP_RESOURCES else 3}
             for s in missing]
    return {"steps": steps, "llm_roadmap": llm}


def interview_questions(post: dict) -> Dict[str, Any]:
    skills = db.json_loads(post["skills"], [])
    llm = llmutil.ask(
        f"Write 8 interview questions (mix of conceptual and hands-on) for this role:\n"
        f"{post['title']} — {post['description'][:1500]}")
    generic = [f"Walk me through a project where you used {s}. What went wrong and how "
               f"did you debug it?" for s in skills[:5]]
    generic += [
        f"How would you design the architecture for the core system a {post['title']} owns?",
        "Tell me about a production incident you handled end to end.",
        "How do you decide what to test, and where do integration tests stop?"]
    return {"questions": generic[:8], "llm_questions": llm}


# ------------------------------- REST API ---------------------------------- #
router = APIRouter(prefix="/api/match", tags=["Job Matching"])


@router.post("/resumes")
def add_resume(body: ResumeIn) -> dict:
    text = body.text
    if not text and body.path:
        try:
            text = extract_text(body.path)
        except (FileNotFoundError, RuntimeError) as e:
            raise HTTPException(422, str(e))
    if not text or not text.strip():
        raise HTTPException(422, "provide resume 'text' or a readable 'path'")
    skills = extract_skills(text)
    rid = db.execute(
        "INSERT INTO resumes(name, text, skills, vec, created_at) VALUES(?,?,?,?,?)",
        (body.name, text, db.json_dumps(skills), db.json_dumps(embed(text)), db.now()))
    _graph_skills("You", skills)
    return {"id": rid, "name": body.name, "skills": skills}


def _graph_skills(person: str, skills: List[str]) -> None:
    """Connect a person to their skills in the knowledge graph."""
    try:
        from ..core import graph
        pid = graph.upsert_node("person", person)
        for s in skills:
            sid = graph.upsert_node(graph.TECH_TYPES.get(s, "skill"), s, bump=0.5)
            graph.link(pid, sid, "has_skill", 1.0)
    except Exception:
        pass


@router.put("/resumes/upload")
async def upload_resume(request: Request, name: str = "resume.txt") -> dict:
    """Raw-body resume upload (PDF/DOCX/TXT): text is extracted server-side,
    skills recognized, embedding stored — same as posting text."""
    body = await request.body()
    if not body:
        raise HTTPException(422, "empty body — send the file as the request body")
    safe = Path(name).name or "resume.txt"
    dest = db.data_dir() / "resumes"
    dest.mkdir(exist_ok=True)
    path = dest / safe
    path.write_bytes(body)
    try:
        text = extract_text(str(path))
    except RuntimeError as e:
        raise HTTPException(422, str(e))
    if not text.strip():
        raise HTTPException(422, f"no extractable text in {safe}")
    skills = extract_skills(text)
    rid = db.execute(
        "INSERT INTO resumes(name, text, skills, vec, created_at) VALUES(?,?,?,?,?)",
        (Path(safe).stem, text, db.json_dumps(skills), db.json_dumps(embed(text)), db.now()))
    return {"id": rid, "name": Path(safe).stem, "skills": skills, "chars": len(text)}


@router.get("/resumes")
def list_resumes() -> list:
    rows = db.query("SELECT id, name, skills, created_at FROM resumes ORDER BY id")
    for r in rows:
        r["skills"] = db.json_loads(r["skills"], [])
    return rows


@router.post("/jobs")
def add_jobs(body: List[JobPostIn]) -> dict:
    ids = []
    for j in body:
        text = f"{j.title}. {j.description}"
        ids.append(db.execute(
            "INSERT INTO job_posts(title, company, description, skills, vec, created_at)"
            " VALUES(?,?,?,?,?,?)",
            (j.title, j.company, j.description, db.json_dumps(extract_skills(text)),
             db.json_dumps(embed(text)), db.now())))
    return {"ids": ids}


@router.get("/jobs")
def list_jobs() -> list:
    rows = db.query("SELECT id, title, company, skills, created_at FROM job_posts ORDER BY id")
    for r in rows:
        r["skills"] = db.json_loads(r["skills"], [])
    return rows


@router.get("/resumes/{resume_id}/matches")
def matches(resume_id: int, top_k: int = 20) -> list:
    resume = db.one("SELECT * FROM resumes WHERE id=?", (resume_id,))
    if not resume:
        raise HTTPException(404, "resume not found")
    posts = db.query("SELECT * FROM job_posts")
    if not posts:
        raise HTTPException(404, "no job posts yet — POST /api/match/jobs first")
    return rank_jobs(resume, posts, top_k)


@router.get("/resumes/{resume_id}/gap/{job_id}")
def skill_gap(resume_id: int, job_id: int) -> dict:
    resume = db.one("SELECT * FROM resumes WHERE id=?", (resume_id,))
    post = db.one("SELECT * FROM job_posts WHERE id=?", (job_id,))
    if not resume or not post:
        raise HTTPException(404, "resume or job not found")
    have = set(db.json_loads(resume["skills"], []))
    need = set(db.json_loads(post["skills"], []))
    missing = sorted(need - have)
    return {"job": post["title"], "matching": sorted(have & need), "missing": missing,
            "roadmap": learning_roadmap(missing, post["title"]) if missing else None}


@router.get("/jobs/{job_id}/interview")
def interview(job_id: int) -> dict:
    post = db.one("SELECT * FROM job_posts WHERE id=?", (job_id,))
    if not post:
        raise HTTPException(404, "job not found")
    return interview_questions(post)


# ---------------- writer chains (ported from the author's jobflow) ------------- #
WRITER_RULES = (
    "You are an expert résumé writer and career coach. Write in clear, confident, "
    "recruiter-friendly language that sounds like a real human — not a keyword-stuffed "
    "corporate bot. Use strong, varied action verbs. Quantify impact whenever the profile "
    "supports it. Never invent facts, employers, dates, or qualifications not in the "
    "profile. Integrate job-description keywords naturally — never repeat them "
    "mechanically. Output clean Markdown only — no preamble, no commentary, no code fences.")


def _load_pair(resume_id: int, job_id: Optional[int]):
    resume = db.one("SELECT * FROM resumes WHERE id=?", (resume_id,))
    if not resume:
        raise HTTPException(404, "resume not found")
    post = None
    if job_id is not None:
        post = db.one("SELECT * FROM job_posts WHERE id=?", (job_id,))
        if not post:
            raise HTTPException(404, "job not found")
    return resume, post


@router.post("/resumes/{resume_id}/write")
def write_resume(resume_id: int, job_id: Optional[int] = None) -> dict:
    """Full ATS-friendly résumé in Markdown, optionally tailored to a job."""
    resume, post = _load_pair(resume_id, job_id)
    job_block = (f"TARGET JOB — weave its critical keywords into bullets where truthful:\n"
                 f"{post['title']} — {post['description'][:2000]}\n\n" if post else "")
    llm = llmutil.ask(
        f"Build a complete, ATS-friendly résumé in Markdown for this candidate.\n\n"
        f"CANDIDATE PROFILE:\n{resume['text'][:5000]}\n\n{job_block}"
        "Structure: Header · Professional Summary (2-3 grounded sentences, no clichés) · "
        "Core Skills (grouped by domain) · Experience (each role 3-5 quantified bullets) · "
        "Projects · Education. Roughly one page.",
        system=WRITER_RULES)
    if llm:
        return {"markdown": llm, "mode": "llm"}
    skills = db.json_loads(resume["skills"], [])
    return {"markdown": (f"# {resume['name']}\n\n## Professional Summary\n"
                         f"_(no model reachable — start Ollama for full writing)_\n\n"
                         f"## Core Skills\n{', '.join(skills) or '—'}\n\n"
                         f"## Profile (raw)\n{resume['text'][:1500]}"),
            "mode": "template"}


@router.post("/resumes/{resume_id}/cover-letter")
def cover_letter(resume_id: int, job_id: int) -> dict:
    resume, post = _load_pair(resume_id, job_id)
    llm = llmutil.ask(
        f"Write a tailored, human cover letter (250-350 words) in Markdown.\n\n"
        f"CANDIDATE PROFILE:\n{resume['text'][:4000]}\n\n"
        f"ROLE: {post['title']}\nCOMPANY: {post['company'] or 'the company'}\n\n"
        f"JOB DESCRIPTION:\n{post['description'][:2000]}\n\n"
        "Rules: open with a specific hook (never 'I am writing to apply'); map 2-3 real "
        "achievements to the job's stated needs; reference a relevant project by name if "
        "there is one; close with a confident, natural call to action; no placeholders.",
        system=WRITER_RULES)
    if llm:
        return {"markdown": llm, "mode": "llm"}
    shared = sorted(set(db.json_loads(resume["skills"], []))
                    & set(db.json_loads(post["skills"], [])))
    return {"markdown": (f"Dear {post['company'] or 'Hiring'} team,\n\n"
                         f"Your {post['title']} opening matches my background in "
                         f"{', '.join(shared[:4]) or 'the required stack'} directly. "
                         f"I'd welcome the chance to show how my project work maps to "
                         f"your needs.\n\nBest regards,\n{resume['name']}\n\n"
                         f"_(template fallback — start a model for the full letter)_"),
            "mode": "template"}


@router.get("/resumes/{resume_id}/ats/{job_id}")
def ats_analysis(resume_id: int, job_id: int) -> dict:
    """Brutally honest ATS fit report (jobflow's analyze chain; deterministic core)."""
    resume, post = _load_pair(resume_id, job_id)
    have = set(db.json_loads(resume["skills"], []))
    need = set(db.json_loads(post["skills"], []))
    ranked = rank_jobs(resume, [post], top_k=1)[0]
    missing = sorted(need - have)
    report = {
        "match_score": ranked["match"],
        "verdict": ("Strong fit — apply now." if ranked["match"] >= 70 else
                    "Borderline — close the gaps below before applying." if ranked["match"] >= 45
                    else "Weak fit as-is — this needs real upskilling, not resume polish."),
        "keywords": sorted(need)[:15],
        "present": sorted(have & need),
        "missing": missing,
        "advice": ([f"Build something real with {s} and put it in Projects" for s in missing[:3]]
                   + (["Quantify outcomes in every experience bullet"] if missing else
                      ["Mirror the job's exact terminology in your summary"]))[:5],
    }
    llm = llmutil.ask(
        "You are a brutally honest ATS analyst. Compare profile and job; do not flatter.\n\n"
        f"PROFILE:\n{resume['text'][:3000]}\n\nJOB:\n{post['description'][:2000]}\n\n"
        "Give: one-sentence verdict, top gaps, 3 concrete steps.")
    if llm:
        report["analyst_notes"] = llm
    return report
