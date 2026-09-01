from __future__ import annotations

import json

import httpx
import respx

from job_radar.sources import adzuna, indeed, linkedin, oracle, reed, workday


@respx.mock
def test_reed_full_description_fetches_detail(monkeypatch):
    monkeypatch.setenv("REED_API_KEY", "k")
    respx.get("https://www.reed.co.uk/api/1.0/jobs/123").mock(
        return_value=httpx.Response(200, json={"jobDescription": "<p>Full PySpark JD</p>"}))
    with httpx.Client() as c:
        assert reed.full_description({"jobId": "123"}, c) == "Full PySpark JD"  # tags stripped


@respx.mock
def test_reed_full_description_failure_returns_none(monkeypatch):
    monkeypatch.setenv("REED_API_KEY", "k")
    respx.get("https://www.reed.co.uk/api/1.0/jobs/9").mock(return_value=httpx.Response(500))
    with httpx.Client() as c:
        assert reed.full_description({"jobId": "9"}, c) is None  # error → keep the snippet


def test_reed_full_description_no_id_returns_none():
    assert reed.full_description({}, None) is None  # no jobId → None, no HTTP needed


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


# --- Workday (per-tenant CXS API) -----------------------------------------

_WD_HOST = "natwest.wd3.myworkdayjobs.com"
_WD_CXS = f"https://{_WD_HOST}/wday/cxs/natwest/NatWestGroup"


@respx.mock
def test_workday_emits_job_per_location_with_jd():
    listing = respx.post(f"{_WD_CXS}/jobs").mock(return_value=httpx.Response(200, json={
        "total": 1,
        "jobPostings": [{"title": "Data Engineer", "externalPath": "/job/Data-Engineer_R1",
                         "locationsText": "2 Locations"}],
    }))
    respx.get(f"{_WD_CXS}/job/Data-Engineer_R1").mock(return_value=httpx.Response(200, json={
        "jobPostingInfo": {
            "title": "Data Engineer",
            "jobDescription": "<p>Build pipelines with <b>Spark</b> and Airflow.</p>",
            "startDate": "2026-06-01", "location": "London", "additionalLocations": ["Edinburgh"],
        }
    }))
    cfg = {"companies": [{"host": _WD_HOST, "site": "NatWestGroup", "name": "NatWest"}],
           "queries": ["data engineer"], "max_pages": 1}
    with httpx.Client() as c:
        jobs = workday.fetch(cfg, c)

    # one posting in two locations → two Jobs (the store later merges them to one row)
    assert {j.location for j in jobs} == {"London", "Edinburgh"}
    j = jobs[0]
    assert j.source == "workday" and j.company == "NatWest" and j.title == "Data Engineer"
    assert j.url == f"https://{_WD_HOST}/en-US/NatWestGroup/job/Data-Engineer_R1"
    assert "Spark" in j.description and "<b>" not in j.description  # JD captured, tags stripped
    assert str(j.posted_at) == "2026-06-01"
    # server-side search narrows the listing
    assert json.loads(listing.calls[0].request.content)["searchText"] == "data engineer"


@respx.mock
def test_workday_fetches_detail_once_across_overlapping_queries():
    # Same posting matches both queries — its JD detail must be fetched ONCE (N+1 fix).
    listing = respx.post(f"{_WD_CXS}/jobs").mock(return_value=httpx.Response(200, json={
        "total": 1,
        "jobPostings": [{"title": "Data Engineer", "externalPath": "/job/DE_R1",
                         "locationsText": "London"}],
    }))
    detail = respx.get(f"{_WD_CXS}/job/DE_R1").mock(return_value=httpx.Response(200, json={
        "jobPostingInfo": {"title": "Data Engineer", "jobDescription": "Spark.",
                           "location": "London"}
    }))
    cfg = {"companies": [{"host": _WD_HOST, "site": "NatWestGroup", "name": "NatWest"}],
           "queries": ["data engineer", "data platform"], "max_pages": 1}
    with httpx.Client() as c:
        jobs = workday.fetch(cfg, c)
    assert listing.call_count == 2   # one list call per query (searchText differs)
    assert detail.call_count == 1    # but the shared posting's JD is fetched only once
    assert len(jobs) == 1


