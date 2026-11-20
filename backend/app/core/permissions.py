"""Общие правила проверки прав доступа (B3, B12).

Права проверяются только на сервере, на каждом запросе — скрытие кнопок на фронтенде защитой не считается.

Проверка состоит из двух уровней:

1. Роль пользователя в системе (researcher / supervisor / admin) — зависимость `require_roles`
   из app.accounts.dependencies. Например, эндпоинт только для администратора.

2. Доступ к конкретному объекту (проект, документ, этап) — функции в `permissions.py` модуля.
   Они проверяют участие пользователя в проекте и его роль в нём.

Соглашение об ответах:
- нет права ЧИТАТЬ объект  -> 404 NOT_FOUND (не раскрываем, что объект существует);
- может читать, но нет права на ДЕЙСТВИЕ -> 403 FORBIDDEN.
"""

from app.core.errors import ForbiddenError, NotFoundError


def ensure_can_read(allowed: bool) -> None:
    """Нет доступа на чтение — ответ такой же, как будто объекта нет."""
    if not allowed:
        raise NotFoundError()


def ensure_can(allowed: bool, message: str = "Access denied") -> None:
    """Объект виден, но действие запрещено."""
    if not allowed:
        raise ForbiddenError(message)
