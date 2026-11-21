from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    openai_api_key: str = ""
    openai_model: str = "gpt-5.4-mini"  # listing text analysis
    openai_vision_model: str = "gpt-5.6-luna"  # photo analysis (chosen 2026-11-20 after side-by-side test)
    rentcast_api_key: str = ""
    rentcast_monthly_cap: int = 45  # stays inside RentCast's 50 free requests/month
    analysis_enabled: bool = True
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_phone_number: str = ""
    twilio_messaging_service_sid: str = ""  # service holding the verified A2P 10DLC campaign
    sms_enabled: bool = False  # sending requires explicit opt-in
    dashboard_url: str = ""  # e.g. https://homescout-delta.vercel.app; SMS links open the report there
    # Recipients who can log in to the dashboard get dashboard links; others get listing links.
    dashboard_recipients: str = "RECIPIENT1"
    run_every_days: int = 2  # every other day (decided 2026-11-20)
    run_hour: int = 8  # Eastern; earliest hour a due run may start
    photo_analysis_enabled: bool = True

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


def load_recipients() -> list:
    """RECIPIENT1..N from the environment / .env files (never stored in the database)."""
    import os

    from dotenv import dotenv_values

    from app.notifications.digest import recipients_from_env

    env: dict[str, str | None] = {}
    for f in (_ROOT / ".env", _ROOT / "backend" / ".env"):
        if f.exists():
            env.update(dotenv_values(f))
    env.update({k: v for k, v in os.environ.items() if k.startswith("RECIPIENT")})
    return recipients_from_env(env)
