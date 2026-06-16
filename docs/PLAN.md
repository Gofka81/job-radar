# job-hunt — architecture & build plan

## Decisions (locked)

| Decision | Choice |
|----------|--------|
| Repo | New standalone **public** repo (this one), feeds career-ops via the API contract |
| Stack | Python + DuckDB + FastAPI + APScheduler |
| Dashboard | Web app on the Pi (viewable from phone) |
| Pi ↔ PC sync | HTTP API on the Pi (FastAPI), bearer-token, reachable over cloudflared. *(was git — rejected)* |
| Pi runtime | **One container**: the server owns the API/dashboard **and** scanning (scheduled + on-demand). Sole DB writer. *(supercronic/systemd — removed)* |
| Deploy | Portainer GitOps from the public repo; secrets = Portainer stack env vars; cloudflared managed separately |
| Config | Edited via `GET/POST /api/config`, stored on the data volume — **not in git** (personal) |

## Architecture

```
┌──────── RASPBERRY PI — one container (always-on, zero LLM) ────────┐
│  FastAPI server (job-serve)                                        │
│   sources/  adzuna · reed · greenhouse · lever · ashby · workable  │
│        ▼  normalize → Job (pydantic) → filter (titles + all-UK)    │
│   DuckDB  ── jobs, scan_runs ── dedup + incremental state          │
│   run_scan():  APScheduler (SCAN_HOURS 7-19/2)  +  POST /api/scan  │
│   API:  /api/pending /api/results /api/funnel /api/config /api/scan │
│   sole DB writer (single-flight lock)                              │
└────────────────────────────┬───────────────────────────────────-─┘
   cloudflared (separate) ──► HTTPS + bearer token
   GET /api/pending  ─► shortlist        POST /api/results ◄─ verdicts
┌────────────────────────────┴─────────── YOUR PC (supervised) ─────┐
│  job-bridge (this repo, client) + career-ops (Node, reused)        │
│   bridge pull → writes pipeline.md → claude /career-ops pipeline    │
│   evaluate A–G · tailor CV · generate-pdf · merge-tracker          │
│   → reports/, applications.md, results.tsv → bridge push           │
└────────────────────────────────────────────────────────────────-─┘
```

**Single writer (no two-writer problem):** the Pi's DuckDB is the only system of record. The PC
never writes it directly — it `GET`s the pending shortlist and `POST`s verdicts (`job_id, score,
status, report_num`), which the Pi applies. The PC still owns its local documents (`reports/`,
`applications.md`, `output/*.pdf`); only the verdict pointer crosses the wire.

## Providers (priority)

| # | Provider | Covers | Phase |
|---|----------|--------|-------|
| 1 | Adzuna (`gb`) | Broad UK aggregator, nationwide | 1 ✅ |
| 2 | Reed | Direct UK, nationwide | 1 ✅ |
| 3 | Greenhouse / Lever / Ashby | Companies (slugs from career-ops `portals.yml`) | 1 ✅ |
| 4 | Workable | Starling, Hugging Face, … | 2 ✅ |
| 5 | Workday | Enterprise sites (NatWest, Lloyds) | 5 |
| 6 | Oracle ORC | JPMorgan + banks | 5 |
| 7 | SmartRecruiters / SuccessFactors | Long tail | later |

To add any unknown ATS: DevTools → Network → XHR → find the JSON request the careers page makes →
replicate it in a `sources/{name}.py`.

## Phases

- **Phase 0 — Foundations** ✅ repo, `Job` schema, DuckDB store, config, filters.
- **Phase 1 — Core discovery** ✅ Adzuna + Reed + Greenhouse/Lever/Ashby (+ Workable); `scan` CLI.
- **Phase 2 — API sync + runtime** ✅ FastAPI (`/api/pending` `/api/results` `/api/funnel`
  `/api/config` `/api/scan`, bearer-token) + PC `job-bridge` (pull→`pipeline.md`, push←`results.tsv`).
  Single-process server owns scheduled (APScheduler) + on-demand scans; config edited via `/api/config`.
  Dockerised for Portainer GitOps. Replaces the rejected git sync; reachable via cloudflared.
- **Phase 3 — Notify (Pi)** — Telegram notifier on new matches. *(scheduling already done in Phase 2.)*
- **Phase 4 — Web dashboard (Pi)** — HTML on the same app: funnel
  (found→filtered→shortlisted→evaluated→applied) from `funnel()`, plus a "Scan now" button and a
  `config.yml` editor (POST /api/config). Phone-viewable via cloudflared.
- **Phase 5 — Enterprise providers** — Workday + Oracle ORC (JPMorgan).
- **Phase 6 — Evaluation workflow (PC)** — DE-personalize career-ops (archetypes, profile, cv); documented supervised loop + tracker writeback.
- **Phase 7 — JD enrichment (optional)** — fetch + heading-segment JDs; write `local:jds/` to dodge prompt-injection and save agent fetches.
- **Phase 8 — Hardening** — connector tests (respx fixtures), GitHub Actions CI, structured logging, README story.

Value milestone: after Phase 2 you have scheduled + on-demand zero-token UK discovery with an API/DB;
Phase 3 adds phone alerts, Phase 4 the dashboard. Everything after is enrichment.

## Token economics (why this exists)

career-ops's native discovery covers only Greenhouse/Lever/Ashby; everything else falls to its
agentic Playwright/WebSearch path (hundreds of K+ tokens/day for ~100 jobs). Deterministic ingest =
~0 tokens for discovery; you pay LLM only for the ~8 evaluations you'd run anyway. The saving is
essentially the entire discovery cost.
