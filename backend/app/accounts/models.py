"""Пользователи, профиль и сессии (B2)."""

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, IdMixin, TimestampMixin, str_enum
from app.core.language import DEFAULT_LANGUAGE, Language


class UserRole(StrEnum):
    RESEARCHER = "researcher"
    SUPERVISOR = "supervisor"
    ADMIN = "admin"


class User(IdMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(str_enum(UserRole), default=UserRole.RESEARCHER)
    is_active: Mapped[bool] = mapped_column(default=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    language: Mapped[Language] = mapped_column(
        str_enum(Language, length=5), default=DEFAULT_LANGUAGE, server_default=DEFAULT_LANGUAGE.value
    )

    # Профиль (B2)
    phone: Mapped[str | None] = mapped_column(String(32))
    avatar_key: Mapped[str | None] = mapped_column(String(512))
    # Научная информация
    organization: Mapped[str | None] = mapped_column(String(255))
    position: Mapped[str | None] = mapped_column(String(255))
    academic_degree: Mapped[str | None] = mapped_column(String(255))
    academic_title: Mapped[str | None] = mapped_column(String(255))
    research_interests: Mapped[str | None] = mapped_column(Text)
    # Настройки пользователя (произвольные настройки интерфейса, задаёт фронтенд)
    preferences: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")

    @property
    def email_verified(self) -> bool:
        return self.email_verified_at is not None

    sessions: Mapped[list["UserSession"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )


class UserSession(IdMixin, Base):
    """Сессия = вход с конкретного устройства. Хранит хеш refresh-токена."""

    __tablename__ = "user_sessions"

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    refresh_token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_agent: Mapped[str | None] = mapped_column(String(512))
    ip_address: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="sessions")


class EmailTokenPurpose(StrEnum):
    VERIFY_EMAIL = "verify_email"
    RESET_PASSWORD = "reset_password"


class EmailToken(IdMixin, Base):
    """Одноразовый токен из письма. В БД хранится только хеш."""

    __tablename__ = "email_tokens"

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    purpose: Mapped[EmailTokenPurpose] = mapped_column(str_enum(EmailTokenPurpose))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
