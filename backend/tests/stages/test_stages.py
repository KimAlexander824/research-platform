"""Этапы через API: CRUD, порядок, блокировки, проверка руководителем, история, прогресс (B5)."""

from httpx import AsyncClient
from sqlalchemy import select

from app.audit.models import AuditLog
from app.core.database import SessionFactory
from app.projects.models import ProjectRole
from tests.helpers import get_user, make_user
from tests.projects.test_projects import API, add_member, create_project


class Ctx:
    def __init__(self, owner: dict, sup: dict | None, pid: str, wid: str) -> None:
        self.owner, self.sup, self.pid, self.wid = owner, sup, pid, wid

    @property
    def url(self) -> str:
        return f"{API}/{self.pid}/works/{self.wid}/stages"


async def setup(client: AsyncClient, *, with_supervisor: bool = True) -> Ctx:
    owner = await make_user(client, "owner@example.com", name="Исследователь")
    pid = (await create_project(client, owner))["id"]
    sup = None
    body = {"title": "Диссертация", "type": "dissertation"}
    if with_supervisor:
        sup = await make_user(client, "sup@example.com", name="Профессор")
        await add_member(pid, "sup@example.com", ProjectRole.SUPERVISOR)
        body["supervisorId"] = str((await get_user("sup@example.com")).id)
    wid = (await client.post(f"{API}/{pid}/works", json=body, headers=owner)).json()["id"]
    return Ctx(owner, sup, pid, wid)


async def add_stage(client: AsyncClient, c: Ctx, title: str, **extra) -> dict:
    response = await client.post(c.url, json={"title": title, **extra}, headers=c.owner)
    assert response.status_code == 201, response.text
    return response.json()


async def set_status(client: AsyncClient, c: Ctx, stage: dict, status: str, headers: dict | None = None, **extra):
    return await client.post(
        f"{c.url}/{stage['id']}/status", json={"status": status, **extra}, headers=headers or c.owner
    )


# --- CRUD и порядок ---


async def test_create_and_list(client: AsyncClient) -> None:
    c = await setup(client)
    owner_id = str((await get_user("owner@example.com")).id)
    first = await add_stage(client, c, "Обзор литературы", deadline="2026-12-01", responsibleId=owner_id)
    second = await add_stage(client, c, "Эксперимент", isRequired=False, description="Описание")

    assert first["position"] == 0 and second["position"] == 1
    assert first["status"] == "not_started" and first["isRequired"] is True
    assert first["deadline"] == "2026-12-01"
    assert first["responsible"]["email"] == "owner@example.com"
    assert second["isRequired"] is False

    stages = (await client.get(c.url, headers=c.owner)).json()
    assert [s["title"] for s in stages] == ["Обзор литературы", "Эксперимент"]


async def test_responsible_must_be_member(client: AsyncClient) -> None:
    c = await setup(client)
    await make_user(client, "stranger@example.com")
    stranger_id = str((await get_user("stranger@example.com")).id)
    response = await client.post(c.url, json={"title": "X", "responsibleId": stranger_id}, headers=c.owner)
    assert response.status_code == 422
    assert response.json()["error"]["fields"] == {"responsibleId": ["NOT_PROJECT_MEMBER"]}


async def test_update_and_delete(client: AsyncClient) -> None:
    c = await setup(client)
    a = await add_stage(client, c, "A")
    b = await add_stage(client, c, "B")
    await add_stage(client, c, "C")

    response = await client.patch(f"{c.url}/{b['id']}", json={"title": "B2", "deadline": "2027-01-01"}, headers=c.owner)
    assert response.status_code == 200 and response.json()["title"] == "B2"

    assert (await client.delete(f"{c.url}/{a['id']}", headers=c.owner)).status_code == 204
    stages = (await client.get(c.url, headers=c.owner)).json()
    assert [(s["title"], s["position"]) for s in stages] == [("B2", 0), ("C", 1)]


