from __future__ import annotations

from pathlib import Path

import yaml

# repo root = three levels up from this file (src/job_radar/config.py)
ROOT = Path(__file__).resolve().parents[2]


def load_config(path: str | Path | None = None) -> dict:
    p = Path(path) if path else ROOT / "config.yml"
    if not p.exists():
        example = ROOT / "config.example.yml"
        raise FileNotFoundError(
            f"{p} not found. Copy {example.name} to config.yml and edit it."
        )
    return yaml.safe_load(p.read_text()) or {}
