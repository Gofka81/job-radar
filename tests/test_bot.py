from __future__ import annotations

import pytest

from job_radar import bot, notify, tgfmt
from job_radar.schema import Job
from job_radar.store import Store

ME = "12345"


def _cb(data, mid=5):
    return {"callback_query": {"id": "c", "from": {"id": ME}, "data": data,
                               "message": {"chat": {"id": ME}, "message_id": mid}}}


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
    assert "New jobs" in text and "(12)" in text and "page 1/2" in text
    kb = markup["inline_keyboard"]
    assert [b["callback_data"] for b in kb[0]] == ["jobs:new:1"]  # Next only on page 1
    assert any(b["callback_data"] == "act:analyze" for b in kb[1])  # action row present


def test_pagination_callback_edits_to_page_2(db, sent):
    cq = {"callback_query": {"id": "c1", "from": {"id": ME}, "data": "jobs:new:1",
                             "message": {"chat": {"id": ME}, "message_id": 5}}}
    bot.handle_update(cq, db)
    assert sent["answer"] == ["c1"]
    mid, text, markup = sent["edit"][0]
    assert mid == 5 and "page 2/2" in text
    assert [b["callback_data"] for b in markup["inline_keyboard"][0]] == ["jobs:new:0"]  # Prev only


def test_top_shows_only_scored_with_reason(db, sent):
    from job_radar.store import Store
    s = Store(db)
    jid = s.list_jobs()[0]["job_id"]
    s.apply_analysis(jid, score=9, reason="great fit", engine="claude-cli:x")
    s.close()
    bot.handle_update(_msg("/top"), db)
    _, text, _ = sent["send"][0]
    assert "Top scored" in text and "(1)" in text  # only the scored one
    assert "9/10" in text and "great fit" in text   # score + AI reason shown


def test_jobs_search_filters(db, sent):
    bot.handle_update(_msg("/jobs Engineer 5"), db)  # matches only "Data Engineer 5"
    _, text, _ = sent["send"][0]
    assert "Search" in text and "(1)" in text


def test_analyze_command_triggers(db, sent):
    fired = []
    bot.handle_update(_msg("/analyze"), db, analyze_fn=lambda: fired.append(1))
    assert fired == [1] and "triage started" in sent["send"][0][1].lower()


def test_analyze_button_callback_triggers(db, sent):
    fired = []
    cq = {"callback_query": {"id": "c2", "from": {"id": ME}, "data": "act:analyze",
                             "message": {"chat": {"id": ME}, "message_id": 7}}}
    bot.handle_update(cq, db, analyze_fn=lambda: fired.append(1))
    assert fired == [1]


def test_stop_command_triggers(db, sent):
    fired = []
    bot.handle_update(_msg("/stop"), db,
                      stop_fn=lambda: fired.append(1) or {"stopping": True, "dropped_queued": 0})
    assert fired == [1] and "halting triage" in sent["send"][0][1].lower()


def test_stop_command_when_idle(db, sent):
    bot.handle_update(_msg("/stop"), db,
                      stop_fn=lambda: {"stopping": False, "dropped_queued": 0})
    assert "nothing to stop" in sent["send"][0][1].lower()


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


# --- per-job actions (redesign) -------------------------------------------

def test_list_has_per_job_open_buttons(db, sent):
    bot.handle_update(_msg("/jobs"), db)
    _, _, markup = sent["send"][0]
    opens = [b["callback_data"] for row in markup["inline_keyboard"] for b in row
             if b.get("callback_data", "").startswith("open:new:0:")]
    assert len(opens) == 8  # one per card on the page (PAGE_SIZE)


def test_open_shows_detail_with_actions(db, sent):
    jid = Store(db).list_jobs()[0]["job_id"]
    bot.handle_update(_cb(f"open:new:0:{jid}"), db)
    mid, text, markup = sent["edit"][0]
    assert mid == 5 and "Details" in text
    cbs = [b.get("callback_data") for row in markup["inline_keyboard"] for b in row]
    assert f"set:applied:new:0:{jid}" in cbs and f"score:new:0:{jid}" in cbs
    assert any(b.get("url") for row in markup["inline_keyboard"] for b in row)  # 🔗 Open link


def test_set_status_updates_db_and_returns_to_list(db, sent):
    jid = Store(db).list_jobs()[0]["job_id"]
    bot.handle_update(_cb(f"set:applied:new:0:{jid}"), db)
    s = Store(db); assert s.job(jid)["status"] == "applied"; s.close()
    _, text, _ = sent["edit"][0]
    assert "New jobs" in text and "(11)" in text  # actioned job left the pending list


def test_score_one_calls_back(db, sent):
    jid = Store(db).list_jobs()[0]["job_id"]
    fired = []
    bot.handle_update(_cb(f"score:new:0:{jid}"), db, score_one_fn=lambda j: fired.append(j))
    assert fired == [jid]


def test_funnel_shows_scored_stage(db, sent):
    bot.handle_update(_msg("/funnel"), db)
    assert "Scored" in sent["send"][0][1]


def test_salary_uses_job_currency():
    assert tgfmt.salary({"salary_min": 150000, "salary_max": 190000, "currency": "USD"}) == "$150k–$190k"
    assert tgfmt.salary({"salary_min": 65000, "salary_max": 80000, "currency": "GBP"}) == "£65k–£80k"
    assert tgfmt.salary({"salary_min": 100000, "currency": "EUR"}) == "€100k+"
