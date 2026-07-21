from __future__ import annotations

import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

from job_radar import analyze
from job_radar.analyze import Triage, run_analyze
from job_radar.schema import Job
from job_radar.server import TOKEN_ENV, create_app
from job_radar.store import Store

CFG = {"analysis": {"model": "claude-haiku-4-5"}}  # engine defaults to claude-cli
U = {"input_tokens": 100, "output_tokens": 20, "cache_read_tokens": 80, "cache_write_tokens": 0}


def _seed(db, n=2):
    """Insert n pending jobs with a JD; return their job_ids (newest first)."""
    s = Store(db)
    for i in range(n):
        s.upsert(Job(source="reed", company=f"Co{i}", title="Data Engineer",
                     url=f"https://x/{i}", description="PySpark on AWS, Delta Lake"))
    ids = [j["job_id"] for j in s.list_jobs()]
    s.close()
    return ids


# --- store writeback -----------------------------------------------------

def test_apply_analysis_writes_score_and_reason_only(tmp_path):
    db = tmp_path / "a.duckdb"
    jid = _seed(db, 1)[0]
    s = Store(db)
    assert s.apply_analysis(jid, score=8, reason="strong Spark fit", engine="anthropic:x")
    row = s.list_jobs()[0]
    assert row["score"] == 8 and row["eval_reason"] == "strong Spark fit"
    assert row["status"] == "new"           # workflow lane untouched → still pending
    assert s.pending_jobs()[0]["job_id"] == jid
    s.close()


def test_apply_analysis_unknown_job_returns_false(tmp_path):
    s = Store(tmp_path / "a.duckdb")
    assert s.apply_analysis("nope", score=5, reason="x", engine="y") is False
    s.close()


def test_jd_enrichment_flag_and_apply(tmp_path):
    db = tmp_path / "j.duckdb"
    s = Store(db)
    s.upsert(Job(source="reed", company="A", title="DE", url="https://x/1",
                 description="snip", jd_full=False, raw={"jobId": "9"}))
    s.upsert(Job(source="greenhouse", company="B", title="DE", url="https://x/2",
                 description="full jd", jd_full=True))
    need = s.jobs_needing_full_jd()
    assert len(need) == 1 and need[0]["source"] == "reed"   # only the Reed snippet
    assert need[0]["raw"]["jobId"] == "9"                   # raw carries the detail id
    jid = need[0]["job_id"]
    assert s.apply_full_jd(jid, "the full jd text") is True
    assert s.jobs_needing_full_jd() == []                   # flag flipped → never re-fetched
    assert s.apply_full_jd("nope", "x") is False
    s.close()


def test_set_status_preserves_score_and_reason(tmp_path):
    db = tmp_path / "a.duckdb"
    jid = _seed(db, 1)[0]
    s = Store(db)
    s.apply_analysis(jid, score=8, reason="fit", engine="claude-cli:x")
    assert s.set_status(jid, "applied") is True        # apply-tracking
    row = s.list_jobs()[0]
    assert row["status"] == "applied"                  # status changed…
    assert row["score"] == 8 and row["eval_reason"] == "fit"  # …score/reason intact
    assert s.set_status("nope", "applied") is False    # unknown job
    with pytest.raises(ValueError):
        s.set_status(jid, "garbage")                   # not a settable status
    s.close()


def test_archived_job_is_never_analyzed(tmp_path):
    """Hidden (dismissed) jobs must never be triaged — the worker only ever selects
    status='new', so archived is structurally excluded from every path."""
    db = tmp_path / "a.duckdb"
    jid = _seed(db, 1)[0]
    s = Store(db)
    s.set_status(jid, "archived")
    assert s.jobs_for_analysis() == []                          # batch path
    assert s.jobs_for_analysis([jid], only_untriaged=False) == []  # explicit per-card target
    s.close()


def test_jobs_for_analysis_skips_already_triaged(tmp_path):
    db = tmp_path / "a.duckdb"
    ids = _seed(db, 2)
    s = Store(db)
    s.apply_analysis(ids[0], score=7, reason="done", engine="e")
    todo = [j["job_id"] for j in s.jobs_for_analysis()]      # only_untriaged default
    assert ids[0] not in todo and ids[1] in todo
    assert len(s.jobs_for_analysis(only_untriaged=False)) == 2  # re-score all
    s.close()


# --- worker --------------------------------------------------------------

