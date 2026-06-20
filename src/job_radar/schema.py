from __future__ import annotations

import hashlib
from datetime import date
from typing import Any

from pydantic import BaseModel, Field

from .dedup import canonical_url, role_key
from .locations import clean_location


def make_job_id(source: str, company: str, title: str, city: str, url: str) -> str:
    """Stable 16-char id = sha1(source : role_key). One vacancy (a role at a
    company in a city) hashes to one id, so tracking-token variants AND agency
    reposts under new ad-ids collapse onto a single row, while the same title in a
    different city stays distinct. Falls back to the canonical URL when company or
    title is blank (no safe role key), so blank-field listings aren't merged."""
    key = role_key(company, title, city) or canonical_url(url)
    return hashlib.sha1(f"{source}:{key}".encode()).hexdigest()[:16]


class Job(BaseModel):
    """Normalised job posting. Every connector maps its raw payload into this."""

    source: str
    company: str
    title: str
    url: str
    location: str = ""
    description: str = ""  # plain-text JD (for tech-stack search); not part of job_id
    posted_at: date | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    currency: str | None = None
    remote: bool | None = None
    raw: dict[str, Any] = Field(default_factory=dict)

    @property
    def job_id(self) -> str:
        # city = canonical UK city; same value stored as location_cleaned, so the
        # id and the column agree.
        return make_job_id(self.source, self.company, self.title,
                           clean_location(self.location), self.url)
