from __future__ import annotations

from job_radar.locations import clean_location


def test_london_variants_all_normalise():
    for raw in (
        "London, UK", "Farringdon, Central London", "Sutton, London",
        "London, England, United Kingdom", "The City, Central London",
    ):
        assert clean_location(raw) == "London"


def test_priority_city_beats_region():
    assert clean_location("Glasgow, Scotland") == "Glasgow"
    assert clean_location("Edinburgh / Hybrid") == "Edinburgh"


def test_priority_when_multiple_cities():
    # Edinburgh/Glasgow/London win over other cities in the same string.
    assert clean_location("Cardiff, London or Remote (UK)") == "London"


def test_remote_region_uk_fallbacks():
    assert clean_location("Remote, EMEA/LATAM") == "Remote"
    assert clean_location("Scotland") == "Scotland"
    assert clean_location("West Midlands, UK") == "UK"


def test_empty_is_unknown():
    assert clean_location("") == "Unknown"
    assert clean_location(None) == "Unknown"
