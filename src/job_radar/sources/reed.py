from __future__ import annotations

import os
from datetime import date, datetime

import httpx

from ..schema import Job
from .base import detect_remote, cfg_locations, strip_tags

ID = "reed"
BASE = "https://www.reed.co.uk/api/1.0/search"
DETAIL = "https://www.reed.co.uk/api/1.0/jobs"  # per-job detail → FULL description


def full_description(raw: dict, http: httpx.Client, cfg: dict | None = None) -> str | None:
    """Fetch the FULL job description from Reed's per-job detail API. The search
    endpoint only returns a ~450-char snippet; this returns the whole thing. A
    deterministic API call (same HTTP Basic key), NOT scraping. Returns stripped
    text, or None on any failure / missing id (caller keeps the snippet)."""
    job_id = (raw or {}).get("jobId")
    key = os.environ.get("REED_API_KEY")
    if not job_id or not key:
        return None
    try:
        r = http.get(f"{DETAIL}/{job_id}", auth=(key, ""))
        r.raise_for_status()
        return strip_tags(r.json().get("jobDescription", "")) or None
    except Exception:
        return None


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def fetch(cfg: dict, http: httpx.Client) -> list[Job]:
    key = os.environ.get("REED_API_KEY")
    if not key:
        raise RuntimeError("REED_API_KEY not set in environment (.env)")

    queries = cfg.get("queries", ["data engineer"])
    take = cfg.get("results_to_take", 100)
    # Per-location targeting (mirror of adzuna): query priority cities separately
    # so each gets its own budget. where="" = nationwide. Legacy `location` honoured.
    locations = cfg_locations(cfg, "location", cfg.get("distance", 30))
    auth = (key, "")  # Reed: API key as username, blank password (HTTP Basic)

    jobs: list[Job] = []
    for q in queries:
        for where, distance in locations:
            params: dict = {"keywords": q, "resultsToTake": take}
            if where:
                params["locationName"] = where
                params["distanceFromLocation"] = distance
            resp = http.get(BASE, params=params, auth=auth)
            resp.raise_for_status()
            for it in resp.json().get("results", []):
                url = it.get("jobUrl") or ""
                if not url:
                    continue
                jobs.append(
                    Job(
                        source=ID,
                        company=it.get("employerName", "") or "",
                        title=it.get("jobTitle", "") or "",
                        url=url,
                        location=it.get("locationName", "") or "",
                        description=strip_tags(it.get("jobDescription", "")),
                        jd_full=False,  # search returns a 452-char snippet; enrich via detail API
                        remote=detect_remote(it.get("jobTitle", "") or "",
                                             it.get("locationName", "") or "",
                                             strip_tags(it.get("jobDescription", ""))),
                        posted_at=_parse_date(it.get("date")),
                        salary_min=it.get("minimumSalary"),
                        salary_max=it.get("maximumSalary"),
                        currency="GBP",
                        raw=it,
                    )
                )
    return jobs
