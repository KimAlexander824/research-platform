"""Общие фикстуры тестов.

Тесты работают с настоящими PostgreSQL и Redis (из docker-compose):
    docker compose up -d postgres redis

Используется отдельная база `research_test` (создаётся автоматически) и Redis DB 15,
поэтому данные разработки не затрагиваются.
"""

import os

# Переменные окружения задаются ДО импорта приложения — настройки читаются при импорте
os.environ.setdefault(
    "TEST_DATABASE_URL", "postgresql+asyncpg://research:research@localhost:5432/research_test"
)
os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
os.environ["REDIS_URL"] = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/15")
os.environ["ENVIRONMENT"] = "development"

from collections.abc import AsyncIterator  # noqa: E402

import asyncpg  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from app.core.database import engine  # noqa: E402
from app.core.mail import EmailMessage, get_mail_sender  # noqa: E402
from app.core.models_registry import Base  # noqa: E402
from app.core.redis import close_redis, get_redis  # noqa: E402
from app.main import create_app  # noqa: E402


async def _ensure_test_database() -> None:
    url = make_url(os.environ["DATABASE_URL"])
    conn = await asyncpg.connect(
        user=url.username, password=url.password, host=url.host, port=url.port or 5432, database="postgres"
    )
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", url.database)
        if not exists:
            await conn.execute(f'CREATE DATABASE "{url.database}"')
    finally:
        await conn.close()


@pytest_asyncio.fixture(scope="session", loop_scope="session", autouse=True)
async def _database() -> AsyncIterator[None]:
    await _ensure_test_database()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
    yield


@pytest.fixture(autouse=True)
async def _clean_state() -> AsyncIterator[None]:
    """Каждый тест начинается с пустой базы и пустого Redis."""
    yield
    tables = ", ".join(f'"{t.name}"' for t in reversed(Base.metadata.sorted_tables))
    if tables:
        async with engine.begin() as conn:
            await conn.execute(text(f"TRUNCATE {tables} CASCADE"))
    await get_redis().flushdb()
    # Пулы соединений привязаны к event loop теста — закрываем их
    await close_redis()
    await engine.dispose()


class FakeMailSender:
    """Вместо отправки складывает письма в список — тесты читают из него ссылки."""

    def __init__(self) -> None:
        self.messages: list[EmailMessage] = []

    async def send(self, message: EmailMessage) -> None:
        self.messages.append(message)


@pytest.fixture
def outbox() -> FakeMailSender:
    return FakeMailSender()


@pytest.fixture
def app(outbox: FakeMailSender) -> FastAPI:
    app = create_app()
    app.dependency_overrides[get_mail_sender] = lambda: outbox
    return app


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
