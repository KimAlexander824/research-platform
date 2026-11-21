"""Запросы к БД для проектов, участников и приглашений.

Списки проектов всегда строятся через членство: пользователь получает только проекты,
в которых он участвует (B3, B12).
"""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.accounts.models import User
from app.projects.models import InvitationStatus, Project, ProjectInvitation, ProjectMember, ProjectRole


class ProjectRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    def add(self, obj: Project | ProjectMember | ProjectInvitation) -> None:
        self.db.add(obj)

    async def get_with_role(self, project_id: UUID, user_id: UUID) -> tuple[Project, ProjectRole] | None:
        row = (
            await self.db.execute(
                select(Project, ProjectMember.role)
                .join(ProjectMember, ProjectMember.project_id == Project.id)
                .where(Project.id == project_id, ProjectMember.user_id == user_id)
                .options(selectinload(Project.owner))
            )
        ).first()
        return (row[0], row[1]) if row else None

    def list_query(
        self,
        user_id: UUID,
        *,
        search: str | None,
        archived: bool | None,
        role: ProjectRole | None,
    ) -> Select:  # type: ignore[type-arg]
        query = (
            select(Project)
            .join(ProjectMember, ProjectMember.project_id == Project.id)
            .where(ProjectMember.user_id == user_id)
            .options(selectinload(Project.owner))
        )
        if search:
            pattern = f"%{search}%"
            query = query.where(or_(Project.title.ilike(pattern), Project.description.ilike(pattern)))
        if archived is True:
            query = query.where(Project.archived_at.is_not(None))
        elif archived is False:
            query = query.where(Project.archived_at.is_(None))
        if role is not None:
            query = query.where(ProjectMember.role == role)
        return query

    async def roles_for(self, user_id: UUID, project_ids: list[UUID]) -> dict[UUID, ProjectRole]:
        rows = await self.db.execute(
            select(ProjectMember.project_id, ProjectMember.role).where(
                ProjectMember.user_id == user_id, ProjectMember.project_id.in_(project_ids)
            )
        )
        return {project_id: role for project_id, role in rows.all()}

    async def members_count(self, project_ids: list[UUID]) -> dict[UUID, int]:
        rows = await self.db.execute(
            select(ProjectMember.project_id, func.count())
            .where(ProjectMember.project_id.in_(project_ids))
            .group_by(ProjectMember.project_id)
        )
        return {project_id: count for project_id, count in rows.all()}

    # --- Участники ---

    async def list_members(self, project_id: UUID) -> list[ProjectMember]:
        result = await self.db.scalars(
            select(ProjectMember)
            .where(ProjectMember.project_id == project_id)
            .options(selectinload(ProjectMember.user))
            .order_by(ProjectMember.joined_at)
        )
        return list(result.all())

    async def get_member(self, project_id: UUID, user_id: UUID) -> ProjectMember | None:
        return await self.db.scalar(
            select(ProjectMember)
            .where(ProjectMember.project_id == project_id, ProjectMember.user_id == user_id)
            .options(selectinload(ProjectMember.user))
        )

    async def is_member_by_email(self, project_id: UUID, email: str) -> bool:
        count = await self.db.scalar(
            select(func.count())
            .select_from(ProjectMember)
            .join(User, User.id == ProjectMember.user_id)
            .where(ProjectMember.project_id == project_id, User.email == email)
        )
        return bool(count)

    # --- Приглашения ---

    async def get_invitation(self, invitation_id: UUID, *, for_update: bool = False) -> ProjectInvitation | None:
        query = (
            select(ProjectInvitation)
            .where(ProjectInvitation.id == invitation_id)
            .options(selectinload(ProjectInvitation.project), selectinload(ProjectInvitation.invited_by))
        )
        if for_update:
            query = query.with_for_update(of=ProjectInvitation)
        return await self.db.scalar(query)

    async def get_pending_invitation(self, project_id: UUID, email: str) -> ProjectInvitation | None:
        return await self.db.scalar(
            select(ProjectInvitation).where(
                ProjectInvitation.project_id == project_id,
                ProjectInvitation.email == email,
                ProjectInvitation.status == InvitationStatus.PENDING,
            )
        )

    async def list_project_invitations(self, project_id: UUID) -> list[ProjectInvitation]:
        result = await self.db.scalars(
            select(ProjectInvitation)
            .where(ProjectInvitation.project_id == project_id)
            .options(selectinload(ProjectInvitation.project), selectinload(ProjectInvitation.invited_by))
            .order_by(ProjectInvitation.created_at.desc())
        )
        return list(result.all())

    async def list_pending_for_email(self, email: str) -> list[ProjectInvitation]:
        result = await self.db.scalars(
            select(ProjectInvitation)
            .where(
                ProjectInvitation.email == email,
                ProjectInvitation.status == InvitationStatus.PENDING,
                ProjectInvitation.expires_at > datetime.now(UTC),
            )
            .options(selectinload(ProjectInvitation.project), selectinload(ProjectInvitation.invited_by))
            .order_by(ProjectInvitation.created_at.desc())
        )
        return list(result.all())
