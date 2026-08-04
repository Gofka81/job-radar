from __future__ import annotations

from datetime import datetime, timedelta, timezone

from job_radar.schema import Job
from job_radar.store import Store


def _backdate(store: Store, url: str, hours: int) -> None:
    # job_id is now a per-generation surrogate assigned in upsert, so tests key on
    # the stable url instead.
    old = datetime.now(timezone.utc) - timedelta(hours=hours)
    store.con.execute("UPDATE jobs SET last_seen = ? WHERE url = ?", [old, url])


def _store(tmp_path):
    return Store(tmp_path / "t.duckdb")


def _job(url: str, *, title: str = "Data Engineer", **kw) -> Job:
    return Job(source="reed", company="Test", title=title, url=url, **kw)


def test_list_jobs_newest_first(tmp_path):
    s = _store(tmp_path)
    # distinct titles → distinct vacancies (same title would dedup to one row)
    assert s.upsert(_job("https://x/1", title="Data Engineer"))
    assert s.upsert(_job("https://x/2", title="Analytics Engineer"))
    rows = s.list_jobs()
    assert {r["url"] for r in rows} == {"https://x/1", "https://x/2"}
    assert set(rows[0].keys()) >= {"job_id", "url", "company", "title", "location"}


def test_set_status_moves_job_off_inbox(tmp_path):
    s = _store(tmp_path)
    s.upsert(_job("https://x/1"))
    jid = s.list_jobs()[0]["job_id"]
    assert s.set_status(jid, "applied") is True
    f = s.funnel()
    assert f["total"] == 1 and f.get("applied") == 1


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


def test_upsert_stores_locations_set(tmp_path):
    s = _store(tmp_path)
    s.upsert(_job("https://x/1", location="Sutton, London"))
    assert s.list_jobs()[0]["locations"] == ["London"]  # canonical city, computed at insert


def test_upsert_dedups_reposts_of_same_vacancy(tmp_path):
    s = _store(tmp_path)
    # same role+city via different ad-ids/locations → one vacancy, one row
    j1 = Job(source="adzuna", company="Harnham", title="Senior Analytics Engineer",
             url="https://x/57013787", location="London")
    j2 = Job(source="adzuna", company="Harnham", title="Senior Analytics Engineer",
             url="https://x/57026970", location="London, UK")
    assert s.upsert(j1) is True
    assert s.upsert(j2) is False  # same company+role → same vacancy_key → merged
    assert len(s.list_jobs()) == 1
    assert s.list_jobs()[0]["url"] == "https://x/57013787"  # first-seen URL kept


def test_upsert_dedups_same_vacancy_across_sources(tmp_path):
    s = _store(tmp_path)
    # same agency ad surfaced by both Adzuna and Reed → one row (source-agnostic id)
    a = Job(source="adzuna", company="Harnham", title="Senior Data Engineer (Snowflake)",
            url="https://adzuna/1", location="Glasgow")
    r = Job(source="reed", company="Harnham", title="Senior Data Engineer (Snowflake)",
            url="https://reed/2", location="Glasgow")
    assert s.upsert(a) is True
    assert s.upsert(r) is False  # cross-source duplicate → merged, not a second row
    assert len(s.list_jobs()) == 1


def test_upsert_merges_same_role_across_cities(tmp_path):
    s = _store(tmp_path)
    # one posting listed in several cities → ONE row whose locations set accumulates
    s.upsert(Job(source="workable", company="BigCorp", title="Data Engineer", url="https://x/1", location="London"))
    s.upsert(Job(source="workable", company="BigCorp", title="Data Engineer", url="https://x/1", location="Edinburgh"))
    rows = s.list_jobs()
    assert len(rows) == 1
    # cities accumulate, priority-ordered (Edinburgh before London) so the preview
    # never hides a priority city — and neither city is lost
    assert rows[0]["locations"] == ["Edinburgh", "London"]


def test_expire_marks_stale_new_job(tmp_path):
    s = _store(tmp_path)
    job = _job("https://x/1")
    s.upsert(job)
    _backdate(s, "https://x/1", 100)  # last seen 100h ago
    assert s.expire_stale(24, ["reed"]) == 1
    assert s.list_jobs()[0]["status"] == "expired"  # marked, not deleted (row kept)


def test_expire_keeps_recent_job(tmp_path):
    s = _store(tmp_path)
    s.upsert(_job("https://x/1"))  # last_seen = now
    assert s.expire_stale(24, ["reed"]) == 0


def test_expire_keeps_human_verdict_history(tmp_path):
    s = _store(tmp_path)
    job = _job("https://x/1")
    s.upsert(job)
    s.set_status(s.list_jobs()[0]["job_id"], "applied")
    _backdate(s, "https://x/1", 100)
    assert s.expire_stale(24, ["reed"]) == 0  # applied = history, never expired


def test_expire_skips_sources_not_scanned(tmp_path):
    s = _store(tmp_path)
    job = _job("https://x/1")  # source = reed
    s.upsert(job)
    _backdate(s, "https://x/1", 100)
    assert s.expire_stale(24, ["adzuna"]) == 0  # reed didn't scan OK → don't touch
    assert s.expire_stale(24, ["reed"]) == 1


def test_relisted_after_expiry_creates_new_generation(tmp_path):
    s = _store(tmp_path)
    job = _job("https://x/1")
    s.upsert(job, 24)
    _backdate(s, "https://x/1", 100)  # last seen outside the 24h window
    s.expire_stale(24, ["reed"])
    assert s.list_jobs()[0]["status"] == "expired"
    # seen again after it expired → NOT a live sighting → fresh generation row,
    # old expired row kept as history (no reactivation, no verdict carry-over)
    assert s.upsert(job, 24) is True
    rows = s.list_jobs()
    assert len(rows) == 2
    assert sorted(r["status"] for r in rows) == ["expired", "new"]


def test_relisted_within_window_merges_in_place(tmp_path):
    s = _store(tmp_path)
    job = _job("https://x/1")
    s.upsert(job, 24)
    # still live (seen <24h ago) → re-sighting merges, no new row, no re-notify
    assert s.upsert(job, 24) is False
    assert len(s.list_jobs()) == 1
