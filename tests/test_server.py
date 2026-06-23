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
    job_id = s.list_jobs()[0]["job_id"]  # surrogate id assigned at insert
    s.close()
    monkeypatch.setenv(TOKEN_ENV, TOKEN)
    monkeypatch.setenv("JOB_RADAR_CONFIG", str(tmp_path / "config.yml"))  # never touch real config
    c = TestClient(create_app(str(db)))
    c.headers.update({"authorization": f"Bearer {TOKEN}"})
    return c, job_id


def test_healthz_is_open(tmp_path):
    c = TestClient(create_app(str(tmp_path / "h.duckdb")))
    assert c.get("/healthz").json() == {"ok": True}


def test_dashboard_served_open_at_root(tmp_path):
    c = TestClient(create_app(str(tmp_path / "h.duckdb")))
    r = c.get("/")  # HTML shell loads without a token
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "job-radar" in r.text
    assert "configView" in r.text and "cfgSave" in r.text  # config editor tab present


def test_jobs_endpoint_includes_salary(client):
    c, _ = client
    jobs = c.get("/api/jobs").json()["jobs"]
    assert set(jobs[0]) >= {"salary_min", "salary_max", "currency"}


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


def test_status_endpoint_tracks_apply(client):
    c, jid = client
    r = c.post("/api/status", json={"job_id": jid, "status": "applied"})
    assert r.status_code == 200 and r.json() == {"updated": True, "status": "applied"}
    jobs = c.get("/api/jobs").json()["jobs"]
    assert next(j for j in jobs if j["job_id"] == jid)["status"] == "applied"
    assert c.post("/api/status", json={"job_id": "nope", "status": "applied"}).status_code == 404
    assert c.post("/api/status", json={"job_id": jid, "status": "weird"}).status_code == 400  # bad status
    assert c.post("/api/status", json={"job_id": jid, "status": "viewed"},
                  headers={"authorization": "x"}).status_code == 401


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


# --- config endpoint ---

def test_get_config_returns_yaml(client):
    c, _ = client
    r = c.get("/api/config")
    assert r.status_code == 200
    assert "title_filter" in r.text  # example fallback (no saved config yet)


def test_post_config_saves_and_reloads(client):
    c, _ = client
    body = "title_filter:\n  positive:\n    - Spark\nsources:\n  reed:\n    enabled: true\n"
    r = c.post("/api/config", content=body, headers={"content-type": "text/plain"})
    assert r.status_code == 200 and r.json() == {"saved": True, "sources": ["reed"]}
    assert "Spark" in c.get("/api/config").text


def test_post_config_rejects_bad_yaml(client):
    c, _ = client
    r = c.post("/api/config", content="foo: [1, 2", headers={"content-type": "text/plain"})
    assert r.status_code == 400


# --- scan endpoint ---

def test_scan_requires_token(client):
    c, _ = client
    assert c.post("/api/scan", headers={"authorization": "x"}).status_code == 401
    assert c.get("/api/scan", headers={"authorization": "x"}).status_code == 401


def test_scan_now_triggers_run(client, monkeypatch):
    import time
    import job_radar.server as srv

    calls = []
    monkeypatch.setattr(srv, "run_scan", lambda cfg, db, **k: calls.append(db) or {"totals": {"found": 1}})
    c, _ = client
    r = c.post("/api/scan")
    assert r.status_code == 202 and r.json() == {"started": True}
    for _ in range(100):  # wait for the background thread
        if calls:
            break
        time.sleep(0.02)
    assert calls, "run_scan was not invoked"
    assert c.get("/api/scan").json()["last"]["totals"]["found"] == 1


def test_scan_409_when_already_running(client):
    import job_radar.server as srv

    c, _ = client
    srv._scan_lock.acquire()
    try:
        assert c.post("/api/scan").status_code == 409
    finally:
        srv._scan_lock.release()


def test_webhook_dispatches_without_secret(client):
    c, _ = client
    # no secret configured -> accepted; unknown user dropped by the allowlist
    r = c.post("/telegram/webhook",
               json={"message": {"from": {"id": 1}, "chat": {"id": 1}, "text": "/jobs"}})
    assert r.status_code == 200 and r.json() == {"ok": True}


def test_webhook_rejects_bad_secret(client, monkeypatch):
    import job_radar.server as srv
    monkeypatch.setitem(srv._WEBHOOK, "secret", "s3cr3t")
    c, _ = client
    r = c.post("/telegram/webhook", json={"message": {}},
               headers={"x-telegram-bot-api-secret-token": "wrong"})
    assert r.status_code == 403


def test_guarded_scan_single_flight(monkeypatch, tmp_path):
    import job_radar.server as srv

    monkeypatch.setenv("JOB_RADAR_CONFIG", str(tmp_path / "c.yml"))
    called = []
    monkeypatch.setattr(srv, "run_scan", lambda *a, **k: called.append(1) or {})
    srv._scan_lock.acquire()  # simulate a scan in progress
    try:
        srv._guarded_scan("db")  # must no-op, not block
    finally:
        srv._scan_lock.release()
    assert called == []
