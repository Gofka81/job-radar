# job-hunt — Pi image. Runs the FastAPI server (default) or the scheduled scan
# (supercronic). Multi-arch: builds on arm64 (Raspberry Pi 64-bit OS) and amd64.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    JOB_RADAR_HOST=0.0.0.0 \
    JOB_RADAR_PORT=8000 \
    TZ=Europe/London

# supercronic = cron built for containers (logs to stdout, no PID-1 quirks,
# no host cron, no docker socket). Arch derived from the base image.
ARG SUPERCRONIC_VERSION=v0.2.33
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends curl ca-certificates tzdata; \
    arch="$(dpkg --print-architecture)"; \
    case "$arch" in \
      amd64) sc=amd64 ;; \
      arm64) sc=arm64 ;; \
      armhf) sc=arm ;; \
      *) echo "unsupported arch: $arch" >&2; exit 1 ;; \
    esac; \
    curl -fsSL -o /usr/local/bin/supercronic \
      "https://github.com/aptible/supercronic/releases/download/${SUPERCRONIC_VERSION}/supercronic-linux-${sc}"; \
    chmod +x /usr/local/bin/supercronic; \
    apt-get purge -y curl; apt-get autoremove -y; rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Deps first for layer caching, then the editable install keeps ROOT=/app so
# config.yml + data/ resolve exactly like the dev layout.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install -e .

COPY docker/crontab /app/crontab

# Non-root. The named volume mounted at /app/data inherits this ownership.
RUN useradd -m -u 1000 app && mkdir -p /app/data && chown -R app:app /app
USER app

EXPOSE 8000

# Default = API server. The scan service overrides this with supercronic.
CMD ["job-serve"]
