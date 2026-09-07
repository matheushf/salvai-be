"""
Feed service — read-time aggregation (v1).

Strategy: fetch the list of users the requester follows, then query events
authored by those users ordered by created_at DESC. Pagination is cursor-based
using the event's created_at timestamp so the results stay stable as new events
are inserted.

Upcoming filtering parses ``date`` / ``end_date`` as dd/mm/yyyy (app format) or
ISO yyyy-mm-dd. Do not compare those text columns to ``date.today().isoformat()``.

When the number of followers or events grows significantly, consider moving to a
precomputed fan-out feed table populated by a Postgres trigger or background job.
"""

from datetime import datetime

from supabase import Client

from app.core.supabase import execute_supabase
from app.schemas.event import EventResponse
from app.schemas.feed import FeedItem, FeedPage
from app.schemas.profile import ProfileResponse
from app.services import events_service as event_svc

_FOLLOWS_TABLE = "follows"
_EVENTS_TABLE = "events"
_PROFILES_TABLE = "profiles"

_DEFAULT_LIMIT = 20
_MAX_LIMIT = 100
_UPCOMING_FETCH_BATCH = 50


def get_feed(
    client: Client,
    user_id: str,
    cursor: str | None = None,
    limit: int = _DEFAULT_LIMIT,
    include_past: bool = False,
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

    rows = _collect_feed_event_rows(
        client,
        followed_ids,
        cursor=cursor,
        limit=limit,
        include_past=include_past,
    )

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


def _collect_feed_event_rows(
    client: Client,
    followed_ids: list[str],
    *,
    cursor: str | None,
    limit: int,
    include_past: bool,
) -> list[dict]:
    if include_past:
        events_resp = execute_supabase(
            client,
            lambda c: _events_query(c, followed_ids, cursor, limit + 1).execute(),
        )
        return list(events_resp.data or []) if events_resp is not None else []

    today = event_svc._utc_today()
    collected: list[dict] = []
    page_cursor = cursor

    while len(collected) <= limit:
        events_resp = execute_supabase(
            client,
            lambda c, pc=page_cursor: _events_query(
                c, followed_ids, pc, _UPCOMING_FETCH_BATCH
            ).execute(),
        )
        page = list(events_resp.data or []) if events_resp is not None else []
        if not page:
            break

        for row in page:
            if event_svc._upcoming_sort_day(row, today) is None:
                continue
            collected.append(row)
            if len(collected) > limit:
                break

        if len(collected) > limit:
            break
        if len(page) < _UPCOMING_FETCH_BATCH:
            break
        page_cursor = _row_created_at(page[-1])
        if page_cursor is None:
            break

    return collected


def _row_created_at(row: dict) -> str | None:
    value = row.get("created_at")
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _events_query(
    client: Client,
    followed_ids: list[str],
    cursor: str | None,
    fetch_limit: int,
):
    query = (
        client.table(_EVENTS_TABLE)
        .select("*")
        .in_("author_id", followed_ids)
        .eq("visible_in_feed", True)
        .order("created_at", desc=True)
        .limit(fetch_limit)
    )
    if cursor:
        query = query.lt("created_at", cursor)
    return query
