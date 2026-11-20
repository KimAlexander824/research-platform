"""Роли, админ-панель и консольная команда создания администратора (B3)."""

from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.accounts.cli import create_admin
from app.accounts.dependencies import CurrentUser, require_roles
from app.accounts.models import User, UserRole
from app.audit.models import AuditLog
from app.core.database import SessionFactory
from tests.accounts.test_auth import PASSWORD, bearer, register

ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "AdminPassw0rd"


@pytest.fixture
def app(app: FastAPI) -> FastAPI:
    @app.get("/test/admin-only")
    async def admin_only(
        current: Annotated[CurrentUser, Depends(require_roles(UserRole.ADMIN))],
    ) -> str:
        return current.user.email

    @app.get("/test/staff")
    async def staff(_: Annotated[CurrentUser, Depends(require_roles(UserRole.ADMIN, UserRole.SUPERVISOR))]) -> str:
        return "ok"

    return app


async def get_user(email: str) -> User:
    async with SessionFactory() as db:
        return await db.scalar(select(User).where(User.email == email))


async def admin_login(client: AsyncClient, email: str = ADMIN_EMAIL, password: str = ADMIN_PASSWORD):
    return await client.post("/admin/login", data={"username": email, "password": password})


def user_form(user: User, **changes) -> dict[str, str]:
    form = {
        "full_name": user.full_name,
        "email": user.email,
        "role": user.role.value,
        "is_active": "y" if user.is_active else "",
        "phone": user.phone or "",
        "organization": user.organization or "",
        "position": user.position or "",
        "academic_degree": user.academic_degree or "",
        "academic_title": user.academic_title or "",
    }
    form.update(changes)
    if form["is_active"] == "":
        del form["is_active"]  # снятый чекбокс браузер не отправляет
    return form


# --- Консольная команда ---


async def test_create_admin_cli_creates_user() -> None:
    message = await create_admin(ADMIN_EMAIL, ADMIN_PASSWORD, "Админ")
    assert "Создан" in message
    user = await get_user(ADMIN_EMAIL)
    assert user.role == UserRole.ADMIN


async def test_create_admin_cli_promotes_existing_user(client: AsyncClient) -> None:
    await register(client)
    await create_admin("user@example.com", None, None)
    assert (await get_user("user@example.com")).role == UserRole.ADMIN


# --- Проверка ролей в API ---


async def test_require_roles(client: AsyncClient) -> None:
    researcher = bearer((await register(client))["accessToken"])
    await create_admin(ADMIN_EMAIL, ADMIN_PASSWORD, None)
    admin = bearer((await client.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})).json()["accessToken"])

    response = await client.get("/test/admin-only", headers=researcher)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"
    assert (await client.get("/test/admin-only", headers=admin)).status_code == 200
    assert (await client.get("/test/staff", headers=researcher)).status_code == 403
    assert (await client.get("/test/admin-only")).status_code == 401


async def test_role_change_takes_effect_immediately(client: AsyncClient) -> None:
    headers = bearer((await register(client))["accessToken"])
    assert (await client.get("/test/admin-only", headers=headers)).status_code == 403
    await create_admin("user@example.com", None, None)
    # Тот же токен: роль читается из БД на каждом запросе
    assert (await client.get("/test/admin-only", headers=headers)).status_code == 200


# --- Вход в админ-панель ---


async def test_admin_panel_requires_login(client: AsyncClient) -> None:
    response = await client.get("/admin/user/list")
    assert response.status_code in (302, 303)
    assert "/admin/login" in response.headers["location"]


async def test_researcher_cannot_login_to_admin_panel(client: AsyncClient) -> None:
    await register(client)
    await admin_login(client, "user@example.com", PASSWORD)
    response = await client.get("/admin/user/list")
    assert response.status_code in (302, 303)


async def test_admin_can_open_panel(client: AsyncClient) -> None:
    await create_admin(ADMIN_EMAIL, ADMIN_PASSWORD, None)
    await admin_login(client)
    response = await client.get("/admin/user/list")
    assert response.status_code == 200
    assert ADMIN_EMAIL in response.text


