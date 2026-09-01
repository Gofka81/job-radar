"""LinkedIn connector — the public guest jobs endpoint (`jobs-guest`), NOT scraping
a logged-in session. Deterministic HTTP: one GET per location×page, `start`-paginated.

No login, no cookie, no account (so no ban risk — the only defense is per-IP rate
limiting, ~10 pages/IP before 429). We stay far under that by filtering hard
server-side and rotating a proxy pool:

- keywords: the config `queries` array OR-joined into ONE boolean search per
  location (3 terms = 1 request, not 3), so `title_filter` still trims post-fetch.
- f_TPR: only jobs posted in the last `hours_old` hours (the biggest page-cut;
  most of the index is old). sortBy=DD → freshest first, so early-stop is safe.
- locations: per-location passes (like adzuna/indeed) so London can't crowd out
  Scotland; distance in MILES; `where=""`/`geoId` optional.
- proxies: round-robin a Webshare-style list (`user:pass@host:port`); a 429/error
  rotates to the next IP. Empty list = direct (fine for the tiny per-scan budget).

The guest search card carries no JD, so cards are emitted with `jd_full=False` and
`full_description()` back-fills the real JD from the guest job-detail endpoint after
the scan — one request per NEW job, once ever (scan.py's `full_jd_max` caps the burst).
Run on the DEEP-scan cadence, not every 2h.

`remote_pass` adds ONE extra search per location with "AND remote" appended to the
keywords, then confirms each hit against its JD — see the remote-pass block in
fetch(). This is how remote roles outside the allowed cities get found at all.
"""

from __future__ import annotations

import html as _html
import logging
import random
import re
import time
from datetime import date

import httpx

from ..schema import Job
from .base import detect_remote, strip_tags

logger = logging.getLogger("job_radar.sources.linkedin")

ID = "linkedin"
BASE = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"

_HEADERS = {
    "user-agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"),
    "accept": "text/html,application/xhtml+xml",
    "accept-language": "en-GB,en;q=0.9",
}


class _ProxyPool:
    """Round-robins a proxy list, one request at a time, caching a client per proxy.
    `get` tries proxies until one returns 200 (so a 429/dead IP just rotates on).
    An empty list means one direct (no-proxy) client."""

    def __init__(self, proxies: list[str]):
        self.urls = [self._norm(p) for p in proxies] or [None]
        self.i = 0
        self._clients: dict[str | None, httpx.Client] = {}

    @staticmethod
    def _norm(p: str) -> str:
        p = (p or "").strip()
        return p if "://" in p else f"http://{p}"  # Webshare list is bare host:port

    def _client(self, url: str | None) -> httpx.Client:
        if url not in self._clients:
            self._clients[url] = httpx.Client(
                proxy=url, headers=_HEADERS, timeout=25, follow_redirects=True)
        return self._clients[url]

    def get(self, url: str, params: dict) -> httpx.Response | None:
        last: object = None
        for _ in range(len(self.urls)):
            purl = self.urls[self.i]
            self.i = (self.i + 1) % len(self.urls)
            try:
                r = self._client(purl).get(url, params=params)
                if r.status_code == 200:
                    return r
                last = r.status_code  # 429 / block → try the next IP
            except Exception as exc:
                last = type(exc).__name__
        logger.debug("linkedin: all %d proxies failed (last=%s)", len(self.urls), last)
        return None

    def close(self) -> None:
        for c in self._clients.values():
            c.close()


def _text(m: re.Match | None) -> str:
    """Unescape entities + strip tags + collapse whitespace from a capture group."""
    if not m:
        return ""
    return re.sub(r"\s+", " ", strip_tags(_html.unescape(m.group(1)))).strip()


def _parse_card(card: str) -> Job | None:
    """One <li> job card → Job, or None if it has no job link (an ad/spacer)."""
    # Capture the clean job URL, stopping at ? (drop tracking query) — no trailing
    # quote anchor, since real hrefs carry ?trk=… before the closing ".
    url_m = re.search(r'href="(https://[^"?]*?linkedin\.com/jobs/view/[^"?]+)', card)
    if not url_m:
        return None
    title = _text(re.search(r'base-search-card__title"[^>]*>(.*?)</h3>', card, re.S))
    company = _text(re.search(r'base-search-card__subtitle"[^>]*>(.*?)</h4>', card, re.S))
    location = _text(re.search(r'job-search-card__location"[^>]*>(.*?)</span>', card, re.S))
    posted_m = re.search(r'datetime="(\d{4}-\d{2}-\d{2})"', card)
    posted = None
    if posted_m:
        try:
            posted = date.fromisoformat(posted_m.group(1))
        except ValueError:
            posted = None
    hay = f"{title} {location}".lower()
    remote = True if any(w in hay for w in ("remote", "work from home", "wfh")) else None
    return Job(
        source=ID, company=company, title=title, url=url_m.group(1),
        location=location, description="",  # guest card has no JD — enriched post-scan
        jd_full=False,                       # → scan.py calls full_description() once
        posted_at=posted, remote=remote, raw={"card_url": url_m.group(1)},
    )


JOB_DETAIL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting"

