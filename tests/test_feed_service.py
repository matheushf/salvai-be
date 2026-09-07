"""Friends feed upcoming filter (dd/mm/yyyy vs ISO string compare)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

from app.services import events_service as event_svc
from app.services import feed_service as feed_svc

VIEWER = "00000000-0000-4000-8000-000000000001"
AUTHOR = "00000000-0000-4000-8000-000000000002"
_TODAY = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)
_CREATED = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)


def _event_row(
    event_id: str,
    *,
    date: str,
    end_date: str | None = None,
    created_at: str | None = None,
) -> dict:
    return {
        "id": event_id,
        "author_id": AUTHOR,
        "title": event_id,
        "date": date,
        "end_date": end_date,
        "time": None,
        "end_time": None,
        "location": None,
        "image": None,
        "source_url": None,
        "category": None,
        "description": None,
        "link": None,
        "visible_in_feed": True,
        "notification_reminder": None,
        "created_at": created_at or _CREATED.isoformat(),
    }


def test_upcoming_dmy_is_kept_unlike_iso_text_compare() -> None:
    today = _TODAY.date()
    iso_today = today.isoformat()
    dmy_future = "11/10/2026"

    assert dmy_future < iso_today
    assert event_svc._upcoming_sort_day(_event_row("e1", date=dmy_future), today) is not None
    assert event_svc._upcoming_sort_day(_event_row("e2", date="01/01/2026"), today) is None


def test_collect_feed_skips_past_dmy_keeps_upcoming(monkeypatch) -> None:
    monkeypatch.setattr(event_svc, "_utc_today", lambda: _TODAY.date())

    past = _event_row("past", date="01/08/2026", created_at="2026-09-02T12:00:00+00:00")
    upcoming = _event_row("soon", date="11/10/2026", created_at="2026-09-01T12:00:00+00:00")

    events_exec = MagicMock()
    events_exec.execute.return_value = MagicMock(data=[past, upcoming])

    events_table = MagicMock()
    events_table.select.return_value.in_.return_value.eq.return_value.order.return_value.limit.return_value = (
        events_exec
    )

    client = MagicMock()
    client.table.return_value = events_table

    rows = feed_svc._collect_feed_event_rows(
        client,
        [AUTHOR],
        cursor=None,
        limit=20,
        include_past=False,
    )

    assert [row["id"] for row in rows] == ["soon"]
