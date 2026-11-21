"""Научные работы: бизнес-логика (B4)."""

from typing import Any
from uuid import UUID

from sqlalchemy import delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.accounts.models import User
from app.audit.service import AuditLogger
from app.core.pagination import PageParams, apply_sort, paginate
from app.projects.models import ProjectRole
from app.projects.permissions import ProjectAccess, ProjectAction
from app.works.exceptions import WorkNotFoundError, WorkValidationError
from app.works.models import ResearchWork, WorkAuthor, WorkType
from app.works.repository import WorkRepository
from app.works.schemas import AuthorIn, WorkCreateIn, WorkUpdateIn

WORK_SORT_FIELDS = {
    "createdAt": ResearchWork.created_at,
    "updatedAt": ResearchWork.updated_at,
    "title": ResearchWork.title,
    "startDate": ResearchWork.start_date,
    "endDate": ResearchWork.end_date,
}

# Поля работы (без авторов), которые сохраняются как есть
_SIMPLE_FIELDS = (
    "title",
    "type",
    "custom_type_name",
    "description",
    "supervisor_id",
    "supervisor_name",
    "direction",
    "topic",
    "goal",
    "tasks",
    "hypothesis",
    "research_object",
    "research_subject",
    "methodology",
    "start_date",
    "end_date",
)


