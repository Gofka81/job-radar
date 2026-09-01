from __future__ import annotations

import re
from collections.abc import Callable

from .locations import clean_location


def build_title_filter(cfg: dict) -> Callable[[str], bool]:
    """Pass if >=1 positive matches (or no positives configured) AND 0 negatives match."""
    positive = [k.lower() for k in (cfg or {}).get("positive", [])]
    negative = [k.lower() for k in (cfg or {}).get("negative", [])]

    def ok(title: str) -> bool:
        t = (title or "").lower()
        has_positive = (not positive) or any(k in t for k in positive)
        has_negative = any(k in t for k in negative)
        return has_positive and not has_negative

    return ok


def build_location_filter(cfg: dict | None) -> Callable[..., bool]:
    """No config => everything passes. block wins over allow. Empty location passes.

    Terms match on WORD BOUNDARIES, not raw substring — so "UK" matches the token
    "UK" in "London, UK" but never inside "Milwaukee", and "Remote" in the allow
    list can't wave through "USA - Remote" once "USA" is on the block list.

    `allow_remote` (default true) lets a job the connector flagged `remote=True`
    through even when its city isn't on the allow list. Boards label a remote role
    with the EMPLOYER's city, not "Remote", so a city whitelist silently drops the
    whole remote bucket. The block list still applies, so US/India-remote stays out.
    Set `allow_remote: false` to go back to city-only matching.

    That bypass is ANCHORED, because an unanchored one admits remote roles from any
    country not explicitly blocked, quietly defeating the whitelist. A role posted in
    Munich as "remote" nearly always means remote *within Germany* (local entity,
    right to work, timezone), so it must not reach a UK inbox. By default the anchor
    is `clean_location()` — the offline GB reference resolves UK towns ("Bristol",
    "Milton Keynes") and returns "Unknown" for Munich/Berlin/Austin — which is why a
    plain term list is not enough: sources emit bare UK city names with no country
    suffix. Set `remote_allow` to a term list to anchor on that instead."""
    if not cfg:
        return lambda _location, _remote=None: True

    def compile_terms(terms):
        return [re.compile(r"\b" + re.escape(str(k).lower()) + r"\b") for k in terms]

    allow = compile_terms(cfg.get("allow", []))
    block = compile_terms(cfg.get("block", []))
    allow_remote = bool(cfg.get("allow_remote", True))
    remote_allow = compile_terms(cfg.get("remote_allow", []))

    def ok(location: str, remote: bool | None = None) -> bool:
        if not location:
            return True
        loc = location.lower()
        if block and any(r.search(loc) for r in block):
            return False  # blocked region wins even for remote roles
        if not allow:
            return True
        if any(r.search(loc) for r in allow):
            return True
        if not (allow_remote and remote is True):
            return False
        if remote_allow:  # explicit term list wins when configured
            return any(r.search(loc) for r in remote_allow)
        # Default anchor: is this a place the GB reference recognises at all?
        return clean_location(location) != "Unknown"

    return ok
