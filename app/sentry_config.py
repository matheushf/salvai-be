"""Sentry error monitoring initialization."""

from __future__ import annotations

import logging

import sentry_sdk
from fastapi import HTTPException
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration
from sentry_sdk.types import Event, Hint

from app.core.config import Settings
from app.core.exceptions import (
    ConflictError,
    DomainValidationError,
    ForbiddenError,
    NotFoundError,
)

_IGNORED_EXCEPTIONS: tuple[type[BaseException], ...] = (
    NotFoundError,
    ForbiddenError,
    ConflictError,
    DomainValidationError,
)


def _filter_expected_errors(event: Event, hint: Hint) -> Event | None:
    exc_info = hint.get("exc_info")
    if exc_info is None:
        return event

    exc_type, exc_value, _ = exc_info

    if isinstance(exc_value, HTTPException) and exc_value.status_code < 500:
        return None

    if isinstance(exc_value, _IGNORED_EXCEPTIONS):
        return None

    if isinstance(exc_type, type) and issubclass(exc_type, HTTPException):
        status_code = getattr(exc_value, "status_code", 500)
        if status_code < 500:
            return None

    if isinstance(exc_type, type) and issubclass(exc_type, _IGNORED_EXCEPTIONS):
        return None

    return event


def init_sentry(settings: Settings) -> None:
    """Initialize Sentry when a DSN is configured; no-op otherwise."""
    if not settings.sentry_dsn:
        return

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.sentry_environment,
        release=settings.sentry_release or None,
        send_default_pii=False,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        integrations=[
            FastApiIntegration(),
            StarletteIntegration(),
            LoggingIntegration(level=logging.ERROR, event_level=logging.ERROR),
        ],
        before_send=_filter_expected_errors,
    )
