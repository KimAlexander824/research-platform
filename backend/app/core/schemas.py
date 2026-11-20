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
