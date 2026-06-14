from __future__ import annotations

from job_radar.schema import Job
from job_radar.store import Store


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
