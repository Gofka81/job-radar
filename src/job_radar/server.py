"""Pi-side HTTP API + dashboard. Exposed remotely via a Cloudflare Tunnel
(cloudflared), so every data endpoint requires a bearer token.

Contract with the PC (career-ops bridge):
  GET  /api/pending  -> {"jobs": [...]}    the shortlist to evaluate
  POST /api/results  <- {"results": [...]} verdicts; Pi applies them to DuckDB

Run:  uvicorn job_radar.server:app   (or `job-serve`)
The Pi is the only writer of the DB; the PC only reads pending + posts verdicts.
"""

from __future__ import annotations

import logging
import os
import threading

from fastapi import Body, Depends, FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel, Field

from . import bot, notify, setup_logging
from .dashboard import DASHBOARD_HTML
from .config import ROOT, load_config, read_config_text, save_config
from .scan import run_scan
from .store import Store

logger = logging.getLogger("job_radar.server")
DEFAULT_DB = str(ROOT / "data" / "jobs.duckdb")
TOKEN_ENV = "JOB_RADAR_API_TOKEN"

# Single-flight scan state, shared by the API trigger and the scheduler so only
# one scan ever runs at a time (one DB writer). Both go through _guarded_scan.
_scan_lock = threading.Lock()
_scan_status: dict = {"running": False, "last": None}

# Telegram webhook secret, set at startup if the bot is configured.
_WEBHOOK: dict = {"secret": None}


def _guarded_scan(db: str) -> None:
    """Run one scan unless one is already in progress (then no-op). Used by the
    API trigger, the scheduler, and the /scan Telegram command. Pushes a Telegram
    notification with the new matches when done."""
    if not _scan_lock.acquire(blocking=False):
        return
    _scan_status["running"] = True
    try:
        result = run_scan(load_config(), db)
        _scan_status["last"] = result
        try:
            notify.notify_new_jobs(result)
        except Exception:
            pass  # a Telegram hiccup must not affect the scan
    except Exception as exc:  # never let a scan crash the server
        _scan_status["last"] = {"error": str(exc)}
    finally:
        _scan_status["running"] = False
        _scan_lock.release()


class Verdict(BaseModel):
    # Key by url (preferred) or job_id; the Pi resolves url -> job_id.
    url: str | None = None
    job_id: str | None = None
    score: float | None = None
    status: str = "evaluated"
    report_num: int | None = None


class ResultsPayload(BaseModel):
    results: list[Verdict] = Field(default_factory=list)


def require_token(authorization: str | None = Header(default=None)) -> None:
    """Bearer-token gate. Fails closed: if no token is configured on the
    server the endpoint refuses rather than serving open to the internet."""
    expected = os.environ.get(TOKEN_ENV)
    if not expected:
        raise HTTPException(503, f"{TOKEN_ENV} not configured on server")
    if authorization != f"Bearer {expected}":
        raise HTTPException(401, "invalid or missing bearer token")


