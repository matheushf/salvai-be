# salvai-be: setup, environment variables, and smoke checks

Backend code: [`salvai-be/`](../salvai-be/). This guide explains how to run the API locally, what each `.env` variable means, how to sanity-check connectivity, and how **not** to confuse secrets with login tokens.

## Security basics

1. **`salvai-be/.env` is gitignored** — create it locally and fill secrets from Supabase Dashboard; never commit real keys. See **Environment variables reference** below.
2. **Never paste production secrets into chat, screenshots, pull requests, or docs.** Rotate anything that was leaked.
3. **`SUPABASE_JWT_SECRET`** and **`SUPABASE_SERVICE_ROLE_KEY`** live only on trusted servers — they are **not** the token you send in `Authorization: Bearer ...` from your app.
4. Copy [`salvai-be/.env.example`](../salvai-be/.env.example) to `salvai-be/.env` for local runs. The same keys are prompted in the Render dashboard (`salvai-be/render.yaml`).

---

## Prerequisites

- **Python 3.12+** and [**uv**](https://docs.astral.sh/uv/) (see [`salvai-be/README.md`](../salvai-be/README.md)).
- A **Supabase** project with the social schema applied (see [`supabase/README.md`](../supabase/README.md): `supabase link` → `supabase db push`). Without migrations, authenticated calls that hit Postgres often return **502** from the API.

---

## Step-by-step: first run

### 1. Install dependencies

```bash
cd salvai-be
uv sync
```

### 2. Create `.env`

Create `salvai-be/.env` (gitignored) and fill in every variable listed in **Environment variables reference** below (see Supabase Dashboard → **Project Settings** → **API** and **JWT Settings**).

### 3. Confirm settings load (no full secrets printed)

```bash
cd salvai-be
uv run python scripts/verify_env.py
```

You should see `OK: settings load`, a masked service role key, masked JWT secret, the **expected JWT issuer** (`https://<project-ref>.supabase.co/auth/v1`), and your parsed CORS origins.

### 4. Apply database migrations (once per Supabase project)

From the **repository root** (not only `salvai-be/`):

```bash
cd /path/to/salvai   # parent of salvai-be/ and supabase/
supabase login
supabase link --project-ref <your-project-ref>
supabase db push
```

Alternatively, run the SQL in Supabase Dashboard → **SQL Editor** (see migration file under `supabase/migrations/`).

### 5. Start the API

```bash
cd salvai-be
uv run task dev
```

Or run uvicorn directly (still uses the project venv via `uv run`):

```bash
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

- Docs: `http://127.0.0.1:8000/docs`
- Health: `GET http://127.0.0.1:8000/health`

### 6. Smoke test (optional)

The script [`salvai-be/scripts/smoke_social_api.py`](../salvai-be/scripts/smoke_social_api.py) hits `/health` and, if given a **user** token, exercises profile and event routes.

```bash
# Terminal A: API running as above.

# Terminal B — only health (no Bearer token):
cd salvai-be
SALVAI_API_BASE=http://127.0.0.1:8000 uv run python scripts/smoke_social_api.py

# With a real user JWT (short-lived — do not commit):
export SUPABASE_ACCESS_TOKEN='<session.access_token from your app>'
SALVAI_API_BASE=http://127.0.0.1:8000 uv run python scripts/smoke_social_api.py
```

Where to get **`session.access_token`**:

- Frontend: after sign-in, `const { data } = await supabase.auth.getSession();` then `data.session?.access_token` ([Supabase Auth — getSession](https://supabase.com/docs/reference/javascript/auth-getsession)).
- It should look like **`eyJ...` with two dots** (header.payload.signature). If it is a single blob or looks like dashboard “JWT Secret”, it is **not** the access token.

---

## Troubleshooting

| Symptom | Likely cause |
|--------|----------------|
| **401** on `/api/v1/*` | Missing/invalid **`Authorization: Bearer`**, expired session, wrong token type (e.g. JWT **secret** vs user **access_token**), or stale backend (Supabase may issue **ES256** JWTs verified via **JWKS**; `salvai-be` supports both HS256 and ES256/RS256). |
| **502** + upstream error on writes/reads | Wrong Supabase URL/keys, or **tables missing** (run migrations). |
| **`ModuleNotFoundError: fastapi`** when running `uvicorn` | Use `uv run task dev` or `uv run uvicorn ...` from `salvai-be/` so dependencies resolve. |
| CORS errors in the browser | Add your frontend origin to **`CORS_ALLOWED_ORIGINS`** (comma-separated, no spaces after commas unless quoted consistently). |

---

## Environment variables reference (`salvai-be/.env`)

Aligned with [`salvai-be/app/core/config.py`](../salvai-be/app/core/config.py).

| Variable | Required | Purpose |
|----------|----------|---------|
| **`SUPABASE_URL`** | Yes | Project API URL: `https://<project-ref>.supabase.co`. Used by the backend’s Supabase client and to build the expected JWT **`iss`** (`<SUPABASE_URL>/auth/v1`). |
| **`SUPABASE_SERVICE_ROLE_KEY`** | Yes | **Service role** API key (Dashboard → API). Used only on the server; **bypasses Row Level Security**. Never expose to browsers or mobile clients. |
| **`SUPABASE_JWT_SECRET`** | Yes | Dashboard **JWT Secret**. Used to verify **HS256** user tokens; **ES256** / **RS256** tokens are verified via JWKS at `<SUPABASE_URL>/auth/v1/.well-known/jwks.json`. Not used as a Bearer token from clients. |
| **`CORS_ALLOWED_ORIGINS`** | Yes (recommended) | Comma-separated list of allowed **browser** origins for CORS (e.g. `http://localhost:8081,https://your-app.com`). Parsed into a list by the app. |
| **`SENTRY_DSN`** | No | Sentry project DSN. When set, unhandled errors and upstream failures are reported. Leave empty in local dev. |
| **`SENTRY_ENVIRONMENT`** | No | Sentry environment label (default `development`; use `production` on the VPS). |
| **`SENTRY_TRACES_SAMPLE_RATE`** | No | APM sample rate `0.0`–`1.0` (default `0.0`, errors only). |
| **`SENTRY_RELEASE`** | No | Optional release/version string (e.g. git SHA) for Sentry regression tracking. |
| **`INSTAGRAM_API_KEY`** | No | If set, `GET /api/v1/instagram/post` requires header **`X-Api-Key`** with this value; if empty, the route is open (useful for local dev only). |
| **`INSTAGRAM_USERNAME`** | No | Instagram **Account A** for authenticated instaloader sessions on salvai-be (layer 2 of the 4-layer retry). |
| **`INSTAGRAM_SESSION_FILE`** | No | Path to Account A session file on the salvai-be host. Create with `instaloader -l USERNAME`. Mount into the Docker container in production. |
| **`WEB_CONCURRENCY`** | No | Uvicorn worker count (default **`2`** in Docker; **`1`** on Cloud Run free tier via deploy script). |
| **`SCRAPER_SERVICE_URL`** | Yes (production) | Base URL of the private [`salvai-scraper`](../salvai-scraper/) service for generic web enrichment and Instagram fallback (layers 3–4). |
| **`SCRAPER_API_KEY`** | Yes (production) | API key sent to salvai-scraper as **`X-Api-Key`**. |
| **`CHOCO_DATA_API_KEY`** | Yes (production, for default Instagram path) | ChocoData API key for `GET https://api.chocodata.com/api/v1/instagram/post`. Server-only; never expose to the mobile app. When empty, Instagram enrichment falls back to instaloader even if the flag below is true. |
| **`INSTAGRAM_CHOCODATA_ENABLED`** | No | Defaults to **`true`**. When true and `CHOCO_DATA_API_KEY` is set, Instagram enrichment uses ChocoData instead of the 4-layer instaloader path. Set **`false`** to restore instaloader without a code rollback. |
| **`ENRICH_CACHE_ENABLED`** | No | When `true` (default), `GET /api/v1/enrich` responses are cached in SQLite. Set `false` to debug upstream. |
| **`ENRICH_CACHE_DB_PATH`** | No | SQLite file path. Default `./data/enrich_cache.db` locally; `/data/enrich_cache.db` in the Docker image. Requires persistent `/data` on the VPS — see [`docs/enrich-cache-vps-setup.md`](enrich-cache-vps-setup.md). |
| **`GROQ_API_KEY`** | No | Server-only Groq key for `POST /api/v1/enrich/extract`. Never put this in `EXPO_PUBLIC_*`. Empty → extraction returns an empty result. |
| **`GROQ_MODEL`** | No | Groq model id (default `llama-3.3-70b-versatile`). |
| **`INTERNAL_NOTIFICATIONS_KEY`** | Yes (production) | Shared secret for `POST /api/v1/internal/notifications/dispatch`. Send as **`X-Api-Key`**. Empty or mismatch → 403. Host cron uses this key; never expose it to the mobile app. |
| **`EXPO_ACCESS_TOKEN`** | No | Optional Expo access token sent as `Authorization: Bearer` to the Expo Push API (enhanced security). |

### Instagram 4-layer retry

Instagram enrichment tries up to four layers (anonymous + authenticated on Hetzner, then anonymous + authenticated on Locaweb) when rate-limited. Layers 3–4 are skipped locally if `SCRAPER_SERVICE_URL` is unset.

Full architecture, diagrams, and Coolify setup for both VPSes: **[`docs/instagram-4-layer-rate-limiting.md`](instagram-4-layer-rate-limiting.md)**.

### Staging (self-hosted Supabase on Coolify)

Staging Supabase runs on the Hetzner VPS via Coolify. Create **`salvai-be/.env.staging`** (gitignored), fill `SUPABASE_*` from Coolify, then run with `set -a && source .env.staging && set +a && uv run task dev`.

Full guide: **[`docs/supabase-staging-coolify-setup.md`](supabase-staging-coolify-setup.md)**.

### Production (Google Cloud Run)

MVP production runs on **Cloud Run** in GCP project **`salvai`**, region **`us-east1`**:

**`https://salvai-be-76v7wwgxga-ue.a.run.app`**

Deploy/redeploy from **`salvai-be/`**:

```bash
./scripts/deploy-cloudrun.sh .env.prod
```

Secrets live on the Cloud Run service (or in gitignored `.env.prod` for manual deploys) — never commit them. Pushes that touch `salvai-be/` or `cloudbuild.yaml` deploy via Cloud Build; see [`salvai-be/README.md`](../salvai-be/README.md#deploy-on-git-push). The service scales to **zero** when idle (`min-instances=0`, `max-instances=1`, 512 MiB, CPU throttling). Set a billing budget alert on the project.

Verify:

```bash
curl -sS https://salvai-be-76v7wwgxga-ue.a.run.app/health
# → {"status":"ok"}
```

Mobile app: set **`EXPO_PUBLIC_SALVAI_API_BASE_URL`** to the URL above (EAS secret + new build). See [`docs/mobile-api-and-auth.md`](mobile-api-and-auth.md).

The enrich SQLite cache is **ephemeral** on Cloud Run (no persistent disk).

### Production (Hetzner VPS — legacy)

`PORT` defaults to `8000` via the Dockerfile (`${PORT:-8000}`). Set all required variables in a `.env` file on the server and pass it with `docker run --env-file`. Include your production frontend origin in **`CORS_ALLOWED_ORIGINS`**. Set **`SCRAPER_SERVICE_URL`** to the production scraper host (see **Environment variables reference** above).

#### Build and run

From the **`salvai-be/`** directory on the VPS:

```bash
docker build -t salvai-be .
docker run -d --name salvai-be \
  -p 8000:8000 \
  -v salvai-enrich-cache:/data \
  --env-file .env \
  --restart unless-stopped \
  salvai-be
```

The volume **`salvai-enrich-cache:/data`** keeps the SQLite enrich cache across redeploys. Step-by-step (Coolify + manual Docker): **[`docs/enrich-cache-vps-setup.md`](enrich-cache-vps-setup.md)**.

Always include **`--restart unless-stopped`** when creating the container. Omitting it is a common mistake after redeploys and leaves crash recovery manual.

Optional: set **`WEB_CONCURRENCY`** in `.env` to tune worker count without rebuilding the image.

#### Crash resilience

Two layers keep the API available on the VPS:

1. **Inside the container** — production runs uvicorn with multiple workers (`WEB_CONCURRENCY`, default `2`). If one worker crashes, the parent respawns it while other workers keep serving traffic (including `/health`).
2. **Docker restart** — **`--restart unless-stopped`** restarts the container when the whole process exits (OOM, fatal error).

HTTP **500** responses from application errors do **not** stop the API; only a process or container exit causes downtime.

The Docker image includes a **`HEALTHCHECK`** against `/health` so `docker ps` shows `(healthy)` / `(unhealthy)` when you SSH in. It reads the same **`PORT`** env var as uvicorn (Coolify and similar platforms may inject `PORT`, e.g. `3000`). It does **not** replace `--restart unless-stopped` for crash recovery.

#### Redeploy after code changes

```bash
docker build -t salvai-be .
docker stop salvai-be && docker rm salvai-be
docker run -d --name salvai-be \
  -p 8000:8000 \
  -v salvai-enrich-cache:/data \
  --env-file .env \
  --restart unless-stopped \
  salvai-be
```

#### Verify after deploy

Health check path: `GET /health`

```bash
curl -sS https://api.apps.salvai.cloud/health
# → {"status":"ok"}

docker inspect salvai-be --format '{{.HostConfig.RestartPolicy.Name}}'
# → unless-stopped

docker ps
# → status should show (healthy) after ~10s
```

Optional (on the VPS): kill one worker PID inside the container and confirm `/health` still responds while uvicorn respawns the worker.

More endpoint and auth detail: [`salvai-be/README.md`](../salvai-be/README.md#deploying-on-hetzner-vps-docker).

---

## Smoke-only variable (not in `.env`)

| Variable | Where | Purpose |
|----------|--------|---------|
| **`SUPABASE_ACCESS_TOKEN`** | Shell only when running the smoke script | Short-lived **user** JWT (`access_token`) used as `Authorization: Bearer ...` to test authenticated routes. Do not store in `.env` or commit. |

---

## Related docs

- [`salvai-be/README.md`](../salvai-be/README.md) — endpoints, auth model, feed notes.
- [`docs/enrich-cache-vps-setup.md`](enrich-cache-vps-setup.md) — persistent SQLite enrich cache on the VPS (Coolify + Docker).
- [`docs/instagram-4-layer-rate-limiting.md`](instagram-4-layer-rate-limiting.md) — Instagram 4-layer retry across Hetzner + Locaweb (Coolify setup).
- [`supabase/README.md`](../supabase/README.md) — migrations and `db push`.
- [`docs/social-screens-and-endpoints.md`](social-screens-and-endpoints.md) — product/API mapping for the app.