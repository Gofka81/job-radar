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
import traceback
from datetime import datetime, timezone

from fastapi import Body, Depends, FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel, Field

from . import bot, notify, setup_logging
from .analyze import run_analyze
from .dashboard import DASHBOARD_HTML
from .config import ROOT, load_config, load_rubric, read_config_text, save_config, save_rubric
from .scan import run_scan
from .store import Store

logger = logging.getLogger("job_radar.server")
DEFAULT_DB = str(ROOT / "data" / "jobs.duckdb")
TOKEN_ENV = "JOB_RADAR_API_TOKEN"

# Single-flight scan state, shared by the API trigger and the scheduler so only
# one scan ever runs at a time (one DB writer). Both go through _guarded_scan.
_scan_lock = threading.Lock()
_scan_status: dict = {"running": False, "last": None}

# Single-flight triage state, mirroring the scan lock. Triage reads the DB (and
# writes score/reason per job), so it shares nothing with the scan writer beyond
# both being background jobs — its own lock keeps two triage runs from overlapping.
_analyze_lock = threading.Lock()
_analyze_status: dict = {"running": False, "last": None}

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
    except Exception as exc:  # never let a scan crash the server — but log it loudly
        # logger.exception emits the FULL traceback (file:line of the failure) at
        # ERROR; we also surface the type + message so the cause is obvious in the
        # logs instead of vanishing silently into the scan status.
        logger.exception("scan failed — %s: %s", type(exc).__name__, exc)
        _scan_status["last"] = {
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
            "at": datetime.now(timezone.utc).isoformat(),
        }
    finally:
        _scan_status["running"] = False
        _scan_lock.release()


def _guarded_analyze(db: str, job_ids: list[str] | None, only_untriaged: bool) -> None:
    """Run one triage pass unless one's already going (then no-op). Mirrors
    _guarded_scan: single-flight + loud error logging into the status."""
    if not _analyze_lock.acquire(blocking=False):
        return
    _analyze_status["running"] = True
    try:
        result = run_analyze(
            load_config(), db, job_ids=job_ids, only_untriaged=only_untriaged
        )
        _analyze_status["last"] = result
        alert = None
        if result.get("auth_failed"):
            alert = ("⛔ <b>LLM not authenticated</b> — triage stopped. Set "
                     "CLAUDE_CODE_OAUTH_TOKEN (claude setup-token) and redeploy.")
        elif result.get("budget_hit"):
            alert = ("⛔ <b>LLM budget / rate limit hit</b> — triage stopped after "
                     f"{result['totals']['scored']} scored. Check usage.")
        if alert:  # surface the stop reason to the phone
            try:
                cid = notify.chat_id()
                if cid:
                    notify.send_message(cid, alert)
            except Exception:
                pass  # a Telegram hiccup must not affect the run
    except Exception as exc:  # never crash the server — log the full traceback
        logger.exception("triage failed — %s: %s", type(exc).__name__, exc)
        _analyze_status["last"] = {
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
            "at": datetime.now(timezone.utc).isoformat(),
        }
    finally:
        _analyze_status["running"] = False
        _analyze_lock.release()


class AnalyzePayload(BaseModel):
    # MVP: triage only. `target` is "all_pending" (default) or a list of job_ids.
    mode: str = "triage"
    target: str | list[str] = "all_pending"


class Verdict(BaseModel):
    # Key by url (preferred) or job_id; the Pi resolves url -> job_id.
    url: str | None = None
    job_id: str | None = None
    score: float | None = None
    status: str = "evaluated"
    report_num: int | None = None


class ResultsPayload(BaseModel):
    results: list[Verdict] = Field(default_factory=list)


class StatusUpdate(BaseModel):
    # Apply-tracking from the dashboard: set ONLY the workflow status of one job.
    job_id: str
    status: str


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

    @app.post("/api/status")
    def set_status(
        body: StatusUpdate,
        _: None = Depends(require_token),
        store: Store = Depends(get_store),
    ) -> dict:
        """Apply-tracking: set a single job's status (applied/viewed/…) from the
        dashboard. Updates status ONLY — never touches the AI score/reason."""
        try:
            ok = store.set_status(body.job_id, body.status)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        if not ok:
            raise HTTPException(404, "unknown job_id")
        return {"updated": True, "status": body.status}

    @app.get("/api/jobs")
    def jobs(
        limit: int = 500,
        q: str | None = None,
        _: None = Depends(require_token),
        store: Store = Depends(get_store),
    ) -> dict:
        """All jobs with timestamps + status, newest-discovered first. Optional
        `q` searches title + company + description (tech-stack terms in the JD)."""
        return {"jobs": store.list_jobs(limit, q)}

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

    @app.get("/api/rubric", response_class=PlainTextResponse)
    def get_rubric(_: None = Depends(require_token)) -> str:
        """Current triage rubric (or the baked example if none saved) — for the editor."""
        return load_rubric()

    @app.post("/api/rubric")
    def post_rubric(
        body: str = Body(..., media_type="text/plain"),
        _: None = Depends(require_token),
    ) -> dict:
        """Save the triage rubric. The next triage run picks it up — no redeploy."""
        try:
            save_rubric(body)
        except Exception as exc:  # empty / unwritable
            raise HTTPException(400, f"invalid rubric: {exc}")
        return {"saved": True}

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

    @app.post("/api/analyze", status_code=202)
    def analyze_now(
        payload: AnalyzePayload, _: None = Depends(require_token)
    ) -> dict:
        """Trigger on-Pi LLM triage of pending jobs (the dashboard 'Analyze'
        button). Returns immediately; runs in the background. 409 if one's already
        going. `target`: 'all_pending' (default) or a list of job_ids."""
        if payload.mode != "triage":
            raise HTTPException(400, "only mode='triage' is supported")
        if _analyze_lock.locked():
            raise HTTPException(409, "a triage run is already running")
        target = payload.target
        job_ids = target if isinstance(target, list) else None
        # explicit job_ids → re-score them even if already triaged; else only-new
        only_untriaged = job_ids is None
        threading.Thread(
            target=_guarded_analyze, args=(db, job_ids, only_untriaged), daemon=True
        ).start()
        return {"started": True}

    @app.get("/api/analyze")
    def analyze_status(_: None = Depends(require_token)) -> dict:
        """Last triage run's result + whether one is running now."""
        return {"running": _analyze_status["running"], "last": _analyze_status["last"]}

    @app.get("/api/usage")
    def usage(
        limit: int = 50,
        _: None = Depends(require_token),
        store: Store = Depends(get_store),
    ) -> dict:
        """LLM token spend — recent runs, grand totals, per-model breakdown. Feeds
        the dashboard Usage view so you can see what's consuming tokens."""
        return store.llm_usage(limit)

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

        def _trigger_analyze() -> None:  # triage all pending (only-untriaged, max_jobs-capped)
            threading.Thread(
                target=_guarded_analyze, args=(db, None, True), daemon=True
            ).start()

        bot.handle_update(update, db, scan_fn=_trigger_scan, analyze_fn=_trigger_analyze)
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
