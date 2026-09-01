from __future__ import annotations

import html

import httpx

from ..schema import Job
from .base import detect_remote, strip_tags

ID = "greenhouse"
BASE = "https://boards-api.greenhouse.io/v1/boards"


def fetch(cfg: dict, http: httpx.Client) -> list[Job]:
    jobs: list[Job] = []
    for slug in cfg.get("companies", []):
        # content=true returns each job's full (HTML-escaped) description in the
        # same call — no extra requests — so the JD is searchable for tech stack.
        resp = http.get(f"{BASE}/{slug}/jobs", params={"content": "true"})
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
                    # content is HTML-escaped HTML: unescape entities, then drop tags
                    description=(_gh_desc := strip_tags(html.unescape(it.get("content", "") or ""))),
                    remote=detect_remote(it.get("title", "") or "",
                                         (it.get("location") or {}).get("name", "") or "", _gh_desc),
                    raw=it,
                )
            )
    return jobs
