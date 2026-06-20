from __future__ import annotations

import httpx

from ..schema import Job

ID = "lever"
BASE = "https://api.lever.co/v0/postings"


def fetch(cfg: dict, http: httpx.Client) -> list[Job]:
    jobs: list[Job] = []
    for slug in cfg.get("companies", []):
        resp = http.get(f"{BASE}/{slug}", params={"mode": "json"})
        if resp.status_code != 200:
            continue
        data = resp.json()
        if not isinstance(data, list):
            continue
        for it in data:
            url = it.get("hostedUrl") or it.get("applyUrl") or ""
            if not url:
                continue
            jobs.append(
                Job(
                    source=ID,
                    company=slug,
                    title=it.get("text", "") or "",
                    url=url,
                    location=(it.get("categories") or {}).get("location", "") or "",
                    description=it.get("descriptionPlain", "") or "",
                    raw=it,
                )
            )
    return jobs
