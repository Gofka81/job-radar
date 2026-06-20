"""Deterministic deduplication, applied at write time via the job_id.

One vacancy = one stored row. `role_key(company, title, city)` is the identity of
a logical vacancy: normalized company + normalized title + canonical city.
`schema.make_job_id` hashes it, so everything that resolves to the same
role-in-the-same-city collapses onto a single primary key:
  - Adzuna tracking-token variants of one ad (`?se=`, `?utm_*`) → same company+
    title+city → one row.
  - Agency reposts of a role under brand-new ad-ids → same key → one row.
  - "London" vs "London, UK" vs "Farringdon, London" → all clean to city
    "London" → one row.
But the SAME title in a DIFFERENT city (e.g. London vs Edinburgh) keeps a distinct
key → stays a separate vacancy, so a second-city opening is never silently lost.

Because dedup is in the id, there's no separate notification gate: a newly inserted
row IS a new vacancy, so the scan notifies on exactly the rows it inserts.

Normalizers are ported from career-ops `dedup-tracker.mjs` (normalizeCompany /
normalizeRole) so both repos collapse the same way. We use normalized-EXACT
matching, not career-ops's fuzzy roleMatch: prod data shows repost titles are
byte-identical ("Senior Analytics Engineer" ×21), while fuzzy would wrongly merge
genuinely distinct roles ("Analytics Engineer" vs "Senior Analytics Engineer").
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

_COMPANY_DROP = re.compile(r"[^a-z0-9 ]")
_ROLE_DROP = re.compile(r"[^a-z0-9 /]")
_SPACES = re.compile(r"\s+")


def canonical_url(url: str | None) -> str:
    """Strip query string + fragment + trailing slash. Used only as the job_id
    fallback when company/title are blank (can't build a role key) — so two
    blank-field listings aren't wrongly merged, and token-variants of such an ad
    still collapse."""
    if not url:
        return ""
    s = urlsplit(url.strip())
    path = s.path.rstrip("/")
    return urlunsplit((s.scheme, s.netloc, path, "", ""))


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


def role_key(company: str | None, title: str | None, city: str | None) -> str | None:
    """Identity of a logical vacancy: normalized company + role + canonical city.
    Returns None when company or title is blank — such rows have no safe role key
    (all blanks would collapse together), so make_job_id falls back to the URL."""
    c, r = normalize_company(company), normalize_role(title)
    if not c or not r:
        return None
    return f"{c}|{r}|{(city or '').lower().strip()}"
