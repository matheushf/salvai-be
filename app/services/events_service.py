from datetime import date, datetime, timezone

from supabase import Client

from app.core.exceptions import DomainValidationError, ForbiddenError, NotFoundError, UpstreamError
from app.core.supabase import execute_supabase
from app.schemas.event import (
    EventCreate,
    EventListPage,
    EventResponse,
    EventUpdate,
    ProfileUpcomingEventsResponse,
)

_TABLE = "events"
_FOLLOWS_TABLE = "follows"

_DEFAULT_LIMIT = 20
_MAX_LIMIT = 100
_PROFILE_UPCOMING_FETCH_CAP = 100
_PROFILE_UPCOMING_MAX_ITEMS = 2


def _parse_dmy_date(value: str) -> date | None:
    """Parse app date string dd/mm/yyyy to a calendar date (UTC-naive)."""
    parts = value.strip().split("/")
    if len(parts) != 3:
        return None
    try:
        dd, mm, yyyy = int(parts[0]), int(parts[1]), int(parts[2])
        return date(yyyy, mm, dd)
    except (ValueError, TypeError):
        return None


def _viewer_follows_author(client: Client, viewer_id: str, author_id: str) -> bool:
    follow_resp = execute_supabase(
        client,
        lambda c: c.table(_FOLLOWS_TABLE)
        .select("follower_id")
        .eq("follower_id", viewer_id)
        .eq("followed_id", author_id)
        .maybe_single()
        .execute(),
    )
    return follow_resp is not None


def create_event(client: Client, author_id: str, data: EventCreate) -> EventResponse:
    payload = {"author_id": author_id, **data.model_dump(exclude_none=True)}
    response = execute_supabase(
        client,
        lambda c: c.table(_TABLE).insert(payload).execute(),
    )
    if not response.data:
        raise UpstreamError("Failed to create event")
    return EventResponse(**response.data[0])


def list_my_events(
    client: Client,
    user_id: str,
    cursor: str | None = None,
    limit: int = _DEFAULT_LIMIT,
) -> EventListPage:
    limit = min(limit, _MAX_LIMIT)

    resp = execute_supabase(
        client,
        lambda c: _my_events_query(c, user_id, cursor, limit).execute(),
    )
    rows = resp.data or []

    has_more = len(rows) > limit
    if has_more:
        rows = rows[:limit]

    items = [EventResponse(**row) for row in rows]
    next_cursor: str | None = None
    if has_more and items:
        last_created_at: datetime | str = items[-1].created_at
        next_cursor = last_created_at.isoformat() if isinstance(last_created_at, datetime) else str(last_created_at)

    return EventListPage(items=items, next_cursor=next_cursor, has_more=has_more)


def _my_events_query(client: Client, user_id: str, cursor: str | None, limit: int):
    query = (
        client.table(_TABLE)
        .select("*")
        .eq("author_id", user_id)
        .order("created_at", desc=True)
        .limit(limit + 1)
    )
    if cursor:
        query = query.lt("created_at", cursor)
    return query


def list_profile_upcoming_events(
    client: Client,
    profile_user_id: str,
    viewer_id: str,
    *,
    limit: int = _PROFILE_UPCOMING_MAX_ITEMS,
) -> ProfileUpcomingEventsResponse:
    """
    Upcoming events for a profile surface (chronological, capped).

    - Author sees all their DB events that are still upcoming.
    - A follower sees at most ``limit`` upcoming events with visible_in_feed=True.
    - Non-followers (viewing someone else) get an empty list.
    """
    cap = min(max(limit, 1), _PROFILE_UPCOMING_MAX_ITEMS)

    if profile_user_id != viewer_id:
        if not _viewer_follows_author(client, viewer_id, profile_user_id):
            return ProfileUpcomingEventsResponse(items=[])

        resp = execute_supabase(
            client,
            lambda c: c.table(_TABLE)
            .select("*")
            .eq("author_id", profile_user_id)
            .eq("visible_in_feed", True)
            .limit(_PROFILE_UPCOMING_FETCH_CAP)
            .execute(),
        )
    else:
        resp = execute_supabase(
            client,
            lambda c: c.table(_TABLE)
            .select("*")
            .eq("author_id", profile_user_id)
            .limit(_PROFILE_UPCOMING_FETCH_CAP)
            .execute(),
        )

    rows = resp.data or []

    today = datetime.now(timezone.utc).date()

    parsed: list[tuple[EventResponse, date]] = []
    for row in rows:
        raw_date = row.get("date")
        if not raw_date or not isinstance(raw_date, str):
            continue
        event_day = _parse_dmy_date(raw_date)
        if event_day is None or event_day < today:
            continue
        parsed.append((EventResponse(**row), event_day))

    parsed.sort(key=lambda pair: (pair[1], pair[0].created_at))
    if profile_user_id == viewer_id:
        items = [pair[0] for pair in parsed]
    else:
        items = [pair[0] for pair in parsed[:cap]]
    return ProfileUpcomingEventsResponse(items=items)


def get_event(client: Client, event_id: str, requester_id: str) -> EventResponse:
    """
    Return the event if the requester is the author or follows the author
    on a publicly visible feed event.

    Raises NotFoundError if it does not exist, ForbiddenError if not visible.
    """
    event_resp = execute_supabase(
        client,
        lambda c: c.table(_TABLE).select("*").eq("id", event_id).maybe_single().execute(),
    )
    if event_resp is None:
        raise NotFoundError("Event", event_id)

    event_data = event_resp.data
    author_id: str = event_data["author_id"]

    if author_id == requester_id:
        return EventResponse(**event_data)

    if not event_data.get("visible_in_feed"):
        raise ForbiddenError("This event is private")

    follow_resp = execute_supabase(
        client,
        lambda c: c.table(_FOLLOWS_TABLE)
        .select("follower_id")
        .eq("follower_id", requester_id)
        .eq("followed_id", author_id)
        .maybe_single()
        .execute(),
    )
    if follow_resp is None:
        raise ForbiddenError("You can only view events from users you follow")

    return EventResponse(**event_data)


def update_event(client: Client, event_id: str, user_id: str, body: EventUpdate) -> EventResponse:
    patch = body.model_dump(exclude_unset=True)
    if not patch:
        raise DomainValidationError("No fields to update")

    existing = execute_supabase(
        client,
        lambda c: c.table(_TABLE).select("author_id").eq("id", event_id).maybe_single().execute(),
    )
    if existing is None:
        raise NotFoundError("Event", event_id)
    if existing.data["author_id"] != user_id:
        raise ForbiddenError("You can only update your own events")

    response = execute_supabase(
        client,
        lambda c: c.table(_TABLE)
        .update(patch)
        .eq("id", event_id)
        .eq("author_id", user_id)
        .select("*")
        .execute(),
    )
    if not response.data:
        raise UpstreamError("Failed to update event")
    return EventResponse(**response.data[0])


def delete_event(client: Client, event_id: str, user_id: str) -> None:
    existing = execute_supabase(
        client,
        lambda c: c.table(_TABLE).select("author_id").eq("id", event_id).maybe_single().execute(),
    )
    if existing is None:
        raise NotFoundError("Event", event_id)
    if existing.data["author_id"] != user_id:
        raise ForbiddenError("You can only delete your own events")

    execute_supabase(
        client,
        lambda c: c.table(_TABLE).delete().eq("id", event_id).execute(),
    )
