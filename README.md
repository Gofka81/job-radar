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
Raspberry Pi (always-on, zero tokens)        Your PC (on-demand, supervised)
  scan → filter → dedup → DuckDB               job-bridge pull  → pipeline.md
  → FastAPI: /api/pending, /api/results        claude → /career-ops pipeline
  → Telegram notify                            evaluate · tailor CV · PDF
  → web dashboard (phone)                      job-bridge push  → verdicts
        └──── HTTPS via Cloudflare Tunnel (bearer token) ────┘
```

The Pi's DuckDB is the single source of truth; the PC reads the shortlist and posts back verdicts
over the API. No shared git repo, no file-merge conflicts.

Evaluation needs a logged-in Claude and human review, so it stays on your PC. Discovery needs neither,
so it runs unattended on the Pi.

## Quick start

```bash
# install uv (manages its own Python 3.11+): https://docs.astral.sh/uv/
uv sync
cp config.example.yml config.yml      # edit: titles, location, sources
cp .env.example .env                  # add Adzuna + Reed API keys
uv run job-scan --dry-run             # preview, writes nothing
uv run job-scan                       # real scan into data/jobs.duckdb
```

See `docs/PLAN.md` for the full architecture and build roadmap.

## Sources

| Provider | Covers | Status |
|----------|--------|--------|
| Adzuna (`gb`) | Broad UK aggregator (Reed/Totaljobs/CV-Library/company sites) | ✅ Phase 1 |
| Reed | Direct UK | ✅ Phase 1 |
| Greenhouse / Lever / Ashby | UK + global startups | ✅ Phase 1 |
| Workday | Enterprise career sites | ⏳ Phase 5 |
| Oracle ORC | JPMorgan + banks | ⏳ Phase 5 |

Anything without a structured API (LinkedIn, bespoke sites) → paste the URL into career-ops's
`pipeline.md` manually. That's the designed fallback, not a gap.
