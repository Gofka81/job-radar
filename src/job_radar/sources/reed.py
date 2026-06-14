from __future__ import annotations

import os
from datetime import date, datetime

import httpx

from ..schema import Job

ID = "reed"
BASE = "https://www.reed.co.uk/api/1.0/search"


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
    location = cfg.get("location", "")
    distance = cfg.get("distance", 30)
    take = cfg.get("results_to_take", 100)
    auth = (key, "")  # Reed: API key as username, blank password (HTTP Basic)

    jobs: list[Job] = []
    for q in queries:
        params: dict = {"keywords": q, "resultsToTake": take}
        if location:
            params["locationName"] = location
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
                    posted_at=_parse_date(it.get("date")),
                    salary_min=it.get("minimumSalary"),
                    salary_max=it.get("maximumSalary"),
                    currency="GBP",
                    raw=it,
                )
            )
    return jobs
