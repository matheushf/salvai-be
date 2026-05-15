import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1 import router as v1_router

app = FastAPI(
    title="Salvai API",
    description="Backend API for Salvai",
    version="0.1.0",
)

_raw_origins = os.getenv("CORS_ALLOWED_ORIGINS", "")
allowed_origins: list[str] = [o.strip() for o in _raw_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(v1_router)


@app.get("/health", tags=["health"])
def health_check() -> JSONResponse:
    return JSONResponse(content={"status": "ok"})
