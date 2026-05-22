import re

from supabase import Client

from app.core.exceptions import NotFoundError, UpstreamError
from app.schemas.profile import ProfileMeResponse, ProfileResponse, ProfileUpdate

_TABLE = "profiles"

_ILIKE_SANITIZE = re.compile(r"[^\w\s\-.]", re.UNICODE)
_MAX_SEARCH_LEN = 50
_MAX_SEARCH_RESULTS = 100

_PUBLIC_FIELDS = (
    "id",
    "username",
    "display_name",
    "avatar_url",
    "bio",
    "interests",
    "updated_at",
)


def _normalize_email(email: str | None) -> str | None:
    if not email:
        return None
    normalized = email.strip().lower()
    return normalized or None


def _to_public(row: dict) -> ProfileResponse:
    data = {field: row.get(field) for field in _PUBLIC_FIELDS}
    if data.get("interests") is None:
        data["interests"] = []
    return ProfileResponse(**data)


def _to_me(row: dict) -> ProfileMeResponse:
    return ProfileMeResponse(
        **_to_public(row).model_dump(),
        email=row.get("email"),
        birth_date=row.get("birth_date"),
    )


def _ensure_profile_row(
    client: Client,
    user_id: str,
    email: str | None,
) -> dict:
    normalized_email = _normalize_email(email)
    payload: dict = {"id": user_id}
    if normalized_email is not None:
        payload["email"] = normalized_email

    response = (
        client.table(_TABLE)
        .upsert(payload, on_conflict="id")
        .execute()
    )
    if not response.data:
        raise UpstreamError("Failed to ensure profile")
    return response.data[0]


def _sanitize_search_term(raw: str) -> str:
    cleaned = _ILIKE_SANITIZE.sub("", raw).strip()
    return cleaned[:_MAX_SEARCH_LEN]


def get_my_profile(
    client: Client,
    user_id: str,
    email: str | None,
) -> ProfileMeResponse:
    response = client.table(_TABLE).select("*").eq("id", user_id).maybe_single().execute()
    if response is None or response.data is None:
        row = _ensure_profile_row(client, user_id, email)
        return _to_me(row)
    return _to_me(response.data)


def get_profile(client: Client, user_id: str) -> ProfileResponse:
    response = client.table(_TABLE).select("*").eq("id", user_id).maybe_single().execute()
    if response is None or response.data is None:
        raise NotFoundError("Profile", user_id)
    return _to_public(response.data)


def upsert_profile(client: Client, user_id: str, update: ProfileUpdate) -> ProfileMeResponse:
    payload = {"id": user_id, **update.model_dump(exclude_none=True)}
    response = (
        client.table(_TABLE)
        .upsert(payload, on_conflict="id")
        .execute()
    )
    if not response.data:
        raise UpstreamError("Failed to upsert profile")
    return _to_me(response.data[0])


def search_profiles(
    client: Client,
    current_user_id: str,
    q: str | None,
    limit: int = 20,
) -> list[ProfileResponse]:
    limit = min(max(limit, 1), _MAX_SEARCH_RESULTS)
    term = _sanitize_search_term(q or "")
    base = client.table(_TABLE).select("*").neq("id", current_user_id)

    if term:
        pattern = f"%{term}%"
        response = (
            base.or_(f"username.ilike.{pattern},display_name.ilike.{pattern}")
            .limit(limit)
            .execute()
        )
    else:
        response = base.order("username", desc=False).limit(limit).execute()

    rows = response.data or []
    return [_to_public(row) for row in rows]
