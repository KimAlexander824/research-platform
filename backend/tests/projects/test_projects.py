"""Проекты: CRUD, архив, фильтры и права доступа (B3, B4)."""

from httpx import AsyncClient
from sqlalchemy import select

from app.audit.models import AuditLog
from app.core.database import SessionFactory
from app.projects.models import ProjectMember, ProjectRole
from tests.helpers import get_user, make_user

API = "/api/v1/projects"


async def create_project(client: AsyncClient, headers: dict, title: str = "Диссертация", **extra) -> dict:
    response = await client.post(API, json={"title": title, **extra}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


async def add_member(project_id: str, email: str, role: ProjectRole) -> None:
    """Добавляет участника напрямую в БД (приглашения проверяются в отдельных тестах)."""
    user = await get_user(email)
    async with SessionFactory() as db:
        db.add(ProjectMember(project_id=project_id, user_id=user.id, role=role))
        await db.commit()


# --- Создание и просмотр ---


async def test_create_project(client: AsyncClient) -> None:
    owner = await make_user(client, "owner@example.com", name="Владелец")
    project = await create_project(client, owner, title="  Диссертация  ", description="Описание")
    assert project["title"] == "Диссертация"
    assert project["description"] == "Описание"
    assert project["myRole"] == "owner"
    assert project["membersCount"] == 1
    assert project["isArchived"] is False
    assert project["owner"]["email"] == "owner@example.com"


async def test_create_project_validation(client: AsyncClient) -> None:
    owner = await make_user(client, "owner@example.com")
    response = await client.post(API, json={"title": "   "}, headers=owner)
    assert response.status_code == 422
    assert "title" in response.json()["error"]["fields"]


async def test_user_can_have_many_projects(client: AsyncClient) -> None:
    owner = await make_user(client, "owner@example.com")
    for i in range(3):
        await create_project(client, owner, title=f"Проект {i}")
    response = await client.get(API, headers=owner)
    assert response.json()["total"] == 3


async def test_get_project(client: AsyncClient) -> None:
    owner = await make_user(client, "owner@example.com")
    project = await create_project(client, owner)
    response = await client.get(f"{API}/{project['id']}", headers=owner)
    assert response.status_code == 200
    assert response.json()["id"] == project["id"]


# --- Права доступа ---


async def test_outsider_cannot_see_project(client: AsyncClient) -> None:
    owner = await make_user(client, "owner@example.com")
    outsider = await make_user(client, "outsider@example.com")
    project = await create_project(client, owner)

    # Чужой проект не виден ни в списке, ни по прямой ссылке — как будто его нет
    assert (await client.get(API, headers=outsider)).json()["total"] == 0
    for method, url in [
        ("GET", f"{API}/{project['id']}"),
        ("PATCH", f"{API}/{project['id']}"),
        ("DELETE", f"{API}/{project['id']}"),
        ("GET", f"{API}/{project['id']}/members"),
    ]:
        response = await client.request(method, url, headers=outsider, json={"title": "x"} if method == "PATCH" else None)
        assert response.status_code == 404, (method, url)
        assert response.json()["error"]["code"] == "PROJECT_NOT_FOUND"


async def test_nonexistent_project_same_error_as_foreign(client: AsyncClient) -> None:
    user = await make_user(client, "user@example.com")
    response = await client.get(f"{API}/00000000-0000-0000-0000-000000000000", headers=user)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PROJECT_NOT_FOUND"


async def test_role_permissions_matrix(client: AsyncClient) -> None:
    owner = await make_user(client, "owner@example.com")
    project = await create_project(client, owner)
    pid = project["id"]

    expected = {
        # роль: (может редактировать, может архивировать/удалять/управлять участниками)
        ProjectRole.EDITOR: (True, False),
        ProjectRole.VIEWER: (False, False),
        ProjectRole.SUPERVISOR: (False, False),
    }
    for role, (can_edit, can_manage) in expected.items():
        email = f"{role.value}@example.com"
        headers = await make_user(client, email)
        await add_member(pid, email, role)

        assert (await client.get(f"{API}/{pid}", headers=headers)).json()["myRole"] == role.value
        assert (await client.get(f"{API}/{pid}/members", headers=headers)).status_code == 200

        edit = await client.patch(f"{API}/{pid}", json={"title": f"by {role.value}"}, headers=headers)
        assert edit.status_code == (200 if can_edit else 403), role

        for method, url in [
            ("POST", f"{API}/{pid}/archive"),
            ("DELETE", f"{API}/{pid}"),
            ("GET", f"{API}/{pid}/invitations"),
        ]:
            response = await client.request(method, url, headers=headers)
            assert response.status_code == 403, (role, method, url)
            assert response.json()["error"]["code"] == "FORBIDDEN"


# --- Редактирование ---


async def test_update_project_and_audit(client: AsyncClient) -> None:
    owner = await make_user(client, "owner@example.com")
    project = await create_project(client, owner)
    response = await client.patch(f"{API}/{project['id']}", json={"description": "Новое"}, headers=owner)
    assert response.status_code == 200
    assert response.json()["description"] == "Новое"
    assert response.json()["title"] == "Диссертация"

    async with SessionFactory() as db:
        entry = await db.scalar(select(AuditLog).where(AuditLog.action == "project.updated"))
    assert entry.data == {"description": [None, "Новое"]}


# --- Архив ---


async def test_archive_and_restore(client: AsyncClient) -> None:
    owner = await make_user(client, "owner@example.com")
    project = await create_project(client, owner)
    pid = project["id"]

    archived = await client.post(f"{API}/{pid}/archive", headers=owner)
    assert archived.status_code == 200 and archived.json()["isArchived"] is True

    # Архив — только чтение
    edit = await client.patch(f"{API}/{pid}", json={"title": "x"}, headers=owner)
    assert edit.status_code == 409 and edit.json()["error"]["code"] == "PROJECT_ARCHIVED"
    assert (await client.post(f"{API}/{pid}/archive", headers=owner)).status_code == 409

    restored = await client.post(f"{API}/{pid}/restore", headers=owner)
    assert restored.status_code == 200 and restored.json()["isArchived"] is False
    assert (await client.post(f"{API}/{pid}/restore", headers=owner)).json()["error"]["code"] == "PROJECT_NOT_ARCHIVED"


async def test_list_filters_by_status(client: AsyncClient) -> None:
    owner = await make_user(client, "owner@example.com")
    active = await create_project(client, owner, title="Активный")
    archived = await create_project(client, owner, title="Архивный")
    await client.post(f"{API}/{archived['id']}/archive", headers=owner)

    async def titles(**params) -> list[str]:
        return [p["title"] for p in (await client.get(API, params=params, headers=owner)).json()["items"]]

    assert await titles() == ["Активный"]  # по умолчанию — только рабочие
    assert await titles(status="archived") == ["Архивный"]
    assert sorted(await titles(status="all")) == ["Активный", "Архивный"]
    assert active["id"]


# --- Удаление ---


async def test_delete_project(client: AsyncClient) -> None:
    owner = await make_user(client, "owner@example.com")
    member = await make_user(client, "member@example.com")
    project = await create_project(client, owner)
    await add_member(project["id"], "member@example.com", ProjectRole.EDITOR)

    assert (await client.delete(f"{API}/{project['id']}", headers=owner)).status_code == 204
    assert (await client.get(f"{API}/{project['id']}", headers=owner)).status_code == 404
    assert (await client.get(API, headers=member)).json()["total"] == 0

    async with SessionFactory() as db:
        entry = await db.scalar(select(AuditLog).where(AuditLog.action == "project.deleted"))
    assert entry.data == {"title": "Диссертация"}


# --- Поиск, фильтры, сортировка ---


async def test_search_and_sort(client: AsyncClient) -> None:
    owner = await make_user(client, "owner@example.com")
    await create_project(client, owner, title="Б: машинное обучение")
    await create_project(client, owner, title="А: история", description="Про машинное обучение")
    await create_project(client, owner, title="В: химия")

    found = (await client.get(API, params={"search": "МАШИННОЕ"}, headers=owner)).json()
    assert found["total"] == 2

    by_title = (await client.get(API, params={"sort": "title"}, headers=owner)).json()["items"]
    assert [p["title"][0] for p in by_title] == ["А", "Б", "В"]
    desc = (await client.get(API, params={"sort": "-title"}, headers=owner)).json()["items"]
    assert [p["title"][0] for p in desc] == ["В", "Б", "А"]

    bad = await client.get(API, params={"sort": "password"}, headers=owner)
    assert bad.status_code == 422


async def test_filter_by_my_role(client: AsyncClient) -> None:
    owner = await make_user(client, "owner@example.com")
    other = await make_user(client, "other@example.com")
    await create_project(client, owner, title="Мой")
    shared = await create_project(client, other, title="Чужой, где я руководитель")
    await add_member(shared["id"], "owner@example.com", ProjectRole.SUPERVISOR)

    mine = (await client.get(API, params={"role": "owner"}, headers=owner)).json()["items"]
    supervised = (await client.get(API, params={"role": "supervisor"}, headers=owner)).json()["items"]
    assert [p["title"] for p in mine] == ["Мой"]
    assert [p["title"] for p in supervised] == ["Чужой, где я руководитель"]


async def test_pagination(client: AsyncClient) -> None:
    owner = await make_user(client, "owner@example.com")
    for i in range(5):
        await create_project(client, owner, title=f"П{i}")
    page = (await client.get(API, params={"page": 2, "pageSize": 2}, headers=owner)).json()
    assert page["total"] == 5 and len(page["items"]) == 2 and page["page"] == 2
