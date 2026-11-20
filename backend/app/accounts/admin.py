"""Админ-панель: вход администратора и управление пользователями (B3)."""

from typing import Any
from uuid import UUID

from sqladmin import ModelView
from sqladmin.authentication import AuthenticationBackend
from sqladmin.filters import BooleanFilter, StaticValuesFilter
from sqlalchemy import func, select
from sqlalchemy.orm import object_session
from starlette.requests import Request

from app.accounts.models import User, UserRole
from app.accounts.service import LoginAttempts
from app.audit.service import build_entry, diff
from app.core.config import settings
from app.core.database import SessionFactory
from app.core.errors import AppError
from app.core.rate_limit import client_ip, hit
from app.core.security import verify_password

ADMIN_SESSION_KEY = "admin_user_id"


def admin_actor_id(request: Request) -> UUID | None:
    value = request.session.get(ADMIN_SESSION_KEY)
    return UUID(value) if value else None


class AdminAuth(AuthenticationBackend):
    """Вход в админ-панель по email и паролю. Пускает только активных пользователей с ролью admin."""

    async def login(self, request: Request) -> bool:
        if await hit(f"rate:admin_login:{client_ip(request)}", settings.AUTH_RATE_LIMIT_PER_MINUTE, 60):
            return False

        form = await request.form()
        email = str(form.get("username", "")).strip().lower()
        password = str(form.get("password", ""))

        attempts = LoginAttempts()
        try:
            await attempts.check(email)
        except AppError:
            return False

        async with SessionFactory() as db:
            user = await db.scalar(select(User).where(User.email == email))

        if user is None or not verify_password(password, user.password_hash):
            await attempts.register_failure(email)
            return False
        if not user.is_active or user.role != UserRole.ADMIN:
            return False

        await attempts.reset(email)
        request.session.clear()
        request.session[ADMIN_SESSION_KEY] = str(user.id)
        return True

    async def logout(self, request: Request) -> bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        # Проверяется на каждом запросе: если админа заблокировали или сняли роль — доступ сразу пропадает
        user_id = admin_actor_id(request)
        if user_id is None:
            return False
        async with SessionFactory() as db:
            user = await db.get(User, user_id)
        if user is None or not user.is_active or user.role != UserRole.ADMIN:
            request.session.clear()
            return False
        return True


_OPTIONAL_TEXT_FIELDS = ("phone", "organization", "position", "academic_degree", "academic_title")


class UserAdmin(ModelView, model=User):
    name = "Пользователь"
    name_plural = "Пользователи"
    icon = "fa-solid fa-users"

    # Пользователи регистрируются сами; удаление заменено блокировкой (is_active)
    can_create = False
    can_delete = False
    can_export = False

    column_list = [User.email, User.full_name, User.role, User.is_active, User.email_verified_at, User.created_at]
    column_searchable_list = [User.email, User.full_name]
    column_sortable_list = [User.email, User.full_name, User.role, User.created_at]
    column_default_sort = (User.created_at, True)
    column_filters = [
        StaticValuesFilter(User.role, values=[(r.value, r.value) for r in UserRole], title="Роль"),
        BooleanFilter(User.is_active, title="Активен"),
    ]
    column_details_exclude_list = [User.password_hash, User.avatar_key, User.sessions, User.preferences]
    form_columns = [
        User.full_name,
        User.email,
        User.role,
        User.is_active,
        User.phone,
        User.organization,
        User.position,
        User.academic_degree,
        User.academic_title,
    ]
    column_labels = {
        User.email: "Email",
        User.full_name: "ФИО",
        User.role: "Роль",
        User.is_active: "Активен",
        User.email_verified_at: "Email подтверждён",
        User.created_at: "Зарегистрирован",
        User.phone: "Телефон",
        User.organization: "Организация",
        User.position: "Должность",
        User.academic_degree: "Учёная степень",
        User.academic_title: "Учёное звание",
        User.language: "Язык",
        User.research_interests: "Научные интересы",
    }

    async def on_model_change(self, data: dict[str, Any], model: User, is_created: bool, request: Request) -> None:
        actor_id = admin_actor_id(request)

        for field in _OPTIONAL_TEXT_FIELDS:
            if field in data and isinstance(data[field], str):
                data[field] = data[field].strip() or None
        if isinstance(data.get("full_name"), str):
            data["full_name"] = data["full_name"].strip()
            if not data["full_name"]:
                raise ValueError("ФИО не может быть пустым")
        if isinstance(data.get("email"), str):
            data["email"] = data["email"].strip().lower()

        new_role = UserRole(data["role"]) if data.get("role") else model.role
        if model.id == actor_id and (new_role != UserRole.ADMIN or data.get("is_active") is False):
            raise ValueError("Нельзя снять роль администратора или заблокировать самого себя")

        if data.get("email") and data["email"] != model.email:
            async with SessionFactory() as db:
                exists = await db.scalar(
                    select(func.count()).where(User.email == data["email"], User.id != model.id)
                )
            if exists:
                raise ValueError("Пользователь с таким email уже существует")

        # Запись журнала добавляется в ту же сессию, что и изменение, — сохранятся одним коммитом
        session = object_session(model)
        assert session is not None

        old = {field: getattr(model, field) for field in data}
        changes = diff(old, data)
        if not changes:
            return

        def log(action: str, fields: dict[str, Any]) -> None:
            session.add(
                build_entry(
                    action,
                    entity_type="user",
                    entity_id=model.id,
                    actor_id=actor_id,
                    data=fields,
                    ip_address=client_ip(request),
                )
            )

        if "role" in changes:
            log("user.role_changed", {"role": changes.pop("role")})
        if "is_active" in changes:
            active = changes.pop("is_active")
            log("user.unblocked" if active[1] else "user.blocked", {"is_active": active})
        if "email" in changes:
            # Новый email не подтверждён
            data["email_verified_at"] = None
        if changes:
            log("user.updated_by_admin", changes)