def test_run_analyze_scores_and_survives_a_bad_job(tmp_path, monkeypatch):
    db = tmp_path / "a.duckdb"
    ids = _seed(db, 2)
    monkeypatch.setattr(analyze, "load_rubric", lambda: "score data engineers 0-10")

    def fake_score(model, rubric, job, **k):     # claude-cli seam — no real CLI/network
        if job["company"] == "Co0":
            raise RuntimeError("boom")          # one bad job must not kill the run
        return Triage(score=8, reason="great"), U

    monkeypatch.setattr(analyze, "_score_cli", fake_score)
    result = run_analyze(CFG, str(db))

    assert result["totals"] == {"jobs": 2, "scored": 1, "errors": 1, "skipped": 0}
    assert result["usage"]["input_tokens"] == 100  # accumulated from the one good job
    assert result["cost_usd"] > 0 and result["budget_hit"] is False
    scored = [j for j in Store(db).list_jobs() if j["score"] is not None]
    assert len(scored) == 1 and scored[0]["score"] == 8  # only the good job written


def test_run_analyze_caps_jobs_per_run(tmp_path, monkeypatch):
    """The cost ceiling: never score more than analysis.max_jobs in one run, and
    report what was skipped rather than silently dropping it."""
    db = tmp_path / "a.duckdb"
    _seed(db, 3)
    monkeypatch.setattr(analyze, "load_rubric", lambda: "r")
    monkeypatch.setattr(analyze, "_score_cli", lambda *a, **k: (Triage(score=5, reason="ok"), U))

    cfg = {"analysis": {"max_jobs": 2}}
    result = run_analyze(cfg, str(db))
    assert result["totals"] == {"jobs": 2, "scored": 2, "errors": 0, "skipped": 1}


def test_run_analyze_stops_on_budget_limit(tmp_path, monkeypatch):
    """A rate/billing error stops the run cleanly: budget_hit flagged, partial
    results kept, run still recorded in the usage ledger."""
    db = tmp_path / "a.duckdb"
    _seed(db, 3)
    monkeypatch.setattr(analyze, "load_rubric", lambda: "r")

    calls = {"n": 0}

    def fake_score(*a, **k):
        calls["n"] += 1
        if calls["n"] == 2:                       # second job: out of budget
            raise RuntimeError("Claude usage limit reached")
        return Triage(score=7, reason="ok"), U

    monkeypatch.setattr(analyze, "_score_cli", fake_score)
    result = run_analyze(CFG, str(db))

    assert result["budget_hit"] is True
    assert result["totals"]["scored"] == 1        # stopped after the first
    assert calls["n"] == 2                         # did NOT keep hammering the API
    usage = Store(db).llm_usage()
    assert usage["totals"]["runs"] == 1 and usage["runs"][0]["budget_hit"] is True


def test_is_budget_error_detects_rate_and_billing():
    assert analyze._is_budget_error(type("RateLimitError", (Exception,), {})("x"))
    assert analyze._is_budget_error(RuntimeError("Your credit balance is too low"))
    assert analyze._is_budget_error(RuntimeError("HTTP 429 Too Many Requests"))
    assert not analyze._is_budget_error(RuntimeError("bad json"))


def test_is_auth_error_detects_not_logged_in():
    assert analyze._is_auth_error(RuntimeError("claude: Not logged in · Please run /login"))
    assert analyze._is_auth_error(RuntimeError("invalid x-api-key"))
    assert analyze._is_auth_error(type("AuthenticationError", (Exception,), {})("x"))
    assert not analyze._is_auth_error(RuntimeError("bad json"))
    # auth must NOT be misread as budget (the prod bug)
    assert not analyze._is_budget_error(RuntimeError("claude: Not logged in · Please run /login"))


def test_run_analyze_stops_fast_on_auth_error(tmp_path, monkeypatch):
    """'Not logged in' fails every job → stop after the FIRST with auth_failed, not
    budget_hit, and don't hammer the CLI for all 88 jobs."""
    db = tmp_path / "a.duckdb"
    _seed(db, 5)
    monkeypatch.setattr(analyze, "load_rubric", lambda: "r")
    calls = {"n": 0}

    def fake(*a, **k):
        calls["n"] += 1
        raise RuntimeError("claude: Not logged in · Please run /login")

    monkeypatch.setattr(analyze, "_score_cli", fake)
    result = run_analyze(CFG, str(db))

    assert result["auth_failed"] is True and result["budget_hit"] is False
    assert calls["n"] == 1 and result["totals"]["scored"] == 0  # stopped after one


