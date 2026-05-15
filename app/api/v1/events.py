from fastapi import APIRouter, Response, status

from app.core.auth import CurrentUser
from app.core.supabase import AdminClient
from app.schemas.event import EventCreate, EventResponse
from app.services import events_service as event_svc

router = APIRouter(prefix="/events", tags=["events"])


@router.post(
    "",
    response_model=EventResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an event for the current user",
)
def create_event(body: EventCreate, current_user: CurrentUser, client: AdminClient) -> EventResponse:
    return event_svc.create_event(client, current_user.id, body)


@router.get(
    "/{event_id}",
    response_model=EventResponse,
    summary="Get a single event by ID",
    description="Returns the event if the requester is the author or follows the author.",
)
def get_event(event_id: str, current_user: CurrentUser, client: AdminClient) -> EventResponse:
    return event_svc.get_event(client, event_id, requester_id=current_user.id)


@router.delete(
    "/{event_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an event (owner only)",
)
def delete_event(event_id: str, current_user: CurrentUser, client: AdminClient) -> Response:
    event_svc.delete_event(client, event_id, current_user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
