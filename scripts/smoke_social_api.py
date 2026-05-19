#!/usr/bin/env python3
"""Quick HTTP checks against a running salvai-be (profiles, events, feed).

Requires:
  - API running (e.g. `uv run uvicorn app.main:app --reload`)
  - Migrations applied to the Supabase project connected in `.env`
  - A valid Supabase user **access** JWT (same as the app uses)

Usage (from `salvai-be/`):

    export SUPABASE_ACCESS_TOKEN='<paste supabase auth access_token>'
    uv run python scripts/smoke_social_api.py

Optional:

    export SALVAI_API_BASE=http://127.0.0.1:8000   # default
"""

from __future__ import annotations

import json
import os
import sys
import uuid
import urllib.error
import urllib.request
from typing import Any


def _request(
    method: str,
    url: str,
    *,
    token: str | None,
    body: dict[str, Any] | None = None,
) -> tuple[int, bytes]:
    data = json.dumps(body).encode() if body is not None else None
    headers: dict[str, str] = {}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.getcode(), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except urllib.error.URLError as e:
        raise ConnectionError(str(e)) from e


def main() -> int:
    base = os.environ.get("SALVAI_API_BASE", "http://127.0.0.1:8000").rstrip("/")
    token = os.environ.get("SUPABASE_ACCESS_TOKEN", "").strip()

    try:
        code, body = _request("GET", f"{base}/health", token=None)
    except ConnectionError as e:
        print(f"Cannot reach {base}: {e}", file=sys.stderr)
        print("Start the API: uv run uvicorn app.main:app --reload", file=sys.stderr)
        return 1
    print(f"GET /health -> {code}")
    if code != 200:
        print(body.decode(errors="replace"), file=sys.stderr)
        return 1

    if not token:
        print("Set SUPABASE_ACCESS_TOKEN to exercise authenticated routes.")
        return 0

    handle = f"smoke_{uuid.uuid4().hex[:10]}"
    code, _ = _request(
        "PATCH",
        f"{base}/api/v1/profiles/me",
        token=token,
        body={
            "username": handle,
            "display_name": "Smoke Test",
            "bio": "smoke_social_api",
        },
    )
    print(f"PATCH /api/v1/profiles/me -> {code}")
    if code != 200:
        print(
            "If 502: check migrations (supabase db push) and service role key.",
            file=sys.stderr,
        )
        return 1

    code, b = _request("GET", f"{base}/api/v1/profiles/me", token=token)
    print(f"GET /api/v1/profiles/me -> {code}")
    if code != 200:
        print(b.decode(errors="replace"), file=sys.stderr)
        return 1
    my_profile = json.loads(b.decode())
    my_id = my_profile.get("id") if isinstance(my_profile, dict) else None

    code, b = _request(
        "POST",
        f"{base}/api/v1/events",
        token=token,
        body={
            "title": "Smoke event",
            "date": "15/06/2030",
            "location": "Test venue",
            "visible_in_feed": True,
            "category": "Music",
        },
    )
    print(f"POST /api/v1/events -> {code}")
    if code != 201:
        print(b.decode(errors="replace"), file=sys.stderr)
        return 1
    event_id = json.loads(b.decode())["id"]
    print(f"  event_id={event_id}")

    code, b = _request("GET", f"{base}/api/v1/events/me", token=token)
    print(f"GET /api/v1/events/me -> {code}")
    if code != 200:
        print(b.decode(errors="replace"), file=sys.stderr)
        return 1

    if my_id:
        code, b = _request("GET", f"{base}/api/v1/profiles/{my_id}/upcoming-events", token=token)
        print(f"GET /api/v1/profiles/{{user_id}}/upcoming-events -> {code}")
        if code != 200:
            print(b.decode(errors="replace"), file=sys.stderr)
            return 1

    code, b = _request(
        "PATCH",
        f"{base}/api/v1/events/{event_id}",
        token=token,
        body={"title": "Smoke event (patched)"},
    )
    print(f"PATCH /api/v1/events/{{id}} -> {code}")
    if code != 200:
        print(b.decode(errors="replace"), file=sys.stderr)
        return 1

    code, _ = _request("GET", f"{base}/api/v1/feed", token=token)
    print(f"GET /api/v1/feed -> {code}")

    code, _ = _request("DELETE", f"{base}/api/v1/events/{event_id}", token=token)
    print(f"DELETE /api/v1/events/{{id}} -> {code}")

    print("Smoke run finished.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
