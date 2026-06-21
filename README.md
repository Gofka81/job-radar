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

## Features

**Discovery (deterministic — zero LLM tokens)**
- **8 source connectors** — Adzuna + Reed (aggregators), Greenhouse / Lever / Ashby / Workable (company
  ATS boards), and Workday / Oracle ORC (self-hosted enterprise sites). Adding a source is one file + one
  registry line.
- **Per-location targeting** — each priority area (Edinburgh / Glasgow / London / nationwide) gets its own
  date-sorted query budget, so high-volume London can't crowd Scotland out of the results.
- **Server-side narrowing** — Adzuna `category=it-jobs`, full-text `what_exclude`, and a tight
  `max_days_old` window keep the result budget focused (and under the API's daily call limit).
- **Title + location filters** — case-insensitive include/exclude lists, kept broad (all UK + remote).

**Dedup & lifecycle**
- **Write-time dedup** — identity is `vacancy_key = sha1(company | title)`, source- and city-agnostic:
  tracking-token variants, agency reposts under new ad-ids, the *same ad on multiple sources*, and the
  *same posting listed in several cities* all collapse to one row. City is an attribute — a multi-city
  posting accumulates a `locations` set (shown as a chip + "+N"), so no opening is lost.
- **Closed-job expiry + generations** — a job that drops off its source for `expire_after_hours` is marked
  `expired`; the same window is the dedup horizon, so a posting that *reappears after expiring* gets a
  fresh row (a new evaluation), while the old one is kept as history.
- **Single DB writer** — one process owns DuckDB (scheduled + on-demand scans + API), no lock fights.

**Dashboard & notifications**
- **Phone-friendly web dashboard** (`GET /`) — funnel chips, job list, and filters by status, location,
  source, and min-salary, defaulting to the last 48h with a show-all toggle.
- **Full-text / tech-stack search** — searches the job description server-side, so terms like *spark* or
  *airflow* are found even when they're not in the title.
- **In-dashboard config editor** — edit `config.yml` from your phone; validated and applied on next scan,
  no redeploy.
- **Telegram bot** — push notifications on new matches, plus `/jobs` (paginated), `/funnel`, `/scan`.

**Sync & ops**
- **HTTP API** to career-ops — `GET /api/pending` (shortlist out) / `POST /api/results` (verdicts back),
  bearer-token, over a Cloudflare Tunnel. The PC `job-bridge` pulls/pushes; the Pi's DuckDB stays the
  single source of truth.
- **Config over the wire** — `GET/POST /api/config`, stored on the data volume, never in git.
- **Deployed via Portainer GitOps** from this public repo; secrets are stack env vars.

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

| Provider | Covers |
|----------|--------|
| Adzuna (`gb`) | Broad UK aggregator (Reed/Totaljobs/CV-Library/company sites), nationwide |
| Reed | Direct UK, nationwide |
| Greenhouse / Lever / Ashby | UK + global companies (board slugs; vanity-domain boards work too) |
| Workable | Companies on Workable (e.g. Starling, Hugging Face) |
| Workday | Self-hosted enterprise sites (`{host, site}` per tenant — e.g. Live Nation, CrowdStrike) |
| Oracle ORC | Self-hosted CandidateExperience sites (e.g. JPMorgan, Goldman Sachs, Bank of England) |

Adding a source is one file + one registry line. Anything without a structured API (LinkedIn, bespoke
portals) → paste the URL into career-ops's `pipeline.md` manually. That's the designed fallback, not a gap.