# The guest job page wraps the JD in .show-more-less-html__markup.
_JD_RE = re.compile(r'show-more-less-html__markup[^>]*>(.*?)</div>', re.S)


def full_description(raw: dict, http: httpx.Client, cfg: dict | None = None) -> str | None:
    """Fetch the full JD from the guest job-detail endpoint (no login, same soft
    surface as the search endpoint). The search card carries no description at all,
    so this is what makes LinkedIn jobs searchable/triageable. One request per job —
    scan.py caps the batch (`full_jd_max`). Returns None on any failure; the caller
    keeps the empty stub and retries next scan."""
    url = (raw or {}).get("card_url") or ""
    m = re.search(r'/jobs/view/(?:[^/?]*-)?(\d+)', url)
    if not m:
        return None
    pool = _ProxyPool((cfg or {}).get("proxies") or [])  # same IP rotation as search
    try:
        r = pool.get(f"{JOB_DETAIL}/{m.group(1)}", {})
        if r is None:
            return None
        m2 = _JD_RE.search(r.text)
        if not m2:
            return None
        # Strip tags to a SPACE, not "": the JD is block markup, and dropping the
        # tags outright welds words together ("...AtlanticGeneral Atlantic is...").
        text = _html.unescape(re.sub(r"<[^>]+>", " ", m2.group(1)))
        return re.sub(r"\s+", " ", text).strip() or None
    finally:
        pool.close()


def _page_html(pool: _ProxyPool, params: dict) -> str | None:
    """One search page's HTML (the seam tests monkeypatch). None = all proxies failed."""
    r = pool.get(BASE, params)
    return r.text if r is not None else None


def fetch(cfg: dict, http: httpx.Client) -> list[Job]:
    queries = cfg.get("queries") or ["data engineer"]
    kw = " OR ".join(f'"{q}"' for q in queries)  # 1 term → '"data engineer"' (no OR)
    hours = int(cfg.get("hours_old", 168))       # f_TPR window; regular scans may tighten it
    tpr = f"r{max(1, hours) * 3600}"
    max_pages = int(cfg.get("max_pages", 2))
    delay = float(cfg.get("request_delay", 1.5))  # politeness between pages
    locations = cfg.get("locations") or [
        {"where": cfg.get("where", ""), "distance": cfg.get("distance", 25)}]

    pool = _ProxyPool(cfg.get("proxies") or [])
    jobs: list[Job] = []
    seen: set[str] = set()
    try:
        for loc in locations:
            jobs.extend(_search(pool, kw, tpr, loc, max_pages, delay, seen))

        # --- remote pass -------------------------------------------------------
        # LinkedIn labels a remote role with the EMPLOYER's city and its guest card
        # exposes no workplace type (f_WT is ignored on this endpoint — verified:
        # on-site/remote/hybrid return identical results), so remote roles outside
        # the allowed cities are invisible to a city whitelist. Appending "AND remote"
        # to the keyword search is a cheap, deterministic proxy: measured 70-80% of
        # its hits are genuinely remote vs 0% in the plain query. We then CONFIRM each
        # hit against its JD rather than trusting the keyword, so the ~20-30% that
        # merely mention the word don't get waved past the location filter.
        if cfg.get("remote_pass"):
            remote_kw = f"({kw}) AND remote"
            rpages = int(cfg.get("remote_max_pages", 2))
            found: list[Job] = []
            for loc in locations:
                found.extend(_search(pool, remote_kw, tpr, loc, rpages, delay, seen))
            budget = int(cfg.get("remote_verify_max", 40))
            for job in found:
                if budget <= 0:
                    break  # out of detail-fetch budget: leave remote=None (no regression)
                budget -= 1
                jd = full_description(job.raw, None, cfg) or ""
                if jd:
                    job.description, job.jd_full = jd, True  # verified AND enriched
                job.remote = detect_remote(job.title, job.location, jd)
            jobs.extend(found)
    finally:
        pool.close()
    return jobs


def _search(pool: _ProxyPool, kw: str, tpr: str, loc: dict, max_pages: int,
            delay: float, seen: set[str]) -> list[Job]:
    """One location's paginated search. `seen` dedups by URL across passes, so the
    remote pass never re-emits a job the main pass already returned."""
    where = str(loc.get("where", "") or "")
    geoid = loc.get("geoId")
    distance = loc.get("distance", 25)
    out: list[Job] = []
    start = 0
    for _ in range(max_pages):
        params: dict = {"keywords": kw, "f_TPR": tpr, "sortBy": "DD", "start": start}
        if where:
            params["location"] = where
            if distance:
                params["distance"] = distance
        if geoid:
            params["geoId"] = geoid
        html = _page_html(pool, params)
        if not html:
            break  # rate-limited/failed for every proxy → give up this location
        cards = re.findall(r"<li>(.*?)</li>", html, re.S)
        if not cards:
            break  # empty page → past the last result (early-stop, lossless)
        for card in cards:
            job = _parse_card(card)
            if job and job.url not in seen:
                seen.add(job.url)
                out.append(job)
        start += len(cards)  # advance by what we actually got (page size varies)
        if delay:
            time.sleep(delay + random.random())
    return out
