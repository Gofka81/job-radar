from __future__ import annotations

import re

import httpx

USER_AGENT = "job-hunt/0.1 (+https://github.com/Gofka81/job-hunt)"
TIMEOUT = 15.0

_TAG_RE = re.compile(r"<[^>]+>")

# Phrases that mean "you can do this job from anywhere", not just any use of the
# word "remote" — "remote sensing"/"remote monitoring"/"remote desktop" are job
# CONTENT, not work arrangement, and would otherwise wave through on-site roles.
_REMOTE_RE = re.compile(
    r"\b(fully[- ]remote|100%\s*remote|remote[- ]first|remote[- ]based|home[- ]?based"
    r"|work(ing)? from home|wfh|uk[- ]remote|remote \(uk"
    r"|remote (role|position|opportunity|working|vacancy))\b", re.I)
# Hybrid still requires you on site N days a week, so it must NOT bypass a city
# filter — a "hybrid, 2 days remote" role in Manchester is a Manchester job.
_HYBRID_RE = re.compile(r"\bhybrid\b", re.I)


def detect_remote(title: str, location: str, description: str = "") -> bool | None:
    """True if the posting reads as genuinely remote, False if explicitly hybrid,
    None if unknown. Connectors that get no structured work-type field (most of
    them) use this so `location_filter.allow_remote` has something to act on."""
    loc = (location or "").lower()
    if re.search(r"\bremote\b", loc) and not _HYBRID_RE.search(loc):
        return True  # the board put it in the location field — strongest signal
    # A bare "Remote" in the TITLE is a work-arrangement signal (titles are short
    # and deliberate) — except where it names the job's subject matter, as in
    # "Remote Sensing Engineer". This is LinkedIn's only signal: its guest card has
    # no workplace-type field and no JD at filter time.
    ttl = (title or "").lower()
    if re.search(r"\bremote\b(?!\s+(sensing|monitoring|desktop|access|support|control))", ttl):
        return False if _HYBRID_RE.search(ttl) else True
    hay = f"{title or ''}\n{description or ''}"
    if _REMOTE_RE.search(hay):
        return False if _HYBRID_RE.search(hay) else True
    if _HYBRID_RE.search(hay):
        return False
    return None


def client() -> httpx.Client:
    return httpx.Client(
        headers={"user-agent": USER_AGENT},
        timeout=TIMEOUT,
        follow_redirects=True,
    )


def strip_tags(text: str) -> str:
    """Some sources (e.g. Adzuna) wrap matched terms in <strong>. Drop markup."""
    return _TAG_RE.sub("", text or "").strip()


def cfg_locations(cfg: dict, legacy_where_key: str, default_distance) -> list[tuple[str, object]]:
    """Per-location targeting: return [(where, distance), ...] to query separately.

    Prefer a `locations` list in config (each {where, distance}); an empty `where`
    means a nationwide/remote pass. Falls back to the legacy single
    where/distance (or one nationwide pull) so old config keeps working.

    Querying priority cities separately gives each its own result budget, so
    high-volume London can't crowd Edinburgh/Glasgow out of a date-sorted pull."""
    locs = cfg.get("locations")
    if locs:
        return [(str(l.get("where", "") or ""), l.get("distance", default_distance)) for l in locs]
    return [(str(cfg.get(legacy_where_key, "") or ""), cfg.get("distance", default_distance))]
