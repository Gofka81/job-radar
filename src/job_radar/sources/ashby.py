from __future__ import annotations

import httpx

from ..schema import Job

ID = "ashby"
BASE = "https://api.ashbyhq.com/posting-api/job-board"


def fetch(cfg: dict, http: httpx.Client) -> list[Job]:
    jobs: list[Job] = []
    for slug in cfg.get("companies", []):
        resp = http.get(f"{BASE}/{slug}", params={"includeCompensation": "true"})
        if resp.status_code != 200:
            continue
        for it in resp.json().get("jobs", []):
            url = it.get("jobUrl") or ""
            if not url:
                continue
            jobs.append(
                Job(
                    source=ID,
                    company=slug,
                    title=it.get("title", "") or "",
                    url=url,
                    location=it.get("location", "") or "",
                    description=it.get("descriptionPlain", "") or "",
                    raw=it,
                )
            )
    return jobs
