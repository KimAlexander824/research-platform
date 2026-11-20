from datetime import datetime
from uuid import UUID

from pydantic import EmailStr, Field, field_validator

from app.accounts.models import UserRole
from app.core.language import Language
from app.core.schemas import BaseSchema

PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128


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
    created_at: datetime


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
