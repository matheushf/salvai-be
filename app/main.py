from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1 import router as v1_router
from app.core.config import get_settings
from app.core.exceptions import (
    AppError,
    ConflictError,
    DomainValidationError,
    ForbiddenError,
    NotFoundError,
    UpstreamError,
)
from app.schemas.error import ErrorResponse


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
    """Validate required configuration at startup so misconfigured deploys
    fail immediately rather than at first request."""
    get_settings()  # raises ValidationError if any required env var is missing
    yield


app = FastAPI(
    title="Salvai API",
    description="Backend API for Salvai",
    version="0.1.0",
    lifespan=lifespan,
)

settings = get_settings()

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(v1_router)


# ── Domain exception handlers ───────────────────────────────────────────────


def _error(code: str, message: str, status_code: int, details: str | None = None) -> JSONResponse:
    body = ErrorResponse(code=code, message=message, details=details)
    return JSONResponse(status_code=status_code, content=body.model_dump(exclude_none=True))


@app.exception_handler(NotFoundError)
async def not_found_handler(_: Request, exc: NotFoundError) -> JSONResponse:
    return _error("NOT_FOUND", str(exc), status.HTTP_404_NOT_FOUND)


@app.exception_handler(ForbiddenError)
async def forbidden_handler(_: Request, exc: ForbiddenError) -> JSONResponse:
    return _error("FORBIDDEN", str(exc), status.HTTP_403_FORBIDDEN)


@app.exception_handler(ConflictError)
async def conflict_handler(_: Request, exc: ConflictError) -> JSONResponse:
    return _error("CONFLICT", str(exc), status.HTTP_409_CONFLICT)


@app.exception_handler(DomainValidationError)
async def validation_handler(_: Request, exc: DomainValidationError) -> JSONResponse:
    return _error("VALIDATION_ERROR", str(exc), status.HTTP_422_UNPROCESSABLE_ENTITY)


@app.exception_handler(UpstreamError)
async def upstream_handler(_: Request, exc: UpstreamError) -> JSONResponse:
    return _error(
        "UPSTREAM_ERROR",
        "An upstream service returned an unexpected error",
        status.HTTP_502_BAD_GATEWAY,
        details=str(exc),
    )


@app.exception_handler(AppError)
async def generic_app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    return _error("INTERNAL_ERROR", str(exc), status.HTTP_500_INTERNAL_SERVER_ERROR)


# ── Health ──────────────────────────────────────────────────────────────────


@app.get(
    "/health",
    tags=["health"],
    response_model=dict,
    summary="Liveness probe",
)
def health_check() -> dict:
    return {"status": "ok"}
