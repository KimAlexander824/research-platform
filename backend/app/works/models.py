"""Научные работы (B4)."""

from datetime import date
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Date, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, IdMixin, TimestampMixin, str_enum

if TYPE_CHECKING:
    from app.accounts.models import User
    from app.projects.models import Project


class WorkType(StrEnum):
    """Предустановленные типы (B4). Для своего типа — CUSTOM и название в custom_type_name."""

    ARTICLE = "article"  # статья
    RESEARCH = "research"  # исследование
    COURSEWORK = "coursework"  # курсовая
    DIPLOMA = "diploma"  # дипломная
    MASTER_THESIS = "master_thesis"  # магистерская
    DISSERTATION = "dissertation"  # диссертация
    THESES = "theses"  # тезисы
    CONFERENCE_PAPER = "conference_paper"  # конференционная работа
    CUSTOM = "custom"  # другое — пользовательский тип


class ResearchWork(IdMixin, TimestampMixin, Base):
    __tablename__ = "research_works"

    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    created_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    title: Mapped[str] = mapped_column(String(500))
    type: Mapped[WorkType] = mapped_column(str_enum(WorkType, length=32), index=True)
    custom_type_name: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)

    # Руководитель: участник проекта с ролью supervisor или просто ФИО, если он не пользуется платформой
    supervisor_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    supervisor_name: Mapped[str | None] = mapped_column(String(255))

    direction: Mapped[str | None] = mapped_column(String(500))  # научное направление
    topic: Mapped[str | None] = mapped_column(Text)  # тема
    goal: Mapped[str | None] = mapped_column(Text)  # цель
    tasks: Mapped[str | None] = mapped_column(Text)  # задачи
    hypothesis: Mapped[str | None] = mapped_column(Text)  # гипотеза
    research_object: Mapped[str | None] = mapped_column(Text)  # объект исследования
    research_subject: Mapped[str | None] = mapped_column(Text)  # предмет исследования
    methodology: Mapped[str | None] = mapped_column(Text)  # методология

    # Сроки
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)

    project: Mapped["Project"] = relationship(lazy="raise")
    supervisor: Mapped["User | None"] = relationship(foreign_keys=[supervisor_id], lazy="raise")
    authors: Mapped[list["WorkAuthor"]] = relationship(
        back_populates="work",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="WorkAuthor.position",
        lazy="raise",
    )

    def __str__(self) -> str:
        return self.title


class WorkAuthor(IdMixin, Base):
    """Автор или соавтор: участник проекта (user_id) или человек вне платформы (только ФИО).

    Порядок важен: первый в списке — автор, остальные — соавторы.
    """

    __tablename__ = "research_work_authors"

    work_id: Mapped[UUID] = mapped_column(ForeignKey("research_works.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    full_name: Mapped[str | None] = mapped_column(String(255))
    position: Mapped[int] = mapped_column(Integer)

    work: Mapped[ResearchWork] = relationship(back_populates="authors", lazy="raise")
    user: Mapped["User | None"] = relationship(lazy="raise")
