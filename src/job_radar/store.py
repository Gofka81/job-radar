from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import duckdb

from .locations import clean_location
from .schema import Job

# SQL schema lives as ordered, idempotent migration files (migrations/*.sql),
# applied in name order on every open.
MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Store:
    def __init__(self, path: str | Path, *, retries: int = 20, retry_delay: float = 0.5):
        # DuckDB allows only one read-write process per file. The Pi runs the
        # server and the scheduled scan as separate processes, so a brief overlap
        # (e.g. a dashboard hit during the daily scan) can hit a lock. Wait and
        # retry rather than error — the scan only holds the file for seconds.
        self.con = self._connect(path, retries, retry_delay)
        self._apply_migrations()

    def _apply_migrations(self) -> None:
        """Run migrations/*.sql in name order. Every statement is idempotent
        (CREATE/ALTER ... IF NOT EXISTS), so re-running on each open is a no-op."""
        for sql_file in sorted(MIGRATIONS_DIR.glob("*.sql")):
            self.con.execute(sql_file.read_text())

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

    def backfill_location_cleaned(self) -> int:
        """Catch up rows that predate the column (existing prod data). Idempotent:
        once everything's filled, the NULL query matches nothing and it's a no-op.
        Returns rows updated."""
        rows = self.con.execute(
            "SELECT job_id, location FROM jobs WHERE location_cleaned IS NULL"
        ).fetchall()
        for job_id, location in rows:
            self.con.execute(
                "UPDATE jobs SET location_cleaned = ? WHERE job_id = ?",
                [clean_location(location), job_id],
            )
        return len(rows)

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

    LIST_COLS = (
        "job_id", "source", "company", "title", "url", "location", "location_cleaned",
        "status", "score", "first_seen", "last_seen",
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
