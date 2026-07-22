"""Interactive Telegram bot. Driven by webhook updates (handled in server.py).
Authorisation: only updates from TELEGRAM_CHAT_ID are acted on — everyone else
is dropped silently before any work happens.

Commands:
  /jobs [search]  active jobs, score-sorted (optional text search incl. JD)
  /top            only AI-scored jobs, best first
  /analyze        run AI triage on pending jobs (claude-cli)
  /stop           halt a running triage batch
  /funnel         counts (found → applied)
  /scan           run a scan now
  /help
Inline buttons: prev/next, ✨ Analyze, and a 🔝 Top / 🆕 New toggle.
"""

from __future__ import annotations

import os
from collections.abc import Callable

from . import notify
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
) -> None:
    """Entry point for a Telegram webhook update."""
    if cq := update.get("callback_query"):
        _on_callback(cq, db, analyze_fn)
    elif msg := update.get("message"):
        _on_message(msg, db, scan_fn, analyze_fn, stop_fn)


# --- message commands -----------------------------------------------------

def _on_message(msg: dict, db: str, scan_fn, analyze_fn, stop_fn=None) -> None:
    if not _allowed((msg.get("from") or {}).get("id")):
        return  # not you → ignore
    chat = (msg.get("chat") or {}).get("id")
    parts = (msg.get("text") or "").strip().split(maxsplit=1)
    cmd = parts[0].lstrip("/").lower() if parts else ""
    arg = parts[1].strip() if len(parts) > 1 else ""

    if cmd in ("jobs", "list"):
        if arg:  # text search (title + company + JD), score-sorted
            jobs = _jobs(db, "new", query=arg)
            _send(chat, jobs, "search", 0, query=arg)
        else:
            _send(chat, _jobs(db, "new"), "new", 0)
    elif cmd in ("top", "best"):
        _send(chat, _jobs(db, "top"), "top", 0)
    elif cmd in ("analyze", "triage", "review"):
        if analyze_fn:
            analyze_fn()
            notify.send_message(chat, "✨ <b>AI triage started</b> — scores will appear in "
                                      "/jobs and /top shortly (bounded by analysis.max_jobs).")
        else:
            notify.send_message(chat, "AI triage isn't configured on the server.")
    elif cmd in ("stop", "halt", "cancel"):
        if stop_fn:
            r = stop_fn() or {}
            if r.get("stopping") or r.get("dropped_queued"):
                notify.send_message(chat, "⏹ <b>Halting triage</b> — stopping after the "
                                          "current job; queued runs dropped.")
            else:
                notify.send_message(chat, "Nothing to stop — no triage is running.")
        else:
            notify.send_message(chat, "Stop isn't wired on the server.")
    elif cmd in ("funnel", "stats"):
        notify.send_message(chat, _funnel_text(db))
    elif cmd == "scan":
        if scan_fn:
            scan_fn()
        notify.send_message(chat, "🔄 Scan started — I'll ping you with new matches.")
    else:  # /start, /help, or anything else
        notify.send_message(chat, _help_text())


# --- inline-keyboard (pagination + actions) -------------------------------

def _on_callback(cq: dict, db: str, analyze_fn) -> None:
    notify.answer_callback(cq.get("id"))  # stop Telegram's loading spinner
    if not _allowed((cq.get("from") or {}).get("id")):
        return
    data = cq.get("data") or ""
    msg = cq.get("message") or {}
    chat = (msg.get("chat") or {}).get("id")
    if chat is None:
        return
    if data == "act:analyze":
        if analyze_fn:
            analyze_fn()
        notify.send_message(chat, "✨ <b>AI triage started</b> — re-open /jobs or /top shortly.")
    elif data.startswith("jobs:"):
        _, mode, page = data.split(":")
        text, markup = _render_page(_jobs(db, "top" if mode == "top" else "new"), mode, int(page))
        notify.edit_message(chat, msg.get("message_id"), text, markup)


