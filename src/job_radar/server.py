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

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from .config import ROOT
from .store import Store

DEFAULT_DB = str(ROOT / "data" / "jobs.duckdb")
TOKEN_ENV = "JOB_RADAR_API_TOKEN"


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

    return app


app = create_app()


def main() -> int:
    import uvicorn

    host = os.environ.get("JOB_RADAR_HOST", "127.0.0.1")
    port = int(os.environ.get("JOB_RADAR_PORT", "8000"))
    uvicorn.run("job_radar.server:app", host=host, port=port, reload=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
