"""Прогресс работ и проектов (B5).

Правило (согласовано с Frontend):
- прогресс работы  = завершённые этапы работы / все этапы работы;
- прогресс проекта = завершённые этапы всех работ проекта / все этапы всех работ проекта.

Руководитель видит в проекте только свои работы, поэтому и прогресс проекта для него считается
только по ним.

Карточки проектов и работ берут прогресс отсюда: это единственное место, где он вычисляется.
"""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.schemas import ProgressOut, progress
from app.stages.models import Stage, StageStatus
from app.works.models import ResearchWork

_completed = func.count().filter(Stage.status == StageStatus.COMPLETED)


async def works_progress(db: AsyncSession, work_ids: list[UUID]) -> dict[UUID, ProgressOut]:
    if not work_ids:
        return {}
    rows = await db.execute(
        select(Stage.work_id, _completed, func.count()).where(Stage.work_id.in_(work_ids)).group_by(Stage.work_id)
    )
    found = {work_id: progress(done, total) for work_id, done, total in rows.all()}
    return {work_id: found.get(work_id, progress(0, 0)) for work_id in work_ids}


async def projects_progress(
    db: AsyncSession, project_ids: list[UUID], *, supervisor_projects: dict[UUID, UUID] | None = None
) -> dict[UUID, ProgressOut]:
    """supervisor_projects: {project_id: user_id} — проекты, где прогресс считается только по работам руководителя."""
    supervisor_projects = supervisor_projects or {}
    result = {project_id: progress(0, 0) for project_id in project_ids}

    base = (
        select(ResearchWork.project_id, _completed, func.count())
        .join(Stage, Stage.work_id == ResearchWork.id)
        .group_by(ResearchWork.project_id)
    )

    regular = [p for p in project_ids if p not in supervisor_projects]
    if regular:
        rows = await db.execute(base.where(ResearchWork.project_id.in_(regular)))
        for project_id, done, total in rows.all():
            result[project_id] = progress(done, total)

    for project_id, user_id in supervisor_projects.items():
        if project_id not in result:
            continue
        row = (
            await db.execute(
                base.where(ResearchWork.project_id == project_id, ResearchWork.supervisor_id == user_id)
            )
        ).first()
        if row:
            result[project_id] = progress(row[1], row[2])
    return result
