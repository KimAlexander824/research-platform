"""Проекты, участники и приглашения (B3, B4)."""

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, IdMixin, TimestampMixin, str_enum

if TYPE_CHECKING:
    from app.accounts.models import User


class ProjectRole(StrEnum):
    """Роль пользователя внутри конкретного проекта."""

    OWNER = "owner"  # владелец: всё, включая участников, архив и удаление
    EDITOR = "editor"  # участник-соавтор: работает с материалами проекта
    VIEWER = "viewer"  # только просмотр
    SUPERVISOR = "supervisor"  # руководитель: просмотр, комментарии, проверка этапов


class InvitationStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    REVOKED = "revoked"
    EXPIRED = "expired"  # в БД не хранится: вычисляется по expires_at


class Project(IdMixin, TimestampMixin, Base):
    __tablename__ = "projects"

    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    owner: Mapped["User"] = relationship(lazy="raise")
    members: Mapped[list["ProjectMember"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", passive_deletes=True, lazy="raise"
    )
    invitations: Mapped[list["ProjectInvitation"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", passive_deletes=True, lazy="raise"
    )

    @property
    def is_archived(self) -> bool:
        return self.archived_at is not None

    def __str__(self) -> str:
        return self.title


class ProjectMember(IdMixin, Base):
    __tablename__ = "project_members"
    __table_args__ = (UniqueConstraint("project_id", "user_id"),)

    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[ProjectRole] = mapped_column(str_enum(ProjectRole))
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped[Project] = relationship(back_populates="members", lazy="raise")
    user: Mapped["User"] = relationship(lazy="raise")


class ProjectInvitation(IdMixin, Base):
    """Приглашение в проект по email. Принять его может только пользователь с этим подтверждённым email."""

    __tablename__ = "project_invitations"
    __table_args__ = (
        # Одно активное приглашение на email в проекте
        Index(
            "uq_project_invitations_pending",
            "project_id",
            "email",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
    )

    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(320), index=True)
    role: Mapped[ProjectRole] = mapped_column(str_enum(ProjectRole))
    status: Mapped[InvitationStatus] = mapped_column(str_enum(InvitationStatus), default=InvitationStatus.PENDING)
    invited_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    project: Mapped[Project] = relationship(back_populates="invitations", lazy="raise")
    invited_by: Mapped["User | None"] = relationship(lazy="raise")

    def effective_status(self, now: datetime) -> InvitationStatus:
        if self.status == InvitationStatus.PENDING and self.expires_at <= now:
            return InvitationStatus.EXPIRED
        return self.status
