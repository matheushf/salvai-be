#!/usr/bin/env python3
"""Load salvai-be settings from `.env` and print a non-secret sanity check.

Run from `salvai-be/`:

    uv run python scripts/verify_env.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pydantic import ValidationError

from app.core.config import get_settings


def _mask(value: str, keep: int = 4) -> str:
    if len(value) <= keep * 2:
        return "***"
    return f"{value[:keep]}…{value[-keep:]}"


def main() -> int:
    try:
        s = get_settings()
    except ValidationError:
        print(
            "Missing or invalid environment variables. From salvai-be/: create .env "
            "and fill SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, SUPABASE_JWT_SECRET, "
            "CORS_ALLOWED_ORIGINS.",
            file=sys.stderr,
        )
        return 1
    if not s.supabase_url.startswith("http"):
        print("SUPABASE_URL must start with http(s)", file=sys.stderr)
        return 1
    if len(s.supabase_service_role_key.strip()) < 20:
        print("SUPABASE_SERVICE_ROLE_KEY looks too short", file=sys.stderr)
        return 1
    if len(s.supabase_jwt_secret.strip()) < 20:
        print("SUPABASE_JWT_SECRET looks too short", file=sys.stderr)
        return 1
    print("OK: settings load from environment / .env")
    print(f"  SUPABASE_URL={s.supabase_url}")
    print(f"  SUPABASE_SERVICE_ROLE_KEY={_mask(s.supabase_service_role_key)}")
    print(f"  SUPABASE_JWT_SECRET={_mask(s.supabase_jwt_secret)}")
    print(f"  Expected JWT iss (Supabase access tokens): {s.supabase_jwt_issuer}")
    print(f"  CORS_ALLOWED_ORIGINS={s.cors_allowed_origins!r} -> {s.allowed_origins}")
    chocodata_key = s.choco_data_api_key.strip()
    print(f"  INSTAGRAM_CHOCODATA_ENABLED={s.instagram_chocodata_enabled}")
    print(
        f"  CHOCO_DATA_API_KEY={_mask(chocodata_key) if chocodata_key else '(empty)'}"
    )
    groq_key = s.groq_api_key.strip()
    print(f"  GROQ_API_KEY={_mask(groq_key) if groq_key else '(empty)'}")
    print(f"  GROQ_MODEL={s.groq_model}")
    internal_key = s.internal_notifications_key.strip()
    print(
        f"  INTERNAL_NOTIFICATIONS_KEY={_mask(internal_key) if internal_key else '(empty)'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
