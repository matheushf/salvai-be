"""Tests for profile upsert (birth_date JSON serialization).

Uses mocked Supabase clients so they run without a live database.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import MagicMock

from app.schemas.profile import ProfileUpdate
from app.services import profiles as profile_svc

USER_ID = "00000000-0000-4000-8000-000000000001"
_UPDATED = datetime(2026, 5, 22, 12, 0, tzinfo=timezone.utc)


def _profile_row(**overrides: object) -> dict:
    row = {
        "id": USER_ID,
        "username": "testuser",
        "display_name": "Test User",
        "avatar_url": None,
        "bio": None,
        "country": "BR",
        "state": "SP",
        "city": "Sao Paulo",
        "interests": [],
        "email": "test@example.com",
        "birth_date": "1990-05-15",
        "updated_at": _UPDATED.isoformat(),
    }
    row.update(overrides)
    return row


def _mock_client_for_upsert(return_row: dict | None = None) -> MagicMock:
    upsert_exec = MagicMock()
    upsert_exec.execute.return_value = MagicMock(data=[return_row or _profile_row()])

    mock_table = MagicMock()
    mock_table.upsert.return_value = upsert_exec

    client = MagicMock()
    client.table.return_value = mock_table
    return client


def test_upsert_profile_serializes_birth_date_as_iso_string() -> None:
    client = _mock_client_for_upsert()
    update = ProfileUpdate(
        username="testuser",
        display_name="Test User",
        birth_date=date(1990, 5, 15),
    )

    profile_svc.upsert_profile(client, USER_ID, update)

    client.table.assert_called_once_with("profiles")
    upsert_call = client.table.return_value.upsert.call_args
    payload = upsert_call.args[0]
    assert payload["id"] == USER_ID
    assert payload["birth_date"] == "1990-05-15"
    assert isinstance(payload["birth_date"], str)
    assert upsert_call.kwargs == {"on_conflict": "id"}


def test_upsert_profile_includes_location_fields() -> None:
    client = _mock_client_for_upsert()
    update = ProfileUpdate(
        country="br",
        state=" SP ",
        city="Sao Paulo",
    )

    profile_svc.upsert_profile(client, USER_ID, update)

    payload = client.table.return_value.upsert.call_args.args[0]
    assert payload["country"] == "BR"
    assert payload["state"] == "SP"
    assert payload["city"] == "Sao Paulo"


def test_profile_update_rejects_invalid_country() -> None:
    import pytest

    with pytest.raises(ValueError, match="country must be a valid ISO"):
        ProfileUpdate(country="XX")


def test_to_public_includes_location_fields() -> None:
    row = _profile_row(country="US", state="CA", city="San Francisco")
    profile = profile_svc._to_public(row)
    assert profile.country == "US"
    assert profile.state == "CA"
    assert profile.city == "San Francisco"
