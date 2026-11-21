"""Этапы научной работы (B5).

По решению команды этапы принадлежат научной работе, а не проекту: в проекте может быть несколько работ
с разными руководителями, и каждый руководитель проверяет этапы своей работы.
"""

from datetime import date, datetime
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, IdMixin, TimestampMixin, str_enum

if TYPE_CHECKING:
    from app.accounts.models import User


class StageStatus(StrEnum):
    NOT_STARTED = "not_started"  # не начат
    IN_PROGRESS = "in_progress"  # в процессе
    PENDING_REVIEW = "pending_review"  # ожидает проверки
    NEEDS_REVISION = "needs_revision"  # требует исправлений
    COMPLETED = "completed"  # завершён
    REJECTED = "rejected"  # отклонён — отказ в принятии этапа


class Stage(IdMixin, TimestampMixin, Base):
    __tablename__ = "stages"

    work_id: Mapped[UUID] = mapped_column(ForeignKey("research_works.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer)
    deadline: Mapped[date | None] = mapped_column(Date)
    responsible_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    is_required: Mapped[bool] = mapped_column(default=True)
    status: Mapped[StageStatus] = mapped_column(str_enum(StageStatus), default=StageStatus.NOT_STARTED)

    responsible: Mapped["User | None"] = relationship(lazy="raise")

    def __str__(self) -> str:
        return self.title


class StageTransition(IdMixin, Base):
    """История переходов статуса этапа (B5)."""

    __tablename__ = "stage_transitions"

    stage_id: Mapped[UUID] = mapped_column(ForeignKey("stages.id", ondelete="CASCADE"), index=True)
    from_status: Mapped[StageStatus | None] = mapped_column(str_enum(StageStatus))
    to_status: Mapped[StageStatus] = mapped_column(str_enum(StageStatus))
    actor_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    actor: Mapped["User | None"] = relationship(lazy="raise")
