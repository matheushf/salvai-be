import re

from postgrest.exceptions import APIError
from supabase import Client

from app.core.exceptions import ConflictError, NotFoundError, UpstreamError
from app.core.supabase import execute_supabase
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
    "country",
    "state",
    "city",
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
        onboarding_completed=bool(row.get("onboarding_completed")),
    )


def _is_username_unique_violation(exc: BaseException | None) -> bool:
    if not isinstance(exc, APIError):
        return False
    code = str(getattr(exc, "code", "") or "")
    if code != "23505":
        return False
    blob = " ".join(
        [
            str(exc),
            str(getattr(exc, "details", "") or ""),
            str(getattr(exc, "hint", "") or ""),
            str(getattr(exc, "message", "") or ""),
        ]
    ).lower()
    return "username" in blob


def _ensure_profile_row(
    client: Client,
    user_id: str,
    email: str | None,
) -> dict:
    normalized_email = _normalize_email(email)
    payload: dict = {"id": user_id}
    if normalized_email is not None:
        payload["email"] = normalized_email

    response = execute_supabase(
        client,
        lambda c: c.table(_TABLE).upsert(payload, on_conflict="id").execute(),
    )
    if not response.data:
        raise UpstreamError("Failed to ensure profile")
    return response.data[0]


def _sanitize_search_term(raw: str) -> str:
    stripped = raw.strip()
    if stripped.startswith("@"):
        stripped = stripped[1:].strip()
    cleaned = _ILIKE_SANITIZE.sub("", stripped).strip()
    return cleaned[:_MAX_SEARCH_LEN]


def _postgrest_quoted_ilike_pattern(term: str) -> str:
    escaped = term.replace("\\", "\\\\").replace('"', '\\"').replace(",", " ")
    return f'%{escaped}%'


def _profile_search_or_filter(term: str) -> str:
    pattern = _postgrest_quoted_ilike_pattern(term)
    return f'username.ilike."{pattern}",display_name.ilike."{pattern}"'


def get_my_profile(
    client: Client,
    user_id: str,
    email: str | None,
) -> ProfileMeResponse:
    response = execute_supabase(
        client,
        lambda c: c.table(_TABLE).select("*").eq("id", user_id).maybe_single().execute(),
    )
    if response is None or response.data is None:
        row = _ensure_profile_row(client, user_id, email)
        return _to_me(row)
    return _to_me(response.data)


def get_profile(client: Client, user_id: str) -> ProfileResponse:
    response = execute_supabase(
        client,
        lambda c: c.table(_TABLE).select("*").eq("id", user_id).maybe_single().execute(),
    )
    if response is None or response.data is None:
        raise NotFoundError("Profile", user_id)
    return _to_public(response.data)


def upsert_profile(client: Client, user_id: str, update: ProfileUpdate) -> ProfileMeResponse:
    payload = {"id": user_id, **update.model_dump(exclude_unset=True, mode="json")}
    try:
        response = execute_supabase(
            client,
            lambda c: c.table(_TABLE).upsert(payload, on_conflict="id").execute(),
        )
    except UpstreamError as exc:
        if _is_username_unique_violation(exc.__cause__):
            raise ConflictError("Username is already taken") from exc
        raise
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
    if term:
        or_filter = _profile_search_or_filter(term)
        response = execute_supabase(
            client,
            lambda c: c.table(_TABLE)
            .select("*")
            .neq("id", current_user_id)
            .or_(or_filter)
            .limit(limit)
            .execute(),
        )
    else:
        response = execute_supabase(
            client,
            lambda c: c.table(_TABLE)
            .select("*")
            .neq("id", current_user_id)
            .order("username", desc=False)
            .limit(limit)
            .execute(),
        )

    rows = response.data or []
    return [_to_public(row) for row in rows]
