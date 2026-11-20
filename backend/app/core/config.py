from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

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
