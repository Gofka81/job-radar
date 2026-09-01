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


def test_remote_job_bypasses_city_whitelist():
    """Boards label a remote role with the EMPLOYER's city, so a city-only whitelist
    silently dropped the whole remote bucket."""
    ok = build_location_filter({"allow": ["Edinburgh", "London"], "block": ["USA"]})
    assert ok("Manchester", None) is False        # on-site elsewhere → still dropped
    assert ok("Manchester", True) is True         # remote → allowed through
    assert ok("London", None) is True             # whitelisted city → unchanged
    assert ok("Austin, USA", True) is False       # block still wins over remote


def test_allow_remote_can_be_switched_off():
    ok = build_location_filter({"allow": ["London"], "allow_remote": False})
    assert ok("Manchester", True) is False        # opt back into city-only matching


def test_remote_bypass_is_anchored_to_the_uk():
    """An unanchored remote bypass admits any country not explicitly blocked, which
    defeats the whitelist. The default anchor is the offline GB reference, so bare
    UK city names (which most sources emit) still pass."""
    ok = build_location_filter({"allow": ["Edinburgh", "London"], "block": ["USA"]})
    assert ok("Bristol", True) is True             # UK city, no country suffix
    assert ok("Milton Keynes", True) is True
    assert ok("England, United Kingdom", True) is True
    assert ok("Munich", True) is False             # remote-in-Germany, not a UK job
    assert ok("Berlin", True) is False
    assert ok("Bristol", None) is False            # non-remote unchanged: still dropped


def test_remote_allow_overrides_the_default_anchor():
    ok = build_location_filter({"allow": ["London"], "remote_allow": ["Germany", "Munich"]})
    assert ok("Munich", True) is True              # explicitly opted into
    assert ok("Bristol", True) is False            # term list replaces the GB anchor
