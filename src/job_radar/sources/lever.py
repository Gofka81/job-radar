from __future__ import annotations

import httpx

from ..schema import Job
from .base import detect_remote, strip_tags

ID = "lever"
BASE = "https://api.lever.co/v0/postings"


def _description(it: dict) -> str:
    """Lever splits a posting across FOUR fields: `descriptionPlain` is only the
    intro blurb, `lists` holds the titled sections (What You'll Do / Who You Are —
    i.e. the requirements and tech stack), and `additionalPlain` the closing. Taking
    descriptionPlain alone dropped ~3/4 of the JD, including the part triage and the
    tech-stack search actually need."""
    parts = [it.get("descriptionPlain") or ""]
    for section in it.get("lists") or []:
        parts.append(section.get("text") or "")            # section heading
        parts.append(strip_tags(section.get("content") or ""))  # <li> markup
    parts.append(it.get("additionalPlain") or "")
    return "\n\n".join(p for p in (s.strip() for s in parts) if p)


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
                    description=(_lv_desc := _description(it)),
                    remote=detect_remote(it.get("text", "") or "",
                                         (it.get("categories") or {}).get("location", "") or "",
                                         _lv_desc),
                    raw=it,
                )
            )
    return jobs
