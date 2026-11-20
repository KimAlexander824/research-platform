"""Подтверждение email и восстановление пароля (B2)."""

import re

from httpx import AsyncClient

from app.core.config import settings
from tests.accounts.test_auth import PASSWORD, bearer, login, register
from tests.conftest import FakeMailSender


def token_from(outbox: FakeMailSender, index: int = -1) -> str:
    match = re.search(r"token=([\w-]+)", outbox.messages[index].text)
    assert match, outbox.messages[index].text
    return match.group(1)


async def me(client: AsyncClient, token: str) -> dict:
    return (await client.get("/api/v1/me", headers=bearer(token))).json()


# --- Подтверждение email ---


async def test_register_sends_verification_email(client: AsyncClient, outbox: FakeMailSender) -> None:
    token = (await register(client))["accessToken"]
    assert len(outbox.messages) == 1
    message = outbox.messages[0]
    assert message.to == "user@example.com"
    assert f"{settings.FRONTEND_URL}{settings.FRONTEND_VERIFY_EMAIL_PATH}?token=" in message.text
    assert (await me(client, token))["emailVerified"] is False


async def test_verification_email_in_user_language(client: AsyncClient, outbox: FakeMailSender) -> None:
    await client.post(
        "/api/v1/auth/register",
        json={"email": "uz@example.com", "password": PASSWORD, "fullName": "Ali", "language": "uz"},
    )
    assert outbox.messages[0].subject == "Emailingizni tasdiqlang"


async def test_confirm_email(client: AsyncClient, outbox: FakeMailSender) -> None:
    access = (await register(client))["accessToken"]
    response = await client.post("/api/v1/auth/verify-email/confirm", json={"token": token_from(outbox)})
    assert response.status_code == 204
    assert (await me(client, access))["emailVerified"] is True


async def test_confirm_email_token_is_single_use(client: AsyncClient, outbox: FakeMailSender) -> None:
    await register(client)
    token = token_from(outbox)
    await client.post("/api/v1/auth/verify-email/confirm", json={"token": token})
    response = await client.post("/api/v1/auth/verify-email/confirm", json={"token": token})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_EMAIL_TOKEN"


async def test_confirm_email_invalid_token(client: AsyncClient) -> None:
    response = await client.post("/api/v1/auth/verify-email/confirm", json={"token": "nope"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_EMAIL_TOKEN"


async def test_resend_verification_invalidates_previous_link(client: AsyncClient, outbox: FakeMailSender) -> None:
    access = (await register(client))["accessToken"]
    old_token = token_from(outbox)

    response = await client.post("/api/v1/auth/verify-email/request", headers=bearer(access))
    assert response.status_code == 202
    assert len(outbox.messages) == 2

    old = await client.post("/api/v1/auth/verify-email/confirm", json={"token": old_token})
    assert old.status_code == 400
    new = await client.post("/api/v1/auth/verify-email/confirm", json={"token": token_from(outbox)})
    assert new.status_code == 204


async def test_resend_verification_cooldown(client: AsyncClient, outbox: FakeMailSender) -> None:
    access = (await register(client))["accessToken"]
    first = await client.post("/api/v1/auth/verify-email/request", headers=bearer(access))
    assert first.status_code == 202
    second = await client.post("/api/v1/auth/verify-email/request", headers=bearer(access))
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "EMAIL_COOLDOWN"
    assert "Retry-After" in second.headers


async def test_resend_verification_when_already_verified(client: AsyncClient, outbox: FakeMailSender) -> None:
    access = (await register(client))["accessToken"]
    await client.post("/api/v1/auth/verify-email/confirm", json={"token": token_from(outbox)})
    response = await client.post("/api/v1/auth/verify-email/request", headers=bearer(access))
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "EMAIL_ALREADY_VERIFIED"


async def test_resend_verification_requires_auth(client: AsyncClient) -> None:
    response = await client.post("/api/v1/auth/verify-email/request")
    assert response.status_code == 401


# --- Восстановление пароля ---


async def test_forgot_password_sends_email(client: AsyncClient, outbox: FakeMailSender) -> None:
    await register(client)
    response = await client.post("/api/v1/auth/password/forgot", json={"email": "USER@example.com"})
    assert response.status_code == 202
    assert len(outbox.messages) == 2
    assert f"{settings.FRONTEND_RESET_PASSWORD_PATH}?token=" in outbox.messages[-1].text


async def test_forgot_password_unknown_email_same_response(client: AsyncClient, outbox: FakeMailSender) -> None:
    response = await client.post("/api/v1/auth/password/forgot", json={"email": "nobody@example.com"})
    assert response.status_code == 202
    assert outbox.messages == []


async def test_reset_password(client: AsyncClient, outbox: FakeMailSender) -> None:
    await register(client)
    await client.post("/api/v1/auth/password/forgot", json={"email": "user@example.com"})

    response = await client.post(
        "/api/v1/auth/password/reset", json={"token": token_from(outbox), "newPassword": "NewPassw0rd!"}
    )
    assert response.status_code == 204
    assert (await login(client)).status_code == 401
    assert (await login(client, password="NewPassw0rd!")).status_code == 200


async def test_reset_password_logs_out_everywhere(client: AsyncClient, outbox: FakeMailSender) -> None:
    access = (await register(client))["accessToken"]
    await client.post("/api/v1/auth/password/forgot", json={"email": "user@example.com"})
    await client.post(
        "/api/v1/auth/password/reset", json={"token": token_from(outbox), "newPassword": "NewPassw0rd!"}
    )
    assert (await client.get("/api/v1/me", headers=bearer(access))).status_code == 401


async def test_reset_password_verifies_email(client: AsyncClient, outbox: FakeMailSender) -> None:
    await register(client)
    await client.post("/api/v1/auth/password/forgot", json={"email": "user@example.com"})
    await client.post(
        "/api/v1/auth/password/reset", json={"token": token_from(outbox), "newPassword": "NewPassw0rd!"}
    )
    access = (await login(client, password="NewPassw0rd!")).json()["accessToken"]
    assert (await me(client, access))["emailVerified"] is True


async def test_reset_token_is_single_use(client: AsyncClient, outbox: FakeMailSender) -> None:
    await register(client)
    await client.post("/api/v1/auth/password/forgot", json={"email": "user@example.com"})
    token = token_from(outbox)
    await client.post("/api/v1/auth/password/reset", json={"token": token, "newPassword": "NewPassw0rd!"})
    response = await client.post(
        "/api/v1/auth/password/reset", json={"token": token, "newPassword": "Another1!"}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_EMAIL_TOKEN"


async def test_verify_token_cannot_reset_password(client: AsyncClient, outbox: FakeMailSender) -> None:
    await register(client)
    response = await client.post(
        "/api/v1/auth/password/reset", json={"token": token_from(outbox), "newPassword": "NewPassw0rd!"}
    )
    assert response.status_code == 400


async def test_reset_password_validation(client: AsyncClient) -> None:
    response = await client.post("/api/v1/auth/password/reset", json={"token": "x", "newPassword": "short"})
    assert response.status_code == 422
    assert response.json()["error"]["fields"] == {"newPassword": ["TOO_SHORT"]}
