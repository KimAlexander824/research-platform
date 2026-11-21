from datetime import date, datetime
from typing import Any, Self
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from app.accounts.schemas import UserBriefOut
from app.core.schemas import BaseSchema, ProgressOut
from app.works.models import WorkType

MAX_AUTHORS = 50

_LONG_TEXT = 20_000

_OPTIONAL_TEXT_FIELDS = (
    "custom_type_name",
    "description",
    "supervisor_name",
    "direction",
    "topic",
    "goal",
    "tasks",
    "hypothesis",
    "research_object",
    "research_subject",
    "methodology",
)


def _clean(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip() or None
    return value


class AuthorIn(BaseSchema):
    """Укажите userId (участник проекта) или fullName (человек вне платформы)."""

    user_id: UUID | None = None
    full_name: str | None = Field(default=None, max_length=255)

    @field_validator("full_name")
    @classmethod
    def clean_name(cls, value: str | None) -> str | None:
        return _clean(value)

    @model_validator(mode="after")
    def one_of(self) -> Self:
        if (self.user_id is None) == (self.full_name is None):
            raise ValueError("specify either userId or fullName")
        return self


class _WorkFields(BaseSchema):
    custom_type_name: str | None = Field(default=None, max_length=255, description="Обязателен для type=custom")
    description: str | None = Field(default=None, max_length=_LONG_TEXT)
    supervisor_id: UUID | None = Field(default=None, description="Участник проекта с ролью supervisor")
    supervisor_name: str | None = Field(default=None, max_length=255, description="ФИО, если руководитель не на платформе")
    direction: str | None = Field(default=None, max_length=500)
    topic: str | None = Field(default=None, max_length=_LONG_TEXT)
    goal: str | None = Field(default=None, max_length=_LONG_TEXT)
    tasks: str | None = Field(default=None, max_length=_LONG_TEXT)
    hypothesis: str | None = Field(default=None, max_length=_LONG_TEXT)
    research_object: str | None = Field(default=None, max_length=_LONG_TEXT)
    research_subject: str | None = Field(default=None, max_length=_LONG_TEXT)
    methodology: str | None = Field(default=None, max_length=_LONG_TEXT)
    start_date: date | None = None
    end_date: date | None = None
    authors: list[AuthorIn] | None = Field(
        default=None,
        max_length=MAX_AUTHORS,
        description="Первый — автор, остальные — соавторы. Список заменяется целиком.",
    )

    @field_validator(*_OPTIONAL_TEXT_FIELDS)
    @classmethod
    def clean_text(cls, value: str | None) -> str | None:
        return _clean(value)


class WorkCreateIn(_WorkFields):
    title: str = Field(min_length=1, max_length=500)
    type: WorkType

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("empty")
        return value


class WorkUpdateIn(_WorkFields):
    """Передаются только изменяемые поля. null очищает необязательное поле."""

    title: str | None = Field(default=None, min_length=1, max_length=500)
    type: WorkType | None = None

    @field_validator("title")
    @classmethod
    def title_not_null(cls, value: str | None) -> str:
        if value is None or not value.strip():
            raise ValueError("required")
        return value.strip()

    @field_validator("type")
    @classmethod
    def type_not_null(cls, value: WorkType | None) -> WorkType:
        if value is None:
            raise ValueError("required")
        return value

    @field_validator("authors")
    @classmethod
    def authors_not_null(cls, value: list[AuthorIn] | None) -> list[AuthorIn]:
        if value is None:
            raise ValueError("required")
        return value


class AuthorOut(BaseSchema):
    user: UserBriefOut | None
    full_name: str
    position: int


class WorkOut(BaseSchema):
    id: UUID
    project_id: UUID
    title: str
    type: WorkType
    custom_type_name: str | None
    description: str | None
    authors: list[AuthorOut]
    supervisor: UserBriefOut | None
    supervisor_name: str | None
    direction: str | None
    topic: str | None
    goal: str | None
    tasks: str | None
    hypothesis: str | None
    research_object: str | None
    research_subject: str | None
    methodology: str | None
    start_date: date | None
    end_date: date | None
    progress: ProgressOut
    created_at: datetime
    updated_at: datetime
