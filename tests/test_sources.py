from __future__ import annotations

import httpx
import respx

from job_radar.sources import adzuna, reed


@respx.mock
def test_adzuna_queries_each_location_with_exclude(monkeypatch):
    monkeypatch.setenv("ADZUNA_APP_ID", "id")
    monkeypatch.setenv("ADZUNA_APP_KEY", "key")
    route = respx.get(url__regex=r"https://api\.adzuna\.com/.*").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    cfg = {
        "queries": ["data engineer"],
        "locations": [{"where": "Edinburgh", "distance": 40}, {"where": ""}],
        "max_pages": 1,
        "what_exclude": "senior lead",
        "category": "it-jobs",
    }
    with httpx.Client() as c:
        adzuna.fetch(cfg, c)

    # one call per (query × location); empty results break the page loop after page 1
    assert route.call_count == 2
    params = [call.request.url.params for call in route.calls]
    wheres = [p.get("where") for p in params]
    assert "Edinburgh" in wheres          # targeted city pull carries where+distance
    assert None in wheres                 # nationwide pull omits where entirely
    for p in params:                      # server-side levers on every call
        assert p["what"] == "data engineer"
        assert p["what_exclude"] == "senior lead"
        assert p["category"] == "it-jobs"
    edi = next(p for p in params if p.get("where") == "Edinburgh")
    assert edi["distance"] == "40"


@respx.mock
def test_adzuna_what_exclude_accepts_list(monkeypatch):
    monkeypatch.setenv("ADZUNA_APP_ID", "id")
    monkeypatch.setenv("ADZUNA_APP_KEY", "key")
    route = respx.get(url__regex=r"https://api\.adzuna\.com/.*").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    cfg = {"queries": ["x"], "locations": [{"where": ""}], "max_pages": 1,
           "what_exclude": ["senior", "lead", "manager"]}
    with httpx.Client() as c:
        adzuna.fetch(cfg, c)
    assert route.calls[0].request.url.params["what_exclude"] == "senior lead manager"


@respx.mock
def test_reed_queries_each_location(monkeypatch):
    monkeypatch.setenv("REED_API_KEY", "k")
    route = respx.get(url__regex=r"https://www\.reed\.co\.uk/.*").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    cfg = {
        "queries": ["data engineer", "analytics engineer"],
        "locations": [{"where": "Glasgow", "distance": 40}, {"where": ""}],
    }
    with httpx.Client() as c:
        reed.fetch(cfg, c)

    assert route.call_count == 4  # 2 queries × 2 locations
    params = [call.request.url.params for call in route.calls]
    assert any(p.get("locationName") == "Glasgow" and p.get("distanceFromLocation") == "40" for p in params)
    assert any(p.get("locationName") is None for p in params)  # nationwide pull


@respx.mock
def test_adzuna_legacy_where_still_works(monkeypatch):
    """Old config (single where/distance, no `locations`) keeps working."""
    monkeypatch.setenv("ADZUNA_APP_ID", "id")
    monkeypatch.setenv("ADZUNA_APP_KEY", "key")
    route = respx.get(url__regex=r"https://api\.adzuna\.com/.*").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    cfg = {"queries": ["x"], "where": "London", "distance": 25, "max_pages": 1}
    with httpx.Client() as c:
        adzuna.fetch(cfg, c)
    assert route.calls[0].request.url.params.get("where") == "London"
