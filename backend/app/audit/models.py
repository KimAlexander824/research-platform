"""Журнал значимых действий (B3)."""

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, IdMixin

if TYPE_CHECKING:
    from app.accounts.models import User


class AuditLog(IdMixin, Base):
    __tablename__ = "audit_logs"

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    # Кто выполнил действие. NULL — система или консольная команда
    actor_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    # Что произошло, например "user.registered", "user.role_changed"
    action: Mapped[str] = mapped_column(String(64), index=True)
    # Над чем: тип и id сущности
    entity_type: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str | None] = mapped_column(String(64), index=True)
    # Подробности: изменённые поля {"поле": [старое, новое]} и т.п. Пароли и токены сюда не пишутся
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    ip_address: Mapped[str | None] = mapped_column(String(64))

    actor: Mapped["User | None"] = relationship(lazy="raise")

    def __str__(self) -> str:
        return f"{self.action} {self.entity_type}:{self.entity_id}"
