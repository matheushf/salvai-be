from supabase import Client

from app.core.exceptions import ConflictError, DomainValidationError, NotFoundError, UpstreamError
from app.schemas.follow import FollowResponse, FollowingListResponse

_TABLE = "follows"


def follow_user(client: Client, follower_id: str, followed_id: str) -> FollowResponse:
    if follower_id == followed_id:
        raise DomainValidationError("Cannot follow yourself")

    existing = (
        client.table(_TABLE)
        .select("follower_id")
        .eq("follower_id", follower_id)
        .eq("followed_id", followed_id)
        .maybe_single()
        .execute()
    )
    if existing is not None:
        raise ConflictError("Already following this user")

    response = (
        client.table(_TABLE)
        .insert({"follower_id": follower_id, "followed_id": followed_id})
        .execute()
    )
    if not response.data:
        raise UpstreamError("Failed to create follow relationship")
    return FollowResponse(**response.data[0])


def unfollow_user(client: Client, follower_id: str, followed_id: str) -> None:
    response = (
        client.table(_TABLE)
        .delete()
        .eq("follower_id", follower_id)
        .eq("followed_id", followed_id)
        .execute()
    )
    if not response.data:
        raise NotFoundError("Follow relationship")


def list_following(client: Client, user_id: str) -> FollowingListResponse:
    response = (
        client.table(_TABLE)
        .select("*")
        .eq("follower_id", user_id)
        .order("created_at", desc=True)
        .execute()
    )
    items = [FollowResponse(**row) for row in (response.data or [])]
    return FollowingListResponse(items=items, total=len(items))


def list_followers(client: Client, user_id: str) -> FollowingListResponse:
    response = (
        client.table(_TABLE)
        .select("*")
        .eq("followed_id", user_id)
        .order("created_at", desc=True)
        .execute()
    )
    items = [FollowResponse(**row) for row in (response.data or [])]
    return FollowingListResponse(items=items, total=len(items))
