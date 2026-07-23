"""Indeed connector — Indeed's mobile GraphQL API (apis.indeed.com), NOT scraping.

Deterministic HTTP: one POST per query×location×page, cursor-paginated. Uses the
Indeed iOS app's public API key + headers (the same surface the app calls); no
login, no per-token cost. Endpoint reached over plain TLS (verify on).

Indeed and Glassdoor share one job index (both Recruit Holdings) — a Glassdoor
connector would be near-duplicate, so we only ship Indeed. The search response
already carries the full JD (`description.html`), so `jd_full` stays True — no
detail-API enrichment needed (unlike Reed).
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import httpx

from ..schema import Job
from .base import cfg_locations, strip_tags

ID = "indeed"
API = "https://apis.indeed.com/graphql"
BASE = "https://uk.indeed.com"  # UK site: job links + `indeed-co` country below

# Public key + headers from the Indeed iOS app (mobile GraphQL surface). `indeed-co`
# = the country code (GB) this pipeline targets. Host is derived from the URL.
_HEADERS = {
    "content-type": "application/json",
    "indeed-api-key": "161092c2017b5bbab13edb12461a62d5a833871e7cad6d9d475304573de67ac8",
    "accept": "application/json",
    "indeed-locale": "en-US",
    "accept-language": "en-US,en;q=0.9",
    "user-agent": ("Mozilla/5.0 (iPhone; CPU iPhone OS 16_6_1 like Mac OS X) "
                   "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Indeed App 193.1"),
    "indeed-app-info": "appv=193.1; appid=com.indeed.jobsearch; osv=16.6.1; os=ios; dtype=phone",
    "indeed-co": "GB",
}

# GraphQL query. Placeholders filled per page: {what}, {location}, {limit}, {cursor}.
# `dateOnIndeed` filter narrows to jobs seen in the last N hours (freshness).
_QUERY = """
query GetJobData {{
  jobSearch(
    {what}
    {location}
    limit: {limit}
    {cursor}
    sort: RELEVANCE
    filters: {{ date: {{ field: "dateOnIndeed", start: "{hours}h" }} }}
  ) {{
    pageInfo {{ nextCursor }}
    results {{ job {{
      key
      title
      datePublished
      employer {{ name }}
      description {{ html }}
      location {{ countryName countryCode admin1Code city formatted {{ short long }} }}
      compensation {{
        baseSalary {{ unitOfWork range {{ ... on Range {{ min max }} }} }}
        estimated {{ currencyCode baseSalary {{ unitOfWork range {{ ... on Range {{ min max }} }} }} }}
        currencyCode
      }}
      attributes {{ label }}
    }} }}
  }}
}}
"""


def _posted(ms: int | None) -> date | None:
    if not ms:
        return None
    try:
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date()
    except (ValueError, OverflowError, OSError):
        return None


def _salary(comp: dict) -> tuple[float | None, float | None, str | None]:
    """Annual GBP min/max, else (None, None, None). Indeed gives many pay units;
    we only trust YEAR (an hourly/daily figure shown as a salary would mislead)."""
    if not comp:
        return None, None, None
    base = comp.get("baseSalary") or (comp.get("estimated") or {}).get("baseSalary")
    if not base or (base.get("unitOfWork") or "").upper() != "YEAR":
        return None, None, None
    rng = base.get("range") or {}
    cur = comp.get("currencyCode") or (comp.get("estimated") or {}).get("currencyCode")
    return rng.get("min"), rng.get("max"), cur


def _location(loc: dict) -> str:
    """Readable location string for the filter + clean_location(). Prefer Indeed's
    formatted long form ("Edinburgh EH1 1BB"), fall back to city/region/country."""
    if not loc:
        return ""
    fmt = (loc.get("formatted") or {}).get("long")
    if fmt:
        return fmt
    parts = [loc.get("city"), loc.get("admin1Code"), loc.get("countryName")]
    return ", ".join(p for p in parts if p)


def _is_remote(job: dict, location: str, description: str) -> bool | None:
    hay = " ".join([
        location.lower(),
        (job.get("title") or "").lower(),
        " ".join((a.get("label") or "").lower() for a in job.get("attributes") or []),
    ])
    if any(k in hay for k in ("remote", "work from home", "wfh")):
        return True
    return None  # unknown — don't assert on-site from a search snippet


def _page(cfg_q: str, where: str, distance, hours: int, limit: int,
          cursor: str | None, http: httpx.Client) -> tuple[list[dict], str | None]:
    """One GraphQL page. Returns (job dicts, next cursor)."""
    what = f'what: "{cfg_q}"' if cfg_q else ""
    location = (f'location: {{where: "{where}", radius: {distance}, radiusUnit: MILES}}'
                if where else "")
    query = _QUERY.format(
        what=what, location=location, limit=limit, hours=hours,
        cursor=(f'cursor: "{cursor}"' if cursor else ""),
    )
    r = http.post(API, headers=_HEADERS, json={"query": query})
    r.raise_for_status()
    search = ((r.json().get("data") or {}).get("jobSearch")) or {}
    results = [it.get("job") or {} for it in (search.get("results") or [])]
    next_cursor = (search.get("pageInfo") or {}).get("nextCursor")
    return results, next_cursor


def fetch(cfg: dict, http: httpx.Client) -> list[Job]:
    queries = cfg.get("queries", ["data engineer"])
    # OR-join the queries into ONE boolean search per location (like linkedin), so
    # overlapping terms ("data engineer" / "data platform") aren't re-fetched under
    # each query. Indeed's `what` supports boolean OR; title_filter trims post-fetch.
    kw = " OR ".join(f'"{q}"' for q in queries if q)
    # Escape backslashes then quotes so the boolean quotes survive as literal `\"`
    # inside the GraphQL `what: "..."` string (Indeed then reads them as phrase quotes).
    q_esc = kw.replace("\\", "\\\\").replace('"', '\\"')
    # Per-location targeting (mirror of adzuna/reed) — distance in MILES for Indeed.
    # where="" = nationwide/remote pass.
    locations = cfg_locations(cfg, "where", cfg.get("distance", 40))
    hours = int(cfg.get("hours_old", 168))     # freshness window (last N hours seen)
    max_pages = int(cfg.get("max_pages", 2))   # cursor pages per location
    limit = min(int(cfg.get("results_per_page", 50)), 100)  # Indeed caps at 100

    jobs: list[Job] = []
    seen: set[str] = set()  # dedup keys across overlapping locations (e.g. city + nationwide)
    for where, distance in locations:
        cursor = None
        for _ in range(max_pages):
            results, cursor = _page(q_esc, where, distance, hours, limit, cursor, http)
            if not results:
                break
            for job in results:
                key = job.get("key")
                if not key or key in seen:
                    continue
                seen.add(key)
                loc = _location(job.get("location") or {})
                desc = strip_tags((job.get("description") or {}).get("html", ""))
                smin, smax, cur = _salary(job.get("compensation") or {})
                jobs.append(
                    Job(
                        source=ID,
                        company=((job.get("employer") or {}).get("name") or "")
                        if job.get("employer") else "",
                        title=job.get("title", "") or "",
                        url=f"{BASE}/viewjob?jk={key}",
                        location=loc,
                        description=desc,
                        posted_at=_posted(job.get("datePublished")),
                        salary_min=smin,
                        salary_max=smax,
                        currency=cur,
                        remote=_is_remote(job, loc, desc),
                        raw=job,
                    )
                )
            if not cursor:
                break
    return jobs
