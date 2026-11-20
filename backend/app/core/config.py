from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    openai_api_key: str = ""
    openai_model: str = "gpt-5.4-mini"
    rentcast_api_key: str = ""
    rentcast_monthly_cap: int = 45  # stays inside RentCast's 50 free requests/month
    analysis_enabled: bool = True

    # Repo-root .env first, backend/.env overrides it.
    model_config = SettingsConfigDict(env_file=(_ROOT / ".env", _ROOT / "backend" / ".env"), extra="ignore")

    api_token: str = ""
    provider: Literal["hasdata", "fixture"] = "fixture"
    hasdata_api_key: str = ""
    hasdata_base_url: str = "https://api.hasdata.com"
    # HasData recommends a 300s client timeout because scrapes can be slow.
    hasdata_timeout_seconds: float = 300.0
    max_requests_per_run: int = 25
    max_pages_per_town: int = 1
    fetch_details: bool = True
    # Persistence. Both empty -> in-memory repository (data lost on restart).
    supabase_url: str = ""
    supabase_service_role_key: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
