"""Dispatch due event reminders via the Expo Push API."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx
from postgrest.exceptions import APIError
from supabase import Client

from app.core.config import get_settings
from app.core.exceptions import UpstreamError
from app.core.supabase import execute_supabase
from app.schemas.event import EventNotificationReminder
from app.services.event_reminders import (
    compute_reminder_at,
    reminder_is_due,
    zoneinfo_or_default,
    REMINDER_OFFSET_LABELS_PT,
)

logger = logging.getLogger(__name__)

_EVENTS_TABLE = "events"
_TOKENS_TABLE = "device_push_tokens"
_DELIVERIES_TABLE = "event_notification_deliveries"
_PROFILES_TABLE = "profiles"

_EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
_EXPO_BATCH_SIZE = 100
_ANDROID_CHANNEL_ID = "event-reminders"

_EVENT_PAGE_SIZE = 1000

def _reminder_copy(title: str, reminder: EventNotificationReminder) -> tuple[str, str]:
    offset = REMINDER_OFFSET_LABELS_PT[reminder]
    return (
        "Evento chegando",
        f"{title} comeca {offset}.",
    )


def _fetch_all_reminder_events(client: Client) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    start = 0
    while True:
        end = start + _EVENT_PAGE_SIZE - 1
        response = execute_supabase(
            client,
            lambda c, s=start, e=end: c.table(_EVENTS_TABLE)
            .select("id, author_id, title, date, time, notification_reminder")
            .not_.is_("notification_reminder", "null")
            .range(s, e)
            .execute(),
        )
        page = response.data or []
        rows.extend(page)
        if len(page) < _EVENT_PAGE_SIZE:
            break
        start += _EVENT_PAGE_SIZE
    return rows


def _fetch_timezones(client: Client, user_ids: list[str]) -> dict[str, str | None]:
    if not user_ids:
        return {}
    unique_ids = list(dict.fromkeys(user_ids))
    response = execute_supabase(
        client,
        lambda c: c.table(_PROFILES_TABLE)
        .select("id, timezone")
        .in_("id", unique_ids)
        .execute(),
    )
    return {row["id"]: row.get("timezone") for row in (response.data or [])}


def _fetch_tokens(client: Client, user_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    if not user_ids:
        return {}
    unique_ids = list(dict.fromkeys(user_ids))
    response = execute_supabase(
        client,
        lambda c: c.table(_TOKENS_TABLE)
        .select("id, user_id, expo_push_token, platform")
        .in_("user_id", unique_ids)
        .execute(),
    )
    by_user: dict[str, list[dict[str, Any]]] = {uid: [] for uid in unique_ids}
    for row in response.data or []:
        by_user.setdefault(row["user_id"], []).append(row)
    return by_user


def _claim_delivery(
    client: Client,
    event_id: str,
    user_id: str,
    reminder_offset: str,
) -> bool:
    """Insert a delivery row. Returns False if this reminder was already sent."""
    try:
        response = execute_supabase(
            client,
            lambda c: c.table(_DELIVERIES_TABLE)
            .insert(
                {
                    "event_id": event_id,
                    "user_id": user_id,
                    "reminder_offset": reminder_offset,
                }
            )
            .execute(),
        )
    except APIError:
        return False
    return bool(response.data)


def _release_delivery(
    client: Client,
    event_id: str,
    user_id: str,
    reminder_offset: str,
) -> None:
    execute_supabase(
        client,
        lambda c: c.table(_DELIVERIES_TABLE)
        .delete()
        .eq("event_id", event_id)
        .eq("user_id", user_id)
        .eq("reminder_offset", reminder_offset)
        .execute(),
    )


def _delete_stale_token(client: Client, expo_push_token: str) -> None:
    execute_supabase(
        client,
        lambda c: c.table(_TOKENS_TABLE)
        .delete()
        .eq("expo_push_token", expo_push_token)
        .execute(),
    )


def _expo_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip, deflate",
        "Content-Type": "application/json",
    }
    token = get_settings().expo_access_token.strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _build_expo_message(
    expo_push_token: str,
    event_id: str,
    title: str,
    body: str,
    platform: str,
) -> dict[str, Any]:
    message: dict[str, Any] = {
        "to": expo_push_token,
        "title": title,
        "body": body,
        "sound": "default",
        "data": {"eventId": event_id},
    }
    if platform == "android":
        message["channelId"] = _ANDROID_CHANNEL_ID
    return message


def _send_expo_batch(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not messages:
        return []
    try:
        response = httpx.post(
            _EXPO_PUSH_URL,
            json=messages,
            headers=_expo_headers(),
            timeout=30.0,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise UpstreamError(f"Expo Push request failed: {exc}") from exc

    tickets = payload.get("data")
    if not isinstance(tickets, list):
        raise UpstreamError("Expo Push returned an unexpected payload")
    return tickets


def _handle_tickets(
    client: Client,
    messages: list[dict[str, Any]],
    tickets: list[dict[str, Any]],
) -> tuple[int, int]:
    sent = 0
    stale = 0
    for message, ticket in zip(messages, tickets, strict=False):
        status = ticket.get("status")
        if status == "ok":
            sent += 1
            continue
        details = ticket.get("details") or {}
        error = details.get("error") if isinstance(details, dict) else None
        token = message.get("to")
        if error == "DeviceNotRegistered" and isinstance(token, str):
            _delete_stale_token(client, token)
            stale += 1
            logger.info("Removed DeviceNotRegistered Expo token")
        else:
            logger.warning("Expo push ticket error: %s", ticket)
    return sent, stale


def dispatch_due_reminders(
    client: Client,
    now: datetime | None = None,
) -> dict[str, int]:
    now_utc = now or datetime.now(timezone.utc)
    events = _fetch_all_reminder_events(client)
    if not events:
        return {"due": 0, "claimed": 0, "sent": 0, "stale_tokens": 0, "skipped": 0}

    author_ids = [row["author_id"] for row in events if row.get("author_id")]
    timezones = _fetch_timezones(client, author_ids)
    tokens_by_user = _fetch_tokens(client, author_ids)

    due_rows: list[dict[str, Any]] = []
    skipped = 0
    for row in events:
        reminder = row.get("notification_reminder")
        if reminder not in ("2d", "1d", "6h", "1h"):
            skipped += 1
            continue
        author_id = row.get("author_id")
        event_date = row.get("date")
        if not author_id or not isinstance(event_date, str):
            skipped += 1
            continue
        tz = zoneinfo_or_default(timezones.get(author_id))
        reminder_at = compute_reminder_at(
            event_date,
            row.get("time") if isinstance(row.get("time"), str) else None,
            reminder,
            tz,
        )
        if reminder_at is None or not reminder_is_due(reminder_at, now_utc):
            continue
        due_rows.append(row)

    sent_total = 0
    stale_total = 0
    claimed = 0

    pending_messages: list[dict[str, Any]] = []
    claimed_keys: list[tuple[str, str, str]] = []

    def flush() -> None:
        nonlocal sent_total, stale_total, pending_messages, claimed_keys
        if not pending_messages:
            return
        try:
            tickets = _send_expo_batch(pending_messages)
            sent, stale = _handle_tickets(client, pending_messages, tickets)
            sent_total += sent
            stale_total += stale
        except UpstreamError:
            logger.exception("Expo Push batch failed; releasing delivery claims")
            for event_id, user_id, offset in claimed_keys:
                _release_delivery(client, event_id, user_id, offset)
            raise
        pending_messages = []
        claimed_keys = []

    for row in due_rows:
        event_id = row["id"]
        author_id = row["author_id"]
        reminder: EventNotificationReminder = row["notification_reminder"]
        tokens = tokens_by_user.get(author_id) or []
        if not tokens:
            skipped += 1
            continue
        if not _claim_delivery(client, event_id, author_id, reminder):
            skipped += 1
            continue
        claimed += 1
        title, body = _reminder_copy(str(row.get("title") or ""), reminder)
        for token_row in tokens:
            pending_messages.append(
                _build_expo_message(
                    token_row["expo_push_token"],
                    event_id,
                    title,
                    body,
                    token_row.get("platform") or "ios",
                )
            )
        claimed_keys.append((event_id, author_id, reminder))
        if len(pending_messages) >= _EXPO_BATCH_SIZE:
            flush()

    flush()

    return {
        "due": len(due_rows),
        "claimed": claimed,
        "sent": sent_total,
        "stale_tokens": stale_total,
        "skipped": skipped,
    }
