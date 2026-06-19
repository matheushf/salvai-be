# salvai-be

Python backend built with FastAPI, managed with [uv](https://docs.astral.sh/uv/).

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) — install with `curl -LsSf https://astral.sh/uv/install.sh | sh`

## Setup

```bash
uv sync
# Create .env locally (gitignored) — see docs/salvai-be-setup-and-env.md
```

Environment variables (see [`docs/salvai-be-setup-and-env.md`](../docs/salvai-be-setup-and-env.md) for descriptions):

| Variable | Required |
|---|---|
| `SUPABASE_URL` | Yes |
| `SUPABASE_SERVICE_ROLE_KEY` | Yes |
| `SUPABASE_JWT_SECRET` | Yes |
| `CORS_ALLOWED_ORIGINS` | Yes |
| `SENTRY_DSN` | No (recommended in production) |
| `SENTRY_ENVIRONMENT` | No (defaults to `development`) |
| `ENRICH_CACHE_ENABLED` | No (defaults to `true`) |
| `ENRICH_CACHE_DB_PATH` | No (defaults to `./data/enrich_cache.db` locally; `/data/enrich_cache.db` in Docker) |
| `PORT` | No (defaults to 8000 in Docker) |

All three Supabase values are in your **Supabase Dashboard → Project Settings → API**.

## Error monitoring (Sentry)

