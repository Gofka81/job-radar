from __future__ import annotations

from datetime import date, datetime

import httpx

from ..schema import Job
from .base import detect_remote, strip_tags

ID = "oracle"
# Oracle Cloud Recruiting (ORC / Fusion HCM CandidateExperience) — self-hosted per
# tenant (UK banks: JPMorgan, etc.). The public REST feed needs the careers
# `siteNumber` from the URL https://{host}/hcmUI/CandidateExperience/en/sites/{site}.
# `keyword` searches the full JD server-side, but the LIST only returns a short
# blurb (`ShortDescriptionStr`) — the real JD comes from the per-requisition detail
# feed, fetched once per job after the scan (see full_description).
_PATH = "/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
_DETAIL = "/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails"
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
                # sortBy=RELEVANCY, NOT POSTING_DATES_DESC: Oracle's keyword match is
                # very loose (a big tenant returns 1000+ hits for "data platform"), so
                # date-sorting + a small page window only ever shows the newest-globally
                # slice (mostly out-of-scope US/India roles) and buries real title-matches
                # like JPMorgan's London "Cloud Data Platform Software Engineer II".
                finder = (f"findReqs;siteNumber={site}{kw},"
                          f"limit={_PAGE},offset={offset},sortBy=RELEVANCY")
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
    # Stash host/site in raw: the post-scan detail fetch needs them to build its URL.
    raw = {**r, "_host": host, "_site": site}
    return [
        Job(source=ID, company=company, title=title, url=url, location=loc,
            description=desc, jd_full=False,  # blurb only → enriched via _DETAIL
            remote=detect_remote(title, loc, desc), posted_at=posted, raw=raw)
        for loc in (_locations(r) or [""])
    ]


def full_description(raw: dict, http: httpx.Client, cfg: dict | None = None) -> str | None:
    """Full JD from the per-requisition detail feed. The list endpoint only carries
    `ShortDescriptionStr` (a blurb), which is too thin to search or triage on.
    Returns None on any failure — the caller keeps the blurb and retries next scan."""
    rid, host, site = (raw or {}).get("Id"), (raw or {}).get("_host"), (raw or {}).get("_site")
    if not (rid and host and site):
        return None
    try:
        r = http.get(f"https://{host}{_DETAIL}", headers={"accept": "application/json"},
                     params={"onlyData": "true", "expand": "all",
                             "finder": f'ByIdAndSiteNumber;Id="{rid}",siteNumber={site}'})
        if r.status_code != 200:
            return None
        items = r.json().get("items") or []
        if not items:
            return None
        d = items[0]
        text = " ".join(strip_tags(d.get(k) or "") for k in
                        ("CorporateDescriptionStr", "ExternalDescriptionStr",
                         "ExternalQualificationsStr", "ExternalResponsibilitiesStr"))
        return text.strip() or None
    except (httpx.HTTPError, ValueError):
        return None
