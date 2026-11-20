"""Просмотр журнала действий в админ-панели (только чтение)."""

import json
from typing import Any

from markupsafe import Markup, escape
from sqladmin import ModelView

from app.audit.models import AuditLog


def _actor(model: AuditLog, _: Any) -> str:
    return model.actor.email if model.actor else "система"


def _data(model: AuditLog, _: Any) -> Markup:
    if not model.data:
        return Markup("")
    text = json.dumps(model.data, ensure_ascii=False, indent=1)
    return Markup(f"<pre style='margin:0;white-space:pre-wrap;max-width:420px'>{escape(text)}</pre>")


class AuditLogAdmin(ModelView, model=AuditLog):
    name = "Запись журнала"
    name_plural = "Журнал действий"
    icon = "fa-solid fa-clock-rotate-left"

    # Журнал нельзя редактировать и удалять
    can_create = False
    can_edit = False
    can_delete = False
    can_export = True

    column_list = [
        AuditLog.created_at,
        AuditLog.action,
        AuditLog.actor,
        AuditLog.data,
        AuditLog.entity_type,
        AuditLog.entity_id,
        AuditLog.ip_address,
    ]
    column_details_list = [
        AuditLog.created_at,
        AuditLog.action,
        AuditLog.actor,
        AuditLog.actor_id,
        AuditLog.entity_type,
        AuditLog.entity_id,
        AuditLog.data,
        AuditLog.ip_address,
    ]
    column_formatters = {AuditLog.actor: _actor, AuditLog.data: _data}
    column_formatters_detail = {AuditLog.actor: _actor, AuditLog.data: _data}
    column_searchable_list = [AuditLog.action, AuditLog.entity_id]
    column_sortable_list = [AuditLog.created_at, AuditLog.action]
    column_default_sort = (AuditLog.created_at, True)
    column_labels = {
        AuditLog.created_at: "Время (UTC)",
        AuditLog.action: "Действие",
        AuditLog.entity_type: "Тип объекта",
        AuditLog.entity_id: "ID объекта",
        AuditLog.actor: "Кто",
        AuditLog.actor_id: "ID пользователя",
        AuditLog.ip_address: "IP",
        AuditLog.data: "Подробности",
    }
