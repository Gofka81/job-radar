from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from .schema import Job

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id      VARCHAR PRIMARY KEY,
    source      VARCHAR,
    company     VARCHAR,
    title       VARCHAR,
    url         VARCHAR,
    location    VARCHAR,
    posted_at   DATE,
    salary_min  DOUBLE,
    salary_max  DOUBLE,
    currency    VARCHAR,
    remote      BOOLEAN,
    status      VARCHAR DEFAULT 'new',
    score       DOUBLE,
    report_num  INTEGER,
    first_seen  TIMESTAMP,
    last_seen   TIMESTAMP,
    raw         JSON
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
        # DuckDB allows only one read-write process per file. The Pi runs the
        # server and the scheduled scan as separate processes, so a brief overlap
        # (e.g. a dashboard hit during the daily scan) can hit a lock. Wait and
        # retry rather than error — the scan only holds the file for seconds.
        self.con = self._connect(path, retries, retry_delay)
        self.con.execute(SCHEMA)

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
        return {row[0] for row in self.con.execute("SELECT job_id FROM jobs").fetchall()}

    def upsert(self, job: Job) -> bool:
        """Insert a new job; if it already exists just bump last_seen.
        Returns True if the row was newly inserted."""
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
               (job_id, source, company, title, url, location, posted_at,
                salary_min, salary_max, currency, remote, status,
                first_seen, last_seen, raw)
               VALUES (?,?,?,?,?,?,?,?,?,?,?, 'new', ?, ?, ?)""",
            [
                job.job_id, job.source, job.company, job.title, job.url, job.location,
                job.posted_at, job.salary_min, job.salary_max, job.currency, job.remote,
                now, now, json.dumps(job.raw, default=str),
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
        """Jobs still awaiting evaluation (status='new'), newest first.
        This is the Pi -> PC shortlist payload."""
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
