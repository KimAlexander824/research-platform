"""Настройки приложения. Все значения берутся из переменных окружения (или файла .env)."""

from enum import StrEnum
from functools import lru_cache

from typing import Annotated

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Используется только в разработке; в production приложение не запустится с этим значением
DEV_JWT_SECRET = "dev-only-secret-do-not-use-in-production-0000"


class Environment(StrEnum):
    DEVELOPMENT = "development"
    PRODUCTION = "production"


class MailBackend(StrEnum):
    CONSOLE = "console"
    RESEND = "resend"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    APP_NAME: str = "Research Platform API"
    ENVIRONMENT: Environment = Environment.DEVELOPMENT
    LOG_LEVEL: str = "INFO"

    DATABASE_URL: str = "postgresql+asyncpg://research:research@localhost:5432/research"
    REDIS_URL: str = "redis://localhost:6379/0"

    CORS_ORIGINS: Annotated[list[str], NoDecode] = []

    # Авторизация
    JWT_SECRET: str = DEV_JWT_SECRET
    ACCESS_TOKEN_TTL_MINUTES: int = 15
    REFRESH_TOKEN_TTL_DAYS: int = 30
    REFRESH_COOKIE_NAME: str = "refresh_token"

    # Защита от перебора паролей: после N неудачных попыток вход по email блокируется на M минут
    LOGIN_MAX_ATTEMPTS: int = 5
    LOGIN_LOCKOUT_MINUTES: int = 15

    # Ограничение частоты запросов к эндпоинтам авторизации (на один IP)
    AUTH_RATE_LIMIT_PER_MINUTE: int = 20

    # Ссылки из писем ведут на страницы фронтенда
    FRONTEND_URL: str = "http://localhost:5173"
    FRONTEND_VERIFY_EMAIL_PATH: str = "/verify-email"
    FRONTEND_RESET_PASSWORD_PATH: str = "/reset-password"

    # Срок действия ссылок из писем
    EMAIL_VERIFICATION_TTL_HOURS: int = 24
    PASSWORD_RESET_TTL_MINUTES: int = 60
    # Повторно отправить письмо на тот же email можно не чаще, чем раз в N секунд
    EMAIL_RESEND_COOLDOWN_SECONDS: int = 60

    # Почта: console — письма пишутся в лог (разработка), resend — отправка через Resend
    MAIL_BACKEND: MailBackend = MailBackend.CONSOLE
    MAIL_FROM: str = "Research Platform <onboarding@resend.dev>"
    RESEND_API_KEY: str = ""

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @model_validator(mode="after")
    def check_production_secrets(self) -> "Settings":
        if self.ENVIRONMENT == Environment.PRODUCTION and (
            self.JWT_SECRET == DEV_JWT_SECRET or len(self.JWT_SECRET) < 32
        ):
            raise ValueError("JWT_SECRET must be set in production (at least 32 characters)")
        if self.MAIL_BACKEND == MailBackend.RESEND and not self.RESEND_API_KEY:
            raise ValueError("RESEND_API_KEY is required when MAIL_BACKEND=resend")
        return self

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == Environment.PRODUCTION


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
