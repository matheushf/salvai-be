"""
Feed service — read-time aggregation (v1).

Strategy: fetch the list of users the requester follows, then query events
authored by those users ordered by created_at DESC. Pagination is cursor-based
using the event's created_at timestamp so the results stay stable as new events
are inserted.

When the number of followers or events grows significantly, consider moving to a
precomputed fan-out feed table populated by a Postgres trigger or background job.
"""

from datetime import datetime

from supabase import Client

from app.core.supabase import execute_supabase
from app.schemas.event import EventResponse
from app.schemas.feed import FeedItem, FeedPage
from app.schemas.profile import ProfileResponse

_FOLLOWS_TABLE = "follows"
_EVENTS_TABLE = "events"
_PROFILES_TABLE = "profiles"

_DEFAULT_LIMIT = 20
_MAX_LIMIT = 100


def get_feed(
    client: Client,
    user_id: str,
    cursor: str | None = None,
    limit: int = _DEFAULT_LIMIT,
) -> FeedPage:
    limit = min(limit, _MAX_LIMIT)

    follows_resp = execute_supabase(
        client,
        lambda c: c.table(_FOLLOWS_TABLE)
        .select("followed_id")
        .eq("follower_id", user_id)
        .execute(),
    )
    followed_ids = [row["followed_id"] for row in (follows_resp.data or [])]

    if not followed_ids:
        return FeedPage(items=[], next_cursor=None, has_more=False)

    events_resp = execute_supabase(
        client,
        lambda c: _events_query(c, followed_ids, cursor, limit).execute(),
    )
    rows = events_resp.data or []

    has_more = len(rows) > limit
    if has_more:
        rows = rows[:limit]

    if not rows:
        return FeedPage(items=[], next_cursor=None, has_more=False)

    author_ids = list({row["author_id"] for row in rows})
    profiles_resp = execute_supabase(
        client,
        lambda c: c.table(_PROFILES_TABLE).select("*").in_("id", author_ids).execute(),
    )
    profile_by_id: dict[str, ProfileResponse] = {}
    for row in profiles_resp.data or []:
        interests = row.get("interests")
        if interests is None:
            row = {**row, "interests": []}
        profile_by_id[row["id"]] = ProfileResponse(**row)

    items: list[FeedItem] = []
    for row in rows:
        author = profile_by_id.get(row["author_id"])
        if author is None:
            continue
        items.append(FeedItem(event=EventResponse(**row), author=author))

    next_cursor: str | None = None
    if has_more and items:
        last_created_at: datetime | str = items[-1].event.created_at
        if isinstance(last_created_at, datetime):
            next_cursor = last_created_at.isoformat()
        else:
            next_cursor = str(last_created_at)

    return FeedPage(items=items, next_cursor=next_cursor, has_more=has_more)


def _events_query(client: Client, followed_ids: list[str], cursor: str | None, limit: int):
    query = (
        client.table(_EVENTS_TABLE)
        .select("*")
        .in_("author_id", followed_ids)
        .eq("visible_in_feed", True)
        .order("created_at", desc=True)
        .limit(limit + 1)
    )
    if cursor:
        query = query.lt("created_at", cursor)
    return query
