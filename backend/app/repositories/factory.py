from functools import lru_cache

from app.core.config import get_settings
from app.repositories.base import Repository
from app.repositories.memory import MemoryRepository


@lru_cache
def get_repository() -> Repository:
    settings = get_settings()
    if settings.supabase_url and settings.supabase_service_role_key:
        from app.repositories.supabase import SupabaseRepository

        return SupabaseRepository(settings.supabase_url, settings.supabase_service_role_key)
    return MemoryRepository()
