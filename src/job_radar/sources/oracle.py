from __future__ import annotations

from datetime import date, datetime

import httpx

from ..schema import Job
from .base import strip_tags

ID = "oracle"
# Oracle Cloud Recruiting (ORC / Fusion HCM CandidateExperience) — self-hosted per
# tenant (UK banks: JPMorgan, etc.). The public REST feed needs the careers
# `siteNumber` from the URL https://{host}/hcmUI/CandidateExperience/en/sites/{site}.
# `keyword` searches the full JD server-side, so the stored snippet is enough.
_PATH = "/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
_PAGE = 20


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _locations(r: dict) -> list[str]:
    """Primary + secondary locations (a multi-location req → one Job per city,
    which the store merges into a single row)."""
    out = []
    if r.get("PrimaryLocation"):
        out.append(r["PrimaryLocation"])
    for s in r.get("secondaryLocations") or []:
        name = s.get("Name") if isinstance(s, dict) else s
        if name:
            out.append(name)
    return out


def fetch(cfg: dict, http: httpx.Client) -> list[Job]:
    jobs: list[Job] = []
    queries = cfg.get("queries") or [""]
    max_pages = int(cfg.get("max_pages", 2))
    for c in cfg.get("companies", []):
        host, site = c.get("host"), c.get("site")
        if not host or not site:
            continue  # malformed entry — skip, don't fail the scan
        company = c.get("name") or host.split(".")[0]
        base = f"https://{host}{_PATH}"
        for q in queries:
            for page in range(max_pages):
                offset = page * _PAGE
                kw = f',keyword="{q}"' if q else ""
                finder = (f"findReqs;siteNumber={site}{kw},"
                          f"limit={_PAGE},offset={offset},sortBy=POSTING_DATES_DESC")
                try:
                    resp = http.get(base, headers={"accept": "application/json"}, params={
                        "onlyData": "true",
                        "expand": "requisitionList.secondaryLocations",
                        "finder": finder,
                    })
                except httpx.HTTPError:
                    break  # network issue for this tenant — move on
                if resp.status_code != 200:
                    break  # bad host/site or rate-limited — skip the rest
                items = resp.json().get("items") or []
                reqs = items[0].get("requisitionList") or [] if items else []
                for r in reqs:
                    jobs.extend(_postings(host, site, company, r))
                total = items[0].get("TotalJobsCount") if items else 0
                if not reqs or offset + _PAGE >= (total or 0):
                    break
    return jobs


def _postings(host: str, site: str, company: str, r: dict) -> list[Job]:
    rid = r.get("Id")
    if not rid:
        return []
    url = f"https://{host}/hcmUI/CandidateExperience/en/sites/{site}/job/{rid}"
    title = r.get("Title", "") or ""
    desc = strip_tags(r.get("ShortDescriptionStr", "") or "")
    posted = _parse_date(r.get("PostedDate"))
    return [
        Job(source=ID, company=company, title=title, url=url, location=loc,
            description=desc, posted_at=posted, raw=r)
        for loc in (_locations(r) or [""])
    ]
