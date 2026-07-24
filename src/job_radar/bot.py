"""Interactive Telegram bot — webhook update router + command handlers.

Layering: `tgfmt` renders, `notify` sends, this module routes. Authorisation:
only updates from TELEGRAM_CHAT_ID are acted on; everyone else is dropped
silently before any work happens.

Two surfaces:
  • Commands — /jobs [search] /top /analyze /stop /funnel /scan /help. The
    command table below is the single source of truth; /help is generated from it.
  • Inline buttons — paginate a list, toggle 🔝 Top / 🆕 New, run ✨ Analyze, and
    open a job to act on it (🔖 Save / ✅ Applied / 🚫 Reject / ✨ Score one).

callback_data grammar (all well under Telegram's 64-byte limit; job_id is 16 hex):
  jobs:<mode>:<page>            paginate a list (mode = new | top)
  act:analyze                   run a triage batch
  open:<mode>:<page>:<jid>      open the per-job detail view
  set:<status>:<mode>:<page>:<jid>   set a job's status, then back to the list
  score:<mode>:<page>:<jid>     queue a single-job triage
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass

from . import notify, tgfmt
from .store import Store

PAGE_SIZE = 8


def _allowed(user_id) -> bool:
    allowed = os.environ.get("TELEGRAM_CHAT_ID")
    return allowed is not None and str(user_id) == str(allowed)


def handle_update(
    update: dict,
    db: str,
    scan_fn: Callable[[], None] | None = None,
    analyze_fn: Callable[[], None] | None = None,
    stop_fn: Callable[[], object] | None = None,
    score_one_fn: Callable[[str], None] | None = None,
) -> None:
    """Entry point for a Telegram webhook update."""
    if cq := update.get("callback_query"):
        _on_callback(cq, db, analyze_fn, score_one_fn)
    elif msg := update.get("message"):
        _on_message(msg, db, scan_fn, analyze_fn, stop_fn)


# --- message commands -----------------------------------------------------

@dataclass
class Ctx:
    chat: object
    arg: str
    db: str
    scan_fn: Callable[[], None] | None
    analyze_fn: Callable[[], None] | None
    stop_fn: Callable[[], object] | None


def _cmd_jobs(c: Ctx) -> None:
    if c.arg:  # text search (title + company + JD), score-sorted, one-shot (no paging)
        text, markup = _render_list(_jobs(c.db, "new", query=c.arg), "search", 0, query=c.arg)
    else:
        text, markup = _render_list(_jobs(c.db, "new"), "new", 0)
    notify.send_message(c.chat, text, markup)


def _cmd_top(c: Ctx) -> None:
    text, markup = _render_list(_jobs(c.db, "top"), "top", 0)
    notify.send_message(c.chat, text, markup)


def _cmd_analyze(c: Ctx) -> None:
    if c.analyze_fn:
        c.analyze_fn()
        notify.send_message(c.chat, "✨ <b>AI triage started</b> — scores appear in /jobs and "
                                    "/top shortly (capped by analysis.max_jobs).")
    else:
        notify.send_message(c.chat, "AI triage isn't configured on the server.")


def _cmd_stop(c: Ctx) -> None:
    if not c.stop_fn:
        notify.send_message(c.chat, "Stop isn't wired on the server.")
        return
    r = c.stop_fn() or {}
    if r.get("stopping") or r.get("dropped_queued"):
        notify.send_message(c.chat, "⏹ <b>Halting triage</b> — stopping after the current job; "
                                    "queued runs dropped.")
    else:
        notify.send_message(c.chat, "Nothing to stop — no triage is running.")


def _cmd_funnel(c: Ctx) -> None:
    notify.send_message(c.chat, _funnel_text(c.db))


def _cmd_scan(c: Ctx) -> None:
    if c.scan_fn:
        c.scan_fn()
        notify.send_message(c.chat, "🔄 Scan started — I'll ping you with new matches.")
    else:
        notify.send_message(c.chat, "Scan isn't wired on the server.")


# Command table — the single source of truth for routing AND /help.
_SPECS: list[tuple[tuple[str, ...], Callable[[Ctx], None], str]] = [
    (("jobs", "list"),           _cmd_jobs,    "📋 /jobs <i>[search]</i> — pending jobs, best score first"),
    (("top", "best"),            _cmd_top,     "🔝 /top — only AI-scored jobs"),
    (("analyze", "triage", "review"), _cmd_analyze, "✨ /analyze — run AI triage on pending"),
    (("stop", "halt", "cancel"), _cmd_stop,    "⏹ /stop — halt a running triage"),
    (("funnel", "stats"),        _cmd_funnel,  "📊 /funnel — counts (discovered → applied)"),
    (("scan",),                  _cmd_scan,    "🔄 /scan — run a scan now"),
]
_DISPATCH = {alias: fn for names, fn, _ in _SPECS for alias in names}


def _on_message(msg: dict, db: str, scan_fn, analyze_fn, stop_fn) -> None:
    if not _allowed((msg.get("from") or {}).get("id")):
        return  # not you → ignore
    chat = (msg.get("chat") or {}).get("id")
    parts = (msg.get("text") or "").strip().split(maxsplit=1)
    cmd = parts[0].lstrip("/").lower() if parts else ""
    arg = parts[1].strip() if len(parts) > 1 else ""
    handler = _DISPATCH.get(cmd)
    if handler:
        handler(Ctx(chat, arg, db, scan_fn, analyze_fn, stop_fn))
    else:  # /start, /help, or anything unknown
        notify.send_message(chat, _help_text())


# --- inline-keyboard callbacks --------------------------------------------

def _on_callback(cq: dict, db: str, analyze_fn, score_one_fn) -> None:
    if not _allowed((cq.get("from") or {}).get("id")):
        return  # not you → ignore (don't even answer — reveal nothing)
    cid = cq.get("id")
    data = cq.get("data") or ""
    msg = cq.get("message") or {}
    chat = (msg.get("chat") or {}).get("id")
    mid = msg.get("message_id")
    if chat is None:
        return

    if data.startswith("jobs:"):
        _, mode, page = data.split(":")
        notify.answer_callback(cid)
        text, markup = _render_list(_jobs(db, mode), mode, int(page))
        notify.edit_message(chat, mid, text, markup)
    elif data == "act:analyze":
        notify.answer_callback(cid, "✨ Triage started")
        if analyze_fn:
            analyze_fn()
    elif data.startswith("open:"):
        _, mode, page, jid = data.split(":")
        notify.answer_callback(cid)
        text, markup = _render_detail(db, jid, mode, int(page))
        notify.edit_message(chat, mid, text, markup)
    elif data.startswith("set:"):
        _, status, mode, page, jid = data.split(":")
        ok = _set_status(db, jid, status)
        notify.answer_callback(cid, f"{'✓' if ok else '✗'} {status}")
        text, markup = _render_list(_jobs(db, mode), mode, int(page))  # back to the list
        notify.edit_message(chat, mid, text, markup)
    elif data.startswith("score:"):
        _, mode, page, jid = data.split(":")
        if score_one_fn:
            score_one_fn(jid)
            notify.answer_callback(cid, "✨ Queued for scoring")
        else:
            notify.answer_callback(cid, "Triage isn't configured")
        text, markup = _render_detail(db, jid, mode, int(page))
        notify.edit_message(chat, mid, text, markup)
    else:
        notify.answer_callback(cid)


# --- rendering ------------------------------------------------------------

_HEADERS = {
    "new": "🆕 <b>New jobs</b>",
    "top": "🔝 <b>Top scored</b>",
    "search": "🔎 <b>Search</b>",
}


def _render_list(jobs: list[dict], mode: str, page: int, query: str | None = None):
    """A page of job cards + inline keyboard. Rows: [nav] [actions] [open-N buttons].
    `open` buttons (one per card, only on paginated modes) drill into the detail view."""
    paginated = mode in ("new", "top")
    pages = max(1, (len(jobs) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, pages - 1))
    chunk = jobs[page * PAGE_SIZE:(page + 1) * PAGE_SIZE] if paginated else jobs[:PAGE_SIZE]

    head = _HEADERS.get(mode, "📋 <b>Jobs</b>")
    if query:
        head += f" · “{tgfmt.esc(query)}”"
    head += f" ({len(jobs)})"
    if paginated and pages > 1:
        head += f" · page {page + 1}/{pages}"
    if not jobs:
        return head + "\n\nNothing here yet — try /scan or /analyze.", None

    lines = [head, ""] + [tgfmt.job_card(j, i + 1) for i, j in enumerate(chunk)]

    nav = []
    if paginated and page > 0:
        nav.append({"text": "◀ Prev", "callback_data": f"jobs:{mode}:{page - 1}"})
    if paginated and page < pages - 1:
        nav.append({"text": "Next ▶", "callback_data": f"jobs:{mode}:{page + 1}"})
    actions = [
        {"text": "✨ Analyze", "callback_data": "act:analyze"},
        {"text": "🆕 New" if mode == "top" else "🔝 Top",
         "callback_data": f"jobs:{'new' if mode == 'top' else 'top'}:0"},
    ]
    opens = []
    if paginated:
        btns = [{"text": str(i + 1), "callback_data": f"open:{mode}:{page}:{j['job_id']}"}
                for i, j in enumerate(chunk)]
        opens = [btns[k:k + 4] for k in range(0, len(btns), 4)]  # rows of 4
    keyboard = [r for r in (nav, actions, *opens) if r]
    return "\n".join(lines), ({"inline_keyboard": keyboard} if keyboard else None)


def _render_detail(db: str, jid: str, mode: str, page: int):
    """One job with per-job actions. `mode`/`page` ride along so ↩ Back and the
    post-action redirect return to the exact list page you came from."""
    s = Store(db)
    try:
        j = s.job(jid)
    finally:
        s.close()
    back = {"text": "↩ Back", "callback_data": f"jobs:{mode}:{page}"}
    if not j:
        return "Job not found — it may have expired.", {"inline_keyboard": [[back]]}
    text = "📄 <b>Details</b>\n\n" + tgfmt.job_card(j) + f"\n\n<i>status: {tgfmt.esc(j['status'])}</i>"
    keyboard = [
        [{"text": "🔗 Open", "url": j["url"]}],
        [{"text": "🔖 Save", "callback_data": f"set:saved:{mode}:{page}:{jid}"},
         {"text": "✅ Applied", "callback_data": f"set:applied:{mode}:{page}:{jid}"},
         {"text": "🚫 Reject", "callback_data": f"set:rejected:{mode}:{page}:{jid}"}],
        [{"text": "✨ Score", "callback_data": f"score:{mode}:{page}:{jid}"}, back],
    ]
    return text, {"inline_keyboard": keyboard}


# --- data + text ----------------------------------------------------------

def _jobs(db: str, mode: str, query: str | None = None) -> list[dict]:
    """Jobs for a view. 'new' = still-pending; 'top' = AI-scored only. Both are
    score-sorted (highest first, unscored last, then newest) to match the dashboard."""
    s = Store(db)
    try:
        rows = s.list_jobs(1000, q=query)
    finally:
        s.close()
    if mode == "top":
        rows = [j for j in rows if j.get("score") is not None]
    else:
        rows = [j for j in rows if j["status"] == "new"]
    rows.sort(key=lambda j: (j.get("score") is None, -(j.get("score") or 0)))
    return rows


def _set_status(db: str, jid: str, status: str) -> bool:
    s = Store(db)
    try:
        return s.set_status(jid, status)
    except Exception:
        return False
    finally:
        s.close()


def _funnel_text(db: str) -> str:
    s = Store(db)
    try:
        f = s.funnel()
        scored = s.count_scored()
    finally:
        s.close()
    rows = [
        ("Discovered", f.get("total", 0)),
        ("Scored", scored),
        ("New", f.get("new", 0)),
        ("Saved", f.get("saved", 0)),
        ("Applied", f.get("applied", 0)),
        ("Rejected", f.get("rejected", 0)),
    ]
    return "📊 <b>Funnel</b>\n" + "\n".join(f"{k}: <b>{v}</b>" for k, v in rows)


def _help_text() -> str:
    lines = ["🤖 <b>job-radar</b>", ""]
    lines += [help_line for _, _, help_line in _SPECS]
    lines += ["", "🟢 7-10 · 🟡 5-6 · 🔴 0-4 · ⚪ not scored"]
    return "\n".join(lines)
