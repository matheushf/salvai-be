# salvai-be

Python backend built with FastAPI, managed with [uv](https://docs.astral.sh/uv/).

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) — install with `curl -LsSf https://astral.sh/uv/install.sh | sh`

## Setup

```bash
uv sync
cp .env.example .env   # fill in your Supabase credentials
```

Environment variables (see `.env.example` for descriptions):

| Variable | Required |
|---|---|
| `SUPABASE_URL` | Yes |
| `SUPABASE_SERVICE_ROLE_KEY` | Yes |
| `SUPABASE_JWT_SECRET` | Yes |
| `CORS_ALLOWED_ORIGINS` | Yes |
| `PORT` | Auto (Railway injects this) |

All three Supabase values are in your **Supabase Dashboard → Project Settings → API**.

## Running locally

```bash
uv run uvicorn app.main:app --reload
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

## Deploying on Railway

1. Create a new Railway service pointing to this repository.
2. Set **Root Directory** to `salvai-be` in the Railway service settings.
3. Railway will automatically detect and use the `Dockerfile`.
4. Set environment variables in the Railway dashboard (see table above).
5. Set the healthcheck path to `/health`.

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

After `cp .env.example .env`, confirm required variables load (nothing secret is printed in full):

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
