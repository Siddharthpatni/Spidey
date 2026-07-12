"""Multi-agent team: Planner → Researcher → Coder → Reviewer → Tester →
Documentation, with shared Memory.

Each role is a focused model call that receives the goal plus everything the
roles before it produced (the shared memory), so the pipeline compounds:
the Reviewer critiques the Coder's actual output, the Tester writes tests for
the reviewed design, the Documentation agent describes what was really built.
Runs execute on the platform queue (they're long); the transcript of every
role's contribution is stored and streamed back over GET /runs/{id}.

This generalizes Spidey's role-router: instead of dispatching to ONE Spider,
the whole team swings at the problem in sequence.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..core import db, llmutil, notify

ROLES: List[Dict[str, str]] = [
    {"name": "planner",
     "system": "You are the Planner. Break the goal into 3-7 concrete, ordered steps. "
               "Note risks and what 'done' looks like. Be terse."},
    {"name": "researcher",
     "system": "You are the Researcher. Given the goal and plan, lay out the key facts, "
               "APIs, algorithms and pitfalls the Coder must know. Cite assumptions."},
    {"name": "coder",
     "system": "You are the Coder. Implement the plan as complete, runnable code with "
               "file paths. No placeholders — write the real logic."},
    {"name": "reviewer",
     "system": "You are the Reviewer. Find correctness bugs, edge cases and design flaws "
               "in the Coder's output. Severity-ordered list; propose concrete fixes."},
    {"name": "tester",
     "system": "You are the Tester. Write runnable tests (pytest if Python) covering the "
               "happy path, the edge cases the Reviewer raised, and failure modes."},
    {"name": "documentation",
     "system": "You are the Documentation agent. Write the README section for what was "
               "built: what it does, how to run it, API/usage examples."},
]


class RunIn(BaseModel):
    goal: str
    roles: Optional[List[str]] = None  # subset, e.g. ["planner", "coder"]; default all


def run_pipeline(run_id: int, goal: str, selected: Optional[List[str]]) -> Dict[str, Any]:
    roles = [r for r in ROLES if not selected or r["name"] in selected]
    memory: List[Dict[str, str]] = []  # shared memory: every role's contribution
    db.execute("UPDATE team_runs SET status='running' WHERE id=?", (run_id,))
    for role in roles:
        context = "\n\n".join(f"### {m['role'].upper()}\n{m['output']}" for m in memory)
        prompt = (f"GOAL: {goal}\n\n"
                  + (f"WORK SO FAR:\n{context}\n\n" if context else "")
                  + f"Produce the {role['name']}'s contribution now.")
        output = llmutil.ask(prompt, system=role["system"])
        if output is None:
            db.execute("UPDATE team_runs SET status='failed', transcript=?, finished_at=?"
                       " WHERE id=?",
                       (db.json_dumps(memory), db.now(), run_id))
            raise RuntimeError(
                "the team needs a model — start Ollama (`spidey up`) or set "
                "SPIDEY_LLM_PROVIDER/SPIDEY_LLM_MODEL to a configured provider")
        memory.append({"role": role["name"], "output": output})
        # stream progress into the row so GET /runs/{id} shows live state
        db.execute("UPDATE team_runs SET transcript=? WHERE id=?",
                   (db.json_dumps(memory), run_id))
    db.execute("UPDATE team_runs SET status='done', finished_at=? WHERE id=?",
               (db.now(), run_id))
    notify.emit("team.run_done", {"run_id": run_id, "roles": [m["role"] for m in memory]})
    return {"roles_completed": [m["role"] for m in memory]}


def _job_run(payload: Dict[str, Any]) -> Dict[str, Any]:
    return run_pipeline(payload["run_id"], payload["goal"], payload.get("roles"))


def register_jobs(queue) -> None:
    queue.register("team.run", _job_run)


# ------------------------------- REST API ---------------------------------- #
router = APIRouter(prefix="/api/team", tags=["Multi-Agent Team"])


@router.get("/roles")
def roles() -> list:
    return [{"name": r["name"], "charter": r["system"]} for r in ROLES]


@router.post("/runs")
def start_run(body: RunIn) -> dict:
    if not body.goal.strip():
        raise HTTPException(422, "goal is required")
    known = {r["name"] for r in ROLES}
    if body.roles and not set(body.roles) <= known:
        raise HTTPException(422, f"unknown roles: {sorted(set(body.roles) - known)}")
    run_id = db.execute("INSERT INTO team_runs(goal, created_at) VALUES(?,?)",
                        (body.goal, db.now()))
    from ..core.queue import default_queue
    default_queue().enqueue("team.run", {"run_id": run_id, "goal": body.goal,
                                         "roles": body.roles}, max_attempts=1)
    return {"id": run_id, "status": "queued",
            "note": "poll GET /api/team/runs/{id} — the transcript grows role by role"}


@router.get("/runs")
def list_runs(limit: int = 20) -> list:
    return db.query("SELECT id, goal, status, created_at, finished_at FROM team_runs"
                    " ORDER BY id DESC LIMIT ?", (limit,))


@router.get("/runs/{run_id}")
def get_run(run_id: int) -> dict:
    row = db.one("SELECT * FROM team_runs WHERE id=?", (run_id,))
    if not row:
        raise HTTPException(404, "run not found")
    row["transcript"] = db.json_loads(row["transcript"], [])
    return row
