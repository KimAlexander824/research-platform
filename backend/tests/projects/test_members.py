"""Участники и приглашения (B3)."""

from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import select, update

from app.audit.models import AuditLog
from app.core.database import SessionFactory
from app.projects.models import ProjectInvitation
from tests.conftest import FakeMailSender
from tests.helpers import get_user, make_user
from tests.projects.test_projects import API, create_project


async def invite(client: AsyncClient, headers: dict, pid: str, email: str, role: str = "editor"):
    return await client.post(f"{API}/{pid}/invitations", json={"email": email, "role": role}, headers=headers)


async def setup(client: AsyncClient) -> tuple[dict, dict, str]:
    owner = await make_user(client, "owner@example.com", name="Владелец Проекта")
    guest = await make_user(client, "guest@example.com")
    project = await create_project(client, owner)
    return owner, guest, project["id"]


# --- Приглашение и принятие ---


async def test_invite_registered_user_and_accept(client: AsyncClient, outbox: FakeMailSender) -> None:
    owner, guest, pid = await setup(client)

    response = await invite(client, owner, pid, " Guest@Example.com ")
    assert response.status_code == 201, response.text
    invitation = response.json()
    assert invitation["email"] == "guest@example.com"
    assert invitation["status"] == "pending"
    assert invitation["invitedBy"]["email"] == "owner@example.com"

    message = outbox.messages[-1]
    assert message.to == "guest@example.com"
    assert "Владелец Проекта" in message.text and "Диссертация" in message.text

    mine = (await client.get("/api/v1/invitations", headers=guest)).json()
    assert [i["id"] for i in mine] == [invitation["id"]]

    accepted = await client.post(f"/api/v1/invitations/{invitation['id']}/accept", headers=guest)
    assert accepted.status_code == 200
    assert accepted.json()["myRole"] == "editor"
    assert (await client.get(f"{API}/{pid}", headers=guest)).status_code == 200
    assert (await client.get("/api/v1/invitations", headers=guest)).json() == []

    members = (await client.get(f"{API}/{pid}/members", headers=owner)).json()
    assert {m["user"]["email"]: m["role"] for m in members} == {
        "owner@example.com": "owner",
        "guest@example.com": "editor",
    }


async def test_invite_unregistered_then_register(client: AsyncClient, outbox: FakeMailSender) -> None:
    owner = await make_user(client, "owner@example.com")
    pid = (await create_project(client, owner))["id"]
    assert (await invite(client, owner, pid, "new@example.com")).status_code == 201
    assert outbox.messages[-1].to == "new@example.com"

    # Человек регистрируется позже с тем же email — приглашение его ждёт
    newcomer = await make_user(client, "new@example.com")
    mine = (await client.get("/api/v1/invitations", headers=newcomer)).json()
    assert len(mine) == 1
    assert (await client.post(f"/api/v1/invitations/{mine[0]['id']}/accept", headers=newcomer)).status_code == 200


async def test_supervisor_invitation_grants_supervisor_role(client: AsyncClient) -> None:
    owner, guest, pid = await setup(client)
    invitation = (await invite(client, owner, pid, "guest@example.com", role="supervisor")).json()
    await client.post(f"/api/v1/invitations/{invitation['id']}/accept", headers=guest)

    assert (await client.get("/api/v1/me", headers=guest)).json()["role"] == "supervisor"
    async with SessionFactory() as db:
        entry = await db.scalar(select(AuditLog).where(AuditLog.action == "user.role_changed"))
    assert entry.data == {"role": ["researcher", "supervisor"], "source": "project_invitation"}


async def test_accept_requires_verified_email(client: AsyncClient) -> None:
    owner = await make_user(client, "owner@example.com")
    pid = (await create_project(client, owner))["id"]
    unverified = await make_user(client, "guest@example.com", verified=False)
    invitation = (await invite(client, owner, pid, "guest@example.com")).json()

    response = await client.post(f"/api/v1/invitations/{invitation['id']}/accept", headers=unverified)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "EMAIL_NOT_VERIFIED"


async def test_cannot_accept_someone_elses_invitation(client: AsyncClient) -> None:
    owner, _, pid = await setup(client)
    stranger = await make_user(client, "stranger@example.com")
    invitation = (await invite(client, owner, pid, "guest@example.com")).json()

    response = await client.post(f"/api/v1/invitations/{invitation['id']}/accept", headers=stranger)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "INVITATION_NOT_FOUND"
    assert (await client.get(f"{API}/{pid}", headers=stranger)).status_code == 404


async def test_decline_invitation(client: AsyncClient) -> None:
    owner, guest, pid = await setup(client)
    invitation = (await invite(client, owner, pid, "guest@example.com")).json()
    assert (await client.post(f"/api/v1/invitations/{invitation['id']}/decline", headers=guest)).status_code == 204
    assert (await client.get(f"{API}/{pid}", headers=guest)).status_code == 404

    again = await client.post(f"/api/v1/invitations/{invitation['id']}/accept", headers=guest)
    assert again.json()["error"]["code"] == "INVITATION_NOT_PENDING"

    statuses = [i["status"] for i in (await client.get(f"{API}/{pid}/invitations", headers=owner)).json()]
    assert statuses == ["declined"]


