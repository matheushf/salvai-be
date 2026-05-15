from fastapi import APIRouter

from app.core.auth import CurrentUser
from app.core.supabase import AdminClient
from app.schemas.profile import ProfileResponse, ProfileSearchResponse, ProfileUpdate
from app.services import profiles as profile_svc

router = APIRouter(prefix="/profiles", tags=["profiles"])


@router.get(
    "/me",
    response_model=ProfileResponse,
    summary="Get the current user's profile",
)
def get_my_profile(current_user: CurrentUser, client: AdminClient) -> ProfileResponse:
    return profile_svc.get_profile(client, current_user.id)


@router.patch(
    "/me",
    response_model=ProfileResponse,
    summary="Create or update the current user's profile",
)
def update_my_profile(
    body: ProfileUpdate,
    current_user: CurrentUser,
    client: AdminClient,
) -> ProfileResponse:
    return profile_svc.upsert_profile(client, current_user.id, body)


@router.get(
    "/search",
    response_model=ProfileSearchResponse,
    summary="Search public profiles by username or display name",
)
def search_public_profiles(
    current_user: CurrentUser,
    client: AdminClient,
    q: str | None = None,
    limit: int = 20,
) -> ProfileSearchResponse:
    items = profile_svc.search_profiles(client, current_user.id, q, limit)
    return ProfileSearchResponse(items=items, total=len(items))


@router.get(
    "/{user_id}",
    response_model=ProfileResponse,
    summary="Get any user's public profile",
)
def get_profile(user_id: str, current_user: CurrentUser, client: AdminClient) -> ProfileResponse:
    return profile_svc.get_profile(client, user_id)