def test_run_analyze_requires_rubric(tmp_path, monkeypatch):
    _seed(tmp_path / "a.duckdb", 1)
    monkeypatch.setattr(analyze, "load_rubric", lambda: "")  # no rubric saved
    with pytest.raises(RuntimeError, match="rubric"):
        run_analyze({"analysis": {}}, str(tmp_path / "a.duckdb"))


def test_parse_triage_tolerates_wrapped_json():
    assert analyze._parse_triage('{"score": 7, "reason": "ok"}').score == 7
    # fenced / prose-wrapped output (the CLI may not honour a strict schema)
    tri = analyze._parse_triage('Here you go:\n```json\n{"score": 99, "reason": "x"}\n```')
    assert tri.score == 10 and tri.reason == "x"   # 99 clamped to 10


def test_score_cli_invokes_claude_and_parses(monkeypatch):
    """claude-cli engine: fake `claude -p` envelope → parse + usage + model alias.
    No real CLI/subscription call is made."""
    import subprocess

    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        envelope = {
            "type": "result", "subtype": "success", "is_error": False,
            "result": '{"score": -3, "reason": "irrelevant"}',
            "usage": {"input_tokens": 1200, "output_tokens": 40,
                      "cache_read_input_tokens": 1000},
        }
        return type("P", (), {"returncode": 0, "stdout": json.dumps(envelope), "stderr": ""})()

    monkeypatch.setattr(subprocess, "run", fake_run)
    tri, used = analyze._score_cli("claude-haiku-4-5", "rubric", {"title": "DE", "description": "x"})

    assert tri.score == 0 and tri.reason == "irrelevant"        # -3 clamped to 0
    assert used["input_tokens"] == 1200 and used["cache_read_tokens"] == 1000
    assert "haiku" in seen["cmd"] and "--allowed-tools" in seen["cmd"]  # alias + tool-less


def test_score_cli_raises_on_failure(monkeypatch):
    import subprocess
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw:
                        type("P", (), {"returncode": 1, "stdout": "", "stderr": "usage limit reached"})())
    try:
        analyze._score_cli("claude-haiku-4-5", "r", {"title": "x"})
        assert False, "should have raised"
    except RuntimeError as e:
        assert analyze._is_budget_error(e)  # surfaces as out-of-budget


# --- endpoints -----------------------------------------------------------

@pytest.fixture
def client(tmp_path, monkeypatch):
    db = tmp_path / "api.duckdb"
    _seed(db, 1)
    monkeypatch.setenv(TOKEN_ENV, "tok")
    monkeypatch.setenv("JOB_RADAR_CONFIG", str(tmp_path / "config.yml"))
    monkeypatch.setenv("JOB_RADAR_RUBRIC", str(tmp_path / "rubric.md"))  # never touch real rubric
    c = TestClient(create_app(str(db)))
    c.headers.update({"authorization": "Bearer tok"})
    return c


@pytest.fixture(autouse=True)
def _reset_analyze_queue():
    """The triage queue + worker are module-global; drain and reset their state
    between tests so the shared worker can't leak tasks or dedup flags across tests."""
    import job_radar.server as srv

    def _reset():
        with srv._analyze_lock:
            while not srv._analyze_q.empty():
                try:
                    srv._analyze_q.get_nowait()
                    srv._analyze_q.task_done()
                except Exception:
                    break
            srv._queued_batch = False
            srv._queued_singles.clear()
            srv._analyze_state.update(running=False, current=None, last=None)

    _reset()
    yield
    _reset()


def _wait(pred, timeout=2.0):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.01)
    return False


def test_analyze_requires_token(client):
    assert client.post("/api/analyze", headers={"authorization": "x"}).status_code == 401
    assert client.get("/api/analyze", headers={"authorization": "x"}).status_code == 401


def test_analyze_rejects_non_triage_mode(client):
    assert client.post("/api/analyze", json={"mode": "deep"}).status_code == 400


def test_analyze_batch_enqueues_and_runs(client, monkeypatch):
    import job_radar.server as srv

    calls = []
    monkeypatch.setattr(srv, "run_analyze",
                        lambda cfg, db, **k: calls.append(k) or {"totals": {"scored": 1}})
    r = client.post("/api/analyze", json={"mode": "triage", "target": "all_pending"})
    assert r.status_code == 202
    body = r.json()
    assert body["queued"] is True and body["kind"] == "batch"
    assert _wait(lambda: bool(calls)), "worker never ran the task"
    assert calls[0]["only_untriaged"] is True and calls[0]["job_ids"] is None
    assert _wait(lambda: client.get("/api/analyze").json()["last"] is not None)
    assert client.get("/api/analyze").json()["last"]["totals"]["scored"] == 1


