"""Smoke tests for user follows (service + HTTP surface).

Uses mocked Supabase clients so they run without a live database.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.core.auth import get_current_user
from app.core.exceptions import ConflictError, DomainValidationError, NotFoundError
from app.core.supabase import get_admin_client
from app.main import app
from app.schemas.follow import FollowResponse, FollowingListResponse
from app.schemas.user import AuthenticatedUser
from app.services import follows as follow_svc

VIEWER = "00000000-0000-4000-8000-000000000001"
TARGET = "00000000-0000-4000-8000-000000000002"

_CREATED = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)


def _row(follower_id: str = VIEWER, followed_id: str = TARGET) -> dict:
    return {
        "follower_id": follower_id,
        "followed_id": followed_id,
        "created_at": _CREATED.isoformat(),
    }


def _mock_client_for_new_follow() -> MagicMock:
    """First SELECT returns empty; INSERT returns one row."""
    select_exec = MagicMock()
    select_exec.execute.return_value = None

    insert_exec = MagicMock()
    insert_exec.execute.return_value = MagicMock(data=[_row()])

    mock_table = MagicMock()
    mock_table.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value = (
        select_exec
    )
    mock_table.insert.return_value = insert_exec

    client = MagicMock()
    client.table.return_value = mock_table
    return client


def test_follow_user_persists_when_not_already_following() -> None:
    client = _mock_client_for_new_follow()
    out = follow_svc.follow_user(client, VIEWER, TARGET)
    assert out.follower_id == VIEWER
    assert out.followed_id == TARGET
    assert isinstance(out.created_at, datetime)
    assert client.table.call_count == 2
    assert all(c.args == ("follows",) for c in client.table.call_args_list)
    client.table.return_value.insert.assert_called_once_with(
        {"follower_id": VIEWER, "followed_id": TARGET}
    )


def test_follow_user_rejects_self() -> None:
    with pytest.raises(DomainValidationError, match="Cannot follow yourself"):
        follow_svc.follow_user(MagicMock(), VIEWER, VIEWER)


def test_follow_user_conflict_when_already_following() -> None:
    select_exec = MagicMock()
    select_exec.execute.return_value = MagicMock(data={"follower_id": VIEWER})

    mock_table = MagicMock()
    mock_table.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value = (
        select_exec
    )

    client = MagicMock()
    client.table.return_value = mock_table

    with pytest.raises(ConflictError, match="Already following"):
        follow_svc.follow_user(client, VIEWER, TARGET)

    mock_table.insert.assert_not_called()


def test_unfollow_user_deletes_row() -> None:
    delete_exec = MagicMock()
    delete_exec.execute.return_value = MagicMock(data=[_row()])

    mock_table = MagicMock()
    mock_table.delete.return_value.eq.return_value.eq.return_value = delete_exec

    client = MagicMock()
    client.table.return_value = mock_table

    follow_svc.unfollow_user(client, VIEWER, TARGET)
    mock_table.delete.assert_called_once()


def test_unfollow_user_not_found_when_no_row() -> None:
    delete_exec = MagicMock()
    delete_exec.execute.return_value = MagicMock(data=[])

    mock_table = MagicMock()
    mock_table.delete.return_value.eq.return_value.eq.return_value = delete_exec

    client = MagicMock()
    client.table.return_value = mock_table

    with pytest.raises(NotFoundError):
        follow_svc.unfollow_user(client, VIEWER, TARGET)


def test_list_following_orders_and_counts() -> None:
    rows = [_row(followed_id=TARGET), _row(followed_id="00000000-0000-4000-8000-000000000003")]

    list_exec = MagicMock()
    list_exec.execute.return_value = MagicMock(data=rows)

    mock_table = MagicMock()
    mock_table.select.return_value.eq.return_value.order.return_value = list_exec

    client = MagicMock()
    client.table.return_value = mock_table

    out = follow_svc.list_following(client, VIEWER)
    assert isinstance(out, FollowingListResponse)
    assert out.total == 2
    assert len(out.items) == 2
    mock_table.select.assert_called_once_with("*")


def test_list_followers_orders_and_counts() -> None:
    rows = [_row(follower_id=TARGET), _row(follower_id="00000000-0000-4000-8000-000000000003")]

    list_exec = MagicMock()
    list_exec.execute.return_value = MagicMock(data=rows)

    mock_table = MagicMock()
    mock_table.select.return_value.eq.return_value.order.return_value = list_exec

    client = MagicMock()
    client.table.return_value = mock_table

    out = follow_svc.list_followers(client, VIEWER)
    assert isinstance(out, FollowingListResponse)
    assert out.total == 2
    assert len(out.items) == 2
    assert out.items[0].follower_id == TARGET
    mock_table.select.assert_called_once_with("*")


@pytest.fixture
def api_client() -> TestClient:
    return TestClient(app)


def test_api_post_follow_returns_201(api_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_follow_user(_client, follower_id: str, followed_id: str) -> FollowResponse:
        assert follower_id == VIEWER
        assert followed_id == TARGET
        return FollowResponse(**_row(follower_id, followed_id))

    monkeypatch.setattr(follow_svc, "follow_user", fake_follow_user)

    app.dependency_overrides[get_admin_client] = lambda: MagicMock()
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(id=VIEWER)

    try:
        res = api_client.post(f"/api/v1/follows/{TARGET}")
    finally:
        app.dependency_overrides.clear()

    assert res.status_code == 201
    body = res.json()
    assert body["follower_id"] == VIEWER
    assert body["followed_id"] == TARGET
    assert "created_at" in body


def test_api_delete_follow_returns_204(api_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, str] = {}

    def fake_unfollow_user(_client, follower_id: str, followed_id: str) -> None:
        called["follower_id"] = follower_id
        called["followed_id"] = followed_id

    monkeypatch.setattr(follow_svc, "unfollow_user", fake_unfollow_user)

    app.dependency_overrides[get_admin_client] = lambda: MagicMock()
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(id=VIEWER)

    try:
        res = api_client.delete(f"/api/v1/follows/{TARGET}")
    finally:
        app.dependency_overrides.clear()

    assert res.status_code == 204
    assert res.content == b""
    assert called == {"follower_id": VIEWER, "followed_id": TARGET}


def test_api_get_follows_me_returns_payload(api_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = FollowingListResponse(
        items=[FollowResponse(**_row())],
        total=1,
    )

    def fake_list_following(_client, user_id: str) -> FollowingListResponse:
        assert user_id == VIEWER
        return payload

    monkeypatch.setattr(follow_svc, "list_following", fake_list_following)

    app.dependency_overrides[get_admin_client] = lambda: MagicMock()
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(id=VIEWER)

    try:
        res = api_client.get("/api/v1/follows/me")
    finally:
        app.dependency_overrides.clear()

    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["followed_id"] == TARGET


def test_api_get_follows_me_followers_returns_payload(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = FollowingListResponse(
        items=[FollowResponse(**_row(follower_id=TARGET, followed_id=VIEWER))],
        total=1,
    )

    def fake_list_followers(_client, user_id: str) -> FollowingListResponse:
        assert user_id == VIEWER
        return payload

    monkeypatch.setattr(follow_svc, "list_followers", fake_list_followers)

    app.dependency_overrides[get_admin_client] = lambda: MagicMock()
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(id=VIEWER)

    try:
        res = api_client.get("/api/v1/follows/me/followers")
    finally:
        app.dependency_overrides.clear()

    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["follower_id"] == TARGET
    assert body["items"][0]["followed_id"] == VIEWER