class WorkService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.works = WorkRepository(db)
        self.audit = AuditLogger(db)

    @staticmethod
    def _visible_to_supervisor(access: ProjectAccess, user: User) -> UUID | None:
        """Руководитель видит только работы, где он указан руководителем (раздел 9 ТЗ).

        Возвращает id для фильтра или None, если пользователь видит все работы проекта.
        """
        return user.id if access.role == ProjectRole.SUPERVISOR else None

    async def list_works(
        self,
        access: ProjectAccess,
        user: User,
        params: PageParams,
        *,
        search: str | None,
        work_type: WorkType | None,
        sort: str | None,
    ) -> tuple[list[ResearchWork], int]:
        access.require(ProjectAction.READ)
        query = self.works.list_query(
            access.project.id,
            search=search,
            work_type=work_type,
            supervisor_id=self._visible_to_supervisor(access, user),
        )
        query = apply_sort(query, sort, WORK_SORT_FIELDS, default="-updatedAt")
        return await paginate(self.db, query, params)

    async def get(self, access: ProjectAccess, user: User, work_id: UUID) -> ResearchWork:
        access.require(ProjectAction.READ)
        work = await self.works.get(
            access.project.id, work_id, supervisor_id=self._visible_to_supervisor(access, user)
        )
        if work is None:
            raise WorkNotFoundError()
        return work

    async def create(self, access: ProjectAccess, user: User, data: WorkCreateIn) -> ResearchWork:
        access.require(ProjectAction.EDIT)
        values = data.model_dump(include=set(_SIMPLE_FIELDS))
        # Автор по умолчанию — тот, кто создаёт работу
        authors = data.authors if data.authors is not None else [AuthorIn(user_id=user.id)]
        await self._validate(access, {**values, "authors": authors})
        self._normalize(values)

        work = ResearchWork(project_id=access.project.id, created_by_id=user.id, **values)
        self.works.add(work)
        await self.db.flush()
        self._set_authors(work, authors, initial=True)
        self.audit.log(
            "work.created", entity_type="research_work", entity_id=work.id, actor_id=user.id,
            data={"project_id": access.project.id, "title": work.title, "type": work.type},
        )
        await self.db.commit()
        return await self._reload(access, work.id)

    async def update(self, access: ProjectAccess, user: User, work_id: UUID, data: WorkUpdateIn) -> ResearchWork:
        access.require(ProjectAction.EDIT)
        work = await self.get(access, user, work_id)
        new = data.model_dump(exclude_unset=True)
        authors = data.authors if "authors" in new else None
        values = {k: v for k, v in new.items() if k in _SIMPLE_FIELDS}

        # Проверяем итоговое состояние работы, а не только переданные поля
        merged = {field: getattr(work, field) for field in _SIMPLE_FIELDS} | values
        if values.get("supervisor_name") and "supervisor_id" not in values:
            # Указали руководителя по ФИО — значит, он не участник платформы
            merged["supervisor_id"] = None
        await self._validate(access, {**merged, "authors": authors})
        self._normalize(merged)

        changes: dict[str, Any] = {}
        for field in _SIMPLE_FIELDS:
            if getattr(work, field) != merged[field]:
                changes[field] = [getattr(work, field), merged[field]]
                setattr(work, field, merged[field])

        if authors is not None:
            old_authors = [(a.user_id, a.full_name) for a in work.authors]
            self._set_authors(work, authors)
            new_authors = [(a.user_id, a.full_name) for a in authors]
            if old_authors != new_authors:
                changes["authors"] = [
                    [str(uid) if uid else name for uid, name in old_authors],
                    [str(uid) if uid else name for uid, name in new_authors],
                ]

        if changes:
            self.audit.log(
                "work.updated", entity_type="research_work", entity_id=work.id, actor_id=user.id, data=changes
            )
        await self.db.commit()
        return await self._reload(access, work.id)

    async def delete(self, access: ProjectAccess, user: User, work_id: UUID) -> None:
        access.require(ProjectAction.EDIT)
        work = await self.get(access, user, work_id)
        self.audit.log(
            "work.deleted", entity_type="research_work", entity_id=work.id, actor_id=user.id,
            data={"project_id": access.project.id, "title": work.title},
        )
        await self.db.execute(sa_delete(ResearchWork).where(ResearchWork.id == work.id))
        await self.db.commit()

    # --- Проверки ---

    async def _validate(self, access: ProjectAccess, values: dict[str, Any]) -> None:
        errors: dict[str, list[str]] = {}

        if values.get("type") == WorkType.CUSTOM and not values.get("custom_type_name"):
            errors["customTypeName"] = ["REQUIRED"]

        start, end = values.get("start_date"), values.get("end_date")
        if start and end and end < start:
            errors["endDate"] = ["BEFORE_START_DATE"]

        supervisor_id: UUID | None = values.get("supervisor_id")
        authors: list[AuthorIn] | None = values.get("authors")
        author_ids = [a.user_id for a in authors or [] if a.user_id]
        roles = await self.works.member_roles(
            access.project.id, set(author_ids) | ({supervisor_id} if supervisor_id else set())
        )

        if supervisor_id and roles.get(supervisor_id) != ProjectRole.SUPERVISOR:
            # Руководителем работы может быть только участник проекта с ролью руководителя
            errors["supervisorId"] = ["NOT_PROJECT_SUPERVISOR"]

        if authors is not None:
            if not authors:
                errors["authors"] = ["REQUIRED"]
            elif len(author_ids) != len(set(author_ids)):
                errors["authors"] = ["DUPLICATE"]
            elif any(uid not in roles for uid in author_ids):
                # Соавтор-пользователь должен иметь доступ к проекту (решение заказчика)
                errors["authors"] = ["NOT_PROJECT_MEMBER"]

        if errors:
            raise WorkValidationError(errors)

    @staticmethod
    def _normalize(values: dict[str, Any]) -> None:
        if values.get("type") != WorkType.CUSTOM:
            values["custom_type_name"] = None
        if values.get("supervisor_id"):
            values["supervisor_name"] = None

    def _set_authors(self, work: ResearchWork, authors: list[AuthorIn], *, initial: bool = False) -> None:
        new = [
            WorkAuthor(user_id=a.user_id, full_name=None if a.user_id else a.full_name, position=i)
            for i, a in enumerate(authors)
        ]
        if initial:
            for author in new:
                author.work_id = work.id
                self.db.add(author)
        else:
            work.authors = new

    async def _reload(self, access: ProjectAccess, work_id: UUID) -> ResearchWork:
        work = await self.works.get(access.project.id, work_id)
        assert work is not None
        return work
