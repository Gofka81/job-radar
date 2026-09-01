from __future__ import annotations

import argparse
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from . import setup_logging
from .config import ROOT, load_config

logger = logging.getLogger("job_radar.scan")
from .filters import build_location_filter, build_title_filter
from .locations import set_priority
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


def archive_dir(db_path: str | Path | None, cfg: dict) -> Path:
    """Where the Parquet history lives — next to the DB (so it's on the same
    jobs-data volume and survives redeploys) unless `archive_dir` overrides it."""
    if cfg.get("archive_dir"):
        return Path(cfg["archive_dir"])
    return Path(db_path).parent / "archive"


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
              "enriched": 0, "archived": 0}
    new_jobs: list[Job] = []  # newly-inserted vacancies → exactly what we notify
    live_sources: list[str] = []  # sources that fetched OK this run (safe to prune)
    started = datetime.now(timezone.utc)

    for sid, mod in REGISTRY.items():
        scfg = sources_cfg.get(sid, {})
        if not scfg.get("enabled", False):
            continue
        if only_source and sid != only_source:
            continue

        # Regular scans tighten the freshness window (fewer results + fewer API
        # calls, since empty pages break the loop earlier). Only affects sources
        # with a max_days_old knob (Adzuna). Deep scans use the full window.
        if recent_days and "max_days_old" in scfg:
            scfg = {**scfg, "max_days_old": min(int(scfg["max_days_old"]), int(recent_days))}
        # Same freshness tightening for hour-windowed sources (indeed, linkedin): a
        # regular scan looks back recent_days×24h at most. Only fires when recent_days
        # is set (unset by default), so no behaviour change out of the box.
        if recent_days and "hours_old" in scfg:
            scfg = {**scfg, "hours_old": min(int(scfg["hours_old"]), int(recent_days) * 24)}

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
            if not title_ok(job.title) or not loc_ok(job.location, job.remote):
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

    # Enrich stub JDs: a source whose search results carry no/partial description
    # sets jd_full=False and exposes full_description(raw, http, cfg) -> str | None.
    # One-shot per job (the flag flips on success), so this only touches newly
    # inserted stubs. Fetch over HTTP first (no DB lock), then a quick write burst.
    # Best-effort — a failure leaves the stub and it retries next scan.
    if not dry_run and cfg.get("fetch_full_jd", True):
        cap = int(cfg.get("full_jd_max", 150))  # detail calls are 1/job — bound the burst
        s = Store(db_path)
        need = s.jobs_needing_full_jd(limit=cap)
        s.close()
        full_jds, by_source = [], {}
        for j in need:
            fn = getattr(REGISTRY.get(j["source"]), "full_description", None)
            if fn is None:
                continue
            try:
                txt = fn(j["raw"], http, sources_cfg.get(j["source"], {}))
            except Exception:
                txt = None  # one bad detail fetch must not kill the enrichment pass
            if txt:
                full_jds.append((j["job_id"], txt))
                by_source[j["source"]] = by_source.get(j["source"], 0) + 1
        if full_jds:
            s = Store(db_path)
            for jid, txt in full_jds:
                s.apply_full_jd(jid, txt)
            s.close()
            totals["enriched"] = len(full_jds)
            detail = ", ".join(f"{k} {v}" for k, v in sorted(by_source.items()))
            log(f"  ↑ enriched {len(full_jds)} JD(s) via detail API ({detail})")

    http.close()

    # Mark jobs that dropped off their (successfully-scanned) source > N hours ago
    # as 'expired' — the posting is closed/filled. Marked, not deleted, so it stays
    # for history and reactivates if relisted (see Store.upsert / expire_stale).
    if not dry_run and live_sources:
        s = Store(db_path)
        totals["expired"] = s.expire_stale(int(cfg.get("expire_after_hours", 24)), live_sources)
        s.close()
        if totals["expired"]:
            log(f"  ⌫ expired {totals['expired']} closed job(s)")

    # Cold history: move long-expired rows out to month-partitioned Parquet so the
    # live DB stays small while every row is kept for analytics. Write-verify-delete
    # (see Store.archive_expired) — a failed write deletes nothing. Best-effort: an
    # archive failure must never fail the scan that already stored new jobs.
    if not dry_run and cfg.get("archive_after_days"):
        s = Store(db_path)
        try:
            res = s.archive_expired(archive_dir(db_path, cfg), int(cfg["archive_after_days"]))
            totals["archived"] = res["archived"]
            if res["archived"]:
                log(f"  📦 archived {res['archived']} expired job(s) → {', '.join(res['months'])}")
        except Exception as exc:
            log(f"  ✗ archive skipped: {exc}")
        finally:
            s.close()

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


def compact_db(db_path: str | Path) -> tuple[int, int]:
    """Reclaim free space by rewriting the DB into a fresh file and swapping it in.
    DuckDB has no VACUUM and never shrinks in place, so deletes (expiry, archiving)
    leave the file fragmented — a rewrite is the only way back.

    MANUAL ONLY, never on the scan path: this replaces the DB file, and doing that
    under a live server risks a reader hitting a half-swapped file. Stop the
    container, run it, start it. Returns (bytes_before, bytes_after)."""
    src = Path(db_path)
    before = src.stat().st_size
    tmp = src.with_suffix(".compact.duckdb")
    tmp.unlink(missing_ok=True)
    con = duckdb.connect(str(tmp))
    con.execute(f"ATTACH '{src}' AS old (READ_ONLY)")
    for (table,) in con.execute(
            "SELECT table_name FROM duckdb_tables() WHERE database_name = 'old'").fetchall():
        con.execute(f'CREATE TABLE "{table}" AS SELECT * FROM old."{table}"')
    con.close()
    after = tmp.stat().st_size
    tmp.replace(src)
    return before, after


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
    ap.add_argument("--compact", action="store_true",
                    help="rewrite the DB to reclaim free space, then exit (STOP THE "
                         "SERVER FIRST — this replaces the DB file)")
    args = ap.parse_args(argv)

    setup_logging()
    _load_env()
    cfg = load_config(args.config)
    if args.compact:
        before, after = compact_db(args.db)
        print(f"compacted {args.db}: {before/1e6:.2f} MB → {after/1e6:.2f} MB")
        return 0
    result = run_scan(cfg, args.db, only_source=args.source, dry_run=args.dry_run, deep=args.deep)

    t = result["totals"]
    bar = "━" * 45
    date = datetime.now(timezone.utc).date().isoformat()
    print(f"\n{bar}\nJob Scan — {date}\n{bar}")
    for k in ("found", "new", "dupes", "filtered", "errors", "expired", "enriched",
              "archived"):
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
