"""Научные работы (B4)."""

from httpx import AsyncClient
from sqlalchemy import select

from app.audit.models import AuditLog
from app.core.database import SessionFactory
from app.projects.models import ProjectRole
from tests.helpers import get_user, make_user
from tests.projects.test_projects import API, add_member, create_project

FULL = {
    "title": "Методы машинного обучения в медицине",
    "type": "dissertation",
    "description": "Описание",
    "direction": "05.13.01",
    "topic": "Тема",
    "goal": "Цель",
    "tasks": "1. ...\n2. ...",
    "hypothesis": "Гипотеза",
    "researchObject": "Объект",
    "researchSubject": "Предмет",
    "methodology": "Методология",
    "startDate": "2026-09-01",
    "endDate": "2027-06-30",
}


async def setup(client: AsyncClient) -> tuple[dict, str]:
    owner = await make_user(client, "owner@example.com", name="Иванов Иван")
    project = await create_project(client, owner)
    return owner, project["id"]


def works_url(pid: str) -> str:
    return f"{API}/{pid}/works"


async def create_work(client: AsyncClient, headers: dict, pid: str, **data):
    return await client.post(works_url(pid), json={"title": "Работа", "type": "article", **data}, headers=headers)


# --- Создание ---


async def test_create_work_with_all_fields(client: AsyncClient) -> None:
    owner, pid = await setup(client)
    response = await client.post(works_url(pid), json=FULL, headers=owner)
    assert response.status_code == 201, response.text
    work = response.json()
    for key, value in FULL.items():
        assert work[key] == value, key
    assert work["projectId"] == pid
    # Автор по умолчанию — создатель
    assert [a["fullName"] for a in work["authors"]] == ["Иванов Иван"]
    assert work["authors"][0]["user"]["email"] == "owner@example.com"


async def test_preset_types(client: AsyncClient) -> None:
    owner, pid = await setup(client)
    types = ["article", "research", "coursework", "diploma", "master_thesis", "dissertation", "theses", "conference_paper"]
    for work_type in types:
        assert (await create_work(client, owner, pid, type=work_type)).status_code == 201, work_type
    assert (await create_work(client, owner, pid, type="poem")).status_code == 422


async def test_custom_type(client: AsyncClient) -> None:
    owner, pid = await setup(client)
    missing = await create_work(client, owner, pid, type="custom")
    assert missing.status_code == 422
    assert missing.json()["error"]["fields"] == {"customTypeName": ["REQUIRED"]}

    work = (await create_work(client, owner, pid, type="custom", customTypeName="Монография")).json()
    assert work["type"] == "custom" and work["customTypeName"] == "Монография"

    # Для предустановленного типа своё название не сохраняется
    other = (await create_work(client, owner, pid, type="article", customTypeName="лишнее")).json()
    assert other["customTypeName"] is None


async def test_dates_validation(client: AsyncClient) -> None:
    owner, pid = await setup(client)
    response = await create_work(client, owner, pid, startDate="2027-01-01", endDate="2026-01-01")
    assert response.status_code == 422
    assert response.json()["error"]["fields"] == {"endDate": ["BEFORE_START_DATE"]}


# --- Авторы и руководитель ---


async def test_authors_members_and_external(client: AsyncClient) -> None:
    owner, pid = await setup(client)
    await make_user(client, "coauthor@example.com", name="Петров Пётр")
    await add_member(pid, "coauthor@example.com", ProjectRole.EDITOR)
    coauthor_id = str((await get_user("coauthor@example.com")).id)
    owner_id = str((await get_user("owner@example.com")).id)

    work = (
        await create_work(
            client, owner, pid,
            authors=[{"userId": owner_id}, {"userId": coauthor_id}, {"fullName": "Сидоров С. С."}],
        )
    ).json()
    assert [(a["fullName"], a["position"], a["user"] is not None) for a in work["authors"]] == [
        ("Иванов Иван", 0, True),
        ("Петров Пётр", 1, True),
        ("Сидоров С. С.", 2, False),
    ]


async def test_author_must_be_project_member(client: AsyncClient) -> None:
    owner, pid = await setup(client)
    await make_user(client, "stranger@example.com")
    stranger_id = str((await get_user("stranger@example.com")).id)
    response = await create_work(client, owner, pid, authors=[{"userId": stranger_id}])
    assert response.status_code == 422
    assert response.json()["error"]["fields"] == {"authors": ["NOT_PROJECT_MEMBER"]}


async def test_author_validation(client: AsyncClient) -> None:
    owner, pid = await setup(client)
    owner_id = str((await get_user("owner@example.com")).id)
    assert (await create_work(client, owner, pid, authors=[])).json()["error"]["fields"] == {"authors": ["REQUIRED"]}
    dup = await create_work(client, owner, pid, authors=[{"userId": owner_id}, {"userId": owner_id}])
    assert dup.json()["error"]["fields"] == {"authors": ["DUPLICATE"]}
    both = await create_work(client, owner, pid, authors=[{"userId": owner_id, "fullName": "X"}])
    assert both.status_code == 422
    neither = await create_work(client, owner, pid, authors=[{}])
    assert neither.status_code == 422


