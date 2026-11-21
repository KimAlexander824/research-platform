from uuid import UUID

from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.projects.models import ProjectMember, ProjectRole
from app.works.models import ResearchWork, WorkAuthor, WorkType


def _with_relations(query: Select) -> Select:  # type: ignore[type-arg]
    return query.options(
        selectinload(ResearchWork.authors).selectinload(WorkAuthor.user),
        selectinload(ResearchWork.supervisor),
    )


class WorkRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    def add(self, work: ResearchWork) -> None:
        self.db.add(work)

    async def get(
        self, project_id: UUID, work_id: UUID, *, supervisor_id: UUID | None = None
    ) -> ResearchWork | None:
        query = select(ResearchWork).where(ResearchWork.id == work_id, ResearchWork.project_id == project_id)
        if supervisor_id is not None:
            query = query.where(ResearchWork.supervisor_id == supervisor_id)
        return await self.db.scalar(_with_relations(query).execution_options(populate_existing=True))

    def list_query(
        self,
        project_id: UUID,
        *,
        search: str | None,
        work_type: WorkType | None,
        supervisor_id: UUID | None = None,
    ) -> Select:  # type: ignore[type-arg]
        query = _with_relations(select(ResearchWork).where(ResearchWork.project_id == project_id))
        if supervisor_id is not None:
            query = query.where(ResearchWork.supervisor_id == supervisor_id)
        if search:
            pattern = f"%{search}%"
            query = query.where(
                or_(
                    ResearchWork.title.ilike(pattern),
                    ResearchWork.topic.ilike(pattern),
                    ResearchWork.description.ilike(pattern),
                )
            )
        if work_type is not None:
            query = query.where(ResearchWork.type == work_type)
        return query

    async def member_roles(self, project_id: UUID, user_ids: set[UUID]) -> dict[UUID, ProjectRole]:
        if not user_ids:
            return {}
        rows = await self.db.execute(
            select(ProjectMember.user_id, ProjectMember.role).where(
                ProjectMember.project_id == project_id, ProjectMember.user_id.in_(user_ids)
            )
        )
        return {user_id: role for user_id, role in rows.all()}
