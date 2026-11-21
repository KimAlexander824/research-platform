"""Эндпоинты научных работ проекта (B4)."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.accounts.dependencies import CurrentUserDep, DbSession
from app.core.pagination import Page, PageParams, page_params
from app.core.storage import Storage
from app.projects.dependencies import ProjectAccessDep, StorageDep
from app.projects.router import user_brief
from app.works.models import ResearchWork, WorkType
from app.works.schemas import AuthorOut, WorkCreateIn, WorkOut, WorkUpdateIn
from app.works.service import WorkService

router = APIRouter(prefix="/projects/{project_id}/works", tags=["Научные работы"])


def get_work_service(db: DbSession) -> WorkService:
    return WorkService(db)


WorkServiceDep = Annotated[WorkService, Depends(get_work_service)]


def work_out(work: ResearchWork, storage: Storage) -> WorkOut:
    authors = [
        AuthorOut(
            user=user_brief(a.user, storage) if a.user else None,
            full_name=a.user.full_name if a.user else (a.full_name or ""),
            position=a.position,
        )
        for a in work.authors
    ]
    return WorkOut(
        id=work.id,
        project_id=work.project_id,
        title=work.title,
        type=work.type,
        custom_type_name=work.custom_type_name,
        description=work.description,
        authors=authors,
        supervisor=user_brief(work.supervisor, storage) if work.supervisor else None,
        supervisor_name=work.supervisor.full_name if work.supervisor else work.supervisor_name,
        direction=work.direction,
        topic=work.topic,
        goal=work.goal,
        tasks=work.tasks,
        hypothesis=work.hypothesis,
        research_object=work.research_object,
        research_subject=work.research_subject,
        methodology=work.methodology,
        start_date=work.start_date,
        end_date=work.end_date,
        created_at=work.created_at,
        updated_at=work.updated_at,
    )


@router.get(
    "",
    summary="Научные работы проекта",
    description="Руководитель видит только работы, где он указан руководителем. Сортировка: `createdAt`, `updatedAt`, `title`, `startDate`, `endDate` "
    "(минус — по убыванию, по умолчанию `-updatedAt`).",
)
async def list_works(
    access: ProjectAccessDep,
    current: CurrentUserDep,
    service: WorkServiceDep,
    storage: StorageDep,
    params: Annotated[PageParams, Depends(page_params)],
    search: Annotated[str | None, Query(max_length=255, description="Поиск по названию, теме и описанию")] = None,
    work_type: Annotated[WorkType | None, Query(alias="type", description="Тип работы")] = None,
    sort: Annotated[str | None, Query()] = None,
) -> Page[WorkOut]:
    works, total = await service.list_works(access, current.user, params, search=search, work_type=work_type, sort=sort)
    return Page(items=[work_out(w, storage) for w in works], total=total, page=params.page, page_size=params.page_size)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Создать научную работу",
    description="Владелец и редакторы проекта. Если `authors` не передан, автором становится создатель. "
    "Для `type=custom` обязателен `customTypeName`.",
)
async def create_work(
    data: WorkCreateIn, access: ProjectAccessDep, current: CurrentUserDep, service: WorkServiceDep, storage: StorageDep
) -> WorkOut:
    return work_out(await service.create(access, current.user, data), storage)


@router.get(
    "/{work_id}",
    summary="Научная работа",
    description="Руководитель видит только работы, где он указан руководителем.",
)
async def get_work(
    work_id: UUID, access: ProjectAccessDep, current: CurrentUserDep, service: WorkServiceDep, storage: StorageDep
) -> WorkOut:
    return work_out(await service.get(access, current.user, work_id), storage)


@router.patch(
    "/{work_id}",
    summary="Редактировать научную работу",
    description="Передаются только изменяемые поля. `authors` заменяется целиком.",
)
async def update_work(
    work_id: UUID,
    data: WorkUpdateIn,
    access: ProjectAccessDep,
    current: CurrentUserDep,
    service: WorkServiceDep,
    storage: StorageDep,
) -> WorkOut:
    return work_out(await service.update(access, current.user, work_id, data), storage)


@router.delete("/{work_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Удалить научную работу")
async def delete_work(work_id: UUID, access: ProjectAccessDep, current: CurrentUserDep, service: WorkServiceDep) -> None:
    await service.delete(access, current.user, work_id)
