from __future__ import annotations

import pytest

from job_radar import bot, notify
from job_radar.schema import Job
from job_radar.store import Store

ME = "12345"


@pytest.fixture
def db(tmp_path):
    p = str(tmp_path / "b.duckdb")
    s = Store(p)
    for i in range(12):  # 12 jobs → 2 pages at PAGE_SIZE 10
        s.upsert(Job(source="reed", company=f"Co{i}", title=f"Data Engineer {i}", url=f"https://x/{i}"))
    s.close()
    return p


@pytest.fixture
def sent(monkeypatch):
    calls = {"send": [], "edit": [], "answer": []}
    monkeypatch.setattr(notify, "send_message", lambda to, text, markup=None: calls["send"].append((to, text, markup)))
    monkeypatch.setattr(notify, "edit_message", lambda to, mid, text, markup=None: calls["edit"].append((mid, text, markup)))
    monkeypatch.setattr(notify, "answer_callback", lambda cid, text=None: calls["answer"].append(cid))
    monkeypatch.setenv("TELEGRAM_CHAT_ID", ME)
    return calls


def _msg(text, uid=ME):
    return {"message": {"from": {"id": uid}, "chat": {"id": uid}, "text": text}}


def test_unauthorized_is_dropped(db, sent):
    bot.handle_update(_msg("/jobs", uid="999"), db)
    assert sent["send"] == []  # not the allowlisted user → ignored, no work


def test_jobs_first_page(db, sent):
    bot.handle_update(_msg("/jobs"), db)
    assert len(sent["send"]) == 1
    _, text, markup = sent["send"][0]
    assert "Active jobs" in text and "(12)" in text and "page 1/2" in text
    btns = markup["inline_keyboard"][0]
    assert [b["callback_data"] for b in btns] == ["jobs:1"]  # Next only on page 1


def test_pagination_callback_edits_to_page_2(db, sent):
    cq = {"callback_query": {"id": "c1", "from": {"id": ME}, "data": "jobs:1",
                             "message": {"chat": {"id": ME}, "message_id": 5}}}
    bot.handle_update(cq, db)
    assert sent["answer"] == ["c1"]
    mid, text, markup = sent["edit"][0]
    assert mid == 5 and "page 2/2" in text
    assert [b["callback_data"] for b in markup["inline_keyboard"][0]] == ["jobs:0"]  # Prev only


def test_funnel(db, sent):
    bot.handle_update(_msg("/funnel"), db)
    assert "Funnel" in sent["send"][0][1]


def test_scan_triggers_callback(db, sent):
    fired = []
    bot.handle_update(_msg("/scan"), db, scan_fn=lambda: fired.append(1))
    assert fired == [1]
    assert "Scan started" in sent["send"][0][1]


def test_unknown_command_shows_help(db, sent):
    bot.handle_update(_msg("/wat"), db)
    assert "job-radar" in sent["send"][0][1]
