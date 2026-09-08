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
        "onboarding_completed": True,
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


def test_profile_update_normalizes_username() -> None:
    update = ProfileUpdate(username="  Test_User  ")
    assert update.username == "test_user"


def test_profile_update_rejects_invalid_username() -> None:
    import pytest

    with pytest.raises(ValueError, match="lowercase letters"):
        ProfileUpdate(username="Bad Name")


def test_profile_update_rejects_short_username() -> None:
    import pytest

    with pytest.raises(ValueError, match="at least 3"):
        ProfileUpdate(username="ab")


def test_upsert_profile_maps_username_unique_violation() -> None:
    from postgrest.exceptions import APIError
    import pytest

    from app.core.exceptions import ConflictError

    err = APIError(
        {
            "message": 'duplicate key value violates unique constraint "profiles_username_key"',
            "code": "23505",
            "details": "Key (username)=(testuser) already exists.",
            "hint": None,
        }
    )
    upsert_exec = MagicMock()
    upsert_exec.execute.side_effect = err
    mock_table = MagicMock()
    mock_table.upsert.return_value = upsert_exec
    client = MagicMock()
    client.table.return_value = mock_table

    with pytest.raises(ConflictError, match="already taken"):
        profile_svc.upsert_profile(client, USER_ID, ProfileUpdate(username="testuser"))


def test_to_me_includes_onboarding_completed() -> None:
    profile = profile_svc._to_me(_profile_row(onboarding_completed=False))
    assert profile.onboarding_completed is False
    profile = profile_svc._to_me(_profile_row())
    assert profile.onboarding_completed is True


def test_get_my_profile_upserts_when_maybe_single_has_no_row() -> None:
    from postgrest.exceptions import APIError

    select_exec = MagicMock()
    select_exec.execute.side_effect = APIError(
        {"message": "JSON object requested, multiple (or no) rows returned", "code": "PGRST116"}
    )
    upsert_exec = MagicMock()
    upsert_exec.execute.return_value = MagicMock(data=[_profile_row()])

    mock_table = MagicMock()
    mock_table.select.return_value.eq.return_value.maybe_single.return_value = select_exec
    mock_table.upsert.return_value = upsert_exec

    client = MagicMock()
    client.table.return_value = mock_table

    profile = profile_svc.get_my_profile(client, USER_ID, "test@example.com")
    assert profile.id == USER_ID
    assert profile.email == "test@example.com"


def _mock_client_for_search(rows: list[dict] | None = None) -> tuple[MagicMock, MagicMock]:
    exec_mock = MagicMock()
    exec_mock.execute.return_value = MagicMock(data=rows or [])
    chain = MagicMock()
    chain.select.return_value = chain
    chain.neq.return_value = chain
    chain.or_.return_value = chain
    chain.order.return_value = chain
    chain.limit.return_value = exec_mock
    client = MagicMock()
    client.table.return_value = chain
    return client, chain


def test_sanitize_search_term_strips_leading_at() -> None:
    assert profile_svc._sanitize_search_term("  @Ana  ") == "Ana"
    assert profile_svc._sanitize_search_term("ana") == "ana"


def test_search_profiles_filters_username_and_display_name() -> None:
    other = _profile_row(id="00000000-0000-4000-8000-000000000002", username="anaribeiro")
    client, chain = _mock_client_for_search([other])

    items = profile_svc.search_profiles(client, USER_ID, "@Ana", limit=20)

    assert [item.username for item in items] == ["anaribeiro"]
    chain.or_.assert_called_once_with(
        'username.ilike."%Ana%",display_name.ilike."%Ana%"'
    )
    chain.limit.assert_called_once_with(20)
    chain.neq.assert_called_once_with("id", USER_ID)


def test_search_profiles_empty_query_does_not_use_or_filter() -> None:
    client, chain = _mock_client_for_search()
    profile_svc.search_profiles(client, USER_ID, "   @   ", limit=10)
    chain.or_.assert_not_called()
    chain.order.assert_called_once()

