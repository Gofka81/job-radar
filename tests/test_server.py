from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from job_radar.schema import Job
from job_radar.server import TOKEN_ENV, create_app
from job_radar.store import Store

TOKEN = "test-secret"


@pytest.fixture
def client(tmp_path, monkeypatch):
    db = tmp_path / "api.duckdb"
    s = Store(db)
    job = Job(source="reed", company="Test", title="Data Engineer", url="https://x/1")
    s.upsert(job)
    s.close()
    monkeypatch.setenv(TOKEN_ENV, TOKEN)
    c = TestClient(create_app(str(db)))
    c.headers.update({"authorization": f"Bearer {TOKEN}"})
    return c, job.job_id


def test_healthz_is_open(tmp_path):
    c = TestClient(create_app(str(tmp_path / "h.duckdb")))
    assert c.get("/healthz").json() == {"ok": True}


def test_pending_requires_token(client):
    c, _ = client
    assert c.get("/api/pending", headers={"authorization": "Bearer wrong"}).status_code == 401
    assert c.get("/api/pending", headers={"authorization": ""}).status_code == 401


def test_pending_returns_jobs(client):
    c, jid = client
    jobs = c.get("/api/pending").json()["jobs"]
    assert [j["job_id"] for j in jobs] == [jid]


def test_results_roundtrip_marks_evaluated(client):
    c, jid = client
    r = c.post("/api/results", json={"results": [{"job_id": jid, "score": 9.0, "status": "applied"}]})
    assert r.json() == {"updated": 1, "received": 1}
    assert c.get("/api/pending").json()["jobs"] == []  # dropped from pending
    assert c.get("/api/funnel").json().get("applied") == 1


def test_results_requires_token(client):
    c, jid = client
    r = c.post(
        "/api/results",
        json={"results": [{"job_id": jid}]},
        headers={"authorization": "Bearer nope"},
    )
    assert r.status_code == 401


def test_fails_closed_without_server_token(tmp_path, monkeypatch):
    monkeypatch.delenv(TOKEN_ENV, raising=False)
    c = TestClient(create_app(str(tmp_path / "n.duckdb")))
    # No token configured server-side => refuse rather than serve open.
    assert c.get("/api/pending", headers={"authorization": "Bearer anything"}).status_code == 503
