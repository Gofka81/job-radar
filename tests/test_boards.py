from __future__ import annotations

import pytest

from job_radar.boards import BoardStore, boards_db_path


def _bs(tmp_path):
    return BoardStore(tmp_path / "boards.duckdb")


def test_upsert_inserts_then_updates(tmp_path):
    bs = _bs(tmp_path)
    assert bs.upsert_board("greenhouse", "monzo", company="Monzo") is True
    # same (ats, slug) → update, not a second row
    assert bs.upsert_board("greenhouse", "monzo", board_url="https://boards.greenhouse.io/monzo") is False
    rows = bs.list_boards()
    assert len(rows) == 1
    assert rows[0]["company"] == "Monzo"  # kept from first insert
    assert rows[0]["board_url"].endswith("/monzo")  # filled on update
    assert rows[0]["company_key"] == "monzo"


def test_slug_is_case_insensitive(tmp_path):
    bs = _bs(tmp_path)
    bs.upsert_board("lever", "Spotify")
    assert bs.upsert_board("lever", "spotify") is False  # same board
    assert len(bs.list_boards()) == 1
    assert bs.list_boards()[0]["slug"] == "spotify"


def test_bad_ats_and_empty_slug_rejected(tmp_path):
    bs = _bs(tmp_path)
    with pytest.raises(ValueError):
        bs.upsert_board("linkedin", "foo")
    with pytest.raises(ValueError):
        bs.upsert_board("greenhouse", "   ")


def test_config_entries_slug_ats(tmp_path):
    bs = _bs(tmp_path)
    bs.upsert_board("ashby", "acme")
    bs.upsert_board("ashby", "beta")
    assert bs.config_entries("ashby") == ["acme", "beta"]


def test_config_entries_tenant_ats_shape(tmp_path):
    bs = _bs(tmp_path)
    bs.upsert_board("workday", "natwest.wd3.myworkdayjobs.com|NatWestGroup", company="NatWest")
    entries = bs.config_entries("workday")
    assert entries == [
        {"host": "natwest.wd3.myworkdayjobs.com", "site": "NatWestGroup", "name": "NatWest"}
    ]


def test_active_only_hides_dead_and_remove(tmp_path):
    bs = _bs(tmp_path)
    bs.upsert_board("greenhouse", "live")
    bs.upsert_board("greenhouse", "gone")
    bs.mark_dead("greenhouse", "gone")
    assert bs.config_entries("greenhouse") == ["live"]  # active-only
    assert bs.config_entries("greenhouse", active_only=False) == ["gone", "live"]
    assert bs.remove("greenhouse", "gone") is True
    assert bs.remove("greenhouse", "gone") is False  # already gone


def test_mark_dead_then_upsert_reactivates(tmp_path):
    bs = _bs(tmp_path)
    bs.upsert_board("lever", "acme")
    bs.mark_dead("lever", "acme")
    bs.upsert_board("lever", "acme")  # re-seen → active again
    assert bs.config_entries("lever") == ["acme"]


def test_boards_db_path_next_to_jobs_db(tmp_path):
    p = boards_db_path(tmp_path / "jobs.duckdb")
    assert p == tmp_path / "ats_boards.duckdb"


def test_boards_db_path_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("JOB_RADAR_BOARDS_DB", str(tmp_path / "custom.duckdb"))
    assert boards_db_path(tmp_path / "jobs.duckdb") == tmp_path / "custom.duckdb"


def test_scan_unions_discovered_boards_into_connector_cfg(tmp_path, monkeypatch):
    """A seeded board is scanned even when config.yml lists no companies."""
    from job_radar import scan

    seen: dict = {}

    class _FakeGreenhouse:
        ID = "greenhouse"

        @staticmethod
        def fetch(cfg, http):
            seen["companies"] = list(cfg.get("companies", []))
            return []

    monkeypatch.setattr(scan, "REGISTRY", {"greenhouse": _FakeGreenhouse})
    db = str(tmp_path / "jobs.duckdb")
    bs = BoardStore(boards_db_path(db))  # sits next to the jobs db
    bs.upsert_board("greenhouse", "monzo")
    bs.close()

    scan.run_scan(
        {"sources": {"greenhouse": {"enabled": True, "companies": ["wise"]}}}, db
    )
    assert seen["companies"] == ["wise", "monzo"]  # config first, discovered appended


def test_scan_dry_run_skips_board_union(tmp_path, monkeypatch):
    from job_radar import scan

    seen: dict = {}

    class _FakeGreenhouse:
        ID = "greenhouse"

        @staticmethod
        def fetch(cfg, http):
            seen["companies"] = list(cfg.get("companies", []))
            return []

    monkeypatch.setattr(scan, "REGISTRY", {"greenhouse": _FakeGreenhouse})
    db = str(tmp_path / "jobs.duckdb")
    bs = BoardStore(boards_db_path(db))
    bs.upsert_board("greenhouse", "monzo")
    bs.close()

    scan.run_scan(
        {"sources": {"greenhouse": {"enabled": True, "companies": ["wise"]}}}, db, dry_run=True
    )
    assert seen["companies"] == ["wise"]  # dry run never opens the board store
