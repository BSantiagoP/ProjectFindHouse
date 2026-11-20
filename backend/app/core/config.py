from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    openai_api_key: str = ""  # used from Milestone 3 (description/photo analysis)

    # Repo-root .env first, backend/.env overrides it.
    model_config = SettingsConfigDict(env_file=(_ROOT / ".env", _ROOT / "backend" / ".env"), extra="ignore")

    api_token: str = ""
    provider: Literal["hasdata", "fixture"] = "fixture"
    hasdata_api_key: str = ""
    hasdata_base_url: str = "https://api.hasdata.com"
    # HasData recommends a 300s client timeout because scrapes can be slow.
    hasdata_timeout_seconds: float = 300.0
    max_requests_per_run: int = 15
    max_pages_per_town: int = 1
    fetch_details: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