async def test_revoke_invitation(client: AsyncClient) -> None:
    owner, guest, pid = await setup(client)
    invitation = (await invite(client, owner, pid, "guest@example.com")).json()
    assert (await client.delete(f"{API}/{pid}/invitations/{invitation['id']}", headers=owner)).status_code == 204
    response = await client.post(f"/api/v1/invitations/{invitation['id']}/accept", headers=guest)
    assert response.json()["error"]["code"] == "INVITATION_NOT_PENDING"


async def test_expired_invitation(client: AsyncClient) -> None:
    owner, guest, pid = await setup(client)
    invitation = (await invite(client, owner, pid, "guest@example.com")).json()
    async with SessionFactory() as db:
        await db.execute(
            update(ProjectInvitation).values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
        )
        await db.commit()

    assert (await client.get("/api/v1/invitations", headers=guest)).json() == []
    response = await client.post(f"/api/v1/invitations/{invitation['id']}/accept", headers=guest)
    assert response.json()["error"]["code"] == "INVITATION_NOT_PENDING"
    listed = (await client.get(f"{API}/{pid}/invitations", headers=owner)).json()
    assert listed[0]["status"] == "expired"

    # Истёкшее приглашение можно заменить новым
    assert (await invite(client, owner, pid, "guest@example.com")).status_code == 201


async def test_duplicate_invitation_and_existing_member(client: AsyncClient) -> None:
    owner, guest, pid = await setup(client)
    assert (await invite(client, owner, pid, "guest@example.com")).status_code == 201
    duplicate = await invite(client, owner, pid, "guest@example.com")
    assert duplicate.status_code == 409 and duplicate.json()["error"]["code"] == "INVITATION_ALREADY_PENDING"

    self_invite = await invite(client, owner, pid, "owner@example.com")
    assert self_invite.status_code == 409 and self_invite.json()["error"]["code"] == "ALREADY_MEMBER"


async def test_cannot_invite_as_owner(client: AsyncClient) -> None:
    owner, _, pid = await setup(client)
    response = await invite(client, owner, pid, "guest@example.com", role="owner")
    assert response.status_code == 422


async def test_only_owner_can_invite(client: AsyncClient) -> None:
    owner, guest, pid = await setup(client)
    invitation = (await invite(client, owner, pid, "guest@example.com")).json()
    await client.post(f"/api/v1/invitations/{invitation['id']}/accept", headers=guest)
    response = await invite(client, guest, pid, "third@example.com")
    assert response.status_code == 403


async def test_cannot_invite_to_archived_project(client: AsyncClient) -> None:
    owner, _, pid = await setup(client)
    await client.post(f"{API}/{pid}/archive", headers=owner)
    response = await invite(client, owner, pid, "guest@example.com")
    assert response.status_code == 409 and response.json()["error"]["code"] == "PROJECT_ARCHIVED"


# --- Управление участниками ---


async def join(client: AsyncClient, owner: dict, guest: dict, pid: str, role: str = "editor") -> None:
    invitation = (await invite(client, owner, pid, "guest@example.com", role=role)).json()
    await client.post(f"/api/v1/invitations/{invitation['id']}/accept", headers=guest)


async def test_change_member_role(client: AsyncClient) -> None:
    owner, guest, pid = await setup(client)
    await join(client, owner, guest, pid)
    guest_id = (await get_user("guest@example.com")).id

    response = await client.patch(f"{API}/{pid}/members/{guest_id}", json={"role": "viewer"}, headers=owner)
    assert response.status_code == 200 and response.json()["role"] == "viewer"
    # Теперь только чтение
    assert (await client.patch(f"{API}/{pid}", json={"title": "x"}, headers=guest)).status_code == 403


async def test_remove_member_revokes_access(client: AsyncClient) -> None:
    owner, guest, pid = await setup(client)
    await join(client, owner, guest, pid)
    guest_id = (await get_user("guest@example.com")).id

    assert (await client.delete(f"{API}/{pid}/members/{guest_id}", headers=owner)).status_code == 204
    assert (await client.get(f"{API}/{pid}", headers=guest)).status_code == 404


async def test_owner_cannot_be_removed_or_changed(client: AsyncClient) -> None:
    owner, _, pid = await setup(client)
    owner_id = (await get_user("owner@example.com")).id
    remove = await client.delete(f"{API}/{pid}/members/{owner_id}", headers=owner)
    change = await client.patch(f"{API}/{pid}/members/{owner_id}", json={"role": "viewer"}, headers=owner)
    assert remove.json()["error"]["code"] == "OWNER_CANNOT_BE_CHANGED"
    assert change.json()["error"]["code"] == "OWNER_CANNOT_BE_CHANGED"


async def test_member_actions_are_logged(client: AsyncClient) -> None:
    owner, guest, pid = await setup(client)
    await join(client, owner, guest, pid)
    guest_id = (await get_user("guest@example.com")).id
    await client.delete(f"{API}/{pid}/members/{guest_id}", headers=owner)

    async with SessionFactory() as db:
        actions = list((await db.scalars(
            select(AuditLog.action).where(AuditLog.entity_type == "project").order_by(AuditLog.created_at)
        )).all())
    assert actions == [
        "project.created",
        "project.member_invited",
        "project.invitation_accepted",
        "project.member_removed",
    ]