@respx.mock
def test_workday_skips_bad_tenant_without_failing():
    respx.post(url__regex=r".*/wday/cxs/.*/jobs").mock(return_value=httpx.Response(404))
    cfg = {"companies": [{"host": _WD_HOST, "site": "NatWestGroup"},
                         {"name": "broken"}]}  # second entry has no host → skipped
    with httpx.Client() as c:
        assert workday.fetch(cfg, c) == []


# --- Oracle ORC (Fusion CandidateExperience REST) -------------------------

_ORC_HOST = "jpmc.fa.oraclecloud.com"
_ORC_URL = f"https://{_ORC_HOST}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"


@respx.mock
def test_oracle_emits_job_per_location_with_snippet():
    route = respx.get(url__regex=rf"{_ORC_URL}.*").mock(return_value=httpx.Response(200, json={
        "items": [{"TotalJobsCount": 1, "requisitionList": [{
            "Id": "210735003", "Title": "Data Engineer",
            "PrimaryLocation": "LONDON, LONDON, United Kingdom", "PostedDate": "2026-06-15",
            "ShortDescriptionStr": "<p>Build <b>Spark</b> pipelines.</p>",
            "secondaryLocations": [{"Name": "Glasgow, United Kingdom"}],
        }]}]
    }))
    cfg = {"companies": [{"host": _ORC_HOST, "site": "CX_1001", "name": "JPMorgan"}],
           "queries": ["data engineer"], "max_pages": 1}
    with httpx.Client() as c:
        jobs = oracle.fetch(cfg, c)

    assert {j.location for j in jobs} == {"LONDON, LONDON, United Kingdom", "Glasgow, United Kingdom"}
    j = jobs[0]
    assert j.source == "oracle" and j.company == "JPMorgan" and j.title == "Data Engineer"
    assert j.url == f"https://{_ORC_HOST}/hcmUI/CandidateExperience/en/sites/CX_1001/job/210735003"
    assert j.description == "Build Spark pipelines." and str(j.posted_at) == "2026-06-15"
    finder = route.calls[0].request.url.params.get("finder")
    assert "siteNumber=CX_1001" in finder and 'keyword="data engineer"' in finder
    assert "sortBy=RELEVANCY" in finder  # loose keyword → relevance, not date (see oracle.py)


@respx.mock
def test_oracle_skips_bad_tenant_without_failing():
    respx.get(url__regex=r".*recruitingCEJobRequisitions.*").mock(return_value=httpx.Response(404))
    cfg = {"companies": [{"host": _ORC_HOST, "site": "CX_1001"}, {"name": "broken"}]}
    with httpx.Client() as c:
        assert oracle.fetch(cfg, c) == []


# --- Indeed (mobile GraphQL API) ------------------------------------------

def _indeed_result(key="abc", title="Data Engineer", company="Acme",
                   city="Edinburgh", unit="YEAR", smin=60000, smax=80000):
    return {"job": {
        "key": key, "title": title, "datePublished": 1750000000000,
        "employer": {"name": company},
        "description": {"html": "<p>Build <b>Spark</b> pipelines.</p>"},
        "location": {"countryName": "United Kingdom", "countryCode": "GB",
                     "admin1Code": "SCT", "city": city,
                     "formatted": {"short": city, "long": f"{city} EH1 1BB"}},
        "compensation": {"baseSalary": {"unitOfWork": unit,
                                        "range": {"min": smin, "max": smax}},
                         "estimated": None, "currencyCode": "GBP"},
        "attributes": [{"label": "Full-time"}],
    }}


@respx.mock
def test_indeed_parses_and_paginates_per_location():
    # page 1 returns one job + a cursor; page 2 returns empty → loop stops early
    page1 = {"data": {"jobSearch": {"pageInfo": {"nextCursor": "C1"},
                                    "results": [_indeed_result()]}}}
    empty = {"data": {"jobSearch": {"pageInfo": {"nextCursor": None}, "results": []}}}
    responses = [httpx.Response(200, json=page1), httpx.Response(200, json=empty)]
    route = respx.post("https://apis.indeed.com/graphql").mock(side_effect=responses)
    cfg = {"queries": ["data engineer"], "locations": [{"where": "Edinburgh", "distance": 40}],
           "max_pages": 3}
    with httpx.Client() as c:
        jobs = indeed.fetch(cfg, c)

    assert route.call_count == 2  # stopped after the empty page, not all 3
    assert len(jobs) == 1
    j = jobs[0]
    assert j.source == "indeed" and j.company == "Acme" and j.title == "Data Engineer"
    assert j.url == "https://uk.indeed.com/viewjob?jk=abc"
    assert j.location == "Edinburgh EH1 1BB"
    assert j.description == "Build Spark pipelines."  # HTML tags stripped
    assert j.jd_full is True                          # full JD came with the search
    assert j.salary_min == 60000 and j.salary_max == 80000 and j.currency == "GBP"
    assert str(j.posted_at) == "2025-06-15"
    # request carried the mobile api key + GB country header
    req = route.calls[0].request
    assert req.headers.get("indeed-api-key") and req.headers.get("indeed-co") == "GB"


