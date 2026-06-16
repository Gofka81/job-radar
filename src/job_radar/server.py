"""Pi-side HTTP API + dashboard. Exposed remotely via a Cloudflare Tunnel
(cloudflared), so every data endpoint requires a bearer token.

Contract with the PC (career-ops bridge):
  GET  /api/pending  -> {"jobs": [...]}    the shortlist to evaluate
  POST /api/results  <- {"results": [...]} verdicts; Pi applies them to DuckDB

Run:  uvicorn job_radar.server:app   (or `job-serve`)
The Pi is the only writer of the DB; the PC only reads pending + posts verdicts.
"""

from __future__ import annotations

import os
import threading

from fastapi import Body, Depends, FastAPI, Header, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from .config import ROOT, load_config, read_config_text, save_config
from .scan import run_scan
from .store import Store

DEFAULT_DB = str(ROOT / "data" / "jobs.duckdb")
TOKEN_ENV = "JOB_RADAR_API_TOKEN"

# Single-flight scan state, shared by the API trigger and the scheduler so only
# one scan ever runs at a time (one DB writer). Both go through _guarded_scan.
_scan_lock = threading.Lock()
_scan_status: dict = {"running": False, "last": None}


def _guarded_scan(db: str) -> None:
    """Run one scan unless one is already in progress (then no-op). Used by both
    POST /api/scan and the scheduler."""
    if not _scan_lock.acquire(blocking=False):
        return
    _scan_status["running"] = True
    try:
        _scan_status["last"] = run_scan(load_config(), db)
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
    print(f"[scheduler] scans at hour={hours} (TZ={os.environ.get('TZ', 'local')})", flush=True)


def main() -> int:
    import uvicorn

    db = os.environ.get("JOB_RADAR_DB") or DEFAULT_DB
    if os.environ.get("SCAN_SCHEDULER", "1") != "0":
        _start_scheduler(db)
    host = os.environ.get("JOB_RADAR_HOST", "127.0.0.1")
    port = int(os.environ.get("JOB_RADAR_PORT", "8000"))
    uvicorn.run("job_radar.server:app", host=host, port=port, reload=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
