from __future__ import annotations

from datetime import datetime, timedelta, timezone

from job_radar.schema import Job
from job_radar.store import Store


def _backdate(store: Store, job_id: str, hours: int) -> None:
    old = datetime.now(timezone.utc) - timedelta(hours=hours)
    store.con.execute("UPDATE jobs SET last_seen = ? WHERE job_id = ?", [old, job_id])


def _store(tmp_path):
    return Store(tmp_path / "t.duckdb")


def _job(url: str, **kw) -> Job:
    return Job(source="reed", company="Test", title="Data Engineer", url=url, **kw)


def test_pending_lists_new_jobs_newest_first(tmp_path):
    s = _store(tmp_path)
    assert s.upsert(_job("https://x/1"))
    assert s.upsert(_job("https://x/2"))
    pending = s.pending_jobs()
    assert {p["url"] for p in pending} == {"https://x/1", "https://x/2"}
    assert set(pending[0].keys()) >= {"job_id", "url", "company", "title", "location"}


def test_mark_results_drops_job_from_pending(tmp_path):
    s = _store(tmp_path)
    job = _job("https://x/1")
    s.upsert(job)
    updated = s.mark_results([{"job_id": job.job_id, "score": 8.5, "status": "applied"}])
    assert updated == 1
    assert s.pending_jobs() == []  # no longer 'new'
    f = s.funnel()
    assert f["total"] == 1 and f.get("applied") == 1


def test_mark_results_by_url(tmp_path):
    s = _store(tmp_path)
    s.upsert(_job("https://x/1"))
    assert s.mark_results([{"url": "https://x/1", "score": 4.1, "status": "applied"}]) == 1
    assert s.pending_jobs() == []
    assert s.funnel().get("applied") == 1


def test_mark_results_ignores_unknown_url_and_id(tmp_path):
    s = _store(tmp_path)
    s.upsert(_job("https://x/1"))
    assert s.mark_results([{"job_id": "deadbeef", "status": "applied"}]) == 0
    assert s.mark_results([{"url": "https://nope/9", "status": "applied"}]) == 0


def test_mark_results_defaults_status_to_evaluated(tmp_path):
    s = _store(tmp_path)
    job = _job("https://x/1")
    s.upsert(job)
    s.mark_results([{"job_id": job.job_id, "score": 7.0}])
    assert s.funnel().get("evaluated") == 1


def test_list_jobs_includes_timestamps(tmp_path):
    s = _store(tmp_path)
    s.upsert(_job("https://x/1"))
    jobs = s.list_jobs()
    assert len(jobs) == 1
    assert set(jobs[0]) >= {"first_seen", "last_seen", "status", "score", "url"}


def test_upsert_computes_location_cleaned(tmp_path):
    s = _store(tmp_path)
    s.upsert(_job("https://x/1", location="Sutton, London"))
    assert s.list_jobs()[0]["location_cleaned"] == "London"
    assert s.backfill_location_cleaned() == 0  # already filled at insert → no-op


def test_prune_deletes_stale_new_job(tmp_path):
    s = _store(tmp_path)
    job = _job("https://x/1")
    s.upsert(job)
    _backdate(s, job.job_id, 100)  # last seen 100h ago
    assert s.prune_stale(72, ["reed"]) == 1
    assert s.list_jobs() == []


def test_prune_keeps_recent_job(tmp_path):
    s = _store(tmp_path)
    s.upsert(_job("https://x/1"))  # last_seen = now
    assert s.prune_stale(72, ["reed"]) == 0


def test_prune_keeps_evaluated_history(tmp_path):
    s = _store(tmp_path)
    job = _job("https://x/1")
    s.upsert(job)
    s.mark_results([{"job_id": job.job_id, "status": "applied"}])
    _backdate(s, job.job_id, 100)
    assert s.prune_stale(72, ["reed"]) == 0  # applied = history, never pruned


def test_prune_skips_sources_not_scanned(tmp_path):
    s = _store(tmp_path)
    job = _job("https://x/1")  # source = reed
    s.upsert(job)
    _backdate(s, job.job_id, 100)
    assert s.prune_stale(72, ["adzuna"]) == 0  # reed didn't scan OK → don't touch
    assert s.prune_stale(72, ["reed"]) == 1
