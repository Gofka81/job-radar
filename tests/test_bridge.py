from __future__ import annotations

import httpx
import respx

from job_radar import bridge

BASE = "https://pi.example.com"
TOKEN = "secret"


def test_render_pipeline_contract():
    md = bridge.render_pipeline(
        [{"url": "https://x/1", "company": "Test", "title": "Data Engineer"}]
    )
    assert "## Pending" in md
    assert "- [ ] https://x/1 | Test | Data Engineer" in md


def test_read_results_parses_url_keyed_tsv(tmp_path):
    p = tmp_path / "results.tsv"
    p.write_text(
        "url\tscore\tstatus\treport_num\n"
        "https://x/1\t8.5\tapplied\t3\n"
        "https://x/2\t4.1/5\tevaluated\t\n"  # career-ops "/5" style accepted
        "\t\t\t\n",  # blank url row skipped
        encoding="utf-8",
    )
    results = bridge.read_results(p)
    assert results == [
        {"url": "https://x/1", "score": 8.5, "status": "applied", "report_num": 3},
        {"url": "https://x/2", "score": 4.1, "status": "evaluated"},
    ]


@respx.mock
def test_pull_writes_pipeline(tmp_path):
    respx.get(f"{BASE}/api/pending").mock(
        return_value=httpx.Response(
            200, json={"jobs": [{"url": "https://x/1", "company": "Test", "title": "DE"}]}
        )
    )
    out = tmp_path / "pipeline.md"
    assert bridge.pull(BASE, TOKEN, out) == 0
    assert "- [ ] https://x/1 | Test | DE" in out.read_text()


@respx.mock
def test_push_posts_verdicts(tmp_path):
    route = respx.post(f"{BASE}/api/results").mock(
        return_value=httpx.Response(200, json={"updated": 1, "received": 1})
    )
    p = tmp_path / "results.tsv"
    p.write_text("url\tscore\tstatus\nhttps://x/9\t9\tapplied\n", encoding="utf-8")
    assert bridge.push(BASE, TOKEN, p) == 0
    assert route.called
    sent = route.calls.last.request
    assert b"https://x/9" in sent.content
    assert sent.headers["authorization"] == f"Bearer {TOKEN}"
