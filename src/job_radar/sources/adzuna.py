from __future__ import annotations

import os
from datetime import date, datetime

import httpx

from ..schema import Job
from .base import cfg_locations, strip_tags

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
    # Per-location targeting: each (where, distance) gets its own date-sorted
    # budget, so high-volume London can't crowd out Edinburgh/Glasgow. where=""
    # is a nationwide/remote catch-all. Falls back to legacy where/distance.
    locations = cfg_locations(cfg, "where", cfg.get("distance", 50))
    sort_by = cfg.get("sort_by", "date")  # freshest first
    max_days_old = cfg.get("max_days_old", 7)  # tighter window — we scan often + dedup
    max_pages = cfg.get("max_pages", 2)  # low: pages × queries × locations all hit the API quota
    per_page = cfg.get("results_per_page", 50)
    category = cfg.get("category", "it-jobs")  # server-side narrowing; "" to disable
    # Push the negative title terms server-side so seniority/stacks we'd filter out
    # locally don't eat the page budget. Accepts a string or list.
    excl = cfg.get("what_exclude", "")
    what_exclude = " ".join(excl) if isinstance(excl, list) else (excl or "")

    base_params = {
        "app_id": app_id,
        "app_key": app_key,
        "results_per_page": per_page,
        "max_days_old": max_days_old,
        "content-type": "application/json",
    }
    if sort_by:
        base_params["sort_by"] = sort_by
    if category:
        base_params["category"] = category
    if what_exclude:
        base_params["what_exclude"] = what_exclude

    jobs: list[Job] = []
    for q in queries:
        for where, distance in locations:
            for page in range(1, max_pages + 1):
                params = {**base_params, "what": q}
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
                            description=strip_tags(it.get("description", "")),
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
