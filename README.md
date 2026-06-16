# job-hunt

Deterministic UK job-discovery pipeline. Inspired by [santifer/career-ops](https://github.com/santifer/career-ops),
but it owns the half career-ops is weak at: **discovery**.

## The idea

Two halves of a job search, split by what each one *should* cost:

- **Discovery** (find jobs, filter, dedup) — pure HTTP + SQL. **Zero LLM tokens.** This repo.
- **Evaluation** (score fit, tailor CV, draft answers) — legitimate LLM work. Delegated to career-ops.

`job-hunt` scans UK job sources on a schedule, filters to roles that match, dedups against history,
and writes a shortlist into career-ops's `data/pipeline.md`. career-ops then does the LLM evaluation —
**only on the handful of jobs that survive filtering, never the raw firehose.**

## Deployment shape

```
Raspberry Pi — one container (always-on, zero tokens)   Your PC (on-demand, supervised)
  FastAPI server (job-serve):                             job-bridge pull  → pipeline.md
   • APScheduler → scan every 2h (07–19)                  claude → /career-ops pipeline
   • POST /api/scan  (on-demand "Scan now")               evaluate · tailor CV · PDF
   • filter → dedup → DuckDB  (sole writer)               job-bridge push  → verdicts
   • /api/pending /api/results /api/funnel
   • /api/config  (edit config from the dashboard)
        └──── HTTPS via your Cloudflare Tunnel (bearer token) ────┘
```

One process owns the database — it serves the API/dashboard **and** runs both the scheduled and
on-demand scans, so there's a single DB writer and no lock fights. The PC only reads the shortlist
and posts back verdicts; the Pi's DuckDB is the single source of truth. No shared git repo.

Evaluation needs a logged-in Claude and human review, so it stays on your PC. Discovery needs neither,
so it runs unattended on the Pi. Deployed via **Portainer GitOps** from this public repo; secrets are
Portainer stack env vars and `config.yml` is edited through `/api/config` — neither lives in git.

## Quick start (local)

```bash
# install uv (manages its own Python 3.11+): https://docs.astral.sh/uv/
uv sync
cp config.example.yml config.yml      # edit: titles, location, sources
cp .env.example .env                  # add Adzuna + Reed API keys
uv run job-scan --dry-run             # preview, writes nothing
uv run job-scan                       # real scan into data/jobs.duckdb
uv run job-serve                      # serve API + dashboard, schedule + on-demand scans
```

## Deploy (Raspberry Pi, Docker)

```bash
docker compose up -d --build          # single service; reads secrets from the environment
```

On the Pi this is a **Portainer GitOps** stack pointed at this repo: secrets are Portainer stack
env vars (`ADZUNA_*`, `REED_API_KEY`, `JOB_RADAR_API_TOKEN`, `SCAN_HOURS`, `TZ`) and `config.yml` is
edited through `POST /api/config` (stored on the data volume, never in git). Point your own
cloudflared tunnel at the published port. See `docs/PLAN.md` for the full architecture.

## Sources

| Provider | Covers | Status |
|----------|--------|--------|
| Adzuna (`gb`) | Broad UK aggregator (Reed/Totaljobs/CV-Library/company sites), nationwide | ✅ |
| Reed | Direct UK, nationwide | ✅ |
| Greenhouse / Lever / Ashby | UK + global companies (slugs from career-ops `portals.yml`) | ✅ |
| Workable | Companies on Workable (e.g. Starling, Hugging Face) | ✅ |
| Workday | Enterprise career sites (NatWest, Lloyds…) | ⏳ Phase 5 |
| Oracle ORC | JPMorgan + banks | ⏳ Phase 5 |

Anything without a structured API (LinkedIn, bespoke sites) → paste the URL into career-ops's
`pipeline.md` manually. That's the designed fallback, not a gap.