@respx.mock
def test_indeed_ignores_non_annual_salary_and_blank_key():
    hourly = _indeed_result(key="h", unit="HOUR", smin=25, smax=40)
    blank = _indeed_result(key="", title="No key")  # dropped (no job key → no url)
    body = {"data": {"jobSearch": {"pageInfo": {"nextCursor": None},
                                   "results": [hourly, blank]}}}
    respx.post("https://apis.indeed.com/graphql").mock(return_value=httpx.Response(200, json=body))
    cfg = {"queries": ["x"], "locations": [{"where": ""}], "max_pages": 1}
    with httpx.Client() as c:
        jobs = indeed.fetch(cfg, c)
    assert len(jobs) == 1                    # blank-key result skipped
    assert jobs[0].salary_min is None and jobs[0].salary_max is None  # hourly not trusted


@respx.mock
def test_indeed_or_joins_queries_per_location():
    body = {"data": {"jobSearch": {"pageInfo": {"nextCursor": None}, "results": []}}}
    route = respx.post("https://apis.indeed.com/graphql").mock(
        return_value=httpx.Response(200, json=body))
    cfg = {"queries": ["data engineer", "databricks"],
           "locations": [{"where": "Glasgow", "distance": 40}, {"where": ""}], "max_pages": 1}
    with httpx.Client() as c:
        indeed.fetch(cfg, c)
    assert route.call_count == 2  # queries OR-joined → 1 search per location, not per query
    queries = [json.loads(call.request.content)["query"] for call in route.calls]
    # both terms OR-joined into ONE `what` (quotes escaped into the GraphQL string)
    assert all(r'\"data engineer\" OR \"databricks\"' in q for q in queries)
    assert any('where: "Glasgow"' in q for q in queries)
    assert any("location:" not in q for q in queries)  # nationwide pass omits location


def test_linkedin_full_description_parses_guest_detail(monkeypatch):
    """The guest card carries no JD; the detail endpoint is what fills it in."""
    from job_radar.sources import linkedin
    html = ('<div class="show-more-less-html__markup relative">We need '
            '<strong>PySpark</strong> &amp; Delta Lake.</div>')
    monkeypatch.setattr(linkedin._ProxyPool, "get",
                        lambda self, url, params: httpx.Response(200, text=html))
    raw = {"card_url": "https://www.linkedin.com/jobs/view/data-engineer-at-acme-4454566336"}
    # tags become a space, not "" — block markup must not weld words together
    assert linkedin.full_description(raw, None, {}) == "We need PySpark & Delta Lake."


def test_linkedin_full_description_bad_url_or_failure(monkeypatch):
    from job_radar.sources import linkedin
    assert linkedin.full_description({"card_url": "https://x/nope"}, None, {}) is None
    monkeypatch.setattr(linkedin._ProxyPool, "get", lambda self, url, params: None)
    raw = {"card_url": "https://www.linkedin.com/jobs/view/x-4454566336"}
    assert linkedin.full_description(raw, None, {}) is None  # all proxies dead → keep stub


def test_linkedin_cards_are_flagged_for_enrichment():
    from job_radar.sources import linkedin
    card = ('<a href="https://www.linkedin.com/jobs/view/de-at-acme-123?trk=x">'
            '<h3 class="base-search-card__title">Data Engineer</h3>')
    job = linkedin._parse_card(card)
    assert job.description == "" and job.jd_full is False


