"""server-side HTTP API + dashboard. Exposed remotely via a Cloudflare Tunnel
(cloudflared), so every data endpoint requires a bearer token.

Contract with the PC (career-ops bridge):
  GET  /api/pending  -> {"jobs": [...]}    the shortlist to evaluate
  POST /api/results  <- {"results": [...]} verdicts; server applies them to DuckDB

Run:  uvicorn job_radar.server:app   (or `job-serve`)
The server is the only writer of the DB; the PC only reads pending + posts verdicts.
"""

from __future__ import annotations

import logging
import os
import queue
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

# Triage QUEUE. A single daemon worker drains a FIFO queue so exactly one triage
# runs at a time (no parallel `claude` processes / Pro-quota hammering) — but the
# batch ✨Analyze and per-card ✨ requests QUEUE instead of being rejected. Two task
# kinds: 'batch' (all untriaged) and 'single' (specific job_ids, re-score allowed).
# In-memory, like the scan state: a restart clears it (triage is idempotent).
_analyze_q: "queue.Queue[dict]" = queue.Queue(maxsize=500)
_analyze_lock = threading.Lock()  # guards the state + dedup bookkeeping below
_analyze_state: dict = {"running": False, "current": None, "last": None}
_queued_singles: set[str] = set()  # job_ids queued or running as singles (dedup)
_queued_batch: bool = False        # a batch is queued or running (dedup + button block)

# Telegram webhook secret, set at startup if the bot is configured.
_WEBHOOK: dict = {"secret": None}


def _guarded_scan(db: str, deep: bool = False) -> None:
    """Run one scan unless one is already in progress (then no-op). Used by the
    API trigger, the scheduler, and the /scan Telegram command. `deep` pulls the
    full window (initial/daily full load). Pushes a Telegram notification when done."""
    if not _scan_lock.acquire(blocking=False):
        return
    _scan_status["running"] = True
    try:
        result = run_scan(load_config(), db, deep=deep)
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


def _analyze_alert(result: dict) -> None:
    """Push a Telegram alert if a triage run stopped on auth/budget. Best-effort."""
    alert = None
    if result.get("auth_failed"):
        alert = ("⛔ <b>LLM not authenticated</b> — triage stopped. Set "
                 "CLAUDE_CODE_OAUTH_TOKEN (claude setup-token) and redeploy.")
    elif result.get("budget_hit"):
        alert = ("⛔ <b>LLM budget / rate limit hit</b> — triage stopped after "
                 f"{result['totals']['scored']} scored. Check usage.")
    if not alert:
        return
    try:
        cid = notify.chat_id()
        if cid:
            notify.send_message(cid, alert)
    except Exception:
        pass  # a Telegram hiccup must not affect the run


def _run_task(task: dict) -> None:
    """Execute one queued triage task, updating _analyze_state with live progress.
    Never raises — a crash is logged into `last` so the worker keeps draining."""
    kind, db = task["kind"], task["db"]
    job_ids, only_untriaged = task.get("job_ids"), task.get("only_untriaged", True)
    with _analyze_lock:
        _analyze_state["running"] = True
        _analyze_state["current"] = {"kind": kind, "total": None, "scored": 0, "errors": 0}

    def progress(scored: int, errors: int, total: int) -> None:
        with _analyze_lock:
            c = _analyze_state["current"]
            if c:
                c.update(total=total, scored=scored, errors=errors)

    try:
        result = run_analyze(load_config(), db, job_ids=job_ids,
                             only_untriaged=only_untriaged, progress=progress)
        with _analyze_lock:
            _analyze_state["last"] = result
        _analyze_alert(result)
    except Exception as exc:  # never crash the worker — log the full traceback
        logger.exception("triage failed — %s: %s", type(exc).__name__, exc)
        with _analyze_lock:
            _analyze_state["last"] = {
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(),
                "at": datetime.now(timezone.utc).isoformat(),
            }
    finally:
        global _queued_batch
        with _analyze_lock:
            _analyze_state["running"] = False
            _analyze_state["current"] = None
            if kind == "batch":
                _queued_batch = False
            else:
                for jid in (job_ids or []):
                    _queued_singles.discard(jid)


def _analyze_worker() -> None:
    """The single triage worker — one task at a time, forever. Started once."""
    while True:
        task = _analyze_q.get()
        try:
            _run_task(task)
        except Exception:
            logger.exception("analyze worker crashed on a task")
        finally:
            _analyze_q.task_done()


_analyze_worker_thread = threading.Thread(
    target=_analyze_worker, name="analyze-worker", daemon=True)
_analyze_worker_thread.start()


