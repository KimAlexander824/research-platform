"""Эндпоинты проектов, участников и приглашений (B3, B4)."""

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.accounts.dependencies import CurrentUserDep
from app.accounts.models import User
from app.accounts.schemas import UserBriefOut
from app.core.pagination import Page, PageParams, page_params
from app.core.schemas import ProgressOut
from app.core.storage import Storage
from app.projects.dependencies import ProjectAccessDep, ProjectServiceDep, StorageDep
from app.projects.models import Project, ProjectInvitation, ProjectMember, ProjectRole
from app.projects.permissions import ProjectAction
from app.projects.schemas import (
    InvitationCreateIn,
    InvitationOut,
    MemberOut,
    MemberRoleIn,
    ProjectBriefOut,
    ProjectCreateIn,
    ProjectOut,
    ProjectStatusFilter,
    ProjectUpdateIn,
)

router = APIRouter(prefix="/projects", tags=["Проекты"])
invitations_router = APIRouter(prefix="/invitations", tags=["Приглашения"])


def user_brief(user: User, storage: Storage) -> UserBriefOut:
    return UserBriefOut(
        id=user.id,
        full_name=user.full_name,
        email=user.email,
        avatar_url=storage.presigned_get_url(user.avatar_key) if user.avatar_key else None,
    )


