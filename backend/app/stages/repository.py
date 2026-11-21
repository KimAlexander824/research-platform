from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.projects.models import ProjectMember
from app.stages.models import Stage, StageTransition


class StageRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    def add(self, obj: Stage | StageTransition) -> None:
        self.db.add(obj)

    async def list_for_work(self, work_id: UUID, *, for_update: bool = False) -> list[Stage]:
        query = (
            select(Stage)
            .where(Stage.work_id == work_id)
            .options(selectinload(Stage.responsible))
            .order_by(Stage.position)
            .execution_options(populate_existing=True)
        )
        if for_update:
            query = query.with_for_update(of=Stage)
        return list((await self.db.scalars(query)).all())

    async def next_position(self, work_id: UUID) -> int:
        current = await self.db.scalar(select(func.max(Stage.position)).where(Stage.work_id == work_id))
        return 0 if current is None else current + 1

    async def is_project_member(self, project_id: UUID, user_id: UUID) -> bool:
        count = await self.db.scalar(
            select(func.count())
            .select_from(ProjectMember)
            .where(ProjectMember.project_id == project_id, ProjectMember.user_id == user_id)
        )
        return bool(count)

    async def history(self, stage_id: UUID) -> list[StageTransition]:
        result = await self.db.scalars(
            select(StageTransition)
            .where(StageTransition.stage_id == stage_id)
            .options(selectinload(StageTransition.actor))
            .order_by(StageTransition.created_at, StageTransition.id)
        )
        return list(result.all())