async def test_reorder(client: AsyncClient) -> None:
    c = await setup(client)
    a, b, d = [await add_stage(client, c, t) for t in "ABD"]
    response = await client.put(f"{c.url}/order", json={"stageIds": [d["id"], a["id"], b["id"]]}, headers=c.owner)
    assert response.status_code == 200
    assert [s["title"] for s in response.json()] == ["D", "A", "B"]

    bad = await client.put(f"{c.url}/order", json={"stageIds": [a["id"], b["id"]]}, headers=c.owner)
    assert bad.status_code == 422 and bad.json()["error"]["fields"] == {"stageIds": ["INVALID"]}


# --- Блокировки ---


async def test_required_stage_blocks_next(client: AsyncClient) -> None:
    c = await setup(client)
    first = await add_stage(client, c, "Обязательный")
    second = await add_stage(client, c, "Следующий")

    stages = (await client.get(c.url, headers=c.owner)).json()
    assert stages[0]["isBlocked"] is False
    assert stages[1]["isBlocked"] is True
    assert stages[1]["blockedBy"] == {"id": first["id"], "title": "Обязательный", "status": "not_started"}
    assert stages[1]["availableTransitions"] == []

    response = await set_status(client, c, second, "in_progress")
    assert response.status_code == 409 and response.json()["error"]["code"] == "STAGE_BLOCKED"


async def test_optional_stage_does_not_block(client: AsyncClient) -> None:
    c = await setup(client)
    await add_stage(client, c, "Необязательный", isRequired=False)
    second = await add_stage(client, c, "Следующий")
    assert (await set_status(client, c, second, "in_progress")).status_code == 200


# --- Полный цикл проверки руководителем (раздел 9) ---


async def test_full_review_cycle(client: AsyncClient) -> None:
    c = await setup(client)
    first = await add_stage(client, c, "Глава 1")
    second = await add_stage(client, c, "Глава 2")

    assert (await set_status(client, c, first, "in_progress")).json()["availableTransitions"] == ["pending_review"]
    # Обязательный этап при наличии руководителя исследователь сам не завершает
    direct = await set_status(client, c, first, "completed")
    assert direct.status_code == 409 and direct.json()["error"]["code"] == "SUPERVISOR_REVIEW_REQUIRED"

    await set_status(client, c, first, "pending_review")
    seen_by_sup = (await client.get(f"{c.url}/{first['id']}", headers=c.sup)).json()
    assert seen_by_sup["availableTransitions"] == ["needs_revision", "completed", "rejected"]

    # Руководитель возвращает на доработку — следующий этап остаётся заблокированным
    revision = await set_status(client, c, first, "needs_revision", headers=c.sup, comment="Добавьте источники")
    assert revision.status_code == 200
    assert (await set_status(client, c, second, "in_progress")).json()["error"]["code"] == "STAGE_BLOCKED"

    # Исследователь исправляет и снова отправляет, руководитель подтверждает
    assert (await set_status(client, c, first, "pending_review")).status_code == 200
    assert (await set_status(client, c, first, "completed", headers=c.sup)).status_code == 200
    # Теперь следующий этап открыт
    assert (await set_status(client, c, second, "in_progress")).status_code == 200


async def test_rejected_blocks_until_supervisor_reconsiders(client: AsyncClient) -> None:
    c = await setup(client)
    first = await add_stage(client, c, "Глава 1")
    second = await add_stage(client, c, "Глава 2")
    await set_status(client, c, first, "in_progress")
    await set_status(client, c, first, "pending_review")
    assert (await set_status(client, c, first, "rejected", headers=c.sup, comment="Не принято")).status_code == 200

    # Исследователь ничего не может сделать с отклонённым этапом, следующие заблокированы
    stages = (await client.get(c.url, headers=c.owner)).json()
    assert stages[0]["availableTransitions"] == []
    assert stages[1]["isBlocked"] is True
    assert (await set_status(client, c, second, "in_progress")).json()["error"]["code"] == "STAGE_BLOCKED"

    # Руководитель пересматривает решение — этап возвращается на доработку
    sup_view = (await client.get(f"{c.url}/{first['id']}", headers=c.sup)).json()
    assert sup_view["availableTransitions"] == ["needs_revision"]
    reconsider = await set_status(client, c, first, "needs_revision", headers=c.sup, comment="Пересмотрено")
    assert reconsider.status_code == 200
    # Дальше обычный цикл: исправить → на проверку → подтвердить
    await set_status(client, c, first, "pending_review")
    await set_status(client, c, first, "completed", headers=c.sup)
    assert (await set_status(client, c, second, "in_progress")).status_code == 200


