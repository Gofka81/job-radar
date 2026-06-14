from __future__ import annotations

import argparse
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .config import ROOT, load_config
from .filters import build_location_filter, build_title_filter
from .sources import REGISTRY
from .sources.base import client
from .store import Store


def _load_env() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    except Exception:
        pass  # dotenv optional; fall back to process env


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="job-scan", description="Deterministic UK job discovery (zero LLM tokens)."
    )
    ap.add_argument("--config", default=None, help="path to config.yml")
    ap.add_argument("--db", default=str(ROOT / "data" / "jobs.duckdb"), help="DuckDB path")
    ap.add_argument("--source", default=None, help="run a single source by id")
    ap.add_argument("--dry-run", action="store_true", help="fetch + filter, write nothing")
    args = ap.parse_args(argv)

    _load_env()
    cfg = load_config(args.config)
    title_ok = build_title_filter(cfg.get("title_filter", {}))
    loc_ok = build_location_filter(cfg.get("location_filter"))
    sources_cfg = cfg.get("sources", {})

    store: Store | None = None
    if not args.dry_run:
        Path(args.db).parent.mkdir(parents=True, exist_ok=True)
        store = Store(args.db)
    seen = store.seen_ids() if store else set()

    http = client()
    totals = {"found": 0, "new": 0, "dupes": 0, "filtered": 0, "errors": 0}
    new_jobs = []

    for sid, mod in REGISTRY.items():
        scfg = sources_cfg.get(sid, {})
        if not scfg.get("enabled", False):
            continue
        if args.source and sid != args.source:
            continue

        run_id = uuid.uuid4().hex[:12]
        started = datetime.now(timezone.utc)
        try:
            jobs = mod.fetch(scfg, http)
        except Exception as exc:  # connector errors must not kill the whole scan
            print(f"  ✗ {sid}: {exc}", file=sys.stderr)
            totals["errors"] += 1
            if store:
                store.record_run(run_id, started, sid, 0, 0, 0, 0, 1, str(exc))
            continue

        found = new = dupes = filtered = 0
        for job in jobs:
            found += 1
            if not title_ok(job.title) or not loc_ok(job.location):
                filtered += 1
                continue
            if job.job_id in seen:
                dupes += 1
                continue
            seen.add(job.job_id)
            new_jobs.append(job)
            if store and store.upsert(job):
                new += 1
            elif store is None:
                new += 1

        for k, v in (("found", found), ("new", new), ("dupes", dupes), ("filtered", filtered)):
            totals[k] += v
        if store:
            store.record_run(run_id, started, sid, found, new, dupes, filtered, 0)
        print(f"  ✓ {sid}: {found} found, {new} new, {dupes} dupes, {filtered} filtered")

    http.close()

    date = datetime.now(timezone.utc).date().isoformat()
    bar = "━" * 45
    print(f"\n{bar}\nJob Scan — {date}\n{bar}")
    print(f"Found:    {totals['found']}")
    print(f"New:      {totals['new']}")
    print(f"Dupes:    {totals['dupes']}")
    print(f"Filtered: {totals['filtered']}")
    print(f"Errors:   {totals['errors']}")
    if new_jobs:
        print("\nNew matches:")
        for j in new_jobs:
            print(f"  + {j.company} | {j.title} | {j.location or 'N/A'}")
    if args.dry_run:
        print("\n(dry run — nothing written)")
    elif store:
        print(f"\nSaved to {args.db}")
        store.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
