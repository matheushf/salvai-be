"""
Supabase admin client lifecycle and resilient query execution.

The admin client is a process-wide singleton so we reuse HTTP connections to
PostgREST. Under concurrent load, a stale HTTP/2 connection can be terminated by
Supabase or an upstream proxy; ``execute_supabase`` retries those transport
failures, resets the cached client, and maps persistent failures to
``UpstreamError`` (HTTP 502).

Monitor recurrence by filtering logs for ``supabase_transport_error``.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from functools import lru_cache
from typing import Annotated, TypeVar

import httpx
from fastapi import Depends
from postgrest.exceptions import APIError
from supabase import Client, create_client
from supabase.lib.client_options import SyncClientOptions

from app.core.config import get_settings
from app.core.exceptions import UpstreamError

logger = logging.getLogger("app.supabase")

T = TypeVar("T")

_MAX_ATTEMPTS = 3
_BACKOFF_SECONDS = 0.1

_TRANSPORT_ERRORS: tuple[type[Exception], ...] = (
    httpx.RemoteProtocolError,
    httpx.ConnectError,
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.PoolTimeout,
    httpx.NetworkError,
)


def _build_httpx_client() -> httpx.Client:
    return httpx.Client(
        timeout=httpx.Timeout(30.0, connect=10.0),
        limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
    )


def _uses_new_api_key(key: str) -> bool:
    return key.startswith("sb_secret_") or key.startswith("sb_publishable_")


def _strip_non_jwt_authorization(client: Client, key: str) -> None:
    """Secret/publishable keys are not JWTs.

    supabase-py still sets ``Authorization: Bearer <key>``. The API gateway then
    tries to parse that as a user JWT and returns Invalid JWT. Keep ``apikey``
    and drop the Bearer header so the gateway can mint its own access token.
    """
    client.options.headers["apikey"] = key
    postgrest_headers = client.postgrest.session.headers
    postgrest_headers["apikey"] = key
    postgrest_headers.pop("Authorization", None)


@lru_cache
def get_admin_client() -> Client:
    """
    Admin Supabase client using the service_role key.
    Cached as a singleton — RLS is bypassed, so callers are responsible
    for enforcing authorization before reaching this client.
    Never expose this client or its key to frontend consumers.
    """
    settings = get_settings()
    key = settings.supabase_service_role_key
    client = create_client(
        settings.supabase_url,
        key,
        options=SyncClientOptions(httpx_client=_build_httpx_client()),
    )
    if _uses_new_api_key(key):
        _strip_non_jwt_authorization(client, key)
    return client


def reset_admin_client() -> None:
    """Drop the cached client and close its HTTP session."""
    if get_admin_client.cache_info().currsize == 0:
        return

    client = get_admin_client()
    try:
        client.postgrest.session.close()
    except Exception:
        logger.exception("Failed to close Supabase HTTP session during reset")

    get_admin_client.cache_clear()


def execute_supabase(client: Client, build: Callable[[Client], T]) -> T | None:
    """
    Run a Supabase query with transport-level retry and client refresh.

    ``build`` receives the active client and must construct a fresh query chain
    on each call so retries can run against a new connection.
    """
    last_exc: Exception | None = None
    current_client = client

    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            return build(current_client)
        except APIError as exc:
            code = getattr(exc, "code", None)
            if code == "PGRST116":
                return None
            logger.warning("supabase_api_error code=%s error=%s", code, exc)
            raise UpstreamError("Supabase request failed") from exc
        except _TRANSPORT_ERRORS as exc:
            last_exc = exc
            logger.warning(
                "supabase_transport_error attempt=%s/%s error=%s",
                attempt,
                _MAX_ATTEMPTS,
                exc,
                exc_info=attempt == _MAX_ATTEMPTS,
            )
            if attempt == _MAX_ATTEMPTS:
                break
            reset_admin_client()
            current_client = get_admin_client()
            time.sleep(_BACKOFF_SECONDS * attempt)

    raise UpstreamError(
        f"Supabase request failed after {_MAX_ATTEMPTS} transport attempts"
    ) from last_exc


AdminClient = Annotated[Client, Depends(get_admin_client)]
