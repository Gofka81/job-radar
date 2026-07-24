"""Telegram rendering — the single place that owns how a job looks in Telegram.

Pure formatting: no I/O, no HTTP. `bot.py` builds messages from these and
`notify.py` sends them. Keeping it separate means the scan push and the
interactive browser share one card style, and there's one place to change it."""

from __future__ import annotations

import html

CURRENCY = {"GBP": "£", "USD": "$", "EUR": "€"}


def esc(s) -> str:
    return html.escape(str(s if s is not None else ""))


def dot(score) -> str:
    """Traffic-light for a fit score (matches the dashboard's badge bands)."""
    if score is None:
        return "⚪"
    return "🟢" if score >= 7 else "🟡" if score >= 5 else "🔴"


def salary(j: dict) -> str:
    """Salary range with the job's own currency symbol (£/$/€; £ if unknown)."""
    sym = CURRENCY.get(j.get("currency"), "£")
    k = lambda n: f"{sym}{round(n / 1000)}k"
    lo, hi = j.get("salary_min"), j.get("salary_max")
    if lo and hi:
        return k(lo) if lo == hi else f"{k(lo)}–{k(hi)}"
    if hi:
        return f"≤{k(hi)}"
    if lo:
        return f"{k(lo)}+"
    return ""


def location(j: dict) -> str:
    """Full canonical city set when present (dashboard/bot rows), else the raw
    first-seen location (fresh scan-result dicts)."""
    locs = j.get("locations")
    return ", ".join(locs) if locs else (j.get("location") or "N/A")


def job_card(j: dict, index: int | None = None) -> str:
    """A rich card: optional list number, score dot + badge, linked title, meta,
    and the one-line AI reason when scored. Shared by the push and the browser."""
    score = j.get("score")
    num = f"<b>{index}.</b> " if index is not None else ""
    badge = f"<b>{round(score)}/10</b> " if score is not None else ""
    title = esc(j.get("title"))
    meta = " · ".join(filter(None, [
        esc(j.get("company")), esc(location(j)), salary(j), esc(j.get("source")),
    ]))
    card = f'{num}{dot(score)} {badge}<a href="{esc(j.get("url"))}">{title}</a>\n   <i>{meta}</i>'
    if reason := j.get("eval_reason"):
        card += f"\n   ✨ {esc(reason)}"
    return card