async def test_admin_wrong_password(client: AsyncClient) -> None:
    await create_admin(ADMIN_EMAIL, ADMIN_PASSWORD, None)
    await admin_login(client, password="wrong")
    assert (await client.get("/admin/user/list")).status_code in (302, 303)


# --- Управление пользователями ---


async def test_admin_assigns_supervisor_role_and_it_is_logged(client: AsyncClient) -> None:
    await register(client)
    await create_admin(ADMIN_EMAIL, ADMIN_PASSWORD, None)
    await admin_login(client)
    user = await get_user("user@example.com")
    admin = await get_user(ADMIN_EMAIL)

    response = await client.post(f"/admin/user/edit/{user.id}", data=user_form(user, role="supervisor"))
    assert response.status_code in (302, 303), response.text

    assert (await get_user("user@example.com")).role == UserRole.SUPERVISOR
    async with SessionFactory() as db:
        entry = await db.scalar(select(AuditLog).where(AuditLog.action == "user.role_changed"))
    assert entry.actor_id == admin.id
    assert entry.entity_id == str(user.id)
    assert entry.data == {"role": ["researcher", "supervisor"]}


async def test_admin_blocks_user(client: AsyncClient) -> None:
    headers = bearer((await register(client))["accessToken"])
    await create_admin(ADMIN_EMAIL, ADMIN_PASSWORD, None)
    await admin_login(client)
    user = await get_user("user@example.com")

    await client.post(f"/admin/user/edit/{user.id}", data=user_form(user, is_active=""))

    response = await client.get("/api/v1/me", headers=headers)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ACCOUNT_DISABLED"
    async with SessionFactory() as db:
        assert await db.scalar(select(AuditLog).where(AuditLog.action == "user.blocked")) is not None


async def test_admin_cannot_demote_self(client: AsyncClient) -> None:
    await create_admin(ADMIN_EMAIL, ADMIN_PASSWORD, None)
    await admin_login(client)
    admin = await get_user(ADMIN_EMAIL)

    response = await client.post(f"/admin/user/edit/{admin.id}", data=user_form(admin, role="researcher"))
    assert response.status_code == 400
    assert (await get_user(ADMIN_EMAIL)).role == UserRole.ADMIN


async def test_admin_email_change_requires_new_verification(client: AsyncClient, outbox) -> None:
    await register(client)
    await create_admin(ADMIN_EMAIL, ADMIN_PASSWORD, None)
    await admin_login(client)
    user = await get_user("user@example.com")

    await client.post(f"/admin/user/edit/{user.id}", data=user_form(user, email=" New@Example.com "))
    updated = await get_user("new@example.com")
    assert updated is not None and updated.email_verified_at is None


async def test_audit_log_is_read_only_in_panel(client: AsyncClient) -> None:
    await create_admin(ADMIN_EMAIL, ADMIN_PASSWORD, None)
    await admin_login(client)
    assert (await client.get("/admin/audit-log/list")).status_code == 200
    async with SessionFactory() as db:
        entry = await db.scalar(select(AuditLog))
    assert (await client.get(f"/admin/audit-log/edit/{entry.id}")).status_code in (403, 404)


async def test_audit_log_list_shows_actor_email_and_details(client: AsyncClient) -> None:
    headers = bearer((await register(client))["accessToken"])
    await client.patch("/api/v1/me", json={"organization": "НУУз"}, headers=headers)
    await create_admin(ADMIN_EMAIL, ADMIN_PASSWORD, None)
    await admin_login(client)

    page = (await client.get("/admin/audit-log/list")).text
    assert "user@example.com" in page  # «Кто» — email, а не UUID
    assert "НУУз" in page  # подробности видны прямо в списке
    assert "система" in page  # создание админа из консоли

    async with SessionFactory() as db:
        entry = await db.scalar(select(AuditLog).where(AuditLog.action == "user.profile_updated"))
    detail = await client.get(f"/admin/audit-log/details/{entry.id}")
    assert detail.status_code == 200
    assert "user@example.com" in detail.text and "НУУз" in detail.text
