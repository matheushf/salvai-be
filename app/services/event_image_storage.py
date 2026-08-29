from __future__ import annotations

import logging
from urllib.parse import unquote, urlparse

from supabase import Client

EVENT_IMAGES_BUCKET = "event-images"

_PUBLIC_OBJECT_MARKER = f"/storage/v1/object/public/{EVENT_IMAGES_BUCKET}/"

logger = logging.getLogger("app.event_image_storage")


def owned_event_image_path(image_url: str | None, user_id: str) -> str | None:
    """Return the storage object path if ``image_url`` is this user's event-images file."""
    if not image_url or not user_id:
        return None

    try:
        parsed = urlparse(image_url.strip())
    except ValueError:
        return None

    path = unquote(parsed.path or "")
    idx = path.find(_PUBLIC_OBJECT_MARKER)
    if idx == -1:
        return None

    object_path = path[idx + len(_PUBLIC_OBJECT_MARKER) :]
    if not object_path or ".." in object_path:
        return None

    folder, _, _rest = object_path.partition("/")
    if folder != user_id:
        return None

    return object_path


def remove_owned_event_image(client: Client, image_url: str | None, user_id: str) -> None:
    """Best-effort delete of an owned event-images object. Never raises."""
    path = owned_event_image_path(image_url, user_id)
    if not path:
        return

    try:
        client.storage.from_(EVENT_IMAGES_BUCKET).remove([path])
    except Exception:
        logger.exception("Failed to remove event image path=%s user_id=%s", path, user_id)
