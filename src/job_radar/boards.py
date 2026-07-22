"""Discovered ATS boards — a durable directory of employers and their ATS slugs.

This is *accumulated knowledge*, not ephemeral scan output, so it lives in its
OWN DuckDB file (`ats_boards.duckdb`, via `JOB_RADAR_BOARDS_DB` or alongside the
jobs DB). `jobs.duckdb` is wiped on schema changes; this file is not, so a company
learned in August is still scanned in December.

Two uses today: (1) a self-expanding source list — the ATS connectors scan the
hand-curated `config.yml` companies UNIONed with the `active` rows here, so
discovery can add employers without editing config; (2) a company directory. Rows
arrive by manual seed today; the aggregator-link → ATS-detect auto-discovery will
write here too (deferred). Insert/union only — we never drop a company silently.

`slug` is the board id after the ATS domain for slug ATS (greenhouse/lever/ashby/
workable); for self-hosted tenants (workday/oracle) it encodes `host|site` and
`company` holds the display name, so `config_entries()` can rebuild the connector's
`{host, site, name}` shape.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from .config import ROOT
from .dedup import normalize_company

logger = logging.getLogger("job_radar.boards")

# ATS taking a plain slug string vs a self-hosted tenant {host, site, name}.
SLUG_ATS = ("greenhouse", "lever", "ashby", "workable")
TENANT_ATS = ("workday", "oracle")
KNOWN_ATS = SLUG_ATS + TENANT_ATS

SCHEMA = """
CREATE TABLE IF NOT EXISTS ats_boards (
    ats             VARCHAR,      -- greenhouse|lever|ashby|workable|workday|oracle
    slug            VARCHAR,      -- board id/slug (or host|site for workday/oracle)
    company_key     VARCHAR,      -- normalize_company(): join key to jobs
    company         VARCHAR,      -- display name as first seen
    board_url       VARCHAR,      -- resolved careers URL that revealed the board
    discovered_from VARCHAR,      -- adzuna|reed|indeed|manual — provenance
    status          VARCHAR DEFAULT 'active',   -- active | dead
    first_seen      TIMESTAMP,
    last_verified   TIMESTAMP,    -- last scan that pulled jobs (set by discovery, later)
    job_count       INTEGER,      -- jobs pulled last verify (health signal)
    PRIMARY KEY (ats, slug)
);
"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def boards_db_path(jobs_db: str | Path | None = None) -> Path:
    """Where the discovered-boards DB lives. `JOB_RADAR_BOARDS_DB` wins; otherwise
    it sits next to the jobs DB (so both land on the same data volume) or under the
    repo `data/` dir as a last resort."""
    env = os.environ.get("JOB_RADAR_BOARDS_DB")
    if env:
        return Path(env)
    if jobs_db:
        return Path(jobs_db).with_name("ats_boards.duckdb")
    return ROOT / "data" / "ats_boards.duckdb"


def _norm_slug(ats: str, slug: str) -> str:
    """Canonical stored slug. Slug ATS are case-insensitive board ids; tenant ATS
    keep `host|site` as-is (host is case-insensitive, site is not)."""
    s = (slug or "").strip()
    return s.lower() if ats in SLUG_ATS else s


