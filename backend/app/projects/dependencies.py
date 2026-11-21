from typing import Annotated
from uuid import UUID

from fastapi import Depends

from app.accounts.dependencies import CurrentUserDep, DbSession, SendEmailDep
from app.core.storage import Storage, get_storage
from app.projects.permissions import ProjectAccess
from app.projects.service import ProjectService


def get_project_service(db: DbSession, send_email: SendEmailDep) -> ProjectService:
    return ProjectService(db, send_email)


ProjectServiceDep = Annotated[ProjectService, Depends(get_project_service)]
StorageDep = Annotated[Storage, Depends(get_storage)]


async def get_project_access(project_id: UUID, current: CurrentUserDep, service: ProjectServiceDep) -> ProjectAccess:
    """Проект из пути и роль в нём текущего пользователя. Не участник — 404."""
    return await service.get_access(project_id, current.user)


ProjectAccessDep = Annotated[ProjectAccess, Depends(get_project_access)]