def _send(chat, jobs: list[dict], mode: str, page: int, query: str | None = None) -> None:
    text, markup = _render_page(jobs, mode, page, query)
    notify.send_message(chat, text, markup)


_HEADERS = {
    "new": "🆕 <b>New jobs</b>",
    "top": "🔝 <b>Top scored</b>",
    "search": "🔎 <b>Search</b>",
}


def _render_page(jobs: list[dict], mode: str, page: int, query: str | None = None):
    paginated = mode in ("new", "top")  # search is one-shot (query can't ride callback_data)
    pages = max(1, (len(jobs) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, pages - 1))
    chunk = jobs[page * PAGE_SIZE:(page + 1) * PAGE_SIZE] if paginated else jobs[:PAGE_SIZE]

    head = _HEADERS.get(mode, "📋 <b>Jobs</b>")
    if query:
        head += f" · “{notify.esc(query)}”"
    head += f" ({len(jobs)})"
    if paginated and pages > 1:
        head += f" · page {page + 1}/{pages}"
    if not jobs:
        return head + "\n\nNothing here yet — try /scan or /analyze.", None

    lines = [head, ""] + [_job_card(j) for j in chunk]

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
    keyboard = [r for r in (nav, actions) if r]
    return "\n".join(lines), ({"inline_keyboard": keyboard} if keyboard else None)


# --- rendering ------------------------------------------------------------

def _dot(score) -> str:
    if score is None:
        return "⚪"
    return "🟢" if score >= 7 else "🟡" if score >= 5 else "🔴"


def _salary(j: dict) -> str:
    lo, hi = j.get("salary_min"), j.get("salary_max")
    k = lambda n: f"£{round(n / 1000)}k"
    if lo and hi:
        return k(lo) if lo == hi else f"{k(lo)}–{k(hi)}"
    if hi:
        return f"≤{k(hi)}"
    if lo:
        return f"{k(lo)}+"
    return ""


def _job_card(j: dict) -> str:
    """A rich multi-line card: score dot + badge, linked title, meta, AI reason."""
    score = j.get("score")
    badge = f"<b>{round(score)}/10</b> " if score is not None else ""
    title = notify.esc(j.get("title"))
    locs = j.get("locations")
    loc = ", ".join(locs) if locs else (j.get("location") or "N/A")
    meta = " · ".join(filter(None, [
        notify.esc(j.get("company")), notify.esc(loc), _salary(j), notify.esc(j.get("source")),
    ]))
    card = f'{_dot(score)} {badge}<a href="{notify.esc(j.get("url"))}">{title}</a>\n   <i>{meta}</i>'
    if reason := j.get("eval_reason"):
        card += f"\n   ✨ {notify.esc(reason)}"
    return card


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
    # list_jobs is newest-first; stable-sort scored-desc to the top, unscored after.
    rows.sort(key=lambda j: (j.get("score") is None, -(j.get("score") or 0)))
    return rows


def _funnel_text(db: str) -> str:
    s = Store(db)
    try:
        f = s.funnel()
    finally:
        s.close()
    order = ["total", "new", "evaluated", "applied", "rejected"]
    rows = [f"{k}: <b>{f[k]}</b>" for k in order if k in f]
    rows += [f"{k}: <b>{v}</b>" for k, v in f.items() if k not in order]
    return "📊 <b>Funnel</b>\n" + "\n".join(rows)


def _help_text() -> str:
    return (
        "🤖 <b>job-radar</b>\n\n"
        "📋 /jobs <i>[search]</i> — pending jobs, best score first\n"
        "🔝 /top — only AI-scored jobs\n"
        "✨ /analyze — run AI triage on pending\n"
        "⏹ /stop — halt a running triage\n"
        "📊 /funnel — counts (found → applied)\n"
        "🔄 /scan — run a scan now\n\n"
        "🟢 7-10 · 🟡 5-6 · 🔴 0-4 · ⚪ not scored"
    )
