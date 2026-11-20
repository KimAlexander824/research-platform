"""Журнал значимых действий (B3)."""

import re

from httpx import AsyncClient
from sqlalchemy import select

from app.audit.models import AuditLog
from app.core.database import SessionFactory
from tests.accounts.test_auth import bearer, register
from tests.conftest import FakeMailSender


async def audit_entries(action: str | None = None) -> list[AuditLog]:
    async with SessionFactory() as db:
        query = select(AuditLog).order_by(AuditLog.created_at)
        if action:
            query = query.where(AuditLog.action == action)
        return list((await db.scalars(query)).all())


async def test_registration_is_logged(client: AsyncClient) -> None:
    await register(client)
    [entry] = await audit_entries("user.registered")
    assert entry.entity_type == "user"
    assert entry.actor_id is not None and str(entry.actor_id) == entry.entity_id
    assert entry.data == {"email": "user@example.com"}
    assert entry.ip_address


async def test_profile_update_logs_changed_fields_only(client: AsyncClient) -> None:
    headers = bearer((await register(client))["accessToken"])
    await client.patch("/api/v1/me", json={"organization": "НУУз", "position": None}, headers=headers)
    [entry] = await audit_entries("user.profile_updated")
    # position уже был пустым — не изменился и в журнал не попал
    assert entry.data == {"organization": [None, "НУУз"]}
    # IP подставляется автоматически из запроса
    assert entry.ip_address


async def test_no_entry_when_nothing_changed(client: AsyncClient) -> None:
    headers = bearer((await register(client))["accessToken"])
    await client.patch("/api/v1/me", json={"fullName": "Иванов Иван"}, headers=headers)
    assert await audit_entries("user.profile_updated") == []


async def test_email_verification_and_password_reset_are_logged(client: AsyncClient, outbox: FakeMailSender) -> None:
    await register(client)
    token = re.search(r"token=([\w-]+)", outbox.messages[-1].text).group(1)
    await client.post("/api/v1/auth/verify-email/confirm", json={"token": token})

    await client.post("/api/v1/auth/password/forgot", json={"email": "user@example.com"})
    token = re.search(r"token=([\w-]+)", outbox.messages[-1].text).group(1)
    await client.post("/api/v1/auth/password/reset", json={"token": token, "newPassword": "NewPassw0rd!"})

    actions = [e.action for e in await audit_entries()]
    assert actions == ["user.registered", "user.email_verified", "user.password_reset"]


async def test_password_is_never_logged(client: AsyncClient) -> None:
    await register(client)
    for entry in await audit_entries():
        assert "Passw0rd" not in str(entry.data)
