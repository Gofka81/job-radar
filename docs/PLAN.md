# job-hunt — architecture & build plan

## Decisions (locked)

| Decision | Choice |
|----------|--------|
| Repo | New standalone repo (this one), feeds career-ops via file contract |
| Stack | Python + DuckDB |
| Dashboard | Web app on the Pi (viewable from phone) |
| Pi ↔ PC sync | HTTP API on the Pi (FastAPI), exposed remotely via Cloudflare Tunnel (cloudflared). Bearer-token auth. *(was git — rejected)* |

## Architecture

```
┌─────────────── RASPBERRY PI (always-on, zero LLM) ────────────────┐
│  job_radar/                                                        │
│   sources/  adzuna · reed · greenhouse · lever · ashby             │
│             workday · oracle           (httpx connectors)          │
│        │                                                           │
│        ▼  normalize → Job (pydantic)                               │
│   DuckDB  ── jobs, scan_runs ── dedup + incremental state          │
│        ├─► filter (DE titles + Edinburgh/Glasgow/remote-UK)        │
│        ├─► notify → Telegram                                       │
│        └─► FastAPI: dashboard + GET /api/pending + POST /api/results│
│   scheduler: systemd timer, daily   ·   cloudflared tunnel         │
└────────────────────────────┬───────────────────────────────────-─┘
              HTTPS via Cloudflare Tunnel (bearer token)
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
| 1 | Adzuna (`gb`) | Broad UK aggregator | 1 ✅ |
| 2 | Reed | Direct UK | 1 ✅ |
| 3 | Greenhouse / Lever / Ashby | Startups | 1 ✅ |
| 4 | Workday | Enterprise sites | 5 |
| 5 | Oracle ORC | JPMorgan + banks | 5 |
| 6 | SmartRecruiters / Workable / SuccessFactors | Long tail | later |

To add any unknown ATS: DevTools → Network → XHR → find the JSON request the careers page makes →
replicate it in a `sources/{name}.py`.

## Phases

- **Phase 0 — Foundations** ✅ repo, `Job` schema, DuckDB store, config, filters.
- **Phase 1 — Core discovery** ✅ Adzuna + Reed + Greenhouse/Lever/Ashby; `scan` CLI.
- **Phase 2 — API sync** ✅ Pi FastAPI (`GET /api/pending`, `POST /api/results`, bearer-token) + PC `job-bridge` client (pull→`pipeline.md`, push←`results.tsv`). Replaces the rejected git sync; exposed via cloudflared.
- **Phase 3 — Schedule + notify (Pi)** — systemd timer (daily), Telegram notifier.
- **Phase 4 — Web dashboard (Pi)** — extend the Phase 2 FastAPI app with an HTML funnel view
  (found→filtered→shortlisted→evaluated→applied) from DuckDB `funnel()`. Phone-viewable via cloudflared.
- **Phase 5 — Enterprise providers** — Workday + Oracle ORC (JPMorgan).
- **Phase 6 — Evaluation workflow (PC)** — DE-personalize career-ops (archetypes, profile, cv); documented supervised loop + tracker writeback.
- **Phase 7 — JD enrichment (optional)** — fetch + heading-segment JDs; write `local:jds/` to dodge prompt-injection and save agent fetches.
- **Phase 8 — Hardening** — connector tests (respx fixtures), GitHub Actions CI, structured logging, README story.

Value milestone: after Phase 3 you have daily zero-token UK discovery + phone alerts. Everything after is enrichment.

## Token economics (why this exists)

career-ops's native discovery covers only Greenhouse/Lever/Ashby; everything else falls to its
agentic Playwright/WebSearch path (hundreds of K+ tokens/day for ~100 jobs). Deterministic ingest =
~0 tokens for discovery; you pay LLM only for the ~8 evaluations you'd run anyway. The saving is
essentially the entire discovery cost.
