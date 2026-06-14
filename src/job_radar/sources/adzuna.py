from __future__ import annotations

import os
from datetime import date, datetime

import httpx

from ..schema import Job
from .base import strip_tags

ID = "adzuna"
BASE = "https://api.adzuna.com/v1/api/jobs"


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def fetch(cfg: dict, http: httpx.Client) -> list[Job]:
    app_id = os.environ.get("ADZUNA_APP_ID")
    app_key = os.environ.get("ADZUNA_APP_KEY")
    if not app_id or not app_key:
        raise RuntimeError("ADZUNA_APP_ID / ADZUNA_APP_KEY not set in environment (.env)")

    country = cfg.get("country", "gb")
    queries = cfg.get("queries", ["data engineer"])
    where = cfg.get("where", "")  # "" = nationwide; let location_filter pick cities
    distance = cfg.get("distance", 50)
    sort_by = cfg.get("sort_by", "date")  # freshest first, so no city dominates the cap
    max_days_old = cfg.get("max_days_old", 14)
    max_pages = cfg.get("max_pages", 5)
    per_page = cfg.get("results_per_page", 50)

    jobs: list[Job] = []
    for q in queries:
        for page in range(1, max_pages + 1):
            params = {
                "app_id": app_id,
                "app_key": app_key,
                "what": q,
                "results_per_page": per_page,
                "max_days_old": max_days_old,
                "content-type": "application/json",
            }
            if sort_by:
                params["sort_by"] = sort_by
            if where:
                params["where"] = where
                params["distance"] = distance
            resp = http.get(f"{BASE}/{country}/search/{page}", params=params)
            resp.raise_for_status()
            results = resp.json().get("results", [])
            if not results:
                break
            for it in results:
                url = it.get("redirect_url") or ""
                if not url:
                    continue
                jobs.append(
                    Job(
                        source=ID,
                        company=(it.get("company") or {}).get("display_name", "") or "",
                        title=strip_tags(it.get("title", "")),
                        url=url,
                        location=(it.get("location") or {}).get("display_name", "") or "",
                        posted_at=_parse_date(it.get("created")),
                        salary_min=it.get("salary_min"),
                        salary_max=it.get("salary_max"),
                        currency="GBP" if country == "gb" else None,
                        raw=it,
                    )
                )
            if len(results) < per_page:
                break
    return jobs
