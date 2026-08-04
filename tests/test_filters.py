from __future__ import annotations

from job_radar.filters import build_location_filter, build_title_filter
from job_radar.schema import Job, make_vacancy_key


def test_title_positive_and_negative():
    ok = build_title_filter({"positive": ["data engineer", "spark"], "negative": ["junior"]})
    assert ok("Senior Data Engineer")
    assert ok("Spark Platform Engineer")
    assert not ok("Junior Data Engineer")  # negative wins
    assert not ok("Frontend Developer")  # no positive


def test_title_no_positives_passes_all_but_negatives():
    ok = build_title_filter({"negative": ["manager"]})
    assert ok("Anything")
    assert not ok("Engineering Manager")


def test_location_allow_block():
    ok = build_location_filter({"allow": ["edinburgh", "remote"], "block": ["london"]})
    assert ok("Edinburgh, Scotland")
    assert ok("Remote (UK)")
    assert ok("")  # empty passes
    assert not ok("London")  # block wins
    assert not ok("Manchester")  # not in allow


def test_location_no_config_passes_all():
    ok = build_location_filter(None)
    assert ok("Anywhere")


def test_location_word_boundary_no_substring_false_positives():
    ok = build_location_filter({"allow": ["uk", "us"]})
    assert ok("London, UK")          # "UK" is a whole token
    assert ok("Austin, TX, US")      # "US" is a whole token
    assert not ok("Milwaukee, WI")   # "uk" is INSIDE milwaukee → not a match
    assert not ok("Houston, TX")     # "us" is INSIDE houston → not a match


def test_location_block_beats_allow_for_us_remote():
    # the real leak: allow lets remote through, but a US-remote must be blocked
    ok = build_location_filter({
        "allow": ["edinburgh", "glasgow", "scotland", "london", "remote"],
        "block": ["usa", "united states"],
    })
    assert ok("Edinburgh, Scotland, United Kingdom")
    assert ok("London, England, United Kingdom")
    assert ok("Remote")
    assert not ok("USA - Remote")                     # block wins over "remote"
    assert not ok("Manchester, England, United Kingdom")   # other-UK dropped (no allow term)
    assert not ok("Belfast, Northern Ireland, United Kingdom")


def test_vacancy_key_is_stable_and_source_city_agnostic():
    a = make_vacancy_key("Acme", "Data Engineer", "https://x/1")
    assert a == make_vacancy_key("Acme", "Data Engineer", "https://x/1")
    # source, URL and city are NOT in the key, so a different source + URL + city
    # still hashes the same — the same role at the same company is one vacancy.
    job = Job(source="adzuna", company="Acme", title="Data Engineer", url="https://x/9", location="London, UK")
    assert job.vacancy_key == a
