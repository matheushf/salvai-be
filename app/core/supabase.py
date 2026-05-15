from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from supabase import Client, create_client

from app.core.config import get_settings


@lru_cache
def get_admin_client() -> Client:
    """
    Admin Supabase client using the service_role key.
    Cached as a singleton — RLS is bypassed, so callers are responsible
    for enforcing authorization before reaching this client.
    Never expose this client or its key to frontend consumers.
    """
    settings = get_settings()
    return create_client(settings.supabase_url, settings.supabase_service_role_key)


AdminClient = Annotated[Client, Depends(get_admin_client)]
