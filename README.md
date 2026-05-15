# salvai-be

Small Python backend built with FastAPI, managed with [uv](https://docs.astral.sh/uv/).

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) — install with `curl -LsSf https://astral.sh/uv/install.sh | sh`

## Setup

```bash
uv sync
```

## Running locally

```bash
uv run uvicorn app.main:app --reload
```

The API will be available at `http://localhost:8000`.

Interactive docs: `http://localhost:8000/docs`

## Endpoints

### Health

```
GET /health
```

Returns `{"status": "ok"}`.

### Instagram post / reel metadata

```
GET /api/v1/instagram/post?identifier=<url_or_shortcode>
```

Returns normalized metadata for a single public Instagram post or reel. No media is downloaded.

Accepts either a full URL or a bare shortcode:

| Parameter | Type | Description |
|-----------|------|-------------|
| `identifier` | query (required) | Full post/reel URL or shortcode |

**Example requests:**

```bash
# by shortcode
curl "http://localhost:8000/api/v1/instagram/post?identifier=ABC123"

# by URL
curl "http://localhost:8000/api/v1/instagram/post?identifier=https://www.instagram.com/p/ABC123/"

# reel URL
curl "http://localhost:8000/api/v1/instagram/post?identifier=https://www.instagram.com/reel/ABC123/"
```

**Example response:**

```json
{
  "platform": "instagram",
  "kind": "image",
  "description": "Caption text...",
  "thumbnailUrl": "https://...",
  "authorHandle": "nasa",
  "publishedAt": "2026-05-14T12:00:00+00:00"
}
```

**Error responses:**

| Status | Reason |
|--------|--------|
| `404` | Post does not exist |
| `403` | Post is from a private account or requires login |
| `429` | Instagram rate limit reached |
| `502` | Upstream connection or scraper error |

## Project structure

```
app/
├── main.py              # FastAPI app entrypoint
├── api/
│   └── v1/
│       ├── __init__.py  # v1 router aggregation
│       └── instagram.py # GET /api/v1/instagram/post
├── schemas/
│   └── instagram.py     # PostMetadataResponse, PostLocation
└── services/
    └── instagram_scraper.py  # shortcode_from_identifier + get_post_metadata
```

> **Note:** Instaloader fetches publicly available data only. For private profiles, Instagram authentication would be required. Be mindful of Instagram rate limits when making frequent requests.
