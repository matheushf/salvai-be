FROM python:3.12-slim

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock ./

RUN uv sync --frozen --no-dev

COPY app ./app

RUN mkdir -p /data

ENV PATH="/app/.venv/bin:$PATH"
ENV ENRICH_CACHE_DB_PATH=/data/enrich_cache.db

# Default port for manual docker run; runtime port follows PORT (Cloud Run / Coolify inject it).
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD sh -c 'python -c "import os, urllib.request; urllib.request.urlopen(f\"http://127.0.0.1:{os.environ.get(\"PORT\", \"8000\")}/health\")"' || exit 1

# Cloud Run: set WEB_CONCURRENCY=1 (see scripts/deploy-cloudrun.sh). Default 2 for larger VPS RAM.
CMD uv run uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers ${WEB_CONCURRENCY:-2}
