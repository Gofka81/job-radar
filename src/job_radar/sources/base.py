from __future__ import annotations

import re

import httpx

USER_AGENT = "job-hunt/0.1 (+https://github.com/Gofka81/job-hunt)"
TIMEOUT = 15.0

_TAG_RE = re.compile(r"<[^>]+>")


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
