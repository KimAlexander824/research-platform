"""Этапы научной работы: бизнес-логика (B5)."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.accounts.models import User
from app.audit.service import AuditLogger, diff
from app.projects.permissions import ProjectAccess, ProjectAction, ProjectArchivedError
from app.stages import rules
from app.stages.exceptions import (
    InvalidStageOrderError,
    ResponsibleNotMemberError,
    StageLockedFieldError,
    StageNotFoundError,
    TransitionDeniedError,
)
from app.stages.models import Stage, StageStatus, StageTransition
from app.stages.repository import StageRepository
from app.stages.schemas import StageCreateIn, StageOrderIn, StageUpdateIn, StatusChangeIn
from app.works.models import ResearchWork
from app.works.service import WorkService


@dataclass(frozen=True)
class StageView:
    """Этап вместе с вычисленными данными для текущего пользователя."""

    stage: Stage
    blocked_by: Stage | None
    available_transitions: list[StageStatus]


class StageService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.stages = StageRepository(db)
        self.works = WorkService(db)
        self.audit = AuditLogger(db)

    # --- Чтение ---

    async def list_stages(self, access: ProjectAccess, user: User, work_id: UUID) -> list[StageView]:
        work = await self.works.get(access, user, work_id)
        return self._views(access, user, work, await self.stages.list_for_work(work.id))

    async def get(self, access: ProjectAccess, user: User, work_id: UUID, stage_id: UUID) -> StageView:
        work = await self.works.get(access, user, work_id)
        return self._find(self._views(access, user, work, await self.stages.list_for_work(work.id)), stage_id)

    async def history(self, access: ProjectAccess, user: User, work_id: UUID, stage_id: UUID) -> list[StageTransition]:
        await self.get(access, user, work_id, stage_id)  # проверка доступа и существования
        return await self.stages.history(stage_id)

    # --- Изменение этапов ---

    async def create(self, access: ProjectAccess, user: User, work_id: UUID, data: StageCreateIn) -> StageView:
        access.require(ProjectAction.EDIT)
        work = await self.works.get(access, user, work_id)
        await self._check_responsible(access, data.responsible_id)

        stage = Stage(
            work_id=work.id,
            position=await self.stages.next_position(work.id),
            status=StageStatus.NOT_STARTED,
            **data.model_dump(),
        )
        self.stages.add(stage)
        await self.db.flush()
        self.stages.add(StageTransition(stage_id=stage.id, from_status=None, to_status=stage.status, actor_id=user.id))
        self.audit.log(
            "stage.created", entity_type="stage", entity_id=stage.id, actor_id=user.id,
            data={"work_id": work.id, "title": stage.title, "is_required": stage.is_required},
        )
        await self.db.commit()
        return await self.get(access, user, work.id, stage.id)

    async def update(
        self, access: ProjectAccess, user: User, work_id: UUID, stage_id: UUID, data: StageUpdateIn
    ) -> StageView:
        access.require(ProjectAction.EDIT)
        stage = (await self.get(access, user, work_id, stage_id)).stage
        new = data.model_dump(exclude_unset=True)

        if "is_required" in new and new["is_required"] != stage.is_required and stage.status != StageStatus.NOT_STARTED:
            # Иначе можно было бы обойти проверку руководителя, сняв обязательность с начатого этапа
            raise StageLockedFieldError()
        if new.get("responsible_id"):
            await self._check_responsible(access, new["responsible_id"])

        old = {field: getattr(stage, field) for field in new}
        for field, value in new.items():
            setattr(stage, field, value)
        changes = diff(old, new)
        if changes:
            self.audit.log("stage.updated", entity_type="stage", entity_id=stage.id, actor_id=user.id, data=changes)
        await self.db.commit()
        return await self.get(access, user, work_id, stage_id)

    async def delete(self, access: ProjectAccess, user: User, work_id: UUID, stage_id: UUID) -> None:
        access.require(ProjectAction.EDIT)
        work = await self.works.get(access, user, work_id)
        stages = await self.stages.list_for_work(work.id, for_update=True)
        stage = self._find_stage(stages, stage_id)
        if stage.is_required and stage.status != StageStatus.NOT_STARTED:
            raise StageLockedFieldError()

        self.audit.log(
            "stage.deleted", entity_type="stage", entity_id=stage.id, actor_id=user.id,
            data={"work_id": work.id, "title": stage.title},
        )
        await self.db.delete(stage)
        # Порядок без «дыр»: 0, 1, 2, ...
        for position, remaining in enumerate(s for s in stages if s.id != stage.id):
            remaining.position = position
        await self.db.commit()

    async def reorder(self, access: ProjectAccess, user: User, work_id: UUID, data: StageOrderIn) -> list[StageView]:
        access.require(ProjectAction.EDIT)
        work = await self.works.get(access, user, work_id)
        stages = await self.stages.list_for_work(work.id, for_update=True)
        by_id = {s.id: s for s in stages}
        if len(data.stage_ids) != len(by_id) or set(data.stage_ids) != set(by_id):
            raise InvalidStageOrderError()

        old_order = [s.id for s in stages]
        for position, stage_id in enumerate(data.stage_ids):
            by_id[stage_id].position = position
        if old_order != data.stage_ids:
            self.audit.log(
                "stage.reordered", entity_type="research_work", entity_id=work.id, actor_id=user.id,
                data={"order": [str(i) for i in data.stage_ids]},
            )
        await self.db.commit()
        return await self.list_stages(access, user, work.id)

    # --- Статусы ---

    async def change_status(
        self, access: ProjectAccess, user: User, work_id: UUID, stage_id: UUID, data: StatusChangeIn
    ) -> StageView:
        if access.project.is_archived:
            raise ProjectArchivedError()
        work = await self.works.get(access, user, work_id)
        stages = await self.stages.list_for_work(work.id, for_update=True)
        stage = self._find_stage(stages, stage_id)
        blockers = rules.blocking_index([rules.StageState(s.status, s.is_required) for s in stages])
        index = stages.index(stage)

        denied = rules.check(
            self._actors(access, user, work),
            stage.status,
            data.status,
            self._context(work, stage, blocked=blockers[index] is not None),
        )
        if denied is not None:
            raise TransitionDeniedError(denied)

        old_status = stage.status
        stage.status = data.status
        self.stages.add(
            StageTransition(
                stage_id=stage.id, from_status=old_status, to_status=data.status, actor_id=user.id, comment=data.comment
            )
        )
        self.audit.log(
            "stage.status_changed", entity_type="stage", entity_id=stage.id, actor_id=user.id,
            data={"status": [old_status, data.status], "comment": data.comment, "work_id": work.id},
        )
        await self.db.commit()
        return await self.get(access, user, work.id, stage.id)

    # --- Вспомогательное ---

    @staticmethod
    def _actors(access: ProjectAccess, user: User, work: ResearchWork) -> set[rules.Actor]:
        actors: set[rules.Actor] = set()
        if access.can(ProjectAction.EDIT):
            actors.add(rules.Actor.RESEARCHER)
        if work.supervisor_id is not None and work.supervisor_id == user.id:
            actors.add(rules.Actor.SUPERVISOR)
        return actors

    @staticmethod
    def _context(work: ResearchWork, stage: Stage, *, blocked: bool) -> rules.Context:
        return rules.Context(
            is_required=stage.is_required,
            # «Руководителя нет» — значит, нет руководителя на платформе (ФИО без аккаунта не считается)
            work_has_supervisor=work.supervisor_id is not None,
            blocked=blocked,
        )

    def _views(self, access: ProjectAccess, user: User, work: ResearchWork, stages: list[Stage]) -> list[StageView]:
        blockers = rules.blocking_index([rules.StageState(s.status, s.is_required) for s in stages])
        actors = set() if access.project.is_archived else self._actors(access, user, work)
        views = []
        for stage, blocker in zip(stages, blockers, strict=True):
            ctx = self._context(work, stage, blocked=blocker is not None)
            views.append(
                StageView(
                    stage=stage,
                    blocked_by=stages[blocker] if blocker is not None else None,
                    available_transitions=rules.available(actors, stage.status, ctx),
                )
            )
        return views

    @staticmethod
    def _find(views: list[StageView], stage_id: UUID) -> StageView:
        for view in views:
            if view.stage.id == stage_id:
                return view
        raise StageNotFoundError()

    @staticmethod
    def _find_stage(stages: list[Stage], stage_id: UUID) -> Stage:
        for stage in stages:
            if stage.id == stage_id:
                return stage
        raise StageNotFoundError()

    async def _check_responsible(self, access: ProjectAccess, user_id: UUID | None) -> None:
        if user_id is not None and not await self.stages.is_project_member(access.project.id, user_id):
            raise ResponsibleNotMemberError()
