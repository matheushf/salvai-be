import re

from supabase import Client

from app.core.exceptions import NotFoundError, UpstreamError
from app.schemas.profile import ProfileResponse, ProfileUpdate

_TABLE = "profiles"

_ILIKE_SANITIZE = re.compile(r"[^\w\s\-.]", re.UNICODE)
_MAX_SEARCH_LEN = 50
_MAX_SEARCH_RESULTS = 100


def _sanitize_search_term(raw: str) -> str:
    cleaned = _ILIKE_SANITIZE.sub("", raw).strip()
    return cleaned[:_MAX_SEARCH_LEN]


def get_profile(client: Client, user_id: str) -> ProfileResponse:
    response = client.table(_TABLE).select("*").eq("id", user_id).maybe_single().execute()
    if not response.data:
        raise NotFoundError("Profile", user_id)
    return ProfileResponse(**response.data)


def upsert_profile(client: Client, user_id: str, update: ProfileUpdate) -> ProfileResponse:
    payload = {"id": user_id, **update.model_dump(exclude_none=True)}
    response = (
        client.table(_TABLE)
        .upsert(payload, on_conflict="id")
        .execute()
    )
    if not response.data:
        raise UpstreamError("Failed to upsert profile")
    return ProfileResponse(**response.data[0])


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
    return [ProfileResponse(**row) for row in rows]
