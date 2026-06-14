"""Source connectors. Each module exposes `ID` and `fetch(cfg, http) -> list[Job]`.

To add a source: drop a module here and add it to REGISTRY below. Nothing else changes.
"""

from __future__ import annotations

from . import adzuna, ashby, greenhouse, lever, reed, workable

REGISTRY = {m.ID: m for m in (adzuna, reed, greenhouse, lever, ashby, workable)}
