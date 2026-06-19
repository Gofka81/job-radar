from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import duckdb

from .dedup import fingerprint
from .locations import clean_location
from .schema import Job

# Single-table schema, created on open. No migration framework: this is a
# development project that re-scrapes freely, so we evolve the schema by editing
# this DDL and re-running scans rather than carrying ordered migrations + backfills.
SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id           VARCHAR PRIMARY KEY,   -- sha1(source : canonical_url)
    source           VARCHAR,
    company          VARCHAR,
    title            VARCHAR,
    url              VARCHAR,               -- original (tokens intact, clickable)
    location         VARCHAR,
    location_cleaned VARCHAR,               -- canonical UK city (locations.py)
    posted_at        DATE,
    salary_min       DOUBLE,
    salary_max       DOUBLE,
    currency         VARCHAR,
    remote           BOOLEAN,
    status           VARCHAR DEFAULT 'new',
    score            DOUBLE,
    report_num       INTEGER,
    first_seen       TIMESTAMP,
    last_seen        TIMESTAMP,
    raw              JSON
);
CREATE TABLE IF NOT EXISTS scan_runs (
    run_id       VARCHAR,
    started_at   TIMESTAMP,
    finished_at  TIMESTAMP,
    source       VARCHAR,
    found        INTEGER,
    new          INTEGER,
    dupes        INTEGER,
    filtered     INTEGER,
    errors       INTEGER,
    error_detail VARCHAR
);
"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Store:
    def __init__(self, path: str | Path, *, retries: int = 20, retry_delay: float = 0.5):
        # DuckDB allows only one read-write connection to a file at a time. The
        # server opens a short-lived connection per request (~5ms; fine at our
        # traffic — see the connection-strategy note in the README/PLAN), and the
        # in-process scan opens its own while writing. A brief overlap (a dashboard
        # hit mid-scan) can hit the lock, so wait and retry rather than error — the
        # scan holds the file only for seconds.
        self.con = self._connect(path, retries, retry_delay)
        self.con.execute(SCHEMA)  # idempotent (IF NOT EXISTS)

    @staticmethod
    def _connect(path: str | Path, retries: int, retry_delay: float):
        last: Exception | None = None
        for attempt in range(max(1, retries)):
            try:
                return duckdb.connect(str(path))
            except duckdb.IOException as exc:  # file locked by the other process
                last = exc
                if attempt < retries - 1:
                    time.sleep(retry_delay)
        raise last  # type: ignore[misc]

    def seen_ids(self) -> set[str]:
        """job_ids already on file. A scan skips any job whose job_id is here.
        Since job_id = sha1(source:canonical_url), tracking-token variants of the
        same ad share an id and are collapsed automatically."""
        return {row[0] for row in self.con.execute("SELECT job_id FROM jobs").fetchall()}

    def seen_fingerprints(self) -> set[str]:
        """Content fingerprints already on file, computed on the fly from
        company+title (blanks dropped). A scan notifies only for jobs whose
        fingerprint is NOT here — suppressing agency reposts of a role we've
        already pinged about (same role, brand-new ad-id)."""
        rows = self.con.execute("SELECT company, title FROM jobs").fetchall()
        return {fp for c, t in rows if (fp := fingerprint(c, t)) is not None}

    def upsert(self, job: Job) -> bool:
        """Insert a new job; if it already exists just bump last_seen. Returns
        True if the row was newly inserted. job_id is canonical-URL based, so the
        same Adzuna ad arriving under a fresh tracking token resolves to the same
        id and is recognised as a duplicate instead of inserted as a phantom."""
        now = _now()
        exists = self.con.execute(
            "SELECT 1 FROM jobs WHERE job_id = ?", [job.job_id]
        ).fetchone()
        if exists:
            self.con.execute(
                "UPDATE jobs SET last_seen = ? WHERE job_id = ?", [now, job.job_id]
            )
            return False
        self.con.execute(
            """INSERT INTO jobs
               (job_id, source, company, title, url, location, location_cleaned, posted_at,
                salary_min, salary_max, currency, remote, status,
                first_seen, last_seen, raw)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?, 'new', ?, ?, ?)""",
            [
                job.job_id, job.source, job.company, job.title, job.url, job.location,
                clean_location(job.location), job.posted_at, job.salary_min, job.salary_max,
                job.currency, job.remote, now, now, json.dumps(job.raw, default=str),
            ],
        )
        return True

    # --- API sync (Pi <-> PC) ---------------------------------------------
    # A job is "pending" (needs evaluation) while status='new'. Verdicts from
    # the PC move it to evaluated/applied/rejected/archived and drop it off the
    # /api/pending feed. The Pi is the only writer of this table.
    PENDING_COLS = (
        "job_id", "url", "company", "title", "location", "source",
        "posted_at", "salary_min", "salary_max", "currency", "remote",
    )

    def pending_jobs(self) -> list[dict]:
        """Jobs still awaiting evaluation (status='new'), newest first. This is
        the Pi -> PC shortlist payload. No phantom dedup needed — job_id is
        canonical-URL based, so each ad is already a single row."""
        rows = self.con.execute(
            f"""SELECT {", ".join(self.PENDING_COLS)}
                FROM jobs WHERE status = 'new'
                ORDER BY first_seen DESC"""
        ).fetchall()
        return [dict(zip(self.PENDING_COLS, r)) for r in rows]

    def mark_results(self, results: list[dict]) -> int:
        """Apply PC -> Pi verdicts. Each result is keyed by `url` (preferred,
        since the PC works in URLs) or `job_id`, plus optional score/status/
        report_num. Unknown jobs are skipped. Returns rows updated."""
        updated = 0
        for r in results:
            jid = r.get("job_id")
            url = r.get("url")
            if not jid and url:
                row = self.con.execute(
                    "SELECT job_id FROM jobs WHERE url = ?", [url]
                ).fetchone()
                jid = row[0] if row else None
            if not jid or not self.con.execute(
                "SELECT 1 FROM jobs WHERE job_id = ?", [jid]
            ).fetchone():
                continue
            self.con.execute(
                "UPDATE jobs SET status = ?, score = ?, report_num = ? WHERE job_id = ?",
                [r.get("status") or "evaluated", r.get("score"), r.get("report_num"), jid],
            )
            updated += 1
        return updated

    LIST_COLS = (
        "job_id", "source", "company", "title", "url", "location", "location_cleaned",
        "status", "score", "salary_min", "salary_max", "currency", "first_seen", "last_seen",
    )

    def list_jobs(self, limit: int = 500) -> list[dict]:
        """All jobs, newest-discovered first, with timestamps + status — for the
        dashboard. `first_seen` = when a scan first found it; `last_seen` = the
        most recent scan that still saw it (a stale value ≈ the posting is gone)."""
        rows = self.con.execute(
            f"""SELECT {", ".join(self.LIST_COLS)}
                FROM jobs ORDER BY first_seen DESC LIMIT ?""",
            [limit],
        ).fetchall()
        return [dict(zip(self.LIST_COLS, r)) for r in rows]

    def prune_stale(self, max_age_hours: int, sources: list[str]) -> int:
        """Delete still-`new` jobs not seen for `max_age_hours` — they've dropped
        off their source (closed/filled) and would otherwise pile up. Guards:
        only `status='new'` (keep evaluated/applied history) and only the given
        `sources` (pass those that scanned OK this run, so an outage can't wipe
        jobs). Returns rows deleted."""
        if not sources or max_age_hours <= 0:
            return 0
        cutoff = _now() - timedelta(hours=max_age_hours)
        marks = ",".join("?" * len(sources))
        where = f"status = 'new' AND last_seen < ? AND source IN ({marks})"
        params = [cutoff, *sources]
        n = self.con.execute(f"SELECT count(*) FROM jobs WHERE {where}", params).fetchone()[0]
        if n:
            self.con.execute(f"DELETE FROM jobs WHERE {where}", params)
        return n

    def funnel(self) -> dict[str, int]:
        """Counts for the dashboard funnel: total discovered + per-status."""
        total = self.con.execute("SELECT count(*) FROM jobs").fetchone()[0]
        by_status = dict(
            self.con.execute("SELECT status, count(*) FROM jobs GROUP BY status").fetchall()
        )
        return {"total": total, **{str(k): v for k, v in by_status.items()}}

    def record_run(
        self,
        run_id: str,
        started: datetime,
        source: str,
        found: int,
        new: int,
        dupes: int,
        filtered: int,
        errors: int,
        error_detail: str = "",
    ) -> None:
        self.con.execute(
            """INSERT INTO scan_runs
               (run_id, started_at, finished_at, source, found, new, dupes,
                filtered, errors, error_detail)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            [run_id, started, _now(), source, found, new, dupes, filtered, errors, error_detail],
        )

    def close(self) -> None:
        self.con.close()
