"""Two layers of deduplication, both deterministic.

Layer 1 — URL canonicalisation (storage): Adzuna hands the same posting back
under different tracking tokens (`?se=`, `?v=`, `?utm_*`), so the same ad becomes
a new URL → a phantom duplicate row that also bloats `/api/pending` (career-ops
would re-evaluate the same ad several times). `canonical_url()` strips the query
string; `schema.make_job_id` hashes that canonical form, so all token-variants of
one ad collapse onto a single primary key. The stored `url` column keeps the
original tokens (clickable) — only the *id* is canonicalised, never the link.

Layer 2 — content fingerprint (notifications): staffing agencies repost the same
role under brand-new ad-ids (new numeric id, not just a new token), which layer 1
can't see. `fingerprint()` collapses those to one logical role so we notify once.
Storage stays URL-keyed (conservative — never merges two genuinely different
postings); the fingerprint only gates notifications and is computed on the fly.

Normalizers are ported from career-ops `dedup-tracker.mjs` (normalizeCompany /
normalizeRole) so both repos collapse the same way. We use normalized-EXACT
matching, not career-ops's fuzzy roleMatch: prod data shows repost titles are
byte-identical ("Senior Analytics Engineer" ×21), while fuzzy would wrongly merge
genuinely distinct roles ("Analytics Engineer" vs "Senior Analytics Engineer").
Location is deliberately excluded from the fingerprint — the same role is posted
as both "London" and "London, UK", which would otherwise split into two pings.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

_COMPANY_DROP = re.compile(r"[^a-z0-9 ]")
_ROLE_DROP = re.compile(r"[^a-z0-9 /]")
_SPACES = re.compile(r"\s+")


# --- layer 1: URL canonicalisation ---------------------------------------

def canonical_url(url: str | None) -> str:
    """Strip query string + fragment + trailing slash so tracking-token variants
    of the same posting collapse. Feeds make_job_id — the stored, clickable URL
    keeps its tokens (some redirect endpoints need them)."""
    if not url:
        return ""
    s = urlsplit(url.strip())
    path = s.path.rstrip("/")
    return urlunsplit((s.scheme, s.netloc, path, "", ""))


# --- layer 2: content fingerprint ----------------------------------------

def normalize_company(name: str | None) -> str:
    """lowercase, drop parens + punctuation, collapse spaces. Mirrors career-ops
    normalizeCompany."""
    s = (name or "").lower().replace("(", "").replace(")", "")
    s = _COMPANY_DROP.sub("", s)
    return _SPACES.sub(" ", s).strip()


def normalize_role(role: str | None) -> str:
    """lowercase, parens → space, keep '/' (e.g. "azure/power bi"), drop other
    punctuation, collapse spaces. Mirrors career-ops normalizeRole."""
    s = (role or "").lower().replace("(", " ").replace(")", " ")
    s = _ROLE_DROP.sub("", s)
    return _SPACES.sub(" ", s).strip()


def fingerprint(company: str | None, title: str | None) -> str | None:
    """Content key for one logical role: normalized company + role.

    Returns None when company or title is blank: such rows can't be fingerprinted
    safely (all blanks would collapse together), so callers should always notify
    them rather than suppress."""
    c, r = normalize_company(company), normalize_role(title)
    if not c or not r:
        return None
    return f"{c}|{r}"