async def test_researcher_completes_required_stage_without_supervisor(client: AsyncClient) -> None:
    c = await setup(client, with_supervisor=False)
    stage = await add_stage(client, c, "Глава 1")
    await set_status(client, c, stage, "in_progress")
    review = await set_status(client, c, stage, "pending_review")
    assert review.json()["error"]["code"] == "NO_SUPERVISOR"
    assert (await set_status(client, c, stage, "completed")).status_code == 200


async def test_external_supervisor_name_counts_as_no_supervisor(client: AsyncClient) -> None:
    c = await setup(client, with_supervisor=False)
    await client.patch(f"{API}/{c.pid}/works/{c.wid}", json={"supervisorName": "Внешний"}, headers=c.owner)
    stage = await add_stage(client, c, "Глава 1")
    await set_status(client, c, stage, "in_progress")
    assert (await set_status(client, c, stage, "completed")).status_code == 200


async def test_researcher_cannot_approve_and_supervisor_cannot_start(client: AsyncClient) -> None:
    c = await setup(client)
    stage = await add_stage(client, c, "Глава 1")
    assert (await set_status(client, c, stage, "in_progress", headers=c.sup)).json()["error"]["code"] == "TRANSITION_NOT_ALLOWED"
    await set_status(client, c, stage, "in_progress")
    await set_status(client, c, stage, "pending_review")
    assert (await set_status(client, c, stage, "completed")).json()["error"]["code"] == "TRANSITION_NOT_ALLOWED"


async def test_other_project_supervisor_has_no_access(client: AsyncClient) -> None:
    c = await setup(client)
    other = await make_user(client, "sup2@example.com")
    await add_member(c.pid, "sup2@example.com", ProjectRole.SUPERVISOR)
    stage = await add_stage(client, c, "Глава 1")
    # Руководитель проекта, но не этой работы — работа для него не существует
    response = await client.get(c.url, headers=other)
    assert response.status_code == 404 and response.json()["error"]["code"] == "WORK_NOT_FOUND"
    assert (await set_status(client, c, stage, "in_progress", headers=other)).status_code == 404


async def test_supervisor_cannot_edit_stages(client: AsyncClient) -> None:
    c = await setup(client)
    stage = await add_stage(client, c, "Глава 1")
    assert (await client.post(c.url, json={"title": "X"}, headers=c.sup)).status_code == 403
    assert (await client.patch(f"{c.url}/{stage['id']}", json={"title": "X"}, headers=c.sup)).status_code == 403
    assert (await client.delete(f"{c.url}/{stage['id']}", headers=c.sup)).status_code == 403


# --- Защита от обхода проверки ---


async def test_required_flag_locked_after_start(client: AsyncClient) -> None:
    c = await setup(client)
    stage = await add_stage(client, c, "Глава 1")
    await set_status(client, c, stage, "in_progress")
    response = await client.patch(f"{c.url}/{stage['id']}", json={"isRequired": False}, headers=c.owner)
    assert response.status_code == 409 and response.json()["error"]["code"] == "STAGE_REQUIRED_LOCKED"
    response = await client.delete(f"{c.url}/{stage['id']}", headers=c.owner)
    assert response.json()["error"]["code"] == "STAGE_REQUIRED_LOCKED"


async def test_required_flag_can_change_before_start(client: AsyncClient) -> None:
    c = await setup(client)
    stage = await add_stage(client, c, "Глава 1")
    response = await client.patch(f"{c.url}/{stage['id']}", json={"isRequired": False}, headers=c.owner)
    assert response.status_code == 200 and response.json()["isRequired"] is False


# --- История и журнал ---


