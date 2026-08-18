#!/usr/bin/env bash
# Deploy salvai-be to Google Cloud Run (scale-to-zero, Always Free region).
# Usage: ./scripts/deploy-cloudrun.sh [.env.prod]
#
# Requires: gcloud auth, billing on project salvai, APIs enabled (see README).
# Does not print secret values.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PROJECT_ID="${GCP_PROJECT_ID:-salvai}"
REGION="${GCP_REGION:-us-east1}"
SERVICE="${CLOUD_RUN_SERVICE:-salvai-be}"
ENV_FILE="${1:-.env.prod}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing env file: $ENV_FILE" >&2
  exit 1
fi

ENV_YAML="$(mktemp)"
trap 'rm -f "$ENV_YAML"' EXIT

python3 - "$ENV_FILE" "$ENV_YAML" <<'PY'
import sys

def yaml_quote(value: str) -> str:
    if value == "":
        return '""'
    if all(c not in value for c in ':{}[]&*#?|-<>=!%@`"\n\\' for c in value):
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'

env_path, out_path = sys.argv[1], sys.argv[2]
lines_out: list[str] = []

# Cloud Run env (always applied on deploy)
lines_out.append(f"WEB_CONCURRENCY: {yaml_quote('1')}")
lines_out.append(f"SENTRY_ENVIRONMENT: {yaml_quote('production')}")
lines_out.append(f"SENTRY_TRACES_SAMPLE_RATE: {yaml_quote('0.0')}")
lines_out.append(f"ENRICH_CACHE_DB_PATH: {yaml_quote('/data/enrich_cache.db')}")

skip = {"WEB_CONCURRENCY", "PORT"}
with open(env_path, encoding="utf-8") as f:
    for raw in f:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not key or key in skip:
            continue
        lines_out.append(f"{key}: {yaml_quote(value)}")

with open(out_path, "w", encoding="utf-8") as out:
    out.write("\n".join(lines_out) + "\n")
PY

echo "Deploying $SERVICE to $REGION (project $PROJECT_ID) from $ENV_FILE …"

gcloud run deploy "$SERVICE" \
  --source . \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --platform managed \
  --quiet \
  --min-instances 0 \
  --max-instances 1 \
  --cpu 1 \
  --memory 512Mi \
  --concurrency 80 \
  --timeout 300 \
  --cpu-throttling \
  --no-cpu-boost \
  --allow-unauthenticated \
  --env-vars-file "$ENV_YAML"

URL="$(gcloud run services describe "$SERVICE" \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --format='value(status.url)')"

echo ""
echo "Service URL: $URL"
echo "Health:      $URL/health"