async def test_supervisor_must_be_project_supervisor(client: AsyncClient) -> None:
    owner, pid = await setup(client)
    await make_user(client, "sup@example.com", name="Профессор")
    await make_user(client, "editor@example.com")
    await add_member(pid, "sup@example.com", ProjectRole.SUPERVISOR)
    await add_member(pid, "editor@example.com", ProjectRole.EDITOR)
    sup_id = str((await get_user("sup@example.com")).id)
    editor_id = str((await get_user("editor@example.com")).id)

    wrong = await create_work(client, owner, pid, supervisorId=editor_id)
    assert wrong.json()["error"]["fields"] == {"supervisorId": ["NOT_PROJECT_SUPERVISOR"]}

    work = (await create_work(client, owner, pid, supervisorId=sup_id)).json()
    assert work["supervisor"]["email"] == "sup@example.com"
    assert work["supervisorName"] == "Профессор"


async def test_external_supervisor_by_name(client: AsyncClient) -> None:
    owner, pid = await setup(client)
    work = (await create_work(client, owner, pid, supervisorName="д.т.н. Каримов К.")).json()
    assert work["supervisor"] is None and work["supervisorName"] == "д.т.н. Каримов К."


# --- Редактирование и удаление ---


async def test_update_work(client: AsyncClient) -> None:
    owner, pid = await setup(client)
    work = (await client.post(works_url(pid), json=FULL, headers=owner)).json()

    response = await client.patch(
        f"{works_url(pid)}/{work['id']}",
        json={"goal": "Новая цель", "hypothesis": None, "authors": [{"fullName": "Внешний Автор"}]},
        headers=owner,
    )
    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["goal"] == "Новая цель"
    assert updated["hypothesis"] is None
    assert updated["topic"] == "Тема"  # не переданное поле не изменилось
    assert [a["fullName"] for a in updated["authors"]] == ["Внешний Автор"]

    async with SessionFactory() as db:
        entry = await db.scalar(select(AuditLog).where(AuditLog.action == "work.updated"))
    assert entry.data["goal"] == ["Цель", "Новая цель"]
    assert entry.data["hypothesis"] == ["Гипотеза", None]
    assert entry.data["authors"][1] == ["Внешний Автор"]


async def test_update_validation_uses_final_state(client: AsyncClient) -> None:
    owner, pid = await setup(client)
    work = (await client.post(works_url(pid), json=FULL, headers=owner)).json()
    # Конец раньше уже сохранённого начала
    response = await client.patch(f"{works_url(pid)}/{work['id']}", json={"endDate": "2020-01-01"}, headers=owner)
    assert response.json()["error"]["fields"] == {"endDate": ["BEFORE_START_DATE"]}
    # Тип custom без названия
    response = await client.patch(f"{works_url(pid)}/{work['id']}", json={"type": "custom"}, headers=owner)
    assert response.json()["error"]["fields"] == {"customTypeName": ["REQUIRED"]}
    # Обязательные поля нельзя очистить
    response = await client.patch(f"{works_url(pid)}/{work['id']}", json={"title": None, "authors": None}, headers=owner)
    assert set(response.json()["error"]["fields"]) == {"title", "authors"}


async def test_delete_work(client: AsyncClient) -> None:
    owner, pid = await setup(client)
    work = (await create_work(client, owner, pid)).json()
    assert (await client.delete(f"{works_url(pid)}/{work['id']}", headers=owner)).status_code == 204
    response = await client.get(f"{works_url(pid)}/{work['id']}", headers=owner)
    assert response.status_code == 404 and response.json()["error"]["code"] == "WORK_NOT_FOUND"


async def test_project_deletion_deletes_works(client: AsyncClient) -> None:
    owner, pid = await setup(client)
    await create_work(client, owner, pid)
    await client.delete(f"{API}/{pid}", headers=owner)
    from app.works.models import ResearchWork

    async with SessionFactory() as db:
        assert (await db.scalars(select(ResearchWork))).all() == []


# --- Права ---


async def test_permissions(client: AsyncClient) -> None:
    owner, pid = await setup(client)
    work = (await create_work(client, owner, pid)).json()
    url = f"{works_url(pid)}/{work['id']}"

    for role, can_edit in [(ProjectRole.EDITOR, True), (ProjectRole.VIEWER, False)]:
        email = f"{role.value}@example.com"
        headers = await make_user(client, email)
        await add_member(pid, email, role)
        assert (await client.get(url, headers=headers)).status_code == 200
        listed = (await client.get(works_url(pid), headers=headers)).json()["items"]
        assert work["id"] in [w["id"] for w in listed]
        expected = 200 if can_edit else 403
        assert (await client.patch(url, json={"goal": role.value}, headers=headers)).status_code == expected, role
        expected = 201 if can_edit else 403
        assert (await create_work(client, headers, pid)).status_code == expected, role


