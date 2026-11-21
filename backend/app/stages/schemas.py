from datetime import date, datetime
from uuid import UUID

from pydantic import Field, field_validator

from app.accounts.schemas import UserBriefOut
from app.core.schemas import BaseSchema
from app.stages.models import StageStatus


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip() or None


class StageCreateIn(BaseSchema):
    title: str = Field(min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=20_000)
    deadline: date | None = None
    responsible_id: UUID | None = Field(default=None, description="Участник проекта")
    is_required: bool = True

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("empty")
        return value

    @field_validator("description")
    @classmethod
    def clean_description(cls, value: str | None) -> str | None:
        return _clean(value)


class StageUpdateIn(BaseSchema):
    """Передаются только изменяемые поля. Статус меняется отдельным запросом."""

    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=20_000)
    deadline: date | None = None
    responsible_id: UUID | None = None
    is_required: bool | None = None

    @field_validator("title")
    @classmethod
    def title_not_null(cls, value: str | None) -> str:
        if value is None or not value.strip():
            raise ValueError("required")
        return value.strip()

    @field_validator("is_required")
    @classmethod
    def required_not_null(cls, value: bool | None) -> bool:
        if value is None:
            raise ValueError("required")
        return value

    @field_validator("description")
    @classmethod
    def clean_description(cls, value: str | None) -> str | None:
        return _clean(value)


class StageOrderIn(BaseSchema):
    stage_ids: list[UUID] = Field(description="Все этапы работы в новом порядке", max_length=500)


class StatusChangeIn(BaseSchema):
    status: StageStatus
    comment: str | None = Field(default=None, max_length=5000, description="Например, причина возврата на доработку")

    @field_validator("comment")
    @classmethod
    def clean_comment(cls, value: str | None) -> str | None:
        return _clean(value)


class BlockedByOut(BaseSchema):
    id: UUID
    title: str
    status: StageStatus


class StageOut(BaseSchema):
    id: UUID
    work_id: UUID
    title: str
    description: str | None
    position: int
    deadline: date | None
    responsible: UserBriefOut | None
    is_required: bool
    status: StageStatus
    is_blocked: bool = Field(description="Этап нельзя начать, пока не завершён обязательный этап выше")
    blocked_by: BlockedByOut | None = Field(description="Какой этап блокирует — для понятной причины в интерфейсе")
    available_transitions: list[StageStatus] = Field(description="Статусы, в которые текущий пользователь может перевести этап")
    created_at: datetime
    updated_at: datetime


class TransitionOut(BaseSchema):
    id: UUID
    from_status: StageStatus | None
    to_status: StageStatus
    actor: UserBriefOut | None
    comment: str | None
    created_at: datetime