class BoardStore:
    COLS = (
        "ats", "slug", "company_key", "company", "board_url", "discovered_from",
        "status", "first_seen", "last_verified", "job_count",
    )

    def __init__(self, path: str | Path, *, retries: int = 20, retry_delay: float = 0.5):
        self.con = self._connect(path, retries, retry_delay)
        self.con.execute(SCHEMA)

    @staticmethod
    def _connect(path: str | Path, retries: int, retry_delay: float):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        last: Exception | None = None
        for attempt in range(max(1, retries)):
            try:
                return duckdb.connect(str(path))
            except duckdb.IOException as exc:  # locked by another process
                last = exc
                if attempt < retries - 1:
                    time.sleep(retry_delay)
        raise last  # type: ignore[misc]

    def upsert_board(
        self,
        ats: str,
        slug: str,
        *,
        company: str | None = None,
        board_url: str = "",
        discovered_from: str = "manual",
    ) -> bool:
        """Add a board or refresh its metadata. Identity is (ats, slug). On an
        existing row we keep first_seen + original provenance and reactivate it
        (status='active'), filling in a better company/board_url if given. Returns
        True if newly inserted. Raises ValueError on an unknown ATS or empty slug."""
        if ats not in KNOWN_ATS:
            raise ValueError(f"ats must be one of {KNOWN_ATS}")
        slug = _norm_slug(ats, slug)
        if not slug:
            raise ValueError("slug must not be empty")
        company = (company or "").strip() or None
        ckey = normalize_company(company or slug)
        row = self.con.execute(
            "SELECT company, board_url FROM ats_boards WHERE ats = ? AND slug = ?",
            [ats, slug],
        ).fetchone()
        if row:
            self.con.execute(
                """UPDATE ats_boards
                   SET company = coalesce(?, company),
                       board_url = CASE WHEN ? <> '' THEN ? ELSE board_url END,
                       company_key = ?, status = 'active'
                   WHERE ats = ? AND slug = ?""",
                [company, board_url, board_url, ckey, ats, slug],
            )
            return False
        self.con.execute(
            """INSERT INTO ats_boards
               (ats, slug, company_key, company, board_url, discovered_from,
                status, first_seen)
               VALUES (?,?,?,?,?,?, 'active', ?)""",
            [ats, slug, ckey, company, board_url, discovered_from, _now()],
        )
        logger.info("board added: %s/%s (%s)", ats, slug, discovered_from)
        return True

    def remove(self, ats: str, slug: str) -> bool:
        """Delete a board (manual correction of a bad slug). Returns False if
        unknown."""
        slug = _norm_slug(ats, slug)
        if not self.con.execute(
            "SELECT 1 FROM ats_boards WHERE ats = ? AND slug = ?", [ats, slug]
        ).fetchone():
            return False
        self.con.execute("DELETE FROM ats_boards WHERE ats = ? AND slug = ?", [ats, slug])
        return True

    def mark_verified(self, ats: str, slug: str, job_count: int) -> None:
        """Record that a scan pulled `job_count` jobs from this board (health
        signal). Reactivates the row; discovery/scan wires this in later."""
        slug = _norm_slug(ats, slug)
        self.con.execute(
            """UPDATE ats_boards
               SET last_verified = ?, job_count = ?, status = 'active'
               WHERE ats = ? AND slug = ?""",
            [_now(), job_count, ats, slug],
        )

    def mark_dead(self, ats: str, slug: str) -> None:
        """Flag a board that 404s / went empty. Kept (not deleted) as history so we
        don't rediscover-and-rescan it every cycle."""
        slug = _norm_slug(ats, slug)
        self.con.execute(
            "UPDATE ats_boards SET status = 'dead' WHERE ats = ? AND slug = ?", [ats, slug]
        )

    def config_entries(self, ats: str, *, active_only: bool = True) -> list:
        """The discovered boards for `ats`, shaped as the connector's `companies`
        entries: a slug string for slug ATS, a `{host, site, name}` dict for tenant
        ATS. Union these with the hand-curated config list before scanning."""
        where = "ats = ?" + (" AND status = 'active'" if active_only else "")
        rows = self.con.execute(
            f"SELECT slug, company FROM ats_boards WHERE {where} ORDER BY slug", [ats]
        ).fetchall()
        if ats in TENANT_ATS:
            out = []
            for slug, company in rows:
                host, _, site = slug.partition("|")
                out.append({"host": host, "site": site, "name": company or host})
            return out
        return [slug for slug, _ in rows]

    def list_boards(self, ats: str | None = None) -> list[dict]:
        """All boards (optionally one ATS), newest-first — for the directory view."""
        where, params = ("WHERE ats = ?", [ats]) if ats else ("", [])
        rows = self.con.execute(
            f"""SELECT {", ".join(self.COLS)} FROM ats_boards {where}
                ORDER BY first_seen DESC""",
            params,
        ).fetchall()
        return [dict(zip(self.COLS, r)) for r in rows]

    def close(self) -> None:
        self.con.close()
