from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from postgrest.exceptions import APIError

from app.core.exceptions import UpstreamError
from app.core.supabase import (
    _strip_non_jwt_authorization,
    execute_supabase,
    get_admin_client,
    reset_admin_client,
)


def test_execute_supabase_returns_on_first_success() -> None:
    client = MagicMock()
    client.table.return_value.select.return_value.execute.return_value = MagicMock(data=[{"id": "1"}])

    result = execute_supabase(client, lambda c: c.table("profiles").select("*").execute())

    assert result.data == [{"id": "1"}]
    client.table.assert_called_once_with("profiles")


def test_execute_supabase_retries_transport_error() -> None:
    client = MagicMock()
    success = MagicMock(data=[{"id": "1"}])
    client.table.return_value.select.return_value.execute.side_effect = [
        httpx.RemoteProtocolError("ConnectionTerminated"),
        success,
    ]

    with patch("app.core.supabase.reset_admin_client") as reset_mock:
        with patch("app.core.supabase.get_admin_client", return_value=client):
            result = execute_supabase(client, lambda c: c.table("profiles").select("*").execute())

    assert result is success
    assert client.table.return_value.select.return_value.execute.call_count == 2
    reset_mock.assert_called_once()


def test_execute_supabase_raises_upstream_error_after_max_attempts() -> None:
    client = MagicMock()
    client.table.return_value.select.return_value.execute.side_effect = httpx.ConnectError(
        "connection refused"
    )

    with patch("app.core.supabase.reset_admin_client"):
        with patch("app.core.supabase.get_admin_client", return_value=client):
            with pytest.raises(UpstreamError, match="transport attempts"):
                execute_supabase(client, lambda c: c.table("profiles").select("*").execute())

    assert client.table.return_value.select.return_value.execute.call_count == 3


def test_execute_supabase_does_not_retry_application_errors() -> None:
    client = MagicMock()
    client.table.return_value.select.return_value.execute.side_effect = ValueError("bad query")

    with pytest.raises(ValueError, match="bad query"):
        execute_supabase(client, lambda c: c.table("profiles").select("*").execute())

    assert client.table.return_value.select.return_value.execute.call_count == 1


def test_execute_supabase_maps_api_error_to_upstream() -> None:
    client = MagicMock()
    err = APIError({"message": "Invalid JWT", "code": "PGRST301", "hint": None, "details": None})
    client.table.return_value.select.return_value.execute.side_effect = err

    with pytest.raises(UpstreamError, match="Supabase request failed"):
        execute_supabase(client, lambda c: c.table("profiles").select("*").execute())


def test_execute_supabase_returns_none_for_maybe_single_no_rows() -> None:
    client = MagicMock()
    err = APIError(
        {"message": "JSON object requested, multiple (or no) rows returned", "code": "PGRST116"}
    )
    client.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.side_effect = err

    result = execute_supabase(
        client,
        lambda c: c.table("profiles").select("*").eq("id", "x").maybe_single().execute(),
    )
    assert result is None


def test_strip_non_jwt_authorization_drops_bearer_secret() -> None:
    client = MagicMock()
    client.options.headers = {"Authorization": "Bearer sb_secret_test", "apikey": "sb_secret_test"}
    client.postgrest.session.headers = {
        "Authorization": "Bearer sb_secret_test",
        "apikey": "sb_secret_test",
    }
    _strip_non_jwt_authorization(client, "sb_secret_test")
    assert "Authorization" not in client.postgrest.session.headers
    assert client.postgrest.session.headers["apikey"] == "sb_secret_test"


def test_reset_admin_client_closes_session_and_clears_cache() -> None:
    get_admin_client.cache_clear()
    try:
        with patch("app.core.config.get_settings") as settings_mock:
            settings_mock.return_value = MagicMock(
                supabase_url="http://localhost:54321",
                supabase_service_role_key="test-key",
            )
            with patch("app.core.supabase.create_client") as create_mock:
                clients = [MagicMock(postgrest=MagicMock(session=MagicMock())) for _ in range(2)]
                create_mock.side_effect = clients

                first = get_admin_client()
                reset_admin_client()
                second = get_admin_client()

                clients[0].postgrest.session.close.assert_called_once()
                assert create_mock.call_count == 2
                assert first is clients[0]
                assert second is clients[1]
    finally:
        get_admin_client.cache_clear()
