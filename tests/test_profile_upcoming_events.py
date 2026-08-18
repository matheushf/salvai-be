"""Tests for profile upcoming events (service layer, mocked Supabase)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.services import events_service as event_svc

VIEWER = "00000000-0000-4000-8000-000000000001"
AUTHOR = "00000000-0000-4000-8000-000000000002"
_CREATED = datetime(2026, 1, 10, 12, 0, tzinfo=timezone.utc)
_TODAY = datetime(2026, 6, 2, 12, 0, tzinfo=timezone.utc)


def _event_row(
    event_id: str,
    *,
    date: str,
    end_date: str | None = None,
    visible_in_feed: bool = True,
    title: str = "Event",
) -> dict:
    return {
        "id": event_id,
        "author_id": AUTHOR,
        "title": title,
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
        "visible_in_feed": visible_in_feed,
        "notification_reminder": None,
        "created_at": _CREATED.isoformat(),
    }


def _mock_client(*, following: bool, event_rows: list[dict]) -> MagicMock:
    follow_exec = MagicMock()
    if following:
        follow_exec.execute.return_value = MagicMock(data={"follower_id": VIEWER})
    else:
        follow_exec.execute.return_value = None

    follow_table = MagicMock()
    follow_table.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value = (
        follow_exec
    )

    events_exec = MagicMock()
    events_exec.execute.return_value = MagicMock(data=event_rows)

    events_table = MagicMock()
    events_table.select.return_value.eq.return_value.eq.return_value.limit.return_value = (
        events_exec
    )
    events_table.select.return_value.eq.return_value.limit.return_value = events_exec

    client = MagicMock()

    def table(name: str) -> MagicMock:
        if name == event_svc._FOLLOWS_TABLE:
            return follow_table
        if name == event_svc._TABLE:
            return events_table
        raise AssertionError(f"unexpected table {name}")

    client.table.side_effect = table
    return client


@pytest.fixture
def fixed_today() -> None:
    with patch.object(event_svc, "_utc_today", return_value=_TODAY.date()):
        yield


def test_parse_event_date_accepts_dmy_and_iso() -> None:
    assert event_svc._parse_event_date("15/08/2026") == _TODAY.date().replace(month=8, day=15)
    assert event_svc._parse_event_date("2026-08-15") == _TODAY.date().replace(month=8, day=15)
    assert event_svc._parse_event_date("2026-08-15T18:00:00Z") == _TODAY.date().replace(
        month=8, day=15
    )


def test_upcoming_sort_day_includes_iso_start_and_multi_day_end(fixed_today: None) -> None:
    iso_row = _event_row("e1", date="2026-09-01")
    assert event_svc._upcoming_sort_day(iso_row, _TODAY.date()) is not None

    range_row = _event_row("e2", date="01/05/2026", end_date="10/09/2026")
    assert event_svc._upcoming_sort_day(range_row, _TODAY.date()) is not None

    past_row = _event_row("e3", date="01/01/2026")
    assert event_svc._upcoming_sort_day(past_row, _TODAY.date()) is None


def test_follower_sees_upcoming_feed_visible_capped_at_four(fixed_today: None) -> None:
    rows = [
        _event_row("e1", date="10/09/2026", title="Later"),
        _event_row("e2", date="15/08/2026", title="Soon"),
        _event_row("e3", date="20/10/2026", title="Latest"),
        _event_row("e4", date="01/01/2026", title="Past"),
        _event_row("e5", date="2026-07-01", title="ISO"),
        _event_row("e6", date="01/11/2026", title="Last"),
    ]
    client = _mock_client(following=True, event_rows=rows)

    out = event_svc.list_profile_upcoming_events(client, AUTHOR, VIEWER)

    assert len(out.items) == 4
    titles = {item.title for item in out.items}
    assert "Past" not in titles
    assert "Soon" in titles
    assert "Last" not in titles


def test_non_follower_gets_empty_list(fixed_today: None) -> None:
    rows = [_event_row("e1", date="15/08/2026")]
    client = _mock_client(following=False, event_rows=rows)

    out = event_svc.list_profile_upcoming_events(client, AUTHOR, VIEWER)

    assert out.items == []


def test_owner_sees_all_upcoming_not_only_feed_visible(fixed_today: None) -> None:
    rows = [
        _event_row("e1", date="15/08/2026", visible_in_feed=False),
        _event_row("e2", date="2026-09-01", visible_in_feed=True),
        _event_row("e3", date="01/01/2026", visible_in_feed=True),
    ]
    client = _mock_client(following=False, event_rows=rows)

    out = event_svc.list_profile_upcoming_events(client, AUTHOR, AUTHOR)

    assert len(out.items) == 2
    assert {item.id for item in out.items} == {"e1", "e2"}


def test_viewer_follows_author_requires_data_not_empty_response() -> None:
    client = MagicMock()
    follow_exec = MagicMock()
    follow_exec.execute.return_value = MagicMock(data=None)

    follow_table = MagicMock()
    follow_table.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value = (
        follow_exec
    )
    client.table.return_value = follow_table

    assert event_svc._viewer_follows_author(client, VIEWER, AUTHOR) is False
