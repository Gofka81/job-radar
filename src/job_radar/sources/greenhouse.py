from __future__ import annotations

import httpx

from ..schema import Job

ID = "greenhouse"
BASE = "https://boards-api.greenhouse.io/v1/boards"


def fetch(cfg: dict, http: httpx.Client) -> list[Job]:
    jobs: list[Job] = []
    for slug in cfg.get("companies", []):
        resp = http.get(f"{BASE}/{slug}/jobs")
        if resp.status_code != 200:
            # Bad slug / closed board — skip, don't fail the whole scan.
            continue
        for it in resp.json().get("jobs", []):
            url = it.get("absolute_url") or ""
            if not url:
                continue
            jobs.append(
                Job(
                    source=ID,
                    company=slug,
                    title=it.get("title", "") or "",
                    url=url,
                    location=(it.get("location") or {}).get("name", "") or "",
                    raw=it,
                )
            )
    return jobs
