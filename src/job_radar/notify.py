"""Telegram transport — the raw send/edit/answer/setWebhook calls, plus the
scan-result push. Opt-in: a silent no-op unless TELEGRAM_BOT_TOKEN is set, and
never raises — a Telegram failure must not affect a scan. Rendering lives in
`tgfmt`; command routing lives in `bot`."""

from __future__ import annotations

import os

import httpx

from . import tgfmt

API = "https://api.telegram.org"
TIMEOUT = 15
MAX_LISTED = 10   # cards in a scan push; /jobs is the paginated browser for the rest


def _token() -> str | None:
    return os.environ.get("TELEGRAM_BOT_TOKEN")


def chat_id() -> str | None:
    return os.environ.get("TELEGRAM_CHAT_ID")


def _call(method: str, payload: dict) -> dict | None:
    token = _token()
    if not token:
        return None
    try:
        r = httpx.post(f"{API}/bot{token}/{method}", json=payload, timeout=TIMEOUT)
        return r.json() if "application/json" in r.headers.get("content-type", "") else None
    except Exception:
        return None


def send_message(to: str | int, text: str, reply_markup: dict | None = None) -> dict | None:
    payload = {"chat_id": to, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return _call("sendMessage", payload)


def edit_message(to: str | int, message_id: int, text: str, reply_markup: dict | None = None) -> dict | None:
    payload = {
        "chat_id": to, "message_id": message_id, "text": text,
        "parse_mode": "HTML", "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return _call("editMessageText", payload)


def answer_callback(callback_id: str, text: str | None = None) -> dict | None:
    payload: dict = {"callback_query_id": callback_id}
    if text:
        payload["text"] = text
    return _call("answerCallbackQuery", payload)


def set_webhook(url: str, secret: str) -> bool:
    r = _call("setWebhook", {
        "url": url, "secret_token": secret,
        "allowed_updates": ["message", "callback_query"],
    })
    return bool(r and r.get("ok"))


def notify_new_jobs(result: dict) -> None:
    """Push the new matches from a scan result (run_scan() output). `new_jobs`
    holds only the rows upsert newly inserted (dedup is at write time via the
    vacancy_key) — so every entry here is a genuinely new vacancy worth a ping."""
    new = result.get("new_jobs") or []
    to = chat_id()
    if not new or not to:
        return
    lines = [f"🆕 <b>{len(new)}</b> new job match(es):", ""]
    lines += [tgfmt.job_card(j) for j in new[:MAX_LISTED]]
    if len(new) > MAX_LISTED:
        lines.append(f"\n…and {len(new) - MAX_LISTED} more — send /jobs to browse all")
    send_message(to, "\n".join(lines))
