"""
Domain exception hierarchy for the application layer.

Services raise these; HTTP mapping lives exclusively in the global
exception handlers registered in app/main.py. This keeps the domain
and data layers free of any FastAPI / HTTP imports.
"""


class AppError(Exception):
    """Base class for all application domain errors."""


class NotFoundError(AppError):
    def __init__(self, resource: str, resource_id: str | None = None) -> None:
        self.resource = resource
        self.resource_id = resource_id
        msg = resource
        if resource_id:
            msg = f"{resource}: {resource_id}"
        super().__init__(msg)


class ConflictError(AppError):
    def __init__(self, message: str) -> None:
        super().__init__(message)


class ForbiddenError(AppError):
    def __init__(self, message: str = "Access denied") -> None:
        super().__init__(message)


class DomainValidationError(AppError):
    def __init__(self, message: str) -> None:
        super().__init__(message)


class UpstreamError(AppError):
    """Raised when an external dependency (e.g. Supabase) returns an unexpected failure."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
