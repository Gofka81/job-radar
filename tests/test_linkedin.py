from __future__ import annotations

from datetime import date

from job_radar.sources import linkedin

CARD1 = (
    '<a class="base-card__full-link" '
    'href="https://uk.linkedin.com/jobs/view/data-engineer-at-monzo-4439246158?trk=x"></a>'
    '<h3 class="base-search-card__title"> Data Engineer </h3>'
    '<h4 class="base-search-card__subtitle">'
    '<a class="hidden-nested-link" href="/company/monzo">Monzo</a></h4>'
    '<span class="job-search-card__location"> Edinburgh, Scotland, United Kingdom </span>'
    '<time class="job-search-card__listdate" datetime="2026-07-20">2 days ago</time>'
)
CARD2 = (
    '<a class="base-card__full-link" '
    'href="https://uk.linkedin.com/jobs/view/data-engineer-databricks-at-m-g-4440190278?r=1"></a>'
    '<h3 class="base-search-card__title"> Data Engineer (Databricks) </h3>'
    '<h4 class="base-search-card__subtitle"><a href="#">M&amp;G</a></h4>'
    '<span class="job-search-card__location"> Stirling, Scotland, United Kingdom </span>'
)
PAGE = f"<li>{CARD1}</li><li>{CARD2}</li>"


def test_parse_card_extracts_fields():
    job = linkedin._parse_card(CARD1)
    assert job is not None
    assert job.title == "Data Engineer"
    assert job.company == "Monzo"
    assert job.location == "Edinburgh, Scotland, United Kingdom"
    assert job.url == "https://uk.linkedin.com/jobs/view/data-engineer-at-monzo-4439246158"
    assert job.posted_at == date(2026, 7, 20)
    assert job.description == ""  # guest card has no JD


def test_parse_card_unescapes_company_entities():
    assert linkedin._parse_card(CARD2).company == "M&G"


def test_parse_card_skips_cards_without_job_link():
    assert linkedin._parse_card("<div>sponsored promo, no job link</div>") is None


def test_fetch_orjoins_queries_and_parses(monkeypatch):
    captured: list[dict] = []

    def fake_page(pool, params):
        captured.append(dict(params))
        return PAGE if params["start"] == 0 else ""  # one page, then empty → stop

    monkeypatch.setattr(linkedin, "_page_html", fake_page)
    cfg = {
        "queries": ["data engineer", "analytics engineer"],
        "locations": [{"where": "United Kingdom"}],
        "max_pages": 3, "request_delay": 0,
    }
    jobs = linkedin.fetch(cfg, None)

    p0 = captured[0]
    assert p0["keywords"] == '"data engineer" OR "analytics engineer"'  # OR-joined
    assert p0["f_TPR"] == "r604800"    # 168h default → seconds
    assert p0["sortBy"] == "DD"        # freshest first
    assert p0["location"] == "United Kingdom"
    assert {j.company for j in jobs} == {"Monzo", "M&G"}
    assert len(jobs) == 2              # early-stopped on the empty second page


def test_fetch_single_query_has_no_or(monkeypatch):
    captured: list[dict] = []
    monkeypatch.setattr(linkedin, "_page_html",
                        lambda pool, params: (captured.append(dict(params)), "")[1])
    linkedin.fetch({"queries": ["data engineer"], "locations": [{"where": ""}],
                    "request_delay": 0}, None)
    assert captured[0]["keywords"] == '"data engineer"'  # no OR for one term


def test_fetch_dedups_repeated_urls_across_pages(monkeypatch):
    monkeypatch.setattr(linkedin, "_page_html",
                        lambda pool, params: PAGE)  # same page every time
    jobs = linkedin.fetch({"queries": ["x"], "locations": [{"where": ""}],
                           "max_pages": 3, "request_delay": 0}, None)
    assert len(jobs) == 2  # 3 identical pages, but URLs dedup within the fetch


def test_proxypool_normalizes_and_defaults_to_direct():
    assert linkedin._ProxyPool([]).urls == [None]                 # empty → direct
    assert linkedin._ProxyPool(["user:pass@1.2.3.4:6754"]).urls == [
        "http://user:pass@1.2.3.4:6754"]                          # bare host:port → http://
    assert linkedin._ProxyPool(["http://a:b@h:1"]).urls == ["http://a:b@h:1"]  # kept as-is
