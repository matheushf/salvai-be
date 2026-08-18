from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Security, status
from fastapi.security.api_key import APIKeyHeader

from app.core.config import get_settings
from app.core.supabase import AdminClient
from app.services import notifications as notifications_svc

router = APIRouter(prefix="/internal/notifications", tags=["internal"])

_api_key_header = APIKeyHeader(name="X-Api-Key", auto_error=False)


def _verify_internal_key(key: Annotated[str | None, Security(_api_key_header)]) -> None:
    expected = get_settings().internal_notifications_key.strip()
    if not expected or key != expected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing or invalid X-Api-Key header",
        )


@router.post(
    "/dispatch",
    dependencies=[Depends(_verify_internal_key)],
    summary="Send due event reminder pushes (cron)",
)
def dispatch_notifications(client: AdminClient) -> dict[str, int]:
    return notifications_svc.dispatch_due_reminders(client)
