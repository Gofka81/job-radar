# job-hunt — Pi image (arm64 Raspberry Pi 64-bit OS, also amd64). One process:
# the FastAPI server, which also owns scheduling (APScheduler) + on-demand scans.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    JOB_RADAR_HOST=0.0.0.0 \
    JOB_RADAR_PORT=8000 \
    JOB_RADAR_CONFIG=/app/data/config.yml \
    TZ=Europe/London

# tzdata so the in-process cron schedule honours TZ (e.g. Europe/London);
# ca-certificates for outbound HTTPS to the job sources.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates tzdata \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Deps first for layer caching; editable install keeps ROOT=/app so the baked
# config.example.yml fallback resolves at /app/config.example.yml.
COPY pyproject.toml README.md config.example.yml ./
COPY src ./src
RUN pip install -e .

# Non-root. The named volume at /app/data inherits this ownership; it holds the
# DuckDB and the live config.yml (written via POST /api/config).
RUN useradd -m -u 1000 app && mkdir -p /app/data && chown -R app:app /app
USER app

EXPOSE 8000
CMD ["job-serve"]
