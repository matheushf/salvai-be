"""Wall-clock reminder math for event notifications.

Events store `date` (dd/mm/yyyy or ISO) and optional `time` (HH:mm) with no
timezone. Fire time is computed in the author's IANA zone, falling back to
America/Sao_Paulo.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.schemas.event import EventNotificationReminder

DEFAULT_TIMEZONE = "America/Sao_Paulo"
DEFAULT_EVENT_HOUR = 9
DEFAULT_EVENT_MINUTE = 0

REMINDER_OFFSETS: dict[EventNotificationReminder, timedelta] = {
    "2d": timedelta(days=2),
    "1d": timedelta(days=1),
    "6h": timedelta(hours=6),
    "1h": timedelta(hours=1),
}

REMINDER_OFFSET_LABELS_PT: dict[EventNotificationReminder, str] = {
    "2d": "2 dias antes",
    "1d": "1 dia antes",
    "6h": "6 horas antes",
    "1h": "1 hora antes",
}

DISPATCH_WINDOW = timedelta(minutes=10)


def zoneinfo_or_default(name: str | None) -> ZoneInfo:
    candidate = (name or "").strip() or DEFAULT_TIMEZONE
    try:
        return ZoneInfo(candidate)
    except ZoneInfoNotFoundError:
        return ZoneInfo(DEFAULT_TIMEZONE)


def parse_event_calendar_date(value: str) -> date | None:
    stripped = value.strip()
    dmy = stripped.split("/")
    if len(dmy) == 3:
        try:
            dd, mm, yyyy = int(dmy[0]), int(dmy[1]), int(dmy[2])
            return date(yyyy, mm, dd)
        except (ValueError, TypeError):
            pass

    match = stripped[:10] if len(stripped) >= 10 else stripped
    if len(match) == 10 and match[4] == "-" and match[7] == "-":
        try:
            yyyy, mm, dd = int(match[0:4]), int(match[5:7]), int(match[8:10])
            return date(yyyy, mm, dd)
        except (ValueError, TypeError):
            return None
    return None


def parse_event_clock(value: str | None) -> tuple[int, int]:
    if not value:
        return DEFAULT_EVENT_HOUR, DEFAULT_EVENT_MINUTE
    parts = value.strip().split(":")
    if len(parts) < 2:
        return DEFAULT_EVENT_HOUR, DEFAULT_EVENT_MINUTE
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except (ValueError, TypeError):
        return DEFAULT_EVENT_HOUR, DEFAULT_EVENT_MINUTE
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return DEFAULT_EVENT_HOUR, DEFAULT_EVENT_MINUTE
    return hour, minute


def compute_event_start_at(
    event_date: str,
    event_time: str | None,
    tz: ZoneInfo,
) -> datetime | None:
    calendar = parse_event_calendar_date(event_date)
    if calendar is None:
        return None
    hour, minute = parse_event_clock(event_time)
    return datetime(
        calendar.year,
        calendar.month,
        calendar.day,
        hour,
        minute,
        tzinfo=tz,
    )


def compute_reminder_at(
    event_date: str,
    event_time: str | None,
    reminder: EventNotificationReminder,
    tz: ZoneInfo,
) -> datetime | None:
    start = compute_event_start_at(event_date, event_time, tz)
    if start is None:
        return None
    return start - REMINDER_OFFSETS[reminder]


def reminder_is_due(
    reminder_at: datetime,
    now: datetime,
    window: timedelta = DISPATCH_WINDOW,
) -> bool:
    return now <= reminder_at < now + window
