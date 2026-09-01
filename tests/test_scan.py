from __future__ import annotations

from datetime import datetime, timezone

from job_radar import scan
from job_radar.schema import Job


class _FakeSource:
    """A source that returns two listings of the SAME vacancy (one duplicate)."""

    ID = "fake"

    @staticmethod
    def fetch(cfg, http):
        return [
            Job(source="fake", company="Acme", title="Data Engineer", url="https://x/1", location="Edinburgh"),
            Job(source="fake", company="Acme", title="Data Engineer", url="https://x/2", location="Edinburgh"),
        ]


def test_run_scan_completes_end_to_end(tmp_path, monkeypatch):
    # Exercises the WHOLE run_scan path — loop, http.close(), the expire step, the
    # summary, the return dict — which unit tests of Store/server never touch. This
    # is the regression guard for the post-loop `NameError` that reached prod.
    monkeypatch.setattr(scan, "REGISTRY", {"fake": _FakeSource})
    result = scan.run_scan({"sources": {"fake": {"enabled": True}}}, str(tmp_path / "db.duckdb"))

    t = result["totals"]
    assert t["found"] == 2 and t["new"] == 1 and t["dupes"] == 1  # dedup collapsed the pair
    assert t["expired"] == 0 and t["errors"] == 0  # post-loop expire step ran cleanly
    assert "notify" not in t                       # the removed counter stays gone
    assert len(result["new_jobs"]) == 1            # one vacancy to notify about


class _ReedSnippet:
    """A Reed source returning a snippet job (jd_full=False) with a detail-API id."""

    ID = "reed"

    @staticmethod
    def fetch(cfg, http):
        return [Job(source="reed", company="Acme", title="Data Engineer", url="https://x/1",
                    location="Edinburgh", description="short snippet", jd_full=False,
                    raw={"jobId": "123"})]


def test_run_scan_enriches_reed_jd_once(tmp_path, monkeypatch):
    from job_radar.store import Store
    # scan.py dispatches enrichment off the REGISTRY module's own full_description
    monkeypatch.setattr(_ReedSnippet, "full_description",
                        staticmethod(lambda raw, http, cfg=None: "FULL JD " * 100), raising=False)
    monkeypatch.setattr(scan, "REGISTRY", {"reed": _ReedSnippet})
    db = str(tmp_path / "db.duckdb")
    cfg = {"sources": {"reed": {"enabled": True}}}

    res = scan.run_scan(cfg, db)
    assert res["totals"]["enriched"] == 1
    s = Store(db)
    assert s.jobs_needing_full_jd() == []                 # flag flipped → none left
    desc, jd_full = s.con.execute("SELECT description, jd_full FROM jobs").fetchone()
    s.close()
    assert "FULL JD" in desc and jd_full is True           # snippet replaced

    res2 = scan.run_scan(cfg, db)                          # same job re-seen → merge
    assert res2["totals"]["enriched"] == 0                 # not re-fetched


class _CaptureCfg:
    """Records the per-source cfg it was handed (to assert the freshness window)."""

    ID = "adz"
    last = {}

    @staticmethod
    def fetch(cfg, http):
        _CaptureCfg.last = dict(cfg)
        return []


def test_regular_scan_tightens_window_deep_uses_full(tmp_path, monkeypatch):
    monkeypatch.setattr(scan, "REGISTRY", {"adz": _CaptureCfg})
    cfg = {"recent_days": 1, "sources": {"adz": {"enabled": True, "max_days_old": 7}}}
    db = str(tmp_path / "db.duckdb")
    scan.run_scan(cfg, db, deep=False)
    assert _CaptureCfg.last["max_days_old"] == 1   # regular → tightened to recent_days
    scan.run_scan(cfg, db, deep=True)
    assert _CaptureCfg.last["max_days_old"] == 7   # deep → full configured window


def test_run_scan_dry_run_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(scan, "REGISTRY", {"fake": _FakeSource})
    db = tmp_path / "db.duckdb"
    result = scan.run_scan({"sources": {"fake": {"enabled": True}}}, str(db), dry_run=True)
    assert result["totals"]["new"] == 1
    assert not db.exists()  # dry run never opens/creates the DB


def test_compact_db_reclaims_space_without_losing_rows(tmp_path):
    """DuckDB has no VACUUM; deletes leave the file fragmented. compact_db rewrites
    it, and must carry over EVERY table (jobs, scan_runs, llm_runs), not just jobs."""
    from job_radar.scan import compact_db
    from job_radar.store import Store
    db = str(tmp_path / "db.duckdb")
    s = Store(db)
    for i in range(200):
        s.upsert(Job(source="reed", company=f"Co{i}", title="Data Engineer",
                     url=f"https://x/{i}", location="Edinburgh", description="x" * 3000))
    s.record_run("run1", datetime.now(timezone.utc), "reed", 1, 1, 0, 0, 0)
    s.con.execute("DELETE FROM jobs WHERE company LIKE 'Co1%'")
    s.close()

    before, after = compact_db(db)
    assert after < before                                  # space actually reclaimed
    s = Store(db)
    assert s.con.execute("SELECT count(*) FROM jobs").fetchone()[0] > 0
    assert s.con.execute("SELECT count(*) FROM scan_runs").fetchone()[0] == 1  # not dropped
    s.close()
