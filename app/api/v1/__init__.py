from fastapi import APIRouter

from app.api.v1.devices import router as devices_router
from app.api.v1.enrich import router as enrich_router
from app.api.v1.events import router as events_router
from app.api.v1.feed import router as feed_router
from app.api.v1.follows import router as follows_router
from app.api.v1.instagram import router as instagram_router
from app.api.v1.internal_notifications import router as internal_notifications_router
from app.api.v1.profiles import router as profiles_router

router = APIRouter(prefix="/api/v1")
router.include_router(enrich_router)
router.include_router(instagram_router)
router.include_router(profiles_router)
router.include_router(follows_router)
router.include_router(events_router)
router.include_router(feed_router)
router.include_router(devices_router)
router.include_router(internal_notifications_router)
