from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.api.v1 import router as v1_router

app = FastAPI(
    title="Salvai API",
    description="Backend API for Salvai",
    version="0.1.0",
)

app.include_router(v1_router)


@app.get("/health", tags=["health"])
def health_check() -> JSONResponse:
    return JSONResponse(content={"status": "ok"})