Optional error reporting via [Sentry](https://sentry.io). Disabled locally when `SENTRY_DSN` is unset.

### Setup

1. Create a Sentry account and a **Python / FastAPI** project.
2. Copy the project **DSN** from **Settings → Client Keys (DSN)**.
3. In Sentry, add an alert rule (e.g. email on **new issue** or error spike).
4. Set variables on the production server (see [`docs/salvai-be-setup-and-env.md`](../docs/salvai-be-setup-and-env.md)):

| Variable | Example | Notes |
|----------|---------|-------|
| `SENTRY_DSN` | `https://…@…ingest.sentry.io/…` | Required to enable reporting |
| `SENTRY_ENVIRONMENT` | `production` | Separates prod from staging in Sentry |
| `SENTRY_RELEASE` | git commit SHA | Optional; helps track regressions by deploy |
| `SENTRY_TRACES_SAMPLE_RATE` | `0.0` | Keep at `0` on the free tier (errors only) |

5. Redeploy/restart the API container after updating `.env`.
6. In the Sentry project, use **Send a test event** or trigger a real 502 (upstream failure) to confirm events arrive. Expected 404/403 responses should **not** appear in Sentry.

## Running locally

```bash
uv run task dev
```

Or run uvicorn directly:

```bash
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

The API will be available at `http://localhost:8000`.

Interactive docs: `http://localhost:8000/docs`

## Running in production

```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
```

Or via Docker:

```bash
docker build -t salvai-be .
docker run -p 8000:8000 \
  -e SUPABASE_URL="..." \
  -e SUPABASE_SERVICE_ROLE_KEY="..." \
  -e SUPABASE_JWT_SECRET="..." \
  -e CORS_ALLOWED_ORIGINS="https://your-frontend.com" \
  salvai-be
```

## Deploying on Hetzner VPS (Docker)

Production runs on a self-hosted Hetzner VPS at `https://api.apps.salvai.cloud`. TLS is handled by a reverse proxy (Caddy or nginx) that forwards to the container on `localhost:8000`.

Build from the `salvai-be/` directory:

```bash
docker build -t salvai-be .
```

Run with an env file, persistent enrich cache volume, and restart policy:

```bash
docker run -d --name salvai-be \
  -p 8000:8000 \
  -v salvai-enrich-cache:/data \
  --env-file .env \
  --restart unless-stopped \
  salvai-be
```

The named volume `salvai-enrich-cache` stores the SQLite enrich cache at `/data/enrich_cache.db` so cached URLs survive container recreate. Without this volume, the cache is lost on every redeploy.

On the VPS, set all required environment variables (see table above). Include your production frontend origin in `CORS_ALLOWED_ORIGINS`. Set `SCRAPER_SERVICE_URL` to the production scraper host (see [`docs/salvai-be-setup-and-env.md`](../docs/salvai-be-setup-and-env.md)).

**Coolify:** mount persistent storage at container path `/data` for the same effect. Step-by-step: [`docs/enrich-cache-vps-setup.md`](../docs/enrich-cache-vps-setup.md).

Optional: set `WEB_CONCURRENCY` in `.env` to tune uvicorn worker count (default `2` in the Docker image).

### Crash resilience

Two layers keep the API available on the VPS:

1. **Inside the container** — production runs uvicorn with multiple workers (`WEB_CONCURRENCY`, default `2`). If one worker crashes, the parent respawns it while other workers keep serving traffic (including `/health`).
2. **Docker restart** — always use `--restart unless-stopped` when creating the container. If the whole process exits (OOM, fatal error), Docker starts a fresh container automatically.

HTTP 500 responses from application errors do **not** stop the API; only a process or container exit causes downtime.

The Docker image includes a `HEALTHCHECK` against `/health` so `docker ps` shows `(healthy)` / `(unhealthy)` when you SSH in. It reads the same `PORT` env var as uvicorn (Coolify and similar platforms may inject `PORT`, e.g. `3000`). It does not replace `--restart unless-stopped` for crash recovery.

Health check path: `GET /health`

Verify after deploy:

```bash
curl -sS https://api.apps.salvai.cloud/health
```

### Universal links on `salvai.cloud`

Event share links use `https://salvai.cloud/events/{eventId}`. The backend serves:

- `GET /.well-known/apple-app-site-association`
- `GET /.well-known/assetlinks.json`
- `GET /events/{eventId}` (HTML fallback when the app is not installed)

Point **`salvai.cloud`** at the same API container (or reverse-proxy these paths to it). Example Caddy snippet:

```caddy
salvai.cloud {
  reverse_proxy localhost:8000
}
```

Set on production `.env`:

| Variable | Purpose |
|---|---|
| `SHARE_BASE_URL` | Public share host (`https://salvai.cloud`) |
| `IOS_APP_TEAM_ID` | Apple Team ID for AASA |
| `ANDROID_SHA256_CERT_FINGERPRINTS` | Release keystore SHA-256 fingerprint(s) for Android App Links |
| `IOS_APP_STORE_URL` | App Store fallback from the HTML page |
| `ANDROID_PLAY_STORE_URL` | Play Store fallback from the HTML page |

Verify after deploy:

```bash
curl -sS https://salvai.cloud/.well-known/apple-app-site-association
curl -sS https://salvai.cloud/.well-known/assetlinks.json
curl -sS https://salvai.cloud/events/11111111-2222-4333-8444-555555555555 | head
```

Redeploy after code changes:

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

## Authentication

All social endpoints require a valid Supabase JWT in the `Authorization` header:

```
Authorization: Bearer <supabase_access_token>
```

The frontend obtains this token from `supabase.auth.getSession()` and passes it with every request. The backend validates the token locally using the `SUPABASE_JWT_SECRET` (no extra HTTP round-trip).

## Endpoints

### Health

```
GET /health
```

### Instagram (public)

```
GET /api/v1/instagram/post?identifier=<url_or_shortcode>
```

### Profiles (authenticated)

```
GET    /api/v1/profiles/me                      # current user's profile
PATCH  /api/v1/profiles/me                      # update current user's profile
GET    /api/v1/profiles/{user_id}/upcoming-events   # upcoming profile moments (≤2 for non-owners; owner gets all upcoming within cap for client merge)
GET    /api/v1/profiles/{user_id}               # any user's public profile
```

### Follows (authenticated)

```
GET    /api/v1/follows/me             # list users the current user follows
POST   /api/v1/follows/{user_id}      # follow a user → 201
DELETE /api/v1/follows/{user_id}      # unfollow a user → 204
```

### Events (authenticated)

```
POST   /api/v1/events                 # create an event → 201 (body may include `visible_in_feed`, default false)
GET    /api/v1/events/me             # list my events (optional `cursor`, `limit`) → newest first
PATCH  /api/v1/events/{event_id}     # update own event (partial body)
GET    /api/v1/events/{event_id}     # get one event (author or follows author + event is public on feed)
DELETE /api/v1/events/{event_id}      # delete own event → 204
```

Private events (`visible_in_feed: false`) are only visible to the author. The social feed lists only followed users’ events with `visible_in_feed: true`.

### Feed (authenticated)

```
GET /api/v1/feed?cursor=<iso_ts>&limit=<n>
```

Returns events from users the current user follows, newest first.
Cursor-based pagination: use `next_cursor` from the response as the `cursor` param on the next request.

## Feed performance

The v1 feed is computed on read: for each request it fetches the follow list and then queries events authored by those users. This is simple and correct for small to medium follow graphs.

**When to upgrade:** if you observe slow feed responses (> 200 ms p95) and the follow list is large (hundreds+), consider moving to a precomputed fan-out table:

1. Add a `feed_items (user_id, event_id, created_at)` table.
2. Populate it via a Postgres trigger on `events` insert that inserts one row per follower.
3. Replace the `feed_service.py` query to hit this denormalized table directly.

## Project structure

```
app/
├── main.py
├── sentry_config.py     # optional Sentry init + noise filters
├── core/
│   ├── config.py          # pydantic-settings: SUPABASE_*, CORS
│   ├── supabase.py        # admin client (service_role, cached)
│   └── auth.py            # get_current_user dependency + CurrentUser type
├── api/
│   └── v1/
│       ├── __init__.py    # aggregates all v1 routers
│       ├── instagram.py   # GET /api/v1/instagram/post
│       ├── profiles.py    # /api/v1/profiles/*
│       ├── follows.py     # /api/v1/follows/*
│       ├── events.py      # /api/v1/events/*
│       └── feed.py        # /api/v1/feed
├── schemas/
│   ├── user.py            # AuthenticatedUser
│   ├── profile.py         # ProfileResponse, ProfileUpdate
│   ├── follow.py          # FollowResponse, FollowingListResponse
│   ├── event.py           # EventCreate, EventUpdate, EventResponse, EventListPage, ProfileUpcomingEventsResponse
│   ├── feed.py            # FeedItem, FeedPage
│   └── instagram.py       # PostMetadataResponse
└── services/
    ├── profiles.py        # get_profile, get_my_profile, upsert_profile
    ├── follows.py         # follow_user, unfollow_user, list_following
    ├── events_service.py  # create_event, get_event, delete_event
    ├── feed_service.py    # get_feed (read-time aggregation)
    └── instagram_scraper.py
```

## Database

Full local setup, every `.env` variable, and smoke-test details: **[`docs/salvai-be-setup-and-env.md`](../docs/salvai-be-setup-and-env.md)**.

Schema migrations live in [`../supabase/migrations/`](../supabase/migrations/) (repo root). See **[`../supabase/README.md`](../supabase/README.md)** for applying them (`supabase link`, `supabase db push`, or SQL Editor).

### Verify environment

After creating `.env`, confirm required variables load (nothing secret is printed in full):

```bash
uv run python scripts/verify_env.py
```

### Smoke test (API + database)

With the API running and migrations applied, exercise authenticated routes using a Supabase user **access token** (same JWT the frontend sends):

```bash
export SUPABASE_ACCESS_TOKEN='<access_token from supabase.auth.getSession()>'
uv run python scripts/smoke_social_api.py
```

Optional: `SALVAI_API_BASE=http://127.0.0.1:8000` if the server is not on the default host/port.
