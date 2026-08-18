from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from postgrest.exceptions import APIError
from supabase import Client

from app.core.exceptions import DomainValidationError, UpstreamError
from app.core.supabase import execute_supabase
from app.schemas.device import PushTokenResponse, PushTokenUpsert

_TABLE = "device_push_tokens"
_PROFILES_TABLE = "profiles"

DEFAULT_TIMEZONE = "America/Sao_Paulo"


def resolve_timezone_name(name: str | None) -> str:
    candidate = (name or "").strip() or DEFAULT_TIMEZONE
    try:
        ZoneInfo(candidate)
    except ZoneInfoNotFoundError as exc:
        raise DomainValidationError(f"Unknown timezone: {candidate}") from exc
    return candidate


def _to_response(row: dict) -> PushTokenResponse:
    return PushTokenResponse(
        id=row["id"],
        user_id=row["user_id"],
        expo_push_token=row["expo_push_token"],
        platform=row["platform"],
        created_at=row["created_at"],
        last_seen_at=row["last_seen_at"],
    )


def _update_profile_timezone(client: Client, user_id: str, tz_name: str) -> None:
    execute_supabase(
        client,
        lambda c: c.table(_PROFILES_TABLE)
        .update({"timezone": tz_name})
        .eq("id", user_id)
        .execute(),
    )


def upsert_push_token(
    client: Client,
    user_id: str,
    body: PushTokenUpsert,
) -> PushTokenResponse:
    token = body.expo_push_token.strip()
    if not token:
        raise DomainValidationError("expo_push_token is required")

    now = datetime.now(timezone.utc).isoformat()
    tz_name = resolve_timezone_name(body.timezone) if body.timezone else None
    if tz_name:
        _update_profile_timezone(client, user_id, tz_name)

    try:
        existing = execute_supabase(
            client,
            lambda c: c.table(_TABLE)
            .select("*")
            .eq("expo_push_token", token)
            .maybe_single()
            .execute(),
        )
    except APIError:
        existing = None

    if existing is not None and existing.data is not None:
        response = execute_supabase(
            client,
            lambda c: c.table(_TABLE)
            .update(
                {
                    "user_id": user_id,
                    "platform": body.platform,
                    "last_seen_at": now,
                }
            )
            .eq("id", existing.data["id"])
            .execute(),
        )
        if not response.data:
            raise UpstreamError("Failed to update push token")
        return _to_response(response.data[0])

    response = execute_supabase(
        client,
        lambda c: c.table(_TABLE)
        .insert(
            {
                "user_id": user_id,
                "expo_push_token": token,
                "platform": body.platform,
                "created_at": now,
                "last_seen_at": now,
            }
        )
        .execute(),
    )
    if not response.data:
        raise UpstreamError("Failed to store push token")
    return _to_response(response.data[0])


def delete_push_token(client: Client, user_id: str, expo_push_token: str) -> None:
    token = expo_push_token.strip()
    if not token:
        raise DomainValidationError("expo_push_token is required")

    execute_supabase(
        client,
        lambda c: c.table(_TABLE)
        .delete()
        .eq("user_id", user_id)
        .eq("expo_push_token", token)
        .execute(),
    )
