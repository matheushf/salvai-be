from fastapi import APIRouter, Query, Response, status

from app.core.auth import CurrentUser
from app.core.supabase import AdminClient
from app.schemas.device import PushTokenResponse, PushTokenUpsert
from app.services import devices as devices_svc

router = APIRouter(prefix="/devices", tags=["devices"])


@router.put(
    "/push-token",
    response_model=PushTokenResponse,
    summary="Register or refresh this device's Expo push token",
)
def upsert_push_token(
    body: PushTokenUpsert,
    current_user: CurrentUser,
    client: AdminClient,
) -> PushTokenResponse:
    return devices_svc.upsert_push_token(client, current_user.id, body)


@router.delete(
    "/push-token",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove this device's Expo push token (logout)",
)
def delete_push_token(
    current_user: CurrentUser,
    client: AdminClient,
    expo_push_token: str = Query(..., min_length=8, max_length=512),
) -> Response:
    devices_svc.delete_push_token(client, current_user.id, expo_push_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
