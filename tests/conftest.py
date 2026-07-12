"""Shared fixtures: a fresh platform database per test session and a TestClient
against the real app. No model is required — every AI path falls back."""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture(scope="session", autouse=True)
def isolated_db(tmp_path_factory):
    home = tmp_path_factory.mktemp("spidey-platform")
    os.environ["SPIDEY_DB"] = str(home / "test.db")
    os.environ["SPIDEY_PLATFORM_HOME"] = str(home)
    os.environ.pop("SPIDEY_TOKEN", None)
    # Force every internal LLM call to fail fast (Ollama 404s unknown models
    # instantly) so the suite always exercises the deterministic fallbacks —
    # same behavior whether or not a model server happens to be running.
    os.environ["SPIDEY_LLM_MODEL"] = "spidey-tests-no-model:0b"
    from spidey.platform.core import db
    db.reset_for_tests()
    yield


@pytest.fixture(scope="session")
def client(isolated_db):
    from fastapi.testclient import TestClient
    from spidey.server.app import create_app

    app = create_app()
    # TestClient's context manager fires startup/shutdown (queue + scheduler threads).
    with TestClient(app) as c:
        yield c


def wait_for_job(client, job_id: int, timeout: float = 10.0):
    """Poll the queue until a job settles; returns the final row."""
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        row = client.get(f"/api/queue/jobs/{job_id}").json()
        if row["status"] in ("done", "failed"):
            return row
        time.sleep(0.15)
    raise AssertionError(f"job {job_id} still {row['status']} after {timeout}s")