def create_app(db_path: str | None = None) -> FastAPI:
    db = db_path or os.environ.get("JOB_RADAR_DB") or DEFAULT_DB
    app = FastAPI(title="job-hunt", version="0.2.0")

    # One short-lived connection per request keeps DuckDB happy across the
    # threadpool FastAPI runs sync handlers in. Traffic is tiny (a few req/day).
    def get_store():
        store = Store(db)
        try:
            yield store
        finally:
            store.close()

    @app.get("/", response_class=HTMLResponse)
    def dashboard() -> str:
        """The phone-friendly dashboard shell. Loads open (no token needed for the
        HTML itself); the page then prompts for the API token and calls the
        bearer-gated /api/* endpoints with it."""
        return DASHBOARD_HTML

    @app.get("/healthz")
    def healthz() -> dict:
        return {"ok": True}

    @app.get("/api/pending")
    def pending(_: None = Depends(require_token), store: Store = Depends(get_store)) -> dict:
        return {"jobs": store.pending_jobs()}

    @app.post("/api/results")
    def results(
        payload: ResultsPayload,
        _: None = Depends(require_token),
        store: Store = Depends(get_store),
    ) -> dict:
        updated = store.mark_results([v.model_dump() for v in payload.results])
        return {"updated": updated, "received": len(payload.results)}

    @app.get("/api/funnel")
    def funnel(_: None = Depends(require_token), store: Store = Depends(get_store)) -> dict:
        return store.funnel()

    @app.get("/api/jobs")
    def jobs(
        limit: int = 500,
        _: None = Depends(require_token),
        store: Store = Depends(get_store),
    ) -> dict:
        """All jobs with timestamps + status, newest-discovered first."""
        return {"jobs": store.list_jobs(limit)}

    @app.get("/api/config", response_class=PlainTextResponse)
    def get_config(_: None = Depends(require_token)) -> str:
        """Current config.yml (or the example if none saved yet) — for the editor."""
        return read_config_text()

    @app.post("/api/config")
    def post_config(
        body: str = Body(..., media_type="text/plain"),
        _: None = Depends(require_token),
    ) -> dict:
        """Validate + save config.yml. The next scan picks it up — no redeploy."""
        try:
            data = save_config(body)
        except Exception as exc:  # bad YAML / wrong shape
            raise HTTPException(400, f"invalid config: {exc}")
        return {"saved": True, "sources": sorted((data.get("sources") or {}).keys())}

    @app.post("/api/scan", status_code=202)
    def scan_now(_: None = Depends(require_token)) -> dict:
        """Trigger a scan on demand (the dashboard 'Scan now' button). Returns
        immediately; the scan runs in the background. 409 if one's already going."""
        if _scan_lock.locked():
            raise HTTPException(409, "a scan is already running")
        threading.Thread(target=_guarded_scan, args=(db,), daemon=True).start()
        return {"started": True}

    @app.get("/api/scan")
    def scan_status(_: None = Depends(require_token)) -> dict:
        """Last scan's result + whether one is running now."""
        return {"running": _scan_status["running"], "last": _scan_status["last"]}

    @app.post("/telegram/webhook")
    def telegram_webhook(
        update: dict = Body(...),
        x_telegram_bot_api_secret_token: str | None = Header(default=None),
    ) -> dict:
        """Telegram interactive bot. Not bearer-gated (Telegram can't send it) —
        secured by the per-startup secret header + the user-id allowlist in bot.py."""
        if _WEBHOOK["secret"] and x_telegram_bot_api_secret_token != _WEBHOOK["secret"]:
            raise HTTPException(403, "bad webhook secret")

        def _trigger_scan() -> None:
            threading.Thread(target=_guarded_scan, args=(db,), daemon=True).start()

        bot.handle_update(update, db, scan_fn=_trigger_scan)
        return {"ok": True}

    return app


app = create_app()


def _start_scheduler(db: str) -> None:
    """In-process cron scheduler — replaces supercronic. Fires scans through the
    same single-flight _guarded_scan, so the server is the sole DB writer. The
    schedule (default '7-19/2' = every 2h, 07:00–19:00) uses the container's
    local time (TZ env), and respects the on-demand lock."""
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger

    hours = os.environ.get("SCAN_HOURS", "7-19/2")
    sched = BackgroundScheduler()
    sched.add_job(lambda: _guarded_scan(db), CronTrigger(hour=hours, minute=0))
    sched.start()
    logger.info("scheduler started — scans at hour=%s (TZ=%s)", hours, os.environ.get("TZ", "local"))


def _setup_telegram() -> None:
    """Register the webhook with Telegram so interactive commands work. Generates
    a fresh secret each startup (held in memory) — only Telegram, sending that
    secret header, can reach the webhook. No-op unless the bot URL + token are set."""
    import secrets

    base = os.environ.get("TELEGRAM_WEBHOOK_URL")
    if not base or not os.environ.get("TELEGRAM_BOT_TOKEN"):
        return
    secret = secrets.token_urlsafe(24)
    _WEBHOOK["secret"] = secret
    url = base.rstrip("/") + "/telegram/webhook"
    ok = notify.set_webhook(url, secret)
    logger.info("telegram webhook -> %s (%s)", url, "registered" if ok else "FAILED")


def main() -> int:
    import uvicorn

    setup_logging()
    db = os.environ.get("JOB_RADAR_DB") or DEFAULT_DB
    if os.environ.get("SCAN_SCHEDULER", "1") != "0":
        _start_scheduler(db)
    _setup_telegram()
    host = os.environ.get("JOB_RADAR_HOST", "127.0.0.1")
    port = int(os.environ.get("JOB_RADAR_PORT", "8000"))
    # log_config=None → uvicorn's own logs flow through our timestamped root logger
    uvicorn.run("job_radar.server:app", host=host, port=port, reload=False, log_config=None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