def _enqueue_analyze(db: str, kind: str, job_ids: list[str] | None) -> dict | None:
    """Queue a triage task. Dedups (one batch in flight; a single already queued/
    running is dropped). Returns a status dict, or None if the queue is full (→409).
    'batch' scores all untriaged; 'single' re-scores the given job_ids."""
    global _queued_batch
    with _analyze_lock:
        if kind == "batch":
            if _queued_batch:
                return {"queued": False, "duplicate": True, "kind": kind,
                        "reason": "a batch is already queued or running"}
        else:
            job_ids = [j for j in (job_ids or []) if j not in _queued_singles]
            if not job_ids:
                return {"queued": False, "duplicate": True, "kind": kind,
                        "reason": "already queued or running"}
        task = {"kind": kind, "db": db, "job_ids": job_ids,
                "only_untriaged": kind == "batch"}
        try:
            _analyze_q.put_nowait(task)
        except queue.Full:
            return None
        if kind == "batch":
            _queued_batch = True
        else:
            _queued_singles.update(job_ids)
        return {"queued": True, "kind": kind, "position": _analyze_q.qsize()}


def _analyze_snapshot() -> dict:
    """Current queue state for GET /api/analyze — running flag, live progress of the
    task in flight, how many are waiting, whether a batch is in the pipeline, and the
    last finished run's result."""
    with _analyze_lock:
        return {
            "running": _analyze_state["running"],
            "current": dict(_analyze_state["current"]) if _analyze_state["current"] else None,
            "queued": _analyze_q.qsize(),
            "batch_active": _queued_batch,
            "last": _analyze_state["last"],
        }


class AnalyzePayload(BaseModel):
    # MVP: triage only. `target` is "all_pending" (default) or a list of job_ids.
    mode: str = "triage"
    target: str | list[str] = "all_pending"


class Verdict(BaseModel):
    # Key by url (preferred) or job_id; the server resolves url -> job_id.
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
    def scan_now(deep: bool = False, _: None = Depends(require_token)) -> dict:
        """Trigger a scan on demand (the dashboard 'Scan now' button). `deep=1`
        pulls the full window (initial/full load). Returns immediately; runs in the
        background. 409 if one's already going."""
        if _scan_lock.locked():
            raise HTTPException(409, "a scan is already running")
        threading.Thread(target=_guarded_scan, args=(db, deep), daemon=True).start()
        return {"started": True, "deep": deep}

    @app.get("/api/scan")
    def scan_status(_: None = Depends(require_token)) -> dict:
        """Last scan's result + whether one is running now."""
        return {"running": _scan_status["running"], "last": _scan_status["last"]}

    @app.post("/api/analyze", status_code=202)
    def analyze_now(
        payload: AnalyzePayload, _: None = Depends(require_token)
    ) -> dict:
        """Queue on-server LLM triage. The batch ✨Analyze and per-card ✨ both land
        here and are QUEUED (one worker, one at a time) rather than rejected. Returns
        immediately. `target`: 'all_pending' (batch) or a list of job_ids (single).
        409 only if the queue is full."""
        if payload.mode != "triage":
            raise HTTPException(400, "only mode='triage' is supported")
        target = payload.target
        if isinstance(target, list):
            kind, job_ids = "single", target
        else:
            kind, job_ids = "batch", None  # 'all_pending' → all untriaged
        result = _enqueue_analyze(db, kind, job_ids)
        if result is None:
            raise HTTPException(409, "triage queue is full — try again shortly")
        return result

    @app.get("/api/analyze")
    def analyze_status(_: None = Depends(require_token)) -> dict:
        """Queue state: running flag, live progress, queue depth, and the last run."""
        return _analyze_snapshot()

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

        def _trigger_analyze() -> None:  # queue a batch (all untriaged, max_jobs-capped)
            _enqueue_analyze(db, "batch", None)

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
    sched.add_job(lambda: _guarded_scan(db, deep=False), CronTrigger(hour=hours, minute=0))
    # Deep scan is MANUAL by default (the 🔭 button / POST /api/scan?deep=1) — run it
    # once to load the week, then occasionally (e.g. weekly) to refresh. This optional
    # cron is OFF unless DEEP_SCAN_HOURS is set; if you do set it, prefer a single hour
    # (e.g. "8") rather than something frequent — a deep scan is a backlog pull, not the
    # hourly job. DEEP_SCAN_DOW (cron day-of-week, e.g. "mon") narrows it to weekly.
    deep_hours = os.environ.get("DEEP_SCAN_HOURS")
    if deep_hours:
        dow = os.environ.get("DEEP_SCAN_DOW", "*")  # default every day; set e.g. "mon" for weekly
        sched.add_job(lambda: _guarded_scan(db, deep=True),
                      CronTrigger(day_of_week=dow, hour=deep_hours, minute=30))
        logger.info("deep scan scheduled — dow=%s hour=%s", dow, deep_hours)
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
