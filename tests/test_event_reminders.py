from datetime import datetime
from zoneinfo import ZoneInfo

from app.services.event_reminders import (
    DEFAULT_TIMEZONE,
    compute_event_start_at,
    compute_reminder_at,
    parse_event_calendar_date,
    parse_event_clock,
    reminder_is_due,
    zoneinfo_or_default,
)


def test_parse_dmy_and_iso_dates() -> None:
    assert parse_event_calendar_date("14/08/2026") == datetime(2026, 8, 14).date()
    assert parse_event_calendar_date("2026-08-14") == datetime(2026, 8, 14).date()
    assert parse_event_calendar_date("not-a-date") is None


def test_parse_event_clock_defaults_to_nine() -> None:
    assert parse_event_clock(None) == (9, 0)
    assert parse_event_clock("18:30") == (18, 30)
    assert parse_event_clock("99:99") == (9, 0)


def test_zoneinfo_falls_back_to_sao_paulo() -> None:
    assert zoneinfo_or_default(None).key == DEFAULT_TIMEZONE
    assert zoneinfo_or_default("Not/AZone").key == DEFAULT_TIMEZONE
    assert zoneinfo_or_default("America/New_York").key == "America/New_York"


def test_compute_reminder_at_one_day_before_in_author_timezone() -> None:
    tz = ZoneInfo("America/Sao_Paulo")
    reminder_at = compute_reminder_at("15/08/2026", "18:00", "1d", tz)
    assert reminder_at == datetime(2026, 8, 14, 18, 0, tzinfo=tz)


def test_compute_event_start_defaults_missing_time_to_nine() -> None:
    tz = ZoneInfo("America/Sao_Paulo")
    start = compute_event_start_at("15/08/2026", None, tz)
    assert start == datetime(2026, 8, 15, 9, 0, tzinfo=tz)


def test_reminder_is_due_in_ten_minute_window() -> None:
    tz = ZoneInfo("UTC")
    reminder_at = datetime(2026, 8, 14, 18, 5, tzinfo=tz)
    now = datetime(2026, 8, 14, 18, 0, tzinfo=tz)
    assert reminder_is_due(reminder_at, now) is True
    assert reminder_is_due(reminder_at, datetime(2026, 8, 14, 18, 5, tzinfo=tz)) is True
    assert reminder_is_due(reminder_at, datetime(2026, 8, 14, 17, 54, tzinfo=tz)) is False
    assert reminder_is_due(reminder_at, datetime(2026, 8, 14, 18, 10, tzinfo=tz)) is False
