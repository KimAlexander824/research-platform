"""Проекты, участники и приглашения: бизнес-логика (B3, B4)."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete as sa_delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.accounts.models import User, UserRole
from app.accounts.repository import UserRepository
from app.accounts.service import SendEmail
from app.audit.service import AuditLogger, diff
from app.core.config import settings
from app.core.pagination import PageParams, apply_sort, paginate
from app.projects.emails import invitation_message
from app.projects.exceptions import (
    AlreadyMemberError,
    EmailNotVerifiedError,
    InvitationAlreadyPendingError,
    InvitationNotFoundError,
    InvitationNotPendingError,
    MemberNotFoundError,
    OwnerCannotBeChangedError,
    ProjectNotArchivedError,
    ProjectNotFoundError,
)
from app.projects.models import InvitationStatus, Project, ProjectInvitation, ProjectMember, ProjectRole
from app.projects.permissions import ProjectAccess, ProjectAction, ProjectArchivedError
from app.projects.repository import ProjectRepository
from app.projects.schemas import (
    InvitationCreateIn,
    MemberRoleIn,
    ProjectCreateIn,
    ProjectStatusFilter,
    ProjectUpdateIn,
)

PROJECT_SORT_FIELDS = {
    "createdAt": Project.created_at,
    "updatedAt": Project.updated_at,
    "title": Project.title,
}


class ProjectService:
    def __init__(self, db: AsyncSession, send_email: SendEmail) -> None:
        self.db = db
        self.send_email = send_email
        self.projects = ProjectRepository(db)
        self.users = UserRepository(db)
        self.audit = AuditLogger(db)

    # --- Доступ ---

    async def get_access(self, project_id: UUID, user: User) -> ProjectAccess:
        """Проект и роль в нём. Не участник — 404: не раскрываем, что проект существует."""
        found = await self.projects.get_with_role(project_id, user.id)
        if found is None:
            raise ProjectNotFoundError()
        project, role = found
        return ProjectAccess(project=project, role=role)

    # --- Проекты ---

    async def create(self, user: User, data: ProjectCreateIn) -> Project:
        project = Project(title=data.title, description=data.description, owner_id=user.id)
        self.projects.add(project)
        await self.db.flush()
        self.projects.add(ProjectMember(project_id=project.id, user_id=user.id, role=ProjectRole.OWNER))
        self.audit.log(
            "project.created", entity_type="project", entity_id=project.id, actor_id=user.id,
            data={"title": project.title},
        )
        await self.db.commit()
        return await self._reload(project.id)

    async def list_projects(
        self,
        user: User,
        params: PageParams,
        *,
        search: str | None,
        status: ProjectStatusFilter,
        role: ProjectRole | None,
        sort: str | None,
    ) -> tuple[list[Project], int]:
        archived = {ProjectStatusFilter.ACTIVE: False, ProjectStatusFilter.ARCHIVED: True}.get(status)
        query = self.projects.list_query(user.id, search=search, archived=archived, role=role)
        query = apply_sort(query, sort, PROJECT_SORT_FIELDS, default="-updatedAt")
        return await paginate(self.db, query, params)

    async def update(self, access: ProjectAccess, user: User, data: ProjectUpdateIn) -> Project:
        access.require(ProjectAction.EDIT)
        project = access.project
        new = data.model_dump(exclude_unset=True)
        old = {field: getattr(project, field) for field in new}
        for field, value in new.items():
            setattr(project, field, value)
        changes = diff(old, new)
        if changes:
            self.audit.log(
                "project.updated", entity_type="project", entity_id=project.id, actor_id=user.id, data=changes
            )
        await self.db.commit()
        return await self._reload(project.id)

    async def archive(self, access: ProjectAccess, user: User) -> Project:
        access.require(ProjectAction.ARCHIVE)
        if access.project.is_archived:
            raise ProjectArchivedError()
        access.project.archived_at = datetime.now(UTC)
        self.audit.log("project.archived", entity_type="project", entity_id=access.project.id, actor_id=user.id)
        await self.db.commit()
        return await self._reload(access.project.id)

    async def restore(self, access: ProjectAccess, user: User) -> Project:
        access.require(ProjectAction.ARCHIVE)
        if not access.project.is_archived:
            raise ProjectNotArchivedError()
        access.project.archived_at = None
        self.audit.log("project.restored", entity_type="project", entity_id=access.project.id, actor_id=user.id)
        await self.db.commit()
        return await self._reload(access.project.id)

    async def delete(self, access: ProjectAccess, user: User) -> None:
        """Удаляет проект вместе со связанными данными (участники, приглашения, далее — работы, этапы, документы)."""
        access.require(ProjectAction.DELETE)
        project = access.project
        self.audit.log(
            "project.deleted", entity_type="project", entity_id=project.id, actor_id=user.id,
            data={"title": project.title},
        )
        # Связанные строки удаляются каскадом на уровне БД (ON DELETE CASCADE)
        await self.db.execute(sa_delete(Project).where(Project.id == project.id))
        await self.db.commit()

    async def enrich(self, user: User, projects: list[Project]) -> tuple[dict[UUID, ProjectRole], dict[UUID, int]]:
        """Роль текущего пользователя и число участников — для списков."""
        ids = [p.id for p in projects]
        if not ids:
            return {}, {}
        return await self.projects.roles_for(user.id, ids), await self.projects.members_count(ids)

    # --- Участники ---

    async def list_members(self, access: ProjectAccess) -> list[ProjectMember]:
        access.require(ProjectAction.READ)
        return await self.projects.list_members(access.project.id)

    async def change_member_role(
        self, access: ProjectAccess, user: User, member_user_id: UUID, data: MemberRoleIn
    ) -> ProjectMember:
        access.require(ProjectAction.MANAGE_MEMBERS)
        member = await self._get_member(access, member_user_id)
        if member.role != data.role:
            self.audit.log(
                "project.member_role_changed", entity_type="project", entity_id=access.project.id,
                actor_id=user.id, data={"user_id": member.user_id, "role": [member.role, data.role]},
            )
            member.role = data.role
            if data.role == ProjectRole.SUPERVISOR:
                self._grant_supervisor(member.user, actor_id=user.id)
            await self.db.commit()
        return member

    async def remove_member(self, access: ProjectAccess, user: User, member_user_id: UUID) -> None:
        """Отзыв доступа к проекту (B3)."""
        access.require(ProjectAction.MANAGE_MEMBERS)
        member = await self._get_member(access, member_user_id)
        self.audit.log(
            "project.member_removed", entity_type="project", entity_id=access.project.id, actor_id=user.id,
            data={"user_id": member.user_id, "role": member.role},
        )
        await self.db.delete(member)
        await self.db.commit()

    async def _get_member(self, access: ProjectAccess, member_user_id: UUID) -> ProjectMember:
        member = await self.projects.get_member(access.project.id, member_user_id)
        if member is None:
            raise MemberNotFoundError()
        if member.role == ProjectRole.OWNER:
            raise OwnerCannotBeChangedError()
        return member

    # --- Приглашения ---

    async def invite(self, access: ProjectAccess, user: User, data: InvitationCreateIn) -> ProjectInvitation:
        access.require(ProjectAction.MANAGE_MEMBERS)
        project = access.project

        if await self.projects.is_member_by_email(project.id, data.email):
            raise AlreadyMemberError()
        now = datetime.now(UTC)
        existing = await self.projects.get_pending_invitation(project.id, data.email)
        if existing is not None:
            if existing.expires_at > now:
                raise InvitationAlreadyPendingError()
            existing.status = InvitationStatus.EXPIRED  # истёкшее заменяем новым

        invitation = ProjectInvitation(
            project_id=project.id,
            email=data.email,
            role=data.role,
            invited_by_id=user.id,
            expires_at=now + timedelta(days=settings.INVITATION_TTL_DAYS),
        )
        self.projects.add(invitation)
        try:
            await self.db.flush()
        except IntegrityError as exc:  # одновременное приглашение того же email
            await self.db.rollback()
            raise InvitationAlreadyPendingError() from exc

        self.audit.log(
            "project.member_invited", entity_type="project", entity_id=project.id, actor_id=user.id,
            data={"email": data.email, "role": data.role, "invitation_id": invitation.id},
        )
        await self.db.commit()

        # Язык письма: у зарегистрированного — его язык, иначе — язык приглашающего
        invitee = await self.users.get_by_email(data.email)
        language = invitee.language if invitee else user.language
        self.send_email(invitation_message(data.email, language, project.title, user.full_name, data.role))

        return await self._reload_invitation(invitation.id)

    async def list_project_invitations(self, access: ProjectAccess) -> list[ProjectInvitation]:
        access.require(ProjectAction.MANAGE_MEMBERS)
        return await self.projects.list_project_invitations(access.project.id)

    async def revoke_invitation(self, access: ProjectAccess, user: User, invitation_id: UUID) -> None:
        access.require(ProjectAction.MANAGE_MEMBERS)
        invitation = await self.projects.get_invitation(invitation_id, for_update=True)
        if invitation is None or invitation.project_id != access.project.id:
            raise InvitationNotFoundError()
        if invitation.effective_status(datetime.now(UTC)) != InvitationStatus.PENDING:
            raise InvitationNotPendingError()
        invitation.status = InvitationStatus.REVOKED
        invitation.responded_at = datetime.now(UTC)
        self.audit.log(
            "project.invitation_revoked", entity_type="project", entity_id=access.project.id, actor_id=user.id,
            data={"email": invitation.email, "invitation_id": invitation.id},
        )
        await self.db.commit()

    async def my_invitations(self, user: User) -> list[ProjectInvitation]:
        return await self.projects.list_pending_for_email(user.email)

    async def accept_invitation(self, user: User, invitation_id: UUID) -> Project:
        invitation = await self._my_pending_invitation(user, invitation_id)
        if not user.email_verified:
            # Иначе приглашение мог бы принять тот, кто зарегистрировался с чужим email
            raise EmailNotVerifiedError()
        project = invitation.project
        if project.is_archived:
            raise ProjectArchivedError()
        if await self.projects.get_member(project.id, user.id) is not None:
            raise AlreadyMemberError()

        now = datetime.now(UTC)
        invitation.status = InvitationStatus.ACCEPTED
        invitation.responded_at = now
        self.projects.add(ProjectMember(project_id=project.id, user_id=user.id, role=invitation.role))
        if invitation.role == ProjectRole.SUPERVISOR:
            self._grant_supervisor(user, actor_id=user.id)
        self.audit.log(
            "project.invitation_accepted", entity_type="project", entity_id=project.id, actor_id=user.id,
            data={"role": invitation.role, "invitation_id": invitation.id},
        )
        await self.db.commit()
        return await self._reload(project.id)

    async def decline_invitation(self, user: User, invitation_id: UUID) -> None:
        invitation = await self._my_pending_invitation(user, invitation_id)
        invitation.status = InvitationStatus.DECLINED
        invitation.responded_at = datetime.now(UTC)
        self.audit.log(
            "project.invitation_declined", entity_type="project", entity_id=invitation.project_id,
            actor_id=user.id, data={"invitation_id": invitation.id},
        )
        await self.db.commit()

    async def _my_pending_invitation(self, user: User, invitation_id: UUID) -> ProjectInvitation:
        invitation = await self.projects.get_invitation(invitation_id, for_update=True)
        # Чужое приглашение — как будто его нет
        if invitation is None or invitation.email != user.email:
            raise InvitationNotFoundError()
        if invitation.effective_status(datetime.now(UTC)) != InvitationStatus.PENDING:
            raise InvitationNotPendingError()
        return invitation

    def _grant_supervisor(self, user: User, *, actor_id: UUID) -> None:
        """По решению заказчика роль Supervisor выдаётся и при приглашении в проект руководителем."""
        if user.role == UserRole.RESEARCHER:
            self.audit.log(
                "user.role_changed", entity_type="user", entity_id=user.id, actor_id=actor_id,
                data={"role": [user.role, UserRole.SUPERVISOR], "source": "project_invitation"},
            )
            user.role = UserRole.SUPERVISOR

    # --- Вспомогательное ---

    async def _reload(self, project_id: UUID) -> Project:
        project = await self.db.get(Project, project_id, populate_existing=True)
        if project is None:
            raise ProjectNotFoundError()
        await self.db.refresh(project, ["owner"])
        return project

    async def _reload_invitation(self, invitation_id: UUID) -> ProjectInvitation:
        invitation = await self.projects.get_invitation(invitation_id)
        assert invitation is not None
        return invitation
