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
