from __future__ import annotations

import hashlib
from datetime import date
from typing import Any

from pydantic import BaseModel, Field


def make_job_id(source: str, url: str) -> str:
    """Stable 16-char id from source + url. Same posting from the same source
    always hashes the same, which is what dedup keys on."""
    return hashlib.sha1(f"{source}:{url}".encode()).hexdigest()[:16]


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
