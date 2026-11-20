"""Профиль пользователя (B2)."""

import re

from httpx import AsyncClient

from app.core.config import settings
from app.core.storage import Storage
from tests.accounts.test_auth import PASSWORD, bearer, login, register
from tests.conftest import FakeMailSender

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 100


async def auth(client: AsyncClient, email: str = "user@example.com") -> dict[str, str]:
    return bearer((await register(client, email=email))["accessToken"])


async def get_me(client: AsyncClient, headers: dict[str, str]) -> dict:
    response = await client.get("/api/v1/me", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


# --- Получение и редактирование ---


async def test_me_returns_full_profile(client: AsyncClient) -> None:
    data = await get_me(client, await auth(client))
    assert data["fullName"] == "Иванов Иван"
    assert data["language"] == "ru"
    for field in ("phone", "avatarUrl", "organization", "position", "academicDegree", "academicTitle", "researchInterests"):
        assert data[field] is None
    assert data["settings"] == {}


async def test_update_profile(client: AsyncClient) -> None:
    headers = await auth(client)
    payload = {
        "fullName": "  Петров Пётр Петрович ",
        "phone": "+998 90 123-45-67",
        "language": "uz",
        "organization": "НУУз",
        "position": "Доцент",
        "academicDegree": "Кандидат наук",
        "academicTitle": "Доцент",
        "researchInterests": "Машинное обучение",
        "settings": {"theme": "dark"},
    }
    response = await client.patch("/api/v1/me", json=payload, headers=headers)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["fullName"] == "Петров Пётр Петрович"
    assert data["phone"] == "+998 90 123-45-67"
    assert data["language"] == "uz"
    assert data["academicDegree"] == "Кандидат наук"
    assert data["settings"] == {"theme": "dark"}
    assert await get_me(client, headers) == data


async def test_partial_update_keeps_other_fields(client: AsyncClient) -> None:
    headers = await auth(client)
    await client.patch("/api/v1/me", json={"organization": "НУУз", "position": "Доцент"}, headers=headers)
    await client.patch("/api/v1/me", json={"position": "Профессор"}, headers=headers)
    data = await get_me(client, headers)
    assert data["organization"] == "НУУз"
    assert data["position"] == "Профессор"


async def test_null_clears_optional_field(client: AsyncClient) -> None:
    headers = await auth(client)
    await client.patch("/api/v1/me", json={"phone": "+998901234567"}, headers=headers)
    await client.patch("/api/v1/me", json={"phone": None}, headers=headers)
    assert (await get_me(client, headers))["phone"] is None


async def test_update_validation(client: AsyncClient) -> None:
    headers = await auth(client)
    response = await client.patch(
        "/api/v1/me",
        json={"fullName": None, "phone": "abc", "language": "fr", "settings": None},
        headers=headers,
    )
    assert response.status_code == 422
    assert set(response.json()["error"]["fields"]) == {"fullName", "phone", "language", "settings"}


async def test_settings_size_limit(client: AsyncClient) -> None:
    headers = await auth(client)
    response = await client.patch("/api/v1/me", json={"settings": {"x": "a" * 20_000}}, headers=headers)
    assert response.status_code == 422


async def test_profile_requires_auth(client: AsyncClient) -> None:
    assert (await client.patch("/api/v1/me", json={"fullName": "X"})).status_code == 401


async def test_role_and_email_cannot_be_changed_via_profile(client: AsyncClient) -> None:
    headers = await auth(client)
    response = await client.patch(
        "/api/v1/me", json={"role": "admin", "email": "hacker@example.com"}, headers=headers
    )
    assert response.status_code == 422
    assert response.json()["error"]["fields"] == {"role": ["NOT_ALLOWED"], "email": ["NOT_ALLOWED"]}
    data = await get_me(client, headers)
    assert data["role"] == "researcher"
    assert data["email"] == "user@example.com"


# --- Смена email ---


async def test_change_email(client: AsyncClient, outbox: FakeMailSender) -> None:
    headers = await auth(client)
    response = await client.post(
        "/api/v1/me/email", json={"newEmail": "New@Example.com", "currentPassword": PASSWORD}, headers=headers
    )
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "new@example.com"
    assert data["emailVerified"] is False
    assert outbox.messages[-1].to == "new@example.com"

    token = re.search(r"token=([\w-]+)", outbox.messages[-1].text).group(1)
    await client.post("/api/v1/auth/verify-email/confirm", json={"token": token})
    assert (await get_me(client, headers))["emailVerified"] is True
    assert (await login(client, email="new@example.com")).status_code == 200


async def test_change_email_wrong_password(client: AsyncClient) -> None:
    headers = await auth(client)
    response = await client.post(
        "/api/v1/me/email", json={"newEmail": "new@example.com", "currentPassword": "wrong"}, headers=headers
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_PASSWORD"
    assert (await get_me(client, headers))["email"] == "user@example.com"


async def test_change_email_to_taken(client: AsyncClient) -> None:
    await register(client, email="taken@example.com")
    headers = await auth(client)
    response = await client.post(
        "/api/v1/me/email", json={"newEmail": "taken@example.com", "currentPassword": PASSWORD}, headers=headers
    )
    assert response.status_code == 409
    assert response.json()["error"]["fields"] == {"newEmail": ["ALREADY_EXISTS"]}


# --- Фото профиля ---


async def test_upload_avatar(client: AsyncClient, storage: Storage) -> None:
    headers = await auth(client)
    response = await client.put(
        "/api/v1/me/avatar", files={"file": ("me.png", PNG_BYTES, "image/png")}, headers=headers
    )
    assert response.status_code == 200, response.text
    url = response.json()["avatarUrl"]
    assert url and "X-Amz-Signature" in url

    keys = [o["Key"] for o in storage._client.list_objects_v2(Bucket=storage.bucket).get("Contents", [])]
    assert len(keys) == 1 and keys[0].endswith(".png")


async def test_replace_avatar_deletes_old(client: AsyncClient, storage: Storage) -> None:
    headers = await auth(client)
    await client.put("/api/v1/me/avatar", files={"file": ("a.png", PNG_BYTES, "image/png")}, headers=headers)
    await client.put("/api/v1/me/avatar", files={"file": ("b.jpg", JPEG_BYTES, "image/jpeg")}, headers=headers)
    keys = [o["Key"] for o in storage._client.list_objects_v2(Bucket=storage.bucket).get("Contents", [])]
    assert len(keys) == 1 and keys[0].endswith(".jpg")


async def test_delete_avatar(client: AsyncClient, storage: Storage) -> None:
    headers = await auth(client)
    await client.put("/api/v1/me/avatar", files={"file": ("a.png", PNG_BYTES, "image/png")}, headers=headers)
    response = await client.delete("/api/v1/me/avatar", headers=headers)
    assert response.status_code == 200
    assert response.json()["avatarUrl"] is None
    assert storage._client.list_objects_v2(Bucket=storage.bucket).get("KeyCount") == 0


async def test_avatar_type_checked_by_content(client: AsyncClient) -> None:
    headers = await auth(client)
    # Расширение и Content-Type говорят «картинка», но внутри — не картинка
    response = await client.put(
        "/api/v1/me/avatar", files={"file": ("evil.png", b"<script>alert(1)</script>", "image/png")}, headers=headers
    )
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"


async def test_avatar_size_limit(client: AsyncClient, monkeypatch) -> None:
    monkeypatch.setattr(settings, "AVATAR_MAX_SIZE_MB", 1)
    headers = await auth(client)
    big = PNG_BYTES + b"\x00" * (1024 * 1024)
    response = await client.put("/api/v1/me/avatar", files={"file": ("big.png", big, "image/png")}, headers=headers)
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "FILE_TOO_LARGE"
