"""Регистрация, вход, токены, сессии, защита от перебора (B2)."""

from httpx import AsyncClient

from app.core.config import settings

PASSWORD = "Str0ngPassw0rd"


async def register(client: AsyncClient, email: str = "user@example.com", password: str = PASSWORD) -> dict:
    response = await client.post(
        "/api/v1/auth/register", json={"email": email, "password": password, "fullName": "Иванов Иван"}
    )
    assert response.status_code == 201, response.text
    return response.json()


async def login(client: AsyncClient, email: str = "user@example.com", password: str = PASSWORD):
    return await client.post("/api/v1/auth/login", json={"email": email, "password": password})


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --- Регистрация ---


async def test_register_returns_tokens_and_cookie(client: AsyncClient) -> None:
    body = await register(client)
    assert body["tokenType"] == "bearer"
    assert body["expiresIn"] == settings.ACCESS_TOKEN_TTL_MINUTES * 60
    assert body["accessToken"]
    assert client.cookies.get(settings.REFRESH_COOKIE_NAME)


async def test_register_sets_researcher_role(client: AsyncClient) -> None:
    body = await register(client)
    me = await client.get("/api/v1/me", headers=bearer(body["accessToken"]))
    assert me.status_code == 200
    data = me.json()
    assert data["email"] == "user@example.com"
    assert data["fullName"] == "Иванов Иван"
    assert data["role"] == "researcher"
    assert "passwordHash" not in data


async def test_register_normalizes_email(client: AsyncClient) -> None:
    await register(client, email="  User@Example.COM ")
    response = await login(client, email="user@example.com")
    assert response.status_code == 200


async def test_register_duplicate_email(client: AsyncClient) -> None:
    await register(client)
    response = await client.post(
        "/api/v1/auth/register", json={"email": "USER@example.com", "password": PASSWORD, "fullName": "X"}
    )
    assert response.status_code == 409
    assert response.json()["error"] == {
        "code": "EMAIL_ALREADY_EXISTS",
        "message": "User with this email already exists",
        "fields": {"email": ["ALREADY_EXISTS"]},
    }


async def test_register_validation(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/register", json={"email": "not-an-email", "password": "short", "fullName": "  "}
    )
    assert response.status_code == 422
    fields = response.json()["error"]["fields"]
    assert set(fields) == {"email", "password", "fullName"}
    assert fields["password"] == ["TOO_SHORT"]


# --- Вход ---


async def test_login_success(client: AsyncClient) -> None:
    await register(client)
    response = await login(client)
    assert response.status_code == 200
    assert response.json()["accessToken"]


async def test_login_wrong_password(client: AsyncClient) -> None:
    await register(client)
    response = await login(client, password="wrong-password")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


async def test_login_unknown_email_same_error(client: AsyncClient) -> None:
    response = await login(client, email="nobody@example.com")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


async def test_login_lockout_after_failed_attempts(client: AsyncClient) -> None:
    await register(client)
    for _ in range(settings.LOGIN_MAX_ATTEMPTS):
        assert (await login(client, password="wrong-password")).status_code == 401

    # Даже правильный пароль не помогает, пока действует блокировка
    response = await login(client)
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "TOO_MANY_LOGIN_ATTEMPTS"
    assert int(response.headers["Retry-After"]) > 0


async def test_successful_login_resets_failed_attempts(client: AsyncClient) -> None:
    await register(client)
    for _ in range(settings.LOGIN_MAX_ATTEMPTS - 1):
        await login(client, password="wrong-password")
    assert (await login(client)).status_code == 200
    for _ in range(settings.LOGIN_MAX_ATTEMPTS - 1):
        await login(client, password="wrong-password")
    assert (await login(client)).status_code == 200


async def test_rate_limit_on_auth_endpoints(client: AsyncClient) -> None:
    statuses = []
    for i in range(settings.AUTH_RATE_LIMIT_PER_MINUTE + 1):
        response = await login(client, email=f"user{i}@example.com")
        statuses.append(response.status_code)
    assert statuses[-1] == 429
    assert all(s == 401 for s in statuses[:-1])


# --- Доступ по токену ---


