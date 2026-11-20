"""Пагинация и сортировка.

Запрос:  ?page=1&pageSize=20&sort=-createdAt
Ответ:   {"items": [...], "total": 134, "page": 1, "pageSize": 20}

`sort` — имя поля в camelCase, минус в начале означает сортировку по убыванию.
"""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Query
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.core.errors import AppError, ErrorCode
from app.core.schemas import BaseSchema

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


class Page[T](BaseSchema):
    items: list[T]
    total: int
    page: int
    page_size: int


@dataclass(frozen=True)
class PageParams:
    page: int
    page_size: int

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


def page_params(
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> PageParams:
    """Зависимость FastAPI для параметров пагинации."""
    return PageParams(page=page, page_size=page_size)


def apply_sort(
    query: Select,  # type: ignore[type-arg]
    sort: str | None,
    allowed: dict[str, InstrumentedAttribute],  # type: ignore[type-arg]
    default: str,
) -> Select:  # type: ignore[type-arg]
    """Применяет сортировку. `allowed` — разрешённые поля: {"createdAt": Model.created_at}."""
    value = sort or default
    descending = value.startswith("-")
    name = value.lstrip("-")
    column = allowed.get(name)
    if column is None:
        raise AppError(
            "Unsupported sort field",
            code=ErrorCode.VALIDATION_ERROR,
            status_code=422,
            fields={"sort": ["INVALID_CHOICE"]},
        )
    return query.order_by(column.desc() if descending else column.asc())


async def paginate[T](
    session: AsyncSession,
    query: Select,  # type: ignore[type-arg]
    params: PageParams,
) -> tuple[list[T], int]:
    """Возвращает (элементы страницы, общее количество)."""
    total = await session.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
    result = await session.scalars(query.offset(params.offset).limit(params.page_size))
    return list(result.all()), int(total or 0)
