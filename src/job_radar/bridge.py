"""PC-side bridge to the Pi API. No DB here — the PC only talks HTTP.

  job-bridge pull   GET /api/pending  -> writes career-ops pipeline.md
  job-bridge push   reads results.tsv -> POST /api/results

results.tsv is a tab-separated file the PC produces after evaluation, keyed by
the job URL (what career-ops works in):
    url<TAB>score<TAB>status<TAB>report_num
(only url is required per row; blank cells are skipped). All rows go in one POST;
the Pi applies each independently and skips any URL it doesn't recognise.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

import httpx

from .config import ROOT

TIMEOUT = 30.0
# career-ops's pipeline reader is language-agnostic (modes/*/pipeline.md: "be
# flexible when reading"), so we write English. Override with --section if you
# ever want to match a Spanish file exactly.
PENDING_SECTION = "Pending"


def _load_env() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    except Exception:
        pass


def _client(base_url: str, token: str) -> httpx.Client:
    if not base_url or not token:
        raise SystemExit(
            "Set JOB_RADAR_API_URL and JOB_RADAR_API_TOKEN (in .env) first."
        )
    return httpx.Client(
        base_url=base_url.rstrip("/"),
        headers={"authorization": f"Bearer {token}"},
        timeout=TIMEOUT,
    )


def render_pipeline(jobs: list[dict], section: str = PENDING_SECTION) -> str:
    """The career-ops integration contract: one job per checkbox line."""
    lines = [f"## {section}", ""]
    for j in jobs:
        url = j.get("url", "")
        company = j.get("company", "") or ""
        title = j.get("title", "") or ""
        lines.append(f"- [ ] {url} | {company} | {title}")
    return "\n".join(lines) + "\n"


def _parse_score(raw: str) -> float:
    """Accept a plain number or career-ops's "4.1/5" style."""
    return float(raw.split("/", 1)[0].strip())


def read_results(path: str | Path) -> list[dict]:
    """Read url-keyed verdicts. Each non-empty `url` row becomes one verdict;
    all are sent in a single POST (the Pi applies them independently)."""
    out: list[dict] = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            url = (row.get("url") or "").strip()
            if not url:
                continue
            verdict: dict = {"url": url}
            if (row.get("score") or "").strip():
                verdict["score"] = _parse_score(row["score"])
            if (row.get("status") or "").strip():
                verdict["status"] = row["status"].strip()
            if (row.get("report_num") or "").strip():
                verdict["report_num"] = int(row["report_num"])
            out.append(verdict)
    return out


def pull(base_url: str, token: str, out_path: str | Path, section: str = PENDING_SECTION) -> int:
    with _client(base_url, token) as c:
        resp = c.get("/api/pending")
        resp.raise_for_status()
        jobs = resp.json().get("jobs", [])
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_pipeline(jobs, section), encoding="utf-8")
    print(f"pulled {len(jobs)} pending job(s) -> {out}")
    return 0


def push(base_url: str, token: str, results_path: str | Path) -> int:
    results = read_results(results_path)
    if not results:
        print(f"no verdicts in {results_path} — nothing to push")
        return 0
    with _client(base_url, token) as c:
        resp = c.post("/api/results", json={"results": results})
        resp.raise_for_status()
    print(f"pushed {len(results)} verdict(s): {resp.json()}")
    return 0


def main(argv: list[str] | None = None) -> int:
    _load_env()
    ap = argparse.ArgumentParser(prog="job-bridge", description="PC <-> Pi API bridge.")
    ap.add_argument("--url", default=os.environ.get("JOB_RADAR_API_URL", ""))
    ap.add_argument("--token", default=os.environ.get("JOB_RADAR_API_TOKEN", ""))
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_pull = sub.add_parser("pull", help="fetch pending -> write pipeline.md")
    p_pull.add_argument("--out", required=True, help="path to career-ops pipeline.md")
    p_pull.add_argument("--section", default=PENDING_SECTION)

    p_push = sub.add_parser("push", help="read results.tsv -> post verdicts")
    p_push.add_argument("--results", required=True, help="path to results.tsv")

    args = ap.parse_args(argv)
    try:
        if args.cmd == "pull":
            return pull(args.url, args.token, args.out, args.section)
        if args.cmd == "push":
            return push(args.url, args.token, args.results)
    except httpx.HTTPError as exc:
        print(f"bridge error: {exc}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
