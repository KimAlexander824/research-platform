"""Параметры пагинации и формат страницы."""

from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.pagination import MAX_PAGE_SIZE, Page, PageParams, page_params
from app.main import create_app


@pytest.fixture
def app() -> FastAPI:
    app = create_app()

    @app.get("/test/page")
    async def page(params: Annotated[PageParams, Depends(page_params)]) -> Page[int]:
        return Page(items=[1, 2], total=42, page=params.page, page_size=params.page_size)

    return app


@pytest.fixture
async def client(app: FastAPI):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


async def test_defaults(client: AsyncClient) -> None:
    response = await client.get("/test/page")
    assert response.json() == {"items": [1, 2], "total": 42, "page": 1, "pageSize": 20}


async def test_custom_page(client: AsyncClient) -> None:
    response = await client.get("/test/page", params={"page": 3, "pageSize": 50})
    body = response.json()
    assert body["page"] == 3
    assert body["pageSize"] == 50


async def test_page_size_limit(client: AsyncClient) -> None:
    response = await client.get("/test/page", params={"pageSize": MAX_PAGE_SIZE + 1})
    assert response.status_code == 422
    assert response.json()["error"]["fields"] == {"pageSize": ["TOO_LARGE"]}


def test_offset() -> None:
    assert PageParams(page=3, page_size=20).offset == 40
