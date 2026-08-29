"""Tests for event-images storage path parsing and cleanup hooks."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.core.exceptions import ForbiddenError, NotFoundError
from app.schemas.event import EventUpdate
from app.services.event_image_storage import (
    EVENT_IMAGES_BUCKET,
    owned_event_image_path,
    remove_owned_event_image,
)
from app.services import events_service as event_svc

USER = "00000000-0000-4000-8000-000000000001"
OTHER = "00000000-0000-4000-8000-000000000002"
EVENT_ID = "11111111-1111-4111-8111-111111111111"
_CREATED = datetime(2026, 1, 10, 12, 0, tzinfo=timezone.utc)

OWNED_URL = (
    f"https://proj.supabase.co/storage/v1/object/public/{EVENT_IMAGES_BUCKET}/"
    f"{USER}/{EVENT_ID}-123.jpg"
)
OTHER_USER_URL = (
    f"https://proj.supabase.co/storage/v1/object/public/{EVENT_IMAGES_BUCKET}/"
    f"{OTHER}/{EVENT_ID}-123.jpg"
)
CDN_URL = "https://p16-sign.tiktokcdn.com/thumb.jpg"


def _event_row(*, image: str | None) -> dict:
    return {
        "id": EVENT_ID,
        "author_id": USER,
        "title": "Show",
        "date": "10/06/2026",
        "end_date": None,
        "time": None,
        "end_time": None,
        "location": None,
        "image": image,
        "source_url": None,
        "category": None,
        "description": None,
        "link": None,
        "visible_in_feed": False,
        "notification_reminder": None,
        "created_at": _CREATED.isoformat(),
    }


class TestOwnedEventImagePath:
    def test_extracts_owned_path(self) -> None:
        assert owned_event_image_path(OWNED_URL, USER) == f"{USER}/{EVENT_ID}-123.jpg"

    def test_decodes_percent_encoded_path(self) -> None:
        url = (
            f"https://proj.supabase.co/storage/v1/object/public/{EVENT_IMAGES_BUCKET}/"
            f"{USER}/file%20name.webp"
        )
        assert owned_event_image_path(url, USER) == f"{USER}/file name.webp"

    def test_rejects_other_user_folder(self) -> None:
        assert owned_event_image_path(OTHER_USER_URL, USER) is None

    def test_rejects_third_party_url(self) -> None:
        assert owned_event_image_path(CDN_URL, USER) is None

    def test_rejects_empty_and_invalid(self) -> None:
        assert owned_event_image_path(None, USER) is None
        assert owned_event_image_path("", USER) is None
        assert owned_event_image_path("not-a-url", USER) is None
        assert owned_event_image_path(OWNED_URL, "") is None

    def test_rejects_path_traversal(self) -> None:
        url = (
            f"https://proj.supabase.co/storage/v1/object/public/{EVENT_IMAGES_BUCKET}/"
            f"{USER}/../secret.jpg"
        )
        assert owned_event_image_path(url, USER) is None


class TestRemoveOwnedEventImage:
    def test_removes_owned_object(self) -> None:
        client = MagicMock()
        remove_owned_event_image(client, OWNED_URL, USER)
        client.storage.from_.assert_called_once_with(EVENT_IMAGES_BUCKET)
        client.storage.from_.return_value.remove.assert_called_once_with(
            [f"{USER}/{EVENT_ID}-123.jpg"]
        )

    def test_skips_third_party_url(self) -> None:
        client = MagicMock()
        remove_owned_event_image(client, CDN_URL, USER)
        client.storage.from_.assert_not_called()

    def test_swallows_storage_errors(self) -> None:
        client = MagicMock()
        client.storage.from_.return_value.remove.side_effect = RuntimeError("storage down")
        remove_owned_event_image(client, OWNED_URL, USER)


def test_delete_event_removes_owned_thumb() -> None:
    select_resp = MagicMock()
    select_resp.data = {"author_id": USER, "image": OWNED_URL}
    calls: list[str] = []

    def fake_execute(_client: object, _build: object) -> MagicMock:
        calls.append("exec")
        if len(calls) == 1:
            return select_resp
        return MagicMock()

    with (
        patch.object(event_svc, "execute_supabase", side_effect=fake_execute),
        patch.object(event_svc, "remove_owned_event_image") as remove_mock,
    ):
        event_svc.delete_event(MagicMock(), EVENT_ID, USER)

    remove_mock.assert_called_once()
    assert remove_mock.call_args.args[1:] == (OWNED_URL, USER)


def test_delete_event_not_found() -> None:
    with patch.object(event_svc, "execute_supabase", return_value=None):
        with pytest.raises(NotFoundError):
            event_svc.delete_event(MagicMock(), EVENT_ID, USER)


def test_delete_event_forbidden() -> None:
    select_resp = MagicMock()
    select_resp.data = {"author_id": OTHER, "image": OWNED_URL}
    with patch.object(event_svc, "execute_supabase", return_value=select_resp):
        with pytest.raises(ForbiddenError):
            event_svc.delete_event(MagicMock(), EVENT_ID, USER)


def test_update_event_removes_previous_owned_thumb_on_replace() -> None:
    new_url = (
        f"https://proj.supabase.co/storage/v1/object/public/{EVENT_IMAGES_BUCKET}/"
        f"{USER}/{EVENT_ID}-999.jpg"
    )
    select_resp = MagicMock()
    select_resp.data = {"author_id": USER, "image": OWNED_URL}
    update_resp = MagicMock()
    update_resp.data = [_event_row(image=new_url)]
    calls: list[str] = []

    def fake_execute(_client: object, _build: object) -> MagicMock:
        calls.append("exec")
        if len(calls) == 1:
            return select_resp
        return update_resp

    client = MagicMock()
    with (
        patch.object(event_svc, "execute_supabase", side_effect=fake_execute),
        patch.object(event_svc, "remove_owned_event_image") as remove_mock,
    ):
        event_svc.update_event(client, EVENT_ID, USER, EventUpdate(image=new_url))

    remove_mock.assert_called_once()
    assert remove_mock.call_args.args[1:] == (OWNED_URL, USER)


def test_update_event_skips_remove_when_image_unchanged() -> None:
    select_resp = MagicMock()
    select_resp.data = {"author_id": USER, "image": OWNED_URL}
    update_resp = MagicMock()
    update_resp.data = [_event_row(image=OWNED_URL)]
    calls: list[str] = []

    def fake_execute(_client: object, _build: object) -> MagicMock:
        calls.append("exec")
        if len(calls) == 1:
            return select_resp
        return update_resp

    with (
        patch.object(event_svc, "execute_supabase", side_effect=fake_execute),
        patch.object(event_svc, "remove_owned_event_image") as remove_mock,
    ):
        event_svc.update_event(MagicMock(), EVENT_ID, USER, EventUpdate(image=OWNED_URL))

    remove_mock.assert_not_called()


def test_update_event_skips_remove_when_image_not_in_patch() -> None:
    select_resp = MagicMock()
    select_resp.data = {"author_id": USER, "image": OWNED_URL}
    update_resp = MagicMock()
    update_resp.data = [_event_row(image=OWNED_URL)]
    calls: list[str] = []

    def fake_execute(_client: object, _build: object) -> MagicMock:
        calls.append("exec")
        if len(calls) == 1:
            return select_resp
        return update_resp

    with (
        patch.object(event_svc, "execute_supabase", side_effect=fake_execute),
        patch.object(event_svc, "remove_owned_event_image") as remove_mock,
    ):
        event_svc.update_event(MagicMock(), EVENT_ID, USER, EventUpdate(title="Updated"))

    remove_mock.assert_not_called()
