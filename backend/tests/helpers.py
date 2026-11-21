"""Общие помощники для тестов разных модулей."""

from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy import select, update

from app.accounts.models import User
from app.core.database import SessionFactory

PASSWORD = "Str0ngPassw0rd"


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def make_user(
    client: AsyncClient, email: str, *, name: str = "Тестовый Пользователь", verified: bool = True
) -> dict[str, str]:
    """Регистрирует пользователя и возвращает заголовки авторизации."""
    response = await client.post(
        "/api/v1/auth/register", json={"email": email, "password": PASSWORD, "fullName": name}
    )
    assert response.status_code == 201, response.text
    if verified:
        async with SessionFactory() as db:
            await db.execute(update(User).where(User.email == email).values(email_verified_at=datetime.now(UTC)))
            await db.commit()
    return bearer(response.json()["accessToken"])


async def get_user(email: str) -> User:
    async with SessionFactory() as db:
        user = await db.scalar(select(User).where(User.email == email))
        assert user is not None
        return user