def test_lever_description_joins_all_sections():
    """Lever splits a posting across descriptionPlain + lists + additionalPlain;
    taking only the first dropped the requirements/tech-stack section."""
    from job_radar.sources import lever
    posting = {
        "descriptionPlain": "We build data platforms.",
        "lists": [{"text": "Who You Are:", "content": "<li>PySpark</li><li>Delta Lake</li>"}],
        "additionalPlain": "We are an equal opportunity employer.",
    }
    d = lever._description(posting)
    assert "We build data platforms." in d
    assert "Who You Are:" in d and "PySpark" in d and "Delta Lake" in d  # was dropped
    assert "equal opportunity" in d


def test_lever_description_tolerates_missing_sections():
    from job_radar.sources import lever
    assert lever._description({"descriptionPlain": "Only an intro."}) == "Only an intro."
    assert lever._description({}) == ""


def test_workable_description_joins_split_fields():
    from job_radar.sources import workable
    d = workable._description({"description": "<p>The role.</p>",
                               "requirements": "<p>5y Spark.</p>", "benefits": "<p>Pension.</p>"})
    assert "The role." in d and "5y Spark." in d and "Pension." in d


def _li_page(*jobs) -> str:
    """Minimal guest-search HTML: one <li> card per (id, title, location)."""
    return "".join(
        f'<li><a href="https://www.linkedin.com/jobs/view/x-{i}?trk=z">'
        f'<h3 class="base-search-card__title">{t}</h3>'
        f'<span class="job-search-card__location">{loc}</span></a></li>'
        for i, t, loc in jobs)


def test_linkedin_remote_pass_rescues_verified_remote_jobs(monkeypatch):
    """The remote keyword pass finds jobs a city whitelist would drop; each hit is
    CONFIRMED against its JD so keyword-only mentions don't slip through."""
    pages = {}

    def fake_page(pool, params):
        first = params["start"] == 0
        if "AND remote" in params["keywords"]:
            return _li_page(("200", "Data Engineer", "Manchester"),
                            ("201", "Data Engineer", "Leeds")) if first else ""
        return _li_page(("100", "Data Engineer", "London")) if first else ""

    jds = {"200": "This is a fully remote role.", "201": "You will build remote sensing kit."}
    monkeypatch.setattr(linkedin, "_page_html", fake_page)
    monkeypatch.setattr(linkedin, "full_description",
                        lambda raw, http, cfg=None: jds[raw["card_url"].rsplit("-", 1)[1]])

    jobs = linkedin.fetch({"queries": ["data engineer"], "locations": [{"where": "UK"}],
                           "max_pages": 1, "request_delay": 0, "remote_pass": True,
                           "remote_max_pages": 1}, None)
    by_loc = {j.location: j for j in jobs}
    assert by_loc["Manchester"].remote is True          # verified remote → rescued
    assert by_loc["Manchester"].description and by_loc["Manchester"].jd_full  # enriched free
    assert by_loc["Leeds"].remote is not True           # "remote sensing" is job CONTENT
    assert by_loc["London"].remote is not True          # main pass untouched


def test_linkedin_remote_pass_is_off_by_default(monkeypatch):
    monkeypatch.setattr(linkedin, "_page_html",
                        lambda pool, params: _li_page(("1", "Data Engineer", "London"))
                        if params["start"] == 0 else "")
    calls = []
    monkeypatch.setattr(linkedin, "full_description",
                        lambda raw, http, cfg=None: calls.append(1) or "remote")
    jobs = linkedin.fetch({"queries": ["data engineer"], "locations": [{"where": "UK"}],
                           "max_pages": 1, "request_delay": 0}, None)
    assert len(jobs) == 1 and not calls          # no extra search, no detail fetches


def test_linkedin_remote_verify_budget_caps_detail_fetches(monkeypatch):
    monkeypatch.setattr(linkedin, "_page_html", lambda pool, params: (
        _li_page(*[(str(i), "Data Engineer", "Leeds") for i in range(5)])
        if params["start"] == 0 and "AND remote" in params["keywords"] else ""))
    calls = []
    monkeypatch.setattr(linkedin, "full_description",
                        lambda raw, http, cfg=None: (calls.append(1), "fully remote role")[1])
    jobs = linkedin.fetch({"queries": ["de"], "locations": [{"where": "UK"}], "max_pages": 1,
                           "request_delay": 0, "remote_pass": True, "remote_verify_max": 2}, None)
    assert len(calls) == 2                      # budget honoured
    assert sum(1 for j in jobs if j.remote is True) == 2
    assert sum(1 for j in jobs if j.remote is None) == 3   # unverified → no regression
