"""Interactive Telegram bot. Driven by webhook updates (handled in server.py).
Authorisation: only updates from TELEGRAM_CHAT_ID are acted on — everyone else
is dropped silently before any work happens.

Commands: /jobs (paginated active jobs), /funnel, /scan, /help.
"""

from __future__ import annotations

import os
from collections.abc import Callable

from . import notify
from .store import Store

PAGE_SIZE = 10


def _allowed(user_id) -> bool:
    allowed = os.environ.get("TELEGRAM_CHAT_ID")
    return allowed is not None and str(user_id) == str(allowed)


def handle_update(update: dict, db: str, scan_fn: Callable[[], None] | None = None) -> None:
    """Entry point for a Telegram webhook update."""
    if cq := update.get("callback_query"):
        _on_callback(cq, db)
    elif msg := update.get("message"):
        _on_message(msg, db, scan_fn)


# --- message commands -----------------------------------------------------

def _on_message(msg: dict, db: str, scan_fn) -> None:
    if not _allowed((msg.get("from") or {}).get("id")):
        return  # not you → ignore
    chat = (msg.get("chat") or {}).get("id")
    cmd = (msg.get("text") or "").strip().split()[0].lstrip("/").lower() if msg.get("text") else ""

    if cmd in ("jobs", "list"):
        jobs = _active_jobs(db)
        if not jobs:
            notify.send_message(chat, "No active jobs yet — try /scan.")
        else:
            text, markup = _render_page(jobs, 0)
            notify.send_message(chat, text, markup)
    elif cmd in ("funnel", "stats"):
        notify.send_message(chat, _funnel_text(db))
    elif cmd == "scan":
        if scan_fn:
            scan_fn()
        notify.send_message(chat, "🔄 Scan started — I'll ping you with new matches.")
    else:  # /start, /help, or anything else
        notify.send_message(chat, _help_text())


# --- inline-keyboard pagination -------------------------------------------

def _on_callback(cq: dict, db: str) -> None:
    notify.answer_callback(cq.get("id"))  # stop Telegram's loading spinner
    if not _allowed((cq.get("from") or {}).get("id")):
        return
    data = cq.get("data") or ""
    msg = cq.get("message") or {}
    chat = (msg.get("chat") or {}).get("id")
    if data.startswith("jobs:") and chat is not None:
        page = int(data.split(":", 1)[1])
        text, markup = _render_page(_active_jobs(db), page)
        notify.edit_message(chat, msg.get("message_id"), text, markup)


def _render_page(jobs: list[dict], page: int) -> tuple[str, dict | None]:
    pages = max(1, (len(jobs) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, pages - 1))
    chunk = jobs[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
    lines = [f"📋 <b>Active jobs</b> ({len(jobs)}) — page {page + 1}/{pages}", ""]
    lines += [notify.job_line(j) for j in chunk]
    row = []
    if page > 0:
        row.append({"text": "◀ Prev", "callback_data": f"jobs:{page - 1}"})
    if page < pages - 1:
        row.append({"text": "Next ▶", "callback_data": f"jobs:{page + 1}"})
    return "\n".join(lines), ({"inline_keyboard": [row]} if row else None)


# --- data + text ----------------------------------------------------------

def _active_jobs(db: str) -> list[dict]:
    s = Store(db)
    try:
        return [j for j in s.list_jobs(1000) if j["status"] == "new"]
    finally:
        s.close()


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
        "/jobs — active jobs (paginated)\n"
        "/funnel — counts (found → applied)\n"
        "/scan — run a scan now"
    )