def project_out(
    project: Project, role: ProjectRole, members_count: int, project_progress: ProgressOut, storage: Storage
) -> ProjectOut:
    return ProjectOut(
        id=project.id,
        title=project.title,
        description=project.description,
        is_archived=project.is_archived,
        archived_at=project.archived_at,
        owner=user_brief(project.owner, storage),
        my_role=role,
        members_count=members_count,
        progress=project_progress,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


def member_out(member: ProjectMember, storage: Storage) -> MemberOut:
    return MemberOut(user=user_brief(member.user, storage), role=member.role, joined_at=member.joined_at)


def invitation_out(invitation: ProjectInvitation, storage: Storage) -> InvitationOut:
    return InvitationOut(
        id=invitation.id,
        project=ProjectBriefOut(id=invitation.project.id, title=invitation.project.title),
        email=invitation.email,
        role=invitation.role,
        status=invitation.effective_status(datetime.now(UTC)),
        invited_by=user_brief(invitation.invited_by, storage) if invitation.invited_by else None,
        created_at=invitation.created_at,
        expires_at=invitation.expires_at,
        responded_at=invitation.responded_at,
    )


async def _many(projects: list[Project], current: CurrentUserDep, service: ProjectServiceDep, storage: Storage) -> list[ProjectOut]:
    roles, counts, progresses = await service.enrich(current.user, projects)
    return [project_out(p, roles[p.id], counts.get(p.id, 0), progresses[p.id], storage) for p in projects]


async def _one(project: Project, current: CurrentUserDep, service: ProjectServiceDep, storage: Storage) -> ProjectOut:
    return (await _many([project], current, service, storage))[0]


# --- Проекты ---


@router.post("", status_code=status.HTTP_201_CREATED, summary="Создать проект")
async def create_project(
    data: ProjectCreateIn, current: CurrentUserDep, service: ProjectServiceDep, storage: StorageDep
) -> ProjectOut:
    project = await service.create(current.user, data)
    return await _one(project, current, service, storage)


@router.get(
    "",
    summary="Мои проекты",
    description="Только проекты, в которых пользователь участвует. "
    "Сортировка: `createdAt`, `updatedAt`, `title`, минус — по убыванию (по умолчанию `-updatedAt`).",
)
async def list_projects(
    current: CurrentUserDep,
    service: ProjectServiceDep,
    storage: StorageDep,
    params: Annotated[PageParams, Depends(page_params)],
    search: Annotated[str | None, Query(max_length=255, description="Поиск по названию и описанию")] = None,
    project_status: Annotated[
        ProjectStatusFilter, Query(alias="status", description="active — рабочие, archived — архив, all — все")
    ] = ProjectStatusFilter.ACTIVE,
    role: Annotated[ProjectRole | None, Query(description="Моя роль в проекте")] = None,
    sort: Annotated[str | None, Query()] = None,
) -> Page[ProjectOut]:
    projects, total = await service.list_projects(
        current.user, params, search=search, status=project_status, role=role, sort=sort
    )
    items = await _many(projects, current, service, storage)
    return Page(items=items, total=total, page=params.page, page_size=params.page_size)


@router.get("/{project_id}", summary="Карточка проекта")
async def get_project(
    access: ProjectAccessDep, current: CurrentUserDep, service: ProjectServiceDep, storage: StorageDep
) -> ProjectOut:
    access.require(ProjectAction.READ)
    return await _one(access.project, current, service, storage)


@router.patch("/{project_id}", summary="Редактировать проект", description="Владелец и участники-редакторы.")
async def update_project(
    data: ProjectUpdateIn,
    access: ProjectAccessDep,
    current: CurrentUserDep,
    service: ProjectServiceDep,
    storage: StorageDep,
) -> ProjectOut:
    project = await service.update(access, current.user, data)
    return await _one(project, current, service, storage)


@router.post("/{project_id}/archive", summary="Архивировать проект", description="Только владелец. Архив — только чтение.")
async def archive_project(
    access: ProjectAccessDep, current: CurrentUserDep, service: ProjectServiceDep, storage: StorageDep
) -> ProjectOut:
    project = await service.archive(access, current.user)
    return await _one(project, current, service, storage)


@router.post("/{project_id}/restore", summary="Восстановить проект из архива", description="Только владелец.")
async def restore_project(
    access: ProjectAccessDep, current: CurrentUserDep, service: ProjectServiceDep, storage: StorageDep
) -> ProjectOut:
    project = await service.restore(access, current.user)
    return await _one(project, current, service, storage)


@router.delete(
    "/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить проект",
    description="Только владелец. Удаляется вместе со всеми связанными данными — восстановить нельзя.",
)
async def delete_project(access: ProjectAccessDep, current: CurrentUserDep, service: ProjectServiceDep) -> None:
    await service.delete(access, current.user)


# --- Участники ---


@router.get("/{project_id}/members", summary="Участники проекта")
async def list_members(access: ProjectAccessDep, service: ProjectServiceDep, storage: StorageDep) -> list[MemberOut]:
    return [member_out(m, storage) for m in await service.list_members(access)]


@router.patch(
    "/{project_id}/members/{user_id}",
    summary="Изменить роль участника",
    description="Только владелец. Роль владельца изменить нельзя.",
)
async def change_member_role(
    user_id: UUID,
    data: MemberRoleIn,
    access: ProjectAccessDep,
    current: CurrentUserDep,
    service: ProjectServiceDep,
    storage: StorageDep,
) -> MemberOut:
    return member_out(await service.change_member_role(access, current.user, user_id, data), storage)


@router.delete(
    "/{project_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Отозвать доступ участника",
    description="Только владелец. Владельца удалить нельзя.",
)
async def remove_member(
    user_id: UUID, access: ProjectAccessDep, current: CurrentUserDep, service: ProjectServiceDep
) -> None:
    await service.remove_member(access, current.user, user_id)


# --- Приглашения (со стороны проекта) ---


@router.post(
    "/{project_id}/invitations",
    status_code=status.HTTP_201_CREATED,
    summary="Пригласить в проект по email",
    description="Только владелец. На email отправляется письмо. Если человек уже зарегистрирован, "
    "приглашение также появится у него в `GET /invitations`. Приглашение действует 7 дней.",
)
async def invite(
    data: InvitationCreateIn,
    access: ProjectAccessDep,
    current: CurrentUserDep,
    service: ProjectServiceDep,
    storage: StorageDep,
) -> InvitationOut:
    return invitation_out(await service.invite(access, current.user, data), storage)


@router.get("/{project_id}/invitations", summary="Приглашения проекта", description="Только владелец.")
async def list_project_invitations(
    access: ProjectAccessDep, service: ProjectServiceDep, storage: StorageDep
) -> list[InvitationOut]:
    return [invitation_out(i, storage) for i in await service.list_project_invitations(access)]


@router.delete(
    "/{project_id}/invitations/{invitation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Отозвать приглашение",
    description="Только владелец, только для активного приглашения.",
)
async def revoke_invitation(
    invitation_id: UUID, access: ProjectAccessDep, current: CurrentUserDep, service: ProjectServiceDep
) -> None:
    await service.revoke_invitation(access, current.user, invitation_id)


# --- Приглашения (со стороны приглашённого) ---


@invitations_router.get("", summary="Мои активные приглашения", description="Приглашения на email текущего пользователя.")
async def my_invitations(current: CurrentUserDep, service: ProjectServiceDep, storage: StorageDep) -> list[InvitationOut]:
    return [invitation_out(i, storage) for i in await service.my_invitations(current.user)]


@invitations_router.post(
    "/{invitation_id}/accept",
    summary="Принять приглашение",
    description="Нужен подтверждённый email. При приглашении руководителем пользователь получает роль supervisor.",
)
async def accept_invitation(
    invitation_id: UUID, current: CurrentUserDep, service: ProjectServiceDep, storage: StorageDep
) -> ProjectOut:
    project = await service.accept_invitation(current.user, invitation_id)
    return await _one(project, current, service, storage)


@invitations_router.post(
    "/{invitation_id}/decline", status_code=status.HTTP_204_NO_CONTENT, summary="Отклонить приглашение"
)
async def decline_invitation(invitation_id: UUID, current: CurrentUserDep, service: ProjectServiceDep) -> None:
    await service.decline_invitation(current.user, invitation_id)
