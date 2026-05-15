from fastapi import APIRouter

from app.api.v1.instagram import router as instagram_router

router = APIRouter(prefix="/api/v1")
router.include_router(instagram_router)
