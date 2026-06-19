from __future__ import annotations

from job_radar.dedup import (
    canonical_url,
    fingerprint,
    normalize_company,
    normalize_role,
)
from job_radar.schema import make_job_id


# --- layer 1: URL canonicalisation ---------------------------------------

def test_canonical_url_strips_tracking_params():
    base = "https://www.adzuna.co.uk/jobs/land/ad/5760606708"
    assert canonical_url(base + "?se=AAA&v=BBB&utm_source=x") == base
    assert canonical_url(base + "?se=ZZZ") == base


def test_canonical_url_strips_fragment_and_trailing_slash():
    assert canonical_url("https://x.io/job/1/#apply") == "https://x.io/job/1"


def test_canonical_url_blank():
    assert canonical_url(None) == ""
    assert canonical_url("") == ""


def test_job_id_collapses_token_variants():
    base = "https://www.adzuna.co.uk/jobs/land/ad/5760606708"
    # same ad, different tracking tokens → same job_id (canonicalised hash)
    assert make_job_id("adzuna", base + "?se=AAA&v=1") == make_job_id("adzuna", base + "?se=BBB&v=2")


def test_job_id_distinguishes_ads_and_sources():
    a = "https://www.adzuna.co.uk/jobs/land/ad/1?se=x"
    b = "https://www.adzuna.co.uk/jobs/land/ad/2?se=x"
    assert make_job_id("adzuna", a) != make_job_id("adzuna", b)
    assert make_job_id("adzuna", a) != make_job_id("reed", a)


# --- layer 2: normalizers + fingerprint ----------------------------------

def test_normalize_company_matches_career_ops_rules():
    assert normalize_company("Harnham - Data & Analytics Recruitment") == "harnham data analytics recruitment"
    assert normalize_company("Tenth Revolution Group") == "tenth revolution group"
    assert normalize_company("Acme (UK) Ltd.") == "acme uk ltd"


def test_normalize_role_keeps_slash_drops_other_punct():
    assert normalize_role("BI Data Engineer (Azure/Power BI)") == "bi data engineer azure/power bi"
    assert normalize_role("Senior Analytics Engineer") == "senior analytics engineer"


def test_fingerprint_collapses_identical_role_regardless_of_location():
    # Same role, different location text → same fingerprint (location excluded).
    a = fingerprint("Harnham", "Senior Analytics Engineer")
    b = fingerprint("Harnham", "Senior Analytics Engineer")
    assert a == b and a is not None


def test_fingerprint_distinguishes_seniority():
    # normalized-EXACT: seniority/contract variants stay distinct (not fuzzy-merged).
    assert fingerprint("Harnham", "Analytics Engineer") != fingerprint("Harnham", "Senior Analytics Engineer")
    assert fingerprint("Harnham", "Analytics Engineer") != fingerprint("Harnham", "Analytics Engineer (Contract)")


def test_fingerprint_none_when_company_or_title_blank():
    assert fingerprint("", "Data Engineer") is None
    assert fingerprint("Acme", "") is None
    assert fingerprint(None, None) is None