def test_analyze_target_job_ids_rescores(client, monkeypatch):
    import job_radar.server as srv

    calls = []
    monkeypatch.setattr(srv, "run_analyze", lambda cfg, db, **k: calls.append(k) or {})
    r = client.post("/api/analyze", json={"mode": "triage", "target": ["abc"]})
    assert r.status_code == 202 and r.json()["kind"] == "single"
    assert _wait(lambda: bool(calls))
    assert calls[0]["job_ids"] == ["abc"] and calls[0]["only_untriaged"] is False


def test_analyze_queue_dedups_batch_while_running(client, monkeypatch):
    """A second batch, while one is queued/running, is a no-op dedup (not a new run)."""
    import job_radar.server as srv

    gate, started = threading.Event(), threading.Event()

    def blocking(cfg, db, **k):
        started.set()
        gate.wait(2)
        return {"totals": {"scored": 0}}

    monkeypatch.setattr(srv, "run_analyze", blocking)
    assert client.post("/api/analyze", json={"mode": "triage"}).json()["queued"] is True
    assert started.wait(2), "worker never started the first batch"
    dup = client.post("/api/analyze", json={"mode": "triage"}).json()
    assert dup["queued"] is False and dup["duplicate"] is True
    gate.set()  # let the first batch finish so the queue drains


def test_analyze_dedups_same_single_job(client, monkeypatch):
    """Two ✨ clicks on the same job while it's in flight enqueue only once."""
    import job_radar.server as srv

    gate, started = threading.Event(), threading.Event()
    monkeypatch.setattr(srv, "run_analyze",
                        lambda cfg, db, **k: (started.set(), gate.wait(2), {})[-1])
    assert client.post("/api/analyze", json={"mode": "triage", "target": ["j1"]}).json()["queued"] is True
    assert started.wait(2)
    dup = client.post("/api/analyze", json={"mode": "triage", "target": ["j1"]}).json()
    assert dup["queued"] is False and dup["duplicate"] is True
    gate.set()


# --- rubric endpoint -----------------------------------------------------

def test_rubric_requires_token(client):
    assert client.get("/api/rubric", headers={"authorization": "x"}).status_code == 401


def test_rubric_get_returns_example_then_saved(client):
    # none saved yet → baked example fallback
    assert "Candidate" in client.get("/api/rubric").text
    r = client.post("/api/rubric", content="# my rubric\nscore 0-10",
                    headers={"content-type": "text/plain"})
    assert r.status_code == 200 and r.json() == {"saved": True}
    assert "my rubric" in client.get("/api/rubric").text  # round-trips


def test_rubric_rejects_empty(client):
    r = client.post("/api/rubric", content="   ", headers={"content-type": "text/plain"})
    assert r.status_code == 400


# --- usage endpoint ------------------------------------------------------

def test_usage_requires_token(client):
    assert client.get("/api/usage", headers={"authorization": "x"}).status_code == 401


def test_usage_returns_shape_and_zeros(client):
    payload = client.get("/api/usage").json()
    assert set(payload) == {"runs", "totals", "by_engine"}
    assert payload["runs"] == [] and payload["totals"]["runs"] == 0  # none recorded yet


def test_record_and_summarise_usage(tmp_path):
    from datetime import datetime, timezone
    s = Store(tmp_path / "u.duckdb")
    s.record_llm_run(
        "r1", stage="triage", model="claude-haiku-4-5", engine="claude-cli",
        started=datetime.now(timezone.utc), jobs=3, scored=2, errors=1,
        usage={"input_tokens": 300, "output_tokens": 60,
               "cache_read_tokens": 200, "cache_write_tokens": 0},
        cost_usd=0.0012,
    )
    summary = s.llm_usage()
    assert summary["totals"] == {
        "scored": 2, "calls": 3, "input_tokens": 300, "output_tokens": 60,  # calls = scored+errors
        "cache_read_tokens": 200, "cost_usd": 0.0012, "runs": 1,
    }
    assert summary["by_engine"][0] == {"engine": "claude-cli", "runs": 1, "calls": 3, "cost_usd": 0.0012}
    s.close()
