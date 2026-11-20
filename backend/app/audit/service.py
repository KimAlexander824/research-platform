"""Запись в журнал действий.

Запись добавляется в ту же сессию БД, что и само изменение, и сохраняется одним коммитом:
если изменение не сохранилось — записи в журнале тоже не будет, и наоборот.

Использование в сервисах модулей:

    AuditLogger(db).log("user.role_changed", actor_id=admin.id, entity_type="user",
                        entity_id=user.id, data={"role": ["researcher", "supervisor"]})
"""

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.audit.models import AuditLog
from app.core.request_context import current_client_ip


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(v) for v in value]
    if value is None or isinstance(value, bool | int | float | str):
        return value
    return str(value)  # UUID, datetime, Enum и т.п.


def diff(old: dict[str, Any], new: dict[str, Any]) -> dict[str, list[Any]]:
    """Изменённые поля в формате {"поле": [старое, новое]}."""
    return {key: [old.get(key), value] for key, value in new.items() if old.get(key) != value}


def build_entry(
    action: str,
    *,
    entity_type: str,
    entity_id: UUID | str | None = None,
    actor_id: UUID | None = None,
    data: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> AuditLog:
    return AuditLog(
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        actor_id=actor_id,
        data=_json_safe(data or {}),
        # IP берётся из текущего HTTP-запроса автоматически; у консольных команд его нет
        ip_address=ip_address or current_client_ip(),
    )


class AuditLogger:
    def __init__(self, db: AsyncSession | Session) -> None:
        self.db = db

    def log(
        self,
        action: str,
        *,
        entity_type: str,
        entity_id: UUID | str | None = None,
        actor_id: UUID | None = None,
        data: dict[str, Any] | None = None,
        ip_address: str | None = None,
    ) -> None:
        self.db.add(
            build_entry(
                action,
                entity_type=entity_type,
                entity_id=entity_id,
                actor_id=actor_id,
                data=data,
                ip_address=ip_address,
            )
        )
