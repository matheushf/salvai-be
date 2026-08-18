from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.core.exceptions import DomainValidationError
from app.schemas.device import PushTokenUpsert
from app.services import devices as devices_svc
from app.services import notifications as notifications_svc

USER_ID = "00000000-0000-4000-8000-000000000001"


def test_resolve_timezone_name_rejects_unknown() -> None:
    with pytest.raises(DomainValidationError):
        devices_svc.resolve_timezone_name("Not/AZone")


def test_resolve_timezone_name_accepts_iana() -> None:
    assert devices_svc.resolve_timezone_name("America/Sao_Paulo") == "America/Sao_Paulo"


def _table_chain(execute_return: MagicMock) -> MagicMock:
    chain = MagicMock()
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.update.return_value = chain
    chain.insert.return_value = chain
    chain.delete.return_value = chain
    chain.maybe_single.return_value = chain
    chain.execute.return_value = execute_return
    return chain


def test_upsert_push_token_inserts_when_new() -> None:
    insert_row = {
        "id": "tok-1",
        "user_id": USER_ID,
        "expo_push_token": "ExponentPushToken[abc]",
        "platform": "ios",
        "created_at": datetime(2026, 8, 14, tzinfo=timezone.utc),
        "last_seen_at": datetime(2026, 8, 14, tzinfo=timezone.utc),
    }
    tokens_table = _table_chain(MagicMock(data=None))
    tokens_table.execute.side_effect = [
        MagicMock(data=None),
        MagicMock(data=[insert_row]),
    ]
    profiles_table = _table_chain(MagicMock(data=[{"id": USER_ID}]))

    def table(name: str) -> MagicMock:
        if name == "profiles":
            return profiles_table
        return tokens_table

    client = MagicMock()
    client.table.side_effect = table

    result = devices_svc.upsert_push_token(
        client,
        USER_ID,
        PushTokenUpsert(
            expo_push_token="ExponentPushToken[abc]",
            platform="ios",
            timezone="America/Sao_Paulo",
        ),
    )

    assert result.expo_push_token == "ExponentPushToken[abc]"
    profiles_table.update.assert_called()
    tokens_table.insert.assert_called()


def test_dispatch_skips_events_outside_window() -> None:
    tz = ZoneInfo("America/Sao_Paulo")
    now = datetime(2026, 8, 14, 12, 0, tzinfo=tz)

    events = [
        {
            "id": "evt-due",
            "author_id": USER_ID,
            "title": "Show",
            "date": "15/08/2026",
            "time": "12:00",
            "notification_reminder": "1d",
        },
        {
            "id": "evt-later",
            "author_id": USER_ID,
            "title": "Later",
            "date": "20/08/2026",
            "time": "12:00",
            "notification_reminder": "1d",
        },
    ]

    client = MagicMock()
    with (
        patch.object(notifications_svc, "_fetch_all_reminder_events", return_value=events),
        patch.object(
            notifications_svc,
            "_fetch_timezones",
            return_value={USER_ID: "America/Sao_Paulo"},
        ),
        patch.object(
            notifications_svc,
            "_fetch_tokens",
            return_value={
                USER_ID: [
                    {
                        "id": "t1",
                        "user_id": USER_ID,
                        "expo_push_token": "ExponentPushToken[abc]",
                        "platform": "ios",
                    }
                ]
            },
        ),
        patch.object(notifications_svc, "_claim_delivery", return_value=True) as claim,
        patch.object(
            notifications_svc,
            "_send_expo_batch",
            return_value=[{"status": "ok"}],
        ) as send,
        patch.object(notifications_svc, "_handle_tickets", return_value=(1, 0)),
    ):
        result = notifications_svc.dispatch_due_reminders(client, now=now)

    assert result["due"] == 1
    assert result["claimed"] == 1
    claim.assert_called_once()
    send.assert_called_once()
    payload = send.call_args.args[0][0]
    assert payload["to"] == "ExponentPushToken[abc]"
    assert payload["data"] == {"eventId": "evt-due"}
    assert payload["title"] == "Evento chegando"
