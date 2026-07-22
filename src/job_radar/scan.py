from __future__ import annotations

import argparse
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import setup_logging
from .boards import KNOWN_ATS, SLUG_ATS, BoardStore, boards_db_path
from .config import ROOT, load_config

logger = logging.getLogger("job_radar.scan")
from .filters import build_location_filter, build_title_filter
from .locations import set_priority
from .schema import Job
from .sources import REGISTRY
from .sources.base import client
from .store import Store


def _union_companies(sid: str, existing: list, discovered: list) -> list:
    """Merge the hand-curated config `companies` with discovered boards for an ATS
    source, config first, de-duplicated. Slug ATS de-dupe case-insensitively on the
    slug string; tenant ATS (workday/oracle) on (host, site)."""
    if not discovered:
        return existing
    out = list(existing)
    if sid in SLUG_ATS:
        seen = {str(s).strip().lower() for s in existing if isinstance(s, str)}
        for s in discovered:
            if s.lower() not in seen:
                out.append(s)
                seen.add(s.lower())
    else:  # tenant ATS: entries are {host, site, name} dicts
        seen = {(e.get("host"), e.get("site")) for e in existing if isinstance(e, dict)}
        for e in discovered:
            if (e.get("host"), e.get("site")) not in seen:
                out.append(e)
                seen.add((e.get("host"), e.get("site")))
    return out


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
    deep: bool = False,
    log=None,
) -> dict:
    """Run the discovery scan once and return a summary. Shared by the CLI and
    the server's /api/scan. The DB is opened/closed per source so the write lock
    is held only during the quick upsert bursts, not during slow HTTP fetches —
    keeping the dashboard responsive while a scan runs.

    `deep`=True pulls the full configured window (e.g. Adzuna max_days_old=7) and
    re-confirms every open job. A regular scan (deep=False) tightens that window to
    `recent_days` (if set in config) — cheaper, fresh-only. Run a deep scan at least
    daily so older-but-open jobs keep being re-seen and don't expire prematurely."""
    if log is None:
        log = logger.info
    log("deep scan started" if deep else "scan started")
    title_ok = build_title_filter(cfg.get("title_filter", {}))
    loc_ok = build_location_filter(cfg.get("location_filter"))
    set_priority(cfg.get("priority_locations") or [])  # priority cities for city ordering
    sources_cfg = cfg.get("sources", {})
    # Regular scans look only `recent_days` back (opt-in; None = full window like deep).
    recent_days = None if deep else cfg.get("recent_days")

    expire_hours = int(cfg.get("expire_after_hours", 24))
    if not dry_run:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    dry_seen: set[str] = set()  # vacancy_keys this run — dry-run-only dedup

    http = client()
    totals = {"found": 0, "new": 0, "dupes": 0, "filtered": 0, "errors": 0, "expired": 0,
              "enriched": 0}
    new_jobs: list[Job] = []  # newly-inserted vacancies → exactly what we notify
    live_sources: list[str] = []  # sources that fetched OK this run (safe to prune)
    started = datetime.now(timezone.utc)

    # Discovered ATS boards live in their own durable DB; scan the hand-curated
    # config companies UNIONed with the active rows there (self-expanding sources).
    boards = None if dry_run else BoardStore(boards_db_path(db_path))

    for sid, mod in REGISTRY.items():
        scfg = sources_cfg.get(sid, {})
        if not scfg.get("enabled", False):
            continue
        if only_source and sid != only_source:
            continue

        # Union in auto-discovered / manually-seeded boards for this ATS.
        if boards is not None and sid in KNOWN_ATS:
            merged = _union_companies(sid, scfg.get("companies", []) or [],
                                      boards.config_entries(sid))
            scfg = {**scfg, "companies": merged}

        # Regular scans tighten the freshness window (fewer results + fewer API
        # calls, since empty pages break the loop earlier). Only affects sources
        # with a max_days_old knob (Adzuna). Deep scans use the full window.
        if recent_days and "max_days_old" in scfg:
            scfg = {**scfg, "max_days_old": min(int(scfg["max_days_old"]), int(recent_days))}

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
            if store is not None:
                # upsert owns dedup: True = new vacancy inserted, False = merged
                # (repost / cross-source / same posting in another city).
                if store.upsert(job, expire_hours):
                    new += 1
                    new_jobs.append(job)  # newly inserted → notify-worthy
                else:
                    dupes += 1
            else:  # dry run — approximate dedup by vacancy_key within this run
                vkey = job.vacancy_key
                if vkey in dry_seen:
                    dupes += 1
                else:
                    dry_seen.add(vkey)
                    new += 1
                    new_jobs.append(job)
        if store:
            store.record_run(run_id, src_started, sid, found, new, dupes, filtered, 0)
            store.close()

        for k, v in (("found", found), ("new", new), ("dupes", dupes), ("filtered", filtered)):
            totals[k] += v
        log(f"  ✓ {sid}: {found} found, {new} new, {dupes} dupes, {filtered} filtered")

    # Enrich truncated JDs: jobs with jd_full=false (Reed snippets) get their full
    # text from the source's detail API. One-shot per job (the flag flips), so this
    # only touches newly-inserted snippets. Fetch over HTTP first (no DB lock), then
    # a quick write burst. Best-effort — a failure just leaves the snippet.
    if not dry_run and cfg.get("fetch_full_jd", True):
        from .sources import reed
        s = Store(db_path)
        need = s.jobs_needing_full_jd()
        s.close()
        full_jds = [
            (j["job_id"], reed.full_description(j["raw"], http))
            for j in need if j["source"] == "reed"
        ]
        full_jds = [(jid, txt) for jid, txt in full_jds if txt]
        if full_jds:
            s = Store(db_path)
            for jid, txt in full_jds:
                s.apply_full_jd(jid, txt)
            s.close()
            totals["enriched"] = len(full_jds)
            log(f"  ↑ enriched {len(full_jds)} Reed JD(s) via detail API")

    http.close()
    if boards is not None:
        boards.close()

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
    ap.add_argument("--deep", action="store_true",
                    help="full window (ignore recent_days) — full/initial load")
    args = ap.parse_args(argv)

    setup_logging()
    _load_env()
    cfg = load_config(args.config)
    result = run_scan(cfg, args.db, only_source=args.source, dry_run=args.dry_run, deep=args.deep)

    t = result["totals"]
    bar = "━" * 45
    date = datetime.now(timezone.utc).date().isoformat()
    print(f"\n{bar}\nJob Scan — {date}\n{bar}")
    for k in ("found", "new", "dupes", "filtered", "errors", "expired", "enriched"):
        print(f"{k.capitalize()+':':9} {t.get(k, 0)}")
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