async def test_history(client: AsyncClient) -> None:
    c = await setup(client)
    stage = await add_stage(client, c, "Глава 1")
    await set_status(client, c, stage, "in_progress")
    await set_status(client, c, stage, "pending_review")
    await set_status(client, c, stage, "needs_revision", headers=c.sup, comment="Исправьте выводы")

    history = (await client.get(f"{c.url}/{stage['id']}/history", headers=c.owner)).json()
    assert [(h["fromStatus"], h["toStatus"]) for h in history] == [
        (None, "not_started"),
        ("not_started", "in_progress"),
        ("in_progress", "pending_review"),
        ("pending_review", "needs_revision"),
    ]
    assert history[-1]["comment"] == "Исправьте выводы"
    assert history[-1]["actor"]["email"] == "sup@example.com"

    async with SessionFactory() as db:
        entries = (await db.scalars(select(AuditLog).where(AuditLog.action == "stage.status_changed"))).all()
    assert len(entries) == 3


async def test_archived_project_blocks_transitions(client: AsyncClient) -> None:
    c = await setup(client)
    stage = await add_stage(client, c, "Глава 1")
    await client.post(f"{API}/{c.pid}/archive", headers=c.owner)
    assert (await client.get(c.url, headers=c.owner)).json()[0]["availableTransitions"] == []
    assert (await set_status(client, c, stage, "in_progress")).json()["error"]["code"] == "PROJECT_ARCHIVED"


# --- Прогресс ---


async def test_progress_work_and_project(client: AsyncClient) -> None:
    c = await setup(client, with_supervisor=False)
    # Работа 1: 2 этапа, оба завершены
    for title in ("A", "B"):
        stage = await add_stage(client, c, title)
        await set_status(client, c, stage, "in_progress")
        await set_status(client, c, stage, "completed")
    # Работа 2: 4 этапа, ни один не завершён
    wid2 = (await client.post(f"{API}/{c.pid}/works", json={"title": "Статья", "type": "article"}, headers=c.owner)).json()["id"]
    for title in "CDEF":
        await client.post(f"{API}/{c.pid}/works/{wid2}/stages", json={"title": title}, headers=c.owner)

    work1 = (await client.get(f"{API}/{c.pid}/works/{c.wid}", headers=c.owner)).json()
    assert work1["progress"] == {"completed": 2, "total": 2, "percent": 100}
    works = (await client.get(f"{API}/{c.pid}/works", headers=c.owner)).json()["items"]
    assert {w["title"]: w["progress"]["percent"] for w in works} == {"Диссертация": 100, "Статья": 0}

    # Проект: 2 завершённых из 6 этапов всех работ = 33%
    project = (await client.get(f"{API}/{c.pid}", headers=c.owner)).json()
    assert project["progress"] == {"completed": 2, "total": 6, "percent": 33}
    listed = (await client.get(API, headers=c.owner)).json()["items"][0]
    assert listed["progress"]["percent"] == 33


async def test_project_progress_for_supervisor_counts_only_their_works(client: AsyncClient) -> None:
    c = await setup(client)  # работа, где sup — руководитель
    await add_stage(client, c, "A")
    wid2 = (await client.post(f"{API}/{c.pid}/works", json={"title": "Чужая", "type": "article"}, headers=c.owner)).json()["id"]
    for title in "BC":
        stage = (await client.post(f"{API}/{c.pid}/works/{wid2}/stages", json={"title": title, "isRequired": False}, headers=c.owner)).json()
        await client.post(f"{API}/{c.pid}/works/{wid2}/stages/{stage['id']}/status", json={"status": "in_progress"}, headers=c.owner)
        await client.post(f"{API}/{c.pid}/works/{wid2}/stages/{stage['id']}/status", json={"status": "completed"}, headers=c.owner)

    assert (await client.get(f"{API}/{c.pid}", headers=c.owner)).json()["progress"] == {"completed": 2, "total": 3, "percent": 67}
    assert (await client.get(f"{API}/{c.pid}", headers=c.sup)).json()["progress"] == {"completed": 0, "total": 1, "percent": 0}


async def test_empty_progress(client: AsyncClient) -> None:
    c = await setup(client)
    assert (await client.get(f"{API}/{c.pid}", headers=c.owner)).json()["progress"] == {"completed": 0, "total": 0, "percent": 0}
