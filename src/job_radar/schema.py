from __future__ import annotations

import hashlib
from datetime import date
from typing import Any

from pydantic import BaseModel, Field

from .dedup import canonical_url


def make_job_id(source: str, url: str) -> str:
    """Stable 16-char id from source + canonical url. The url is canonicalised
    (query string stripped) so the same Adzuna ad arriving under a fresh tracking
    token (`?se=`, `?utm_*`) hashes to the same id and collapses onto one row,
    instead of becoming a phantom duplicate. The stored `url` keeps its tokens."""
    return hashlib.sha1(f"{source}:{canonical_url(url)}".encode()).hexdigest()[:16]


class Job(BaseModel):
    """Normalised job posting. Every connector maps its raw payload into this."""

    source: str
    company: str
    title: str
    url: str
    location: str = ""
    posted_at: date | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    currency: str | None = None
    remote: bool | None = None
    raw: dict[str, Any] = Field(default_factory=dict)

    @property
    def job_id(self) -> str:
        return make_job_id(self.source, self.url)