async def test_supervisor_sees_only_assigned_works(client: AsyncClient) -> None:
    owner, pid = await setup(client)
    sup = await make_user(client, "sup@example.com")
    await make_user(client, "sup2@example.com")
    await add_member(pid, "sup@example.com", ProjectRole.SUPERVISOR)
    await add_member(pid, "sup2@example.com", ProjectRole.SUPERVISOR)
    sup_id = str((await get_user("sup@example.com")).id)
    sup2_id = str((await get_user("sup2@example.com")).id)

    mine = (await create_work(client, owner, pid, title="Моя", supervisorId=sup_id)).json()
    other = (await create_work(client, owner, pid, title="Чужая", supervisorId=sup2_id)).json()
    unassigned = (await create_work(client, owner, pid, title="Без руководителя")).json()

    # Руководитель видит проект, но в нём — только свои работы (раздел 9 ТЗ)
    assert (await client.get(f"{API}/{pid}", headers=sup)).status_code == 200
    listed = (await client.get(works_url(pid), headers=sup)).json()
    assert [w["title"] for w in listed["items"]] == ["Моя"] and listed["total"] == 1
    assert (await client.get(f"{works_url(pid)}/{mine['id']}", headers=sup)).status_code == 200
    for work in (other, unassigned):
        response = await client.get(f"{works_url(pid)}/{work['id']}", headers=sup)
        assert response.status_code == 404 and response.json()["error"]["code"] == "WORK_NOT_FOUND"

    # Руководитель не редактирует и не создаёт работы
    assert (await client.patch(f"{works_url(pid)}/{mine['id']}", json={"goal": "x"}, headers=sup)).status_code == 403
    assert (await create_work(client, sup, pid)).status_code == 403

    # Владелец видит все работы
    assert (await client.get(works_url(pid), headers=owner)).json()["total"] == 3


async def test_reassigning_supervisor_changes_visibility(client: AsyncClient) -> None:
    owner, pid = await setup(client)
    sup = await make_user(client, "sup@example.com")
    await add_member(pid, "sup@example.com", ProjectRole.SUPERVISOR)
    sup_id = str((await get_user("sup@example.com")).id)
    work = (await create_work(client, owner, pid)).json()
    url = f"{works_url(pid)}/{work['id']}"

    assert (await client.get(url, headers=sup)).status_code == 404
    await client.patch(url, json={"supervisorId": sup_id}, headers=owner)
    assert (await client.get(url, headers=sup)).status_code == 200
    await client.patch(url, json={"supervisorName": "Внешний руководитель"}, headers=owner)
    assert (await client.get(url, headers=sup)).status_code == 404


async def test_outsider_and_wrong_project(client: AsyncClient) -> None:
    owner, pid = await setup(client)
    work = (await create_work(client, owner, pid)).json()
    outsider = await make_user(client, "outsider@example.com")
    assert (await client.get(f"{works_url(pid)}/{work['id']}", headers=outsider)).status_code == 404

    # Работа одного проекта недоступна по адресу другого проекта
    other_pid = (await create_project(client, owner, title="Другой"))["id"]
    response = await client.get(f"{works_url(other_pid)}/{work['id']}", headers=owner)
    assert response.status_code == 404 and response.json()["error"]["code"] == "WORK_NOT_FOUND"


async def test_archived_project_is_read_only(client: AsyncClient) -> None:
    owner, pid = await setup(client)
    work = (await create_work(client, owner, pid)).json()
    await client.post(f"{API}/{pid}/archive", headers=owner)
    assert (await client.get(f"{works_url(pid)}/{work['id']}", headers=owner)).status_code == 200
    response = await client.patch(f"{works_url(pid)}/{work['id']}", json={"goal": "x"}, headers=owner)
    assert response.json()["error"]["code"] == "PROJECT_ARCHIVED"


# --- Поиск, фильтр, сортировка ---


async def test_filter_search_sort(client: AsyncClient) -> None:
    owner, pid = await setup(client)
    await create_work(client, owner, pid, title="Б статья", type="article", endDate="2027-01-01")
    await create_work(client, owner, pid, title="А тезисы", type="theses", topic="нейросети", endDate="2026-01-01")
    await create_work(client, owner, pid, title="В статья", type="article", endDate="2028-01-01")

    async def titles(**params) -> list[str]:
        return [w["title"] for w in (await client.get(works_url(pid), params=params, headers=owner)).json()["items"]]

    assert sorted(await titles(type="article")) == ["Б статья", "В статья"]
    assert await titles(search="НЕЙРО") == ["А тезисы"]
    assert await titles(sort="title") == ["А тезисы", "Б статья", "В статья"]
    assert await titles(sort="-endDate") == ["В статья", "Б статья", "А тезисы"]