async def test_me_requires_token(client: AsyncClient) -> None:
    response = await client.get("/api/v1/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


async def test_me_with_invalid_token(client: AsyncClient) -> None:
    response = await client.get("/api/v1/me", headers=bearer("garbage"))
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_TOKEN"


# --- Обновление токена ---


async def test_refresh_rotates_token(client: AsyncClient) -> None:
    await register(client)
    old_refresh = client.cookies.get(settings.REFRESH_COOKIE_NAME)

    response = await client.post("/api/v1/auth/refresh")
    assert response.status_code == 200
    new_refresh = client.cookies.get(settings.REFRESH_COOKIE_NAME)
    assert new_refresh and new_refresh != old_refresh

    me = await client.get("/api/v1/me", headers=bearer(response.json()["accessToken"]))
    assert me.status_code == 200


async def test_old_refresh_token_is_invalid_after_rotation(client: AsyncClient) -> None:
    await register(client)
    old_refresh = client.cookies.get(settings.REFRESH_COOKIE_NAME)
    await client.post("/api/v1/auth/refresh")

    client.cookies.clear()
    client.cookies.set(settings.REFRESH_COOKIE_NAME, old_refresh)
    response = await client.post("/api/v1/auth/refresh")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_REFRESH_TOKEN"


async def test_refresh_without_cookie(client: AsyncClient) -> None:
    response = await client.post("/api/v1/auth/refresh")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_REFRESH_TOKEN"


# --- Выход и сессии ---


async def test_logout_invalidates_access_and_refresh(client: AsyncClient) -> None:
    token = (await register(client))["accessToken"]
    refresh = client.cookies.get(settings.REFRESH_COOKIE_NAME)

    response = await client.post("/api/v1/auth/logout", headers=bearer(token))
    assert response.status_code == 204

    assert (await client.get("/api/v1/me", headers=bearer(token))).status_code == 401
    client.cookies.clear()
    client.cookies.set(settings.REFRESH_COOKIE_NAME, refresh)
    response = await client.post("/api/v1/auth/refresh")
    assert response.status_code == 401


async def test_list_sessions_marks_current(client: AsyncClient) -> None:
    await register(client)
    token = (await login(client)).json()["accessToken"]

    response = await client.get("/api/v1/auth/sessions", headers=bearer(token))
    assert response.status_code == 200
    sessions = response.json()
    assert len(sessions) == 2
    assert sum(s["isCurrent"] for s in sessions) == 1


async def test_revoke_other_session(client: AsyncClient) -> None:
    first_token = (await register(client))["accessToken"]
    second_token = (await login(client)).json()["accessToken"]

    sessions = (await client.get("/api/v1/auth/sessions", headers=bearer(second_token))).json()
    other = next(s for s in sessions if not s["isCurrent"])

    response = await client.delete(f"/api/v1/auth/sessions/{other['id']}", headers=bearer(second_token))
    assert response.status_code == 204
    assert (await client.get("/api/v1/me", headers=bearer(first_token))).status_code == 401
    assert (await client.get("/api/v1/me", headers=bearer(second_token))).status_code == 200


async def test_revoke_all_other_sessions(client: AsyncClient) -> None:
    first = (await register(client))["accessToken"]
    second = (await login(client)).json()["accessToken"]
    current = (await login(client)).json()["accessToken"]

    response = await client.delete("/api/v1/auth/sessions", headers=bearer(current))
    assert response.status_code == 204
    assert (await client.get("/api/v1/me", headers=bearer(first))).status_code == 401
    assert (await client.get("/api/v1/me", headers=bearer(second))).status_code == 401
    sessions = (await client.get("/api/v1/auth/sessions", headers=bearer(current))).json()
    assert len(sessions) == 1


async def test_cannot_revoke_session_of_another_user(client: AsyncClient) -> None:
    alice = (await register(client, email="alice@example.com"))["accessToken"]
    bob = (await register(client, email="bob@example.com"))["accessToken"]
    bob_session = (await client.get("/api/v1/auth/sessions", headers=bearer(bob))).json()[0]

    response = await client.delete(f"/api/v1/auth/sessions/{bob_session['id']}", headers=bearer(alice))
    assert response.status_code == 404
    assert (await client.get("/api/v1/me", headers=bearer(bob))).status_code == 200
