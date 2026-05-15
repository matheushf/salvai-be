from pydantic import BaseModel


class ErrorResponse(BaseModel):
    """Standardized error payload returned by all error handlers."""

    code: str
    message: str
    details: str | None = None
