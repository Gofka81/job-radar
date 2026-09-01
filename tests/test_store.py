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


def test_merge_upgrades_a_stub_jd(tmp_path):
    """A JD-less source must not permanently shadow the same vacancy's real JD."""
    s = _store(tmp_path)
    stub = Job(source="linkedin", company="Acme", title="Data Engineer",
               url="https://li/1", location="Edinburgh", description="", jd_full=False)
    assert s.upsert(stub) is True
    full = Job(source="indeed", company="Acme", title="Data Engineer",
               url="https://in/1", location="Edinburgh", description="PySpark " * 200)
    assert s.upsert(full) is False  # same vacancy_key → merged, not a new row
    desc, jd_full = s.con.execute("SELECT description, jd_full FROM jobs").fetchone()
    assert "PySpark" in desc and jd_full is True
    # a shorter JD arriving later must NOT clobber the good one
    s.upsert(Job(source="adzuna", company="Acme", title="Data Engineer",
                 url="https://ad/1", location="Edinburgh", description="tiny snippet"))
    assert len(s.con.execute("SELECT description FROM jobs").fetchone()[0]) > 1000
    s.close()


def test_jobs_needing_full_jd_includes_legacy_empty_rows(tmp_path):
    """Rows written before their connector grew a hook have jd_full=true + no JD."""
    s = _store(tmp_path)
    s.upsert(Job(source="linkedin", company="A", title="DE", url="https://li/9",
                 location="Glasgow", description="", jd_full=True))
    assert len(s.jobs_needing_full_jd()) == 1
    s.close()


def _expired(store: Store, url: str, *, days: int, status: str = "expired") -> None:
    old = datetime.now(timezone.utc) - timedelta(days=days)
    store.con.execute(
        "UPDATE jobs SET status = ?, last_seen = ?, first_seen = ? WHERE url = ?",
        [status, old, old, url])


def test_archive_moves_old_expired_rows_to_parquet(tmp_path):
    s = _store(tmp_path)
    s.upsert(_job("https://x/old", title="Old Engineer"))
    s.upsert(_job("https://x/recent", title="Recent Engineer"))
    s.upsert(_job("https://x/applied", title="Applied Engineer"))
    _expired(s, "https://x/old", days=60)
    _expired(s, "https://x/recent", days=5)
    _expired(s, "https://x/applied", days=90, status="applied")

    arch = tmp_path / "archive"
    res = s.archive_expired(arch, after_days=30)
    assert res["archived"] == 1                                   # only the 60-day row
    live = {r[0] for r in s.con.execute("SELECT url FROM jobs").fetchall()}
    assert live == {"https://x/recent", "https://x/applied"}      # applied never archived
    assert list(arch.glob("month=*/part.parquet"))                # written, partitioned

    s.attach_history(arch)                                        # history readable again
    assert s.con.execute("SELECT count(*) FROM jobs_all").fetchone()[0] == 3
    assert s.con.execute(
        "SELECT title FROM jobs_all WHERE url = 'https://x/old'").fetchone()[0] == "Old Engineer"
    s.close()


def test_archive_is_idempotent_and_lossless(tmp_path):
    s = _store(tmp_path)
    for i in range(3):
        s.upsert(_job(f"https://x/{i}", title=f"Engineer {i}"))
        _expired(s, f"https://x/{i}", days=60)
    arch = tmp_path / "archive"
    assert s.archive_expired(arch, after_days=30)["archived"] == 3
    assert s.archive_expired(arch, after_days=30)["archived"] == 0   # nothing left
    s.upsert(_job("https://x/late", title="Late Engineer"))          # a 4th, same month
    _expired(s, "https://x/late", days=60)
    s.archive_expired(arch, after_days=30)
    s.attach_history(arch)
    assert s.con.execute("SELECT count(*) FROM jobs_all").fetchone()[0] == 4  # none lost
    s.close()


def test_attach_history_without_archive_mirrors_jobs(tmp_path):
    s = _store(tmp_path)
    s.upsert(_job("https://x/1"))
    assert s.attach_history(tmp_path / "nope") is False
    assert s.con.execute("SELECT count(*) FROM jobs_all").fetchone()[0] == 1
    s.close()


def test_list_jobs_exposes_remote_for_the_dashboard_badge(tmp_path):
    """The dashboard badges remote roles off this flag — it used to guess with a
    regex on the location text, which misses roles labelled with a city."""
    s = _store(tmp_path)
    s.upsert(_job("https://x/r", title="Data Engineer", remote=True, location="Manchester"))
    s.upsert(_job("https://x/o", title="Data Engineer II", location="London"))
    rows = {r["url"]: r for r in s.list_jobs()}
    assert rows["https://x/r"]["remote"] is True
    assert rows["https://x/o"]["remote"] in (None, False)
    s.close()
