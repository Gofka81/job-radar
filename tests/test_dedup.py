from __future__ import annotations

from job_radar.dedup import (
    canonical_url,
    normalize_company,
    normalize_role,
    role_key,
)
from job_radar.schema import make_job_id

LDN = "https://www.adzuna.co.uk/jobs/land/ad/5760606708"


# --- canonical_url (job_id fallback for blank-field rows) -----------------

def test_canonical_url_strips_tracking_params():
    assert canonical_url(LDN + "?se=AAA&v=BBB&utm_source=x") == LDN
    assert canonical_url(LDN + "?se=ZZZ") == LDN


def test_canonical_url_strips_fragment_and_trailing_slash():
    assert canonical_url("https://x.io/job/1/#apply") == "https://x.io/job/1"


def test_canonical_url_blank():
    assert canonical_url(None) == ""
    assert canonical_url("") == ""


# --- normalizers (ported from career-ops) --------------------------------

def test_normalize_company_matches_career_ops_rules():
    assert normalize_company("Harnham - Data & Analytics Recruitment") == "harnham data analytics recruitment"
    assert normalize_company("Acme (UK) Ltd.") == "acme uk ltd"


def test_normalize_role_keeps_slash_drops_other_punct():
    assert normalize_role("BI Data Engineer (Azure/Power BI)") == "bi data engineer azure/power bi"
    assert normalize_role("Senior Analytics Engineer") == "senior analytics engineer"


# --- role_key (the vacancy identity) -------------------------------------

def test_role_key_combines_company_role_city():
    assert role_key("Harnham", "Senior Analytics Engineer", "London") == "harnham|senior analytics engineer|london"


def test_role_key_none_when_company_or_title_blank():
    assert role_key("", "Data Engineer", "London") is None
    assert role_key("Acme", "", "London") is None


# --- make_job_id (write-time dedup behaviour) ----------------------------

def test_job_id_collapses_reposts_of_same_role_and_city():
    # token variant, brand-new ad-id, and "London" vs "London, UK" → same id
    base = make_job_id("adzuna", "Harnham", "Senior Analytics Engineer", "London", LDN + "?se=A")
    variant = make_job_id("adzuna", "Harnham", "Senior Analytics Engineer", "London", LDN + "?se=B")
    new_adid = make_job_id("adzuna", "Harnham", "Senior Analytics Engineer", "London", "https://x/57013787")
    assert base == variant == new_adid


def test_job_id_keeps_different_city_distinct():
    ldn = make_job_id("adzuna", "BigCorp", "Data Engineer", "London", "https://x/1")
    edi = make_job_id("adzuna", "BigCorp", "Data Engineer", "Edinburgh", "https://x/2")
    assert ldn != edi  # same title, different city → not lost


def test_job_id_distinguishes_role_and_source():
    assert make_job_id("adzuna", "Co", "Data Engineer", "London", "u") != make_job_id("adzuna", "Co", "Analytics Engineer", "London", "u")
    assert make_job_id("adzuna", "Co", "Data Engineer", "London", "u") != make_job_id("reed", "Co", "Data Engineer", "London", "u")


def test_job_id_falls_back_to_url_when_fields_blank():
    # no role key (blank company) → identify by canonical URL, so two blank-company
    # ads at different URLs stay distinct, but token-variants of one still collapse
    a = make_job_id("adzuna", "", "Data Engineer", "London", "https://x/1?se=A")
    b = make_job_id("adzuna", "", "Data Engineer", "London", "https://x/1?se=B")
    c = make_job_id("adzuna", "", "Data Engineer", "London", "https://x/2")
    assert a == b != c
