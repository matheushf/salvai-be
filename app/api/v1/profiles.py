from fastapi import APIRouter

from app.core.auth import CurrentUser
from app.core.supabase import AdminClient
from app.schemas.event import ProfileUpcomingEventsResponse
from app.schemas.profile import (
    ProfileMeResponse,
    ProfileResponse,
    ProfileSearchResponse,
    ProfileUpdate,
)
from app.services import events_service as event_svc
from app.services import profiles as profile_svc

router = APIRouter(prefix="/profiles", tags=["profiles"])


@router.get(
    "/me",
    response_model=ProfileMeResponse,
    summary="Get the current user's profile",
)
def get_my_profile(current_user: CurrentUser, client: AdminClient) -> ProfileMeResponse:
    return profile_svc.get_my_profile(client, current_user.id, current_user.email)


@router.patch(
    "/me",
    response_model=ProfileMeResponse,
    summary="Create or update the current user's profile",
)
def update_my_profile(
    body: ProfileUpdate,
    current_user: CurrentUser,
    client: AdminClient,
) -> ProfileMeResponse:
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
    "/{user_id}/upcoming-events",
    response_model=ProfileUpcomingEventsResponse,
    summary="Upcoming moments on a user's profile",
    description=(
        "Returns up to two upcoming events for this profile. "
        "Authors see all their upcoming saved events; followers see feed-visible events only; "
        "non-followers receive an empty list."
    ),
)
def get_profile_upcoming_events(
    user_id: str,
    current_user: CurrentUser,
    client: AdminClient,
) -> ProfileUpcomingEventsResponse:
    return event_svc.list_profile_upcoming_events(client, user_id, current_user.id)


@router.get(
    "/{user_id}",
    response_model=ProfileResponse,
    summary="Get any user's public profile",
)
def get_profile(user_id: str, current_user: CurrentUser, client: AdminClient) -> ProfileResponse:
    return profile_svc.get_profile(client, user_id)
