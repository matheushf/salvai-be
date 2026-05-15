from supabase import Client

from app.core.exceptions import ForbiddenError, NotFoundError, UpstreamError
from app.schemas.event import EventCreate, EventResponse

_TABLE = "events"
_FOLLOWS_TABLE = "follows"


def create_event(client: Client, author_id: str, data: EventCreate) -> EventResponse:
    payload = {"author_id": author_id, **data.model_dump(exclude_none=True)}
    response = client.table(_TABLE).insert(payload).execute()
    if not response.data:
        raise UpstreamError("Failed to create event")
    return EventResponse(**response.data[0])


def get_event(client: Client, event_id: str, requester_id: str) -> EventResponse:
    """
    Return the event if the requester is the author or follows the author.
    Raises NotFoundError if it does not exist, ForbiddenError if not visible.
    """
    event_resp = client.table(_TABLE).select("*").eq("id", event_id).maybe_single().execute()
    if not event_resp.data:
        raise NotFoundError("Event", event_id)

    event_data = event_resp.data
    author_id: str = event_data["author_id"]

    if author_id == requester_id:
        return EventResponse(**event_data)

    follow_resp = (
        client.table(_FOLLOWS_TABLE)
        .select("follower_id")
        .eq("follower_id", requester_id)
        .eq("followed_id", author_id)
        .maybe_single()
        .execute()
    )
    if not follow_resp.data:
        raise ForbiddenError("You can only view events from users you follow")

    return EventResponse(**event_data)


def delete_event(client: Client, event_id: str, user_id: str) -> None:
    existing = (
        client.table(_TABLE)
        .select("author_id")
        .eq("id", event_id)
        .maybe_single()
        .execute()
    )
    if not existing.data:
        raise NotFoundError("Event", event_id)
    if existing.data["author_id"] != user_id:
        raise ForbiddenError("You can only delete your own events")

    client.table(_TABLE).delete().eq("id", event_id).execute()
