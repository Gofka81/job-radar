from __future__ import annotations

import os
from pathlib import Path

import yaml

# repo root = three levels up from this file (src/job_radar/config.py)
ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "config.example.yml"


def config_path() -> Path:
    """Where config.yml lives. On the Pi this is a writable path on the data
    volume (set via JOB_RADAR_CONFIG) so the /api/config route can update it;
    locally it defaults to repo-root config.yml."""
    env = os.environ.get("JOB_RADAR_CONFIG")
    return Path(env) if env else ROOT / "config.yml"


def load_config(path: str | Path | None = None) -> dict:
    """Load config. If the chosen path doesn't exist yet (fresh Pi, before the
    first /api/config PUT), fall back to the baked-in example so scans still run
    with sane defaults instead of crashing."""
    p = Path(path) if path else config_path()
    if not p.exists():
        if EXAMPLE.exists():
            return yaml.safe_load(EXAMPLE.read_text()) or {}
        raise FileNotFoundError(f"{p} not found and no {EXAMPLE.name} fallback.")
    return yaml.safe_load(p.read_text()) or {}


def read_config_text(path: str | Path | None = None) -> str:
    """Raw YAML text for the /api/config editor — current config, or the example
    if none has been saved yet."""
    p = Path(path) if path else config_path()
    if p.exists():
        return p.read_text()
    return EXAMPLE.read_text() if EXAMPLE.exists() else ""


def save_config(text: str, path: str | Path | None = None) -> dict:
    """Validate YAML and write it atomically. Raises ValueError on bad content so
    the API can reject it without ever leaving a half-written config on disk."""
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError("config must be a YAML mapping")
    for key in ("title_filter", "location_filter", "sources"):
        if data.get(key) is not None and not isinstance(data[key], dict):
            raise ValueError(f"'{key}' must be a mapping")
    p = Path(path) if path else config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(text)
    tmp.replace(p)  # atomic swap — a concurrent scan never reads a partial file
    return data
