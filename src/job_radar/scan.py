from __future__ import annotations

import argparse
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import setup_logging
from .config import ROOT, load_config

logger = logging.getLogger("job_radar.scan")
from .filters import build_location_filter, build_title_filter
from .schema import Job
from .sources import REGISTRY
from .sources.base import client
from .store import Store


def _load_env() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    except Exception:
        pass  # dotenv optional; fall back to process env


def run_scan(
    cfg: dict,
    db_path: str | Path | None,
    *,
    only_source: str | None = None,
    dry_run: bool = False,
    log=None,
) -> dict:
    """Run the discovery scan once and return a summary. Shared by the CLI and
    the server's /api/scan. The DB is opened/closed per source so the write lock
    is held only during the quick upsert bursts, not during slow HTTP fetches —
    keeping the dashboard responsive while a scan runs."""
    if log is None:
        log = logger.info
    log("scan started")
    title_ok = build_title_filter(cfg.get("title_filter", {}))
    loc_ok = build_location_filter(cfg.get("location_filter"))
    sources_cfg = cfg.get("sources", {})

    if not dry_run:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        s = Store(db_path)
        seen = s.seen_ids()  # job_ids on file = vacancies already stored (role+city)
        s.close()
    else:
        seen = set()

    http = client()
    totals = {"found": 0, "new": 0, "dupes": 0, "filtered": 0, "errors": 0, "expired": 0}
    new_jobs: list[Job] = []  # newly-inserted vacancies → exactly what we notify
    live_sources: list[str] = []  # sources that fetched OK this run (safe to prune)
    started = datetime.now(timezone.utc)

    for sid, mod in REGISTRY.items():
        scfg = sources_cfg.get(sid, {})
        if not scfg.get("enabled", False):
            continue
        if only_source and sid != only_source:
            continue

        run_id = uuid.uuid4().hex[:12]
        src_started = datetime.now(timezone.utc)
        try:
            jobs = mod.fetch(scfg, http)  # slow network work — no DB held here
        except Exception as exc:  # one bad connector must not kill the scan
            log(f"  ✗ {sid}: {exc}")
            totals["errors"] += 1
            if not dry_run:
                s = Store(db_path)
                s.record_run(run_id, src_started, sid, 0, 0, 0, 0, 1, str(exc))
                s.close()
            continue

        live_sources.append(sid)  # fetch succeeded → its jobs are current
        found = new = dupes = filtered = 0
        store = Store(db_path) if not dry_run else None
        for job in jobs:
            found += 1
            if not title_ok(job.title) or not loc_ok(job.location):
                filtered += 1
                continue
            if job.job_id in seen:  # same vacancy (role+city) already stored — merge, don't re-add
                dupes += 1
                continue
            seen.add(job.job_id)
            new_jobs.append(job)  # a new job_id = a new vacancy → notify-worthy
            if store and store.upsert(job):
                new += 1
            elif store is None:
                new += 1
        if store:
            store.record_run(run_id, src_started, sid, found, new, dupes, filtered, 0)
            store.close()

        for k, v in (("found", found), ("new", new), ("dupes", dupes), ("filtered", filtered)):
            totals[k] += v
        log(f"  ✓ {sid}: {found} found, {new} new, {dupes} dupes, {filtered} filtered")

    http.close()
    totals["notify"] = len(notify_jobs)

    # Mark jobs that dropped off their (successfully-scanned) source > N hours ago
    # as 'expired' — the posting is closed/filled. Marked, not deleted, so it stays
    # for history and reactivates if relisted (see Store.upsert / expire_stale).
    if not dry_run and live_sources:
        s = Store(db_path)
        totals["expired"] = s.expire_stale(int(cfg.get("expire_after_hours", 24)), live_sources)
        s.close()
        if totals["expired"]:
            log(f"  ⌫ expired {totals['expired']} closed job(s)")

    log(
        f"scan complete — found {totals['found']}, new {totals['new']}, "
        f"merged {totals['dupes']}, filtered {totals['filtered']}, "
        f"expired {totals['expired']}, errors {totals['errors']}"
    )

    return {
        "started": started.isoformat(),
        "finished": datetime.now(timezone.utc).isoformat(),
        "totals": totals,
        # new_jobs = newly-inserted vacancies (one row per role+city) — both the
        # storage/dashboard view and exactly what we notify about.
        "new_jobs": [
            {"source": j.source, "company": j.company, "title": j.title,
             "location": j.location, "url": j.url}
            for j in new_jobs
        ],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="job-scan", description="Deterministic UK job discovery (zero LLM tokens)."
    )
    ap.add_argument("--config", default=None, help="path to config.yml")
    ap.add_argument("--db", default=str(ROOT / "data" / "jobs.duckdb"), help="DuckDB path")
    ap.add_argument("--source", default=None, help="run a single source by id")
    ap.add_argument("--dry-run", action="store_true", help="fetch + filter, write nothing")
    args = ap.parse_args(argv)

    setup_logging()
    _load_env()
    cfg = load_config(args.config)
    result = run_scan(cfg, args.db, only_source=args.source, dry_run=args.dry_run)

    t = result["totals"]
    bar = "━" * 45
    date = datetime.now(timezone.utc).date().isoformat()
    print(f"\n{bar}\nJob Scan — {date}\n{bar}")
    for k in ("found", "new", "dupes", "filtered", "errors", "expired"):
        print(f"{k.capitalize()+':':9} {t[k]}")
    if result["new_jobs"]:
        print("\nNew matches:")
        for j in result["new_jobs"]:
            print(f"  + {j['company']} | {j['title']} | {j['location'] or 'N/A'}")
    if args.dry_run:
        print("\n(dry run — nothing written)")
    else:
        print(f"\nSaved to {args.db}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
