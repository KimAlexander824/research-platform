from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import EmailStr, Field, field_validator

from app.accounts.schemas import UserBriefOut
from app.core.schemas import BaseSchema, ProgressOut
from app.projects.models import InvitationStatus, ProjectRole


def _strip_required(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("empty")
    return value


def _strip_optional(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip() or None


# --- Проекты ---


class ProjectCreateIn(BaseSchema):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=10_000)

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        return _strip_required(value)

    @field_validator("description")
    @classmethod
    def clean_description(cls, value: str | None) -> str | None:
        return _strip_optional(value)


class ProjectUpdateIn(BaseSchema):
    """Передаются только изменяемые поля."""

    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=10_000)

    @field_validator("title")
    @classmethod
    def title_not_null(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("required")
        return _strip_required(value)

    @field_validator("description")
    @classmethod
    def clean_description(cls, value: str | None) -> str | None:
        return _strip_optional(value)


class ProjectStatusFilter(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    ALL = "all"


class ProjectOut(BaseSchema):
    id: UUID
    title: str
    description: str | None
    is_archived: bool
    archived_at: datetime | None
    owner: UserBriefOut
    my_role: ProjectRole
    members_count: int
    progress: ProgressOut = Field(description="Завершённые этапы всех работ / все этапы (для руководителя — только его работ)")
    created_at: datetime
    updated_at: datetime


# --- Участники ---


class MemberOut(BaseSchema):
    user: UserBriefOut
    role: ProjectRole
    joined_at: datetime


class MemberRoleIn(BaseSchema):
    role: ProjectRole

    @field_validator("role")
    @classmethod
    def not_owner(cls, value: ProjectRole) -> ProjectRole:
        if value == ProjectRole.OWNER:
            raise ValueError("owner role cannot be assigned")
        return value


# --- Приглашения ---


class InvitationCreateIn(BaseSchema):
    email: EmailStr
    role: ProjectRole

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("role")
    @classmethod
    def not_owner(cls, value: ProjectRole) -> ProjectRole:
        if value == ProjectRole.OWNER:
            raise ValueError("owner role cannot be assigned")
        return value


class ProjectBriefOut(BaseSchema):
    id: UUID
    title: str


class InvitationOut(BaseSchema):
    id: UUID
    project: ProjectBriefOut
    email: str
    role: ProjectRole
    status: InvitationStatus
    invited_by: UserBriefOut | None
    created_at: datetime
    expires_at: datetime
    responded_at: datetime | None
