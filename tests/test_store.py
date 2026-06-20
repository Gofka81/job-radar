from __future__ import annotations

from datetime import datetime, timedelta, timezone

from job_radar.schema import Job
from job_radar.store import Store


def _backdate(store: Store, job_id: str, hours: int) -> None:
    old = datetime.now(timezone.utc) - timedelta(hours=hours)
    store.con.execute("UPDATE jobs SET last_seen = ? WHERE job_id = ?", [old, job_id])


def _store(tmp_path):
    return Store(tmp_path / "t.duckdb")


def _job(url: str, *, title: str = "Data Engineer", **kw) -> Job:
    return Job(source="reed", company="Test", title=title, url=url, **kw)


def test_pending_lists_new_jobs_newest_first(tmp_path):
    s = _store(tmp_path)
    # distinct titles → distinct vacancies (same title would dedup to one row)
    assert s.upsert(_job("https://x/1", title="Data Engineer"))
    assert s.upsert(_job("https://x/2", title="Analytics Engineer"))
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


def test_list_jobs_q_searches_description(tmp_path):
    s = _store(tmp_path)
    s.upsert(Job(source="reed", company="Acme", title="Data Engineer", url="https://x/1",
                 description="You will build pipelines with Apache Spark and Airflow."))
    s.upsert(Job(source="reed", company="Beta", title="Data Engineer", url="https://x/2",
                 location="Glasgow", description="Snowflake and dbt shop, no big-data stack."))
    # "spark" is only in the JD of job 1, not in any title → still found
    spark = s.list_jobs(q="spark")
    assert [j["url"] for j in spark] == ["https://x/1"]
    # matches title/company too, case-insensitive
    assert len(s.list_jobs(q="DATA ENGINEER")) == 2
    assert [j["url"] for j in s.list_jobs(q="snowflake")] == ["https://x/2"]
    # description is searched but not shipped in the payload
    assert "description" not in spark[0]


def test_upsert_computes_location_cleaned(tmp_path):
    s = _store(tmp_path)
    s.upsert(_job("https://x/1", location="Sutton, London"))
    assert s.list_jobs()[0]["location_cleaned"] == "London"  # computed at insert


def test_upsert_dedups_reposts_of_same_vacancy(tmp_path):
    s = _store(tmp_path)
    # same role+city via different ad-ids/locations → one vacancy, one row
    j1 = Job(source="adzuna", company="Harnham", title="Senior Analytics Engineer",
             url="https://x/57013787", location="London")
    j2 = Job(source="adzuna", company="Harnham", title="Senior Analytics Engineer",
             url="https://x/57026970", location="London, UK")
    assert s.upsert(j1) is True
    assert s.upsert(j2) is False  # same role+city (London) → same job_id → merged
    assert len(s.list_jobs()) == 1
    assert s.list_jobs()[0]["url"] == "https://x/57013787"  # first-seen URL kept


def test_upsert_keeps_same_role_in_different_city(tmp_path):
    s = _store(tmp_path)
    s.upsert(Job(source="adzuna", company="BigCorp", title="Data Engineer", url="https://x/1", location="London"))
    s.upsert(Job(source="adzuna", company="BigCorp", title="Data Engineer", url="https://x/2", location="Edinburgh"))
    assert len(s.list_jobs()) == 2  # different city → distinct vacancies, not lost


def test_expire_marks_stale_new_job(tmp_path):
    s = _store(tmp_path)
    job = _job("https://x/1")
    s.upsert(job)
    _backdate(s, job.job_id, 100)  # last seen 100h ago
    assert s.expire_stale(24, ["reed"]) == 1
    assert s.list_jobs()[0]["status"] == "expired"  # marked, not deleted (row kept)
    assert s.pending_jobs() == []                   # dropped off the active feed


def test_expire_keeps_recent_job(tmp_path):
    s = _store(tmp_path)
    s.upsert(_job("https://x/1"))  # last_seen = now
    assert s.expire_stale(24, ["reed"]) == 0


def test_expire_keeps_human_verdict_history(tmp_path):
    s = _store(tmp_path)
    job = _job("https://x/1")
    s.upsert(job)
    s.mark_results([{"job_id": job.job_id, "status": "applied"}])
    _backdate(s, job.job_id, 100)
    assert s.expire_stale(24, ["reed"]) == 0  # applied = history, never expired


def test_expire_skips_sources_not_scanned(tmp_path):
    s = _store(tmp_path)
    job = _job("https://x/1")  # source = reed
    s.upsert(job)
    _backdate(s, job.job_id, 100)
    assert s.expire_stale(24, ["adzuna"]) == 0  # reed didn't scan OK → don't touch
    assert s.expire_stale(24, ["reed"]) == 1


def test_expired_job_reactivates_when_relisted(tmp_path):
    s = _store(tmp_path)
    job = _job("https://x/1")
    s.upsert(job)
    _backdate(s, job.job_id, 100)
    s.expire_stale(24, ["reed"])
    assert s.list_jobs()[0]["status"] == "expired"
    s.upsert(job)  # seen again in a later scan → reactivate
    assert s.list_jobs()[0]["status"] == "new"
    assert len(s.list_jobs()) == 1  # reactivated in place, not duplicated
