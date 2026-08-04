from __future__ import annotations

import re
from collections.abc import Callable


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


def build_location_filter(cfg: dict | None) -> Callable[[str], bool]:
    """No config => everything passes. block wins over allow. Empty location passes.

    Terms match on WORD BOUNDARIES, not raw substring — so "UK" matches the token
    "UK" in "London, UK" but never inside "Milwaukee", and "Remote" in the allow
    list can't wave through "USA - Remote" once "USA" is on the block list."""
    if not cfg:
        return lambda _location: True

    def compile_terms(terms):
        return [re.compile(r"\b" + re.escape(str(k).lower()) + r"\b") for k in terms]

    allow = compile_terms(cfg.get("allow", []))
    block = compile_terms(cfg.get("block", []))

    def ok(location: str) -> bool:
        if not location:
            return True
        loc = location.lower()
        if block and any(r.search(loc) for r in block):
            return False
        if not allow:
            return True
        return any(r.search(loc) for r in allow)

    return ok
