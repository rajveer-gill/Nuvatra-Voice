"""
Central application settings (environment variables).

Loaded after dotenv in main; use get_settings() for a cached singleton.
"""

from __future__ import annotations

from functools import lru_cache
from typing import List, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    openai_api_key: str = Field(default="", validation_alias="OPENAI_API_KEY")
    database_url: Optional[str] = Field(default=None, validation_alias="DATABASE_URL")
    frontend_url: Optional[str] = Field(default=None, validation_alias="FRONTEND_URL")
    cron_secret: Optional[str] = Field(default=None, validation_alias="CRON_SECRET")
    twilio_account_sid: Optional[str] = Field(default=None, validation_alias="TWILIO_ACCOUNT_SID")
    twilio_auth_token: Optional[str] = Field(default=None, validation_alias="TWILIO_AUTH_TOKEN")
    twilio_phone_number: Optional[str] = Field(default=None, validation_alias="TWILIO_PHONE_NUMBER")
    stripe_webhook_secret: Optional[str] = Field(default=None, validation_alias="STRIPE_WEBHOOK_SECRET")
    sentry_dsn: Optional[str] = Field(default=None, validation_alias="SENTRY_DSN")
    sentry_environment: str = Field(default="development", validation_alias="SENTRY_ENVIRONMENT")
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")
    ngrok_url: Optional[str] = Field(default=None, validation_alias="NGROK_URL")

    def cors_origins(self) -> List[str]:
        origins = [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "https://nuvatrasite.netlify.app",
            "https://nuvatra-voice.vercel.app",
            "https://nuvatrahq.com",
        ]
        if self.frontend_url:
            u = self.frontend_url.rstrip("/")
            if u not in origins:
                origins.append(u)
        return origins


@lru_cache
def get_settings() -> Settings:
    return Settings()
