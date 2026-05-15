from fastapi import APIRouter, Response, status

from app.core.auth import CurrentUser
from app.core.supabase import AdminClient
from app.schemas.follow import FollowResponse, FollowingListResponse
from app.services import follows as follow_svc

router = APIRouter(prefix="/follows", tags=["follows"])


@router.get(
    "/me",
    response_model=FollowingListResponse,
    summary="List users the current user follows",
)
def list_my_following(current_user: CurrentUser, client: AdminClient) -> FollowingListResponse:
    return follow_svc.list_following(client, current_user.id)


@router.post(
    "/{user_id}",
    response_model=FollowResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Follow a user",
)
def follow_user(user_id: str, current_user: CurrentUser, client: AdminClient) -> FollowResponse:
    return follow_svc.follow_user(client, current_user.id, user_id)


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Unfollow a user",
)
def unfollow_user(user_id: str, current_user: CurrentUser, client: AdminClient) -> Response:
    follow_svc.unfollow_user(client, current_user.id, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
