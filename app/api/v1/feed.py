from fastapi import APIRouter, Query

from app.core.auth import CurrentUser
from app.core.supabase import AdminClient
from app.schemas.feed import FeedPage
from app.services import feed_service as feed_svc

router = APIRouter(prefix="/feed", tags=["feed"])


@router.get(
    "",
    response_model=FeedPage,
    summary="Get the current user's feed (events from followed users)",
    description=(
        "Returns a paginated list of events from users the current user follows, "
        "ordered by newest first. Use `cursor` (ISO-8601 timestamp from `next_cursor`) "
        "to fetch the next page."
    ),
)
def get_feed(
    current_user: CurrentUser,
    client: AdminClient,
    cursor: str | None = Query(default=None, description="Pagination cursor (ISO-8601 timestamp)"),
    limit: int = Query(default=20, ge=1, le=100, description="Number of items per page"),
    include_past: bool = Query(default=False, description="Include events with a past date"),
) -> FeedPage:
    return feed_svc.get_feed(client, current_user.id, cursor=cursor, limit=limit, include_past=include_past)
