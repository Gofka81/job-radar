from __future__ import annotations

import pytest

from job_radar import config


def test_save_and_load_roundtrip(tmp_path, monkeypatch):
    p = tmp_path / "config.yml"
    monkeypatch.setenv("JOB_RADAR_CONFIG", str(p))
    text = "title_filter:\n  positive:\n    - Data Engineer\nsources:\n  reed:\n    enabled: true\n"
    config.save_config(text)
    assert p.exists()
    assert config.load_config()["sources"]["reed"]["enabled"] is True
    assert config.read_config_text().lstrip().startswith("title_filter")


def test_save_is_atomic_and_validates_yaml(tmp_path, monkeypatch):
    p = tmp_path / "config.yml"
    monkeypatch.setenv("JOB_RADAR_CONFIG", str(p))
    config.save_config("sources:\n  reed:\n    enabled: true\n")
    with pytest.raises(Exception):  # invalid YAML — must not overwrite the good file
        config.save_config("foo: [1, 2")
    assert config.load_config()["sources"]["reed"]["enabled"] is True


def test_save_rejects_non_mapping(tmp_path, monkeypatch):
    monkeypatch.setenv("JOB_RADAR_CONFIG", str(tmp_path / "c.yml"))
    with pytest.raises(ValueError):
        config.save_config("- just\n- a\n- list\n")


def test_load_falls_back_to_example_when_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("JOB_RADAR_CONFIG", str(tmp_path / "nope.yml"))
    cfg = config.load_config()  # no file yet -> baked example defaults
    assert isinstance(cfg, dict) and "sources" in cfg
