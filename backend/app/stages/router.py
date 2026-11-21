"""Эндпоинты этапов научной работы (B5)."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.accounts.dependencies import CurrentUserDep, DbSession
from app.core.storage import Storage
from app.projects.dependencies import ProjectAccessDep, StorageDep
from app.projects.router import user_brief
from app.stages.schemas import (
    BlockedByOut,
    StageCreateIn,
    StageOrderIn,
    StageOut,
    StageUpdateIn,
    StatusChangeIn,
    TransitionOut,
)
from app.stages.service import StageService, StageView

router = APIRouter(prefix="/projects/{project_id}/works/{work_id}/stages", tags=["Этапы"])


def get_stage_service(db: DbSession) -> StageService:
    return StageService(db)


StageServiceDep = Annotated[StageService, Depends(get_stage_service)]


def stage_out(view: StageView, storage: Storage) -> StageOut:
    stage = view.stage
    return StageOut(
        id=stage.id,
        work_id=stage.work_id,
        title=stage.title,
        description=stage.description,
        position=stage.position,
        deadline=stage.deadline,
        responsible=user_brief(stage.responsible, storage) if stage.responsible else None,
        is_required=stage.is_required,
        status=stage.status,
        is_blocked=view.blocked_by is not None,
        blocked_by=(
            BlockedByOut(id=view.blocked_by.id, title=view.blocked_by.title, status=view.blocked_by.status)
            if view.blocked_by
            else None
        ),
        available_transitions=view.available_transitions,
        created_at=stage.created_at,
        updated_at=stage.updated_at,
    )


@router.get(
    "",
    summary="Этапы работы (roadmap)",
    description="По порядку. Для каждого этапа: заблокирован ли он и чем (`blockedBy`), "
    "и в какие статусы текущий пользователь может его перевести (`availableTransitions`).",
)
async def list_stages(
    work_id: UUID, access: ProjectAccessDep, current: CurrentUserDep, service: StageServiceDep, storage: StorageDep
) -> list[StageOut]:
    return [stage_out(v, storage) for v in await service.list_stages(access, current.user, work_id)]


@router.post("", status_code=status.HTTP_201_CREATED, summary="Добавить этап", description="Добавляется в конец списка.")
async def create_stage(
    work_id: UUID,
    data: StageCreateIn,
    access: ProjectAccessDep,
    current: CurrentUserDep,
    service: StageServiceDep,
    storage: StorageDep,
) -> StageOut:
    return stage_out(await service.create(access, current.user, work_id, data), storage)


@router.put(
    "/order",
    summary="Изменить порядок этапов",
    description="Передаются id всех этапов работы в новом порядке.",
)
async def reorder_stages(
    work_id: UUID,
    data: StageOrderIn,
    access: ProjectAccessDep,
    current: CurrentUserDep,
    service: StageServiceDep,
    storage: StorageDep,
) -> list[StageOut]:
    return [stage_out(v, storage) for v in await service.reorder(access, current.user, work_id, data)]


@router.get("/{stage_id}", summary="Этап")
async def get_stage(
    work_id: UUID,
    stage_id: UUID,
    access: ProjectAccessDep,
    current: CurrentUserDep,
    service: StageServiceDep,
    storage: StorageDep,
) -> StageOut:
    return stage_out(await service.get(access, current.user, work_id, stage_id), storage)


@router.patch(
    "/{stage_id}",
    summary="Редактировать этап",
    description="Передаются только изменяемые поля. Обязательность можно менять только у ещё не начатого этапа.",
)
async def update_stage(
    work_id: UUID,
    stage_id: UUID,
    data: StageUpdateIn,
    access: ProjectAccessDep,
    current: CurrentUserDep,
    service: StageServiceDep,
    storage: StorageDep,
) -> StageOut:
    return stage_out(await service.update(access, current.user, work_id, stage_id, data), storage)


@router.delete(
    "/{stage_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить этап",
    description="Обязательный этап можно удалить, только пока он не начат.",
)
async def delete_stage(
    work_id: UUID, stage_id: UUID, access: ProjectAccessDep, current: CurrentUserDep, service: StageServiceDep
) -> None:
    await service.delete(access, current.user, work_id, stage_id)


@router.post(
    "/{stage_id}/status",
    summary="Изменить статус этапа",
    description="Исследователь: начать, отправить на проверку, завершить (необязательный или если нет руководителя). "
    "Руководитель работы: подтвердить (`completed`), вернуть на доработку (`needs_revision`), отклонить (`rejected`). "
    "Ошибки: `STAGE_BLOCKED`, `SUPERVISOR_REVIEW_REQUIRED`, `NO_SUPERVISOR`, `TRANSITION_NOT_ALLOWED`.",
)
async def change_stage_status(
    work_id: UUID,
    stage_id: UUID,
    data: StatusChangeIn,
    access: ProjectAccessDep,
    current: CurrentUserDep,
    service: StageServiceDep,
    storage: StorageDep,
) -> StageOut:
    return stage_out(await service.change_status(access, current.user, work_id, stage_id, data), storage)


@router.get("/{stage_id}/history", summary="История переходов статуса")
async def stage_history(
    work_id: UUID,
    stage_id: UUID,
    access: ProjectAccessDep,
    current: CurrentUserDep,
    service: StageServiceDep,
    storage: StorageDep,
) -> list[TransitionOut]:
    return [
        TransitionOut(
            id=t.id,
            from_status=t.from_status,
            to_status=t.to_status,
            actor=user_brief(t.actor, storage) if t.actor else None,
            comment=t.comment,
            created_at=t.created_at,
        )
        for t in await service.history(access, current.user, work_id, stage_id)
    ]
