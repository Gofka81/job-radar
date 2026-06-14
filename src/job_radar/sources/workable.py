from __future__ import annotations

from datetime import date, datetime

import httpx

from ..schema import Job

ID = "workable"
# Public widget JSON — no auth. Slug is the apply.workable.com/{slug} subpath.
BASE = "https://apply.workable.com/api/v1/widget/accounts"


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _location(it: dict) -> str:
    parts = [it.get("city"), it.get("state"), it.get("country")]
    return ", ".join(p for p in parts if p)


def fetch(cfg: dict, http: httpx.Client) -> list[Job]:
    jobs: list[Job] = []
    for slug in cfg.get("companies", []):
        resp = http.get(f"{BASE}/{slug}", params={"details": "true"})
        if resp.status_code != 200:
            continue  # bad/closed account — skip, don't fail the scan
        data = resp.json()
        company = data.get("name") or slug
        for it in data.get("jobs", []):
            url = it.get("url") or it.get("shortlink") or it.get("application_url") or ""
            if not url:
                continue
            jobs.append(
                Job(
                    source=ID,
                    company=company,
                    title=it.get("title", "") or "",
                    url=url,
                    location=_location(it),
                    posted_at=_parse_date(it.get("published_on")),
                    remote=it.get("telecommuting"),
                    raw=it,
                )
            )
    return jobs
