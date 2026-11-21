"""Базовые схемы API: в JSON поля в camelCase, в Python-коде — snake_case."""

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class BaseSchema(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
        # Неизвестные поля в запросе — ошибка 422 (NOT_ALLOWED), а не молчаливый игнор:
        # так фронтенд сразу видит опечатки и попытки изменить недоступные поля
        extra="forbid",
    )


class ProgressOut(BaseSchema):
    """Прогресс: завершённые этапы / все этапы (правило согласовано с Frontend)."""

    completed: int
    total: int
    percent: int


def progress(completed: int, total: int) -> ProgressOut:
    return ProgressOut(completed=completed, total=total, percent=round(completed * 100 / total) if total else 0)
