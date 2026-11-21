import json
import re
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import EmailStr, Field, field_validator

from app.accounts.models import UserRole
from app.core.language import Language
from app.core.schemas import BaseSchema

PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128
PHONE_PATTERN = re.compile(r"^\+?[0-9][0-9 ()\-]{5,30}$")
SETTINGS_MAX_BYTES = 10_000


def _normalize_email(value: str) -> str:
    return value.strip().lower()


class RegisterIn(BaseSchema):
    email: EmailStr
    password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)
    full_name: str = Field(min_length=1, max_length=255)
    language: Language | None = Field(
        default=None, description="Язык интерфейса при регистрации; используется для писем"
    )

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return _normalize_email(value)

    @field_validator("full_name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("empty")
        return value


class LoginIn(BaseSchema):
    email: EmailStr
    password: str = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return _normalize_email(value)


class TokenOut(BaseSchema):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Срок жизни access-токена в секундах")


class UserOut(BaseSchema):
    id: UUID
    email: str
    full_name: str
    role: UserRole
    language: Language
    email_verified: bool
    phone: str | None
    avatar_url: str | None = Field(default=None, description="Временная ссылка на фото профиля")
    organization: str | None
    position: str | None
    academic_degree: str | None
    academic_title: str | None
    research_interests: str | None
    settings: dict[str, Any] = Field(validation_alias="preferences")
    created_at: datetime


class UserBriefOut(BaseSchema):
    """Краткие данные пользователя для списков (участники, авторы и т.п.)."""

    id: UUID
    full_name: str
    email: str
    avatar_url: str | None = None


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


class ProfileUpdateIn(BaseSchema):
    """Передаются только изменяемые поля. null очищает необязательное поле."""

    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    phone: str | None = Field(default=None, max_length=32)
    language: Language | None = None
    organization: str | None = Field(default=None, max_length=255)
    position: str | None = Field(default=None, max_length=255)
    academic_degree: str | None = Field(default=None, max_length=255)
    academic_title: str | None = Field(default=None, max_length=255)
    research_interests: str | None = Field(default=None, max_length=5000)
    settings: dict[str, Any] | None = Field(default=None, description="Настройки интерфейса (до 10 КБ)")

    @field_validator("full_name")
    @classmethod
    def strip_name(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("required")
        value = value.strip()
        if not value:
            raise ValueError("empty")
        return value

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str | None) -> str | None:
        value = _clean_optional(value)
        if value is not None and not PHONE_PATTERN.match(value):
            raise ValueError("invalid phone")
        return value

    @field_validator("organization", "position", "academic_degree", "academic_title", "research_interests")
    @classmethod
    def strip_optional(cls, value: str | None) -> str | None:
        return _clean_optional(value)

    @field_validator("language", "settings")
    @classmethod
    def not_null(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("required")
        return value

    @field_validator("settings")
    @classmethod
    def limit_settings_size(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(value, ensure_ascii=False).encode()) > SETTINGS_MAX_BYTES:
            raise ValueError("too long")
        return value


class ChangeEmailIn(BaseSchema):
    new_email: EmailStr
    current_password: str = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)

    @field_validator("new_email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return _normalize_email(value)


class SessionOut(BaseSchema):
    id: UUID
    user_agent: str | None
    ip_address: str | None
    created_at: datetime
    last_used_at: datetime
    expires_at: datetime
    is_current: bool = False


class EmailTokenIn(BaseSchema):
    token: str = Field(min_length=1, max_length=256)


class ForgotPasswordIn(BaseSchema):
    email: EmailStr

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return _normalize_email(value)


class ResetPasswordIn(BaseSchema):
    token: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)
