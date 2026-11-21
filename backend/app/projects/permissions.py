"""Права внутри проекта (B3).

Кто что может делать в проекте — в одном месте. Остальные модули (работы, этапы, документы)
используют эти же правила через `ProjectAccess`.

| Действие                                  | owner | editor | supervisor | viewer |
|-------------------------------------------|:-----:|:------:|:----------:|:------:|
| Видеть проект и его материалы             |   ✓   |   ✓    |     ✓      |   ✓    |
| Редактировать проект и материалы          |   ✓   |   ✓    |            |        |
| Приглашать, менять роли, удалять участников|   ✓   |        |            |        |
| Архивировать, восстанавливать, удалять    |   ✓   |        |            |        |

Руководитель не редактирует материалы исследователя (B3); его действия — комментарии и проверка этапов
(появятся в следующих шагах).
"""

from dataclasses import dataclass
from enum import StrEnum

from app.core.errors import ConflictError
from app.core.permissions import ensure_can
from app.projects.models import Project, ProjectRole


class ProjectAction(StrEnum):
    READ = "read"
    EDIT = "edit"
    MANAGE_MEMBERS = "manage_members"
    ARCHIVE = "archive"
    DELETE = "delete"


_ALLOWED: dict[ProjectAction, set[ProjectRole]] = {
    ProjectAction.READ: set(ProjectRole),
    ProjectAction.EDIT: {ProjectRole.OWNER, ProjectRole.EDITOR},
    ProjectAction.MANAGE_MEMBERS: {ProjectRole.OWNER},
    ProjectAction.ARCHIVE: {ProjectRole.OWNER},
    ProjectAction.DELETE: {ProjectRole.OWNER},
}

# Действия, запрещённые в архивном проекте (архив — только для чтения)
_BLOCKED_WHEN_ARCHIVED = {ProjectAction.EDIT, ProjectAction.MANAGE_MEMBERS}


class ProjectArchivedError(ConflictError):
    code = "PROJECT_ARCHIVED"
    message = "Project is archived; restore it to make changes"


def can(role: ProjectRole, action: ProjectAction) -> bool:
    return role in _ALLOWED[action]


@dataclass(frozen=True)
class ProjectAccess:
    """Проект и роль в нём текущего пользователя."""

    project: Project
    role: ProjectRole

    def can(self, action: ProjectAction) -> bool:
        return can(self.role, action)

    def require(self, action: ProjectAction) -> None:
        ensure_can(self.can(action), f"Project role '{self.role}' cannot perform '{action}'")
        if action in _BLOCKED_WHEN_ARCHIVED and self.project.is_archived:
            raise ProjectArchivedError()
