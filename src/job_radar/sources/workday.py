from __future__ import annotations

from datetime import date, datetime

import httpx

from ..schema import Job
from .base import strip_tags

ID = "workday"
# Workday self-hosts per tenant; the public careers site is backed by the "CXS"
# JSON API. Each company config entry gives its host + site:
#   { host: "natwest.wd3.myworkdayjobs.com", site: "NatWestGroup", name: "NatWest" }
# tenant defaults to the first host label. `queries` (server-side searchText)
# narrows the list so we only fetch JD detail for relevant roles.
_HEADERS = {"accept": "application/json", "content-type": "application/json"}
_PAGE = 20


def _tenant(host: str, explicit: str | None) -> str:
    return explicit or host.split(".")[0]


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _detail_locations(info: dict) -> list[str]:
    """Primary + additional locations from a posting's detail (a multi-location
    req lists several; each becomes a Job that the store merges into one row)."""
    out = []
    if info.get("location"):
        out.append(info["location"])
    out += [a for a in (info.get("additionalLocations") or []) if a]
    return out


def fetch(cfg: dict, http: httpx.Client) -> list[Job]:
    jobs: list[Job] = []
    queries = cfg.get("queries") or [""]
    max_pages = int(cfg.get("max_pages", 2))
    for c in cfg.get("companies", []):
        host, site = c.get("host"), c.get("site")
        if not host or not site:
            continue  # malformed entry — skip, don't fail the scan
        tenant = _tenant(host, c.get("tenant"))
        company = c.get("name") or tenant
        lang = c.get("lang", "en-US")
        cxs = f"https://{host}/wday/cxs/{tenant}/{site}"
        # Collect unique postings across ALL queries/pages FIRST (keyed by
        # externalPath), THEN fetch each JD detail exactly once. A req matching
        # several queries otherwise had its detail re-fetched per query — the N+1.
        listings: dict[str, dict] = {}
        for q in queries:
            for page in range(max_pages):
                try:
                    resp = http.post(
                        f"{cxs}/jobs", headers=_HEADERS,
                        json={"limit": _PAGE, "offset": page * _PAGE,
                              "searchText": q, "appliedFacets": {}},
                    )
                except httpx.HTTPError:
                    break  # network issue for this tenant — move on
                if resp.status_code != 200:
                    break  # bad host/site or rate-limited — skip the rest
                data = resp.json()
                postings = data.get("jobPostings") or []
                for p in postings:
                    path = p.get("externalPath") or ""
                    if path:
                        listings.setdefault(path, p)  # first sighting wins; dedups queries
                if not postings or (page + 1) * _PAGE >= (data.get("total") or 0):
                    break
        for path, p in listings.items():
            jobs.extend(_postings(http, cxs, host, lang, site, company, p, path))
    return jobs


def _postings(http, cxs, host, lang, site, company, p, path) -> list[Job]:
    """One list entry → one Job per location (detail call adds the JD + cities)."""
    title = p.get("title", "") or ""
    url = f"https://{host}/{lang}/{site}{path}"
    description, posted, locations = "", None, []
    try:
        d = http.get(f"{cxs}{path}", headers=_HEADERS)
        if d.status_code == 200:
            info = (d.json() or {}).get("jobPostingInfo") or {}
            description = strip_tags(info.get("jobDescription", "") or "")
            posted = _parse_date(info.get("startDate"))
            title = info.get("title") or title
            url = info.get("externalUrl") or url
            locations = _detail_locations(info)
    except httpx.HTTPError:
        pass  # detail fetch failed — fall back to the list location text
    if not locations:
        locations = [p.get("locationsText", "") or ""]
    return [
        Job(source=ID, company=company, title=title, url=url, location=loc,
            description=description, posted_at=posted, raw=p)
        for loc in locations
    ]
