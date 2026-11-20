"""Единый формат ошибок API."""

from typing import Annotated

import pytest
from fastapi import FastAPI, Query
from httpx import ASGITransport, AsyncClient
from pydantic import Field

from app.core.errors import ConflictError, NotFoundError
from app.core.schemas import BaseSchema
from app.main import create_app


class ItemIn(BaseSchema):
    title: str = Field(min_length=3)
    page_count: int = Field(ge=1)


@pytest.fixture
def app() -> FastAPI:
    app = create_app()

    @app.get("/test/not-found")
    async def not_found() -> None:
        raise NotFoundError()

    @app.get("/test/conflict")
    async def conflict() -> None:
        raise ConflictError("Stage is locked", code="STAGE_LOCKED")

    @app.get("/test/crash")
    async def crash() -> None:
        raise RuntimeError("secret internal details")

    @app.post("/test/items")
    async def create_item(item: ItemIn) -> ItemIn:
        return item

    @app.get("/test/query")
    async def query(limit: Annotated[int, Query(ge=1)]) -> int:
        return limit

    return app


@pytest.fixture
async def client(app: FastAPI):
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def test_app_error(client: AsyncClient) -> None:
    response = await client.get("/test/not-found")
    assert response.status_code == 404
    assert response.json() == {"error": {"code": "NOT_FOUND", "message": "Resource not found"}}


async def test_app_error_with_custom_code(client: AsyncClient) -> None:
    response = await client.get("/test/conflict")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "STAGE_LOCKED"


async def test_unknown_route(client: AsyncClient) -> None:
    response = await client.get("/no-such-route")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


async def test_method_not_allowed(client: AsyncClient) -> None:
    response = await client.delete("/test/not-found")
    assert response.status_code == 405
    assert response.json()["error"]["code"] == "METHOD_NOT_ALLOWED"


async def test_validation_error_body(client: AsyncClient) -> None:
    response = await client.post("/test/items", json={"title": "ab"})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert error["fields"] == {"title": ["TOO_SHORT"], "pageCount": ["REQUIRED"]}


async def test_validation_error_query(client: AsyncClient) -> None:
    response = await client.get("/test/query", params={"limit": 0})
    assert response.status_code == 422
    assert response.json()["error"]["fields"] == {"limit": ["TOO_SMALL"]}


async def test_camel_case_input_and_output(client: AsyncClient) -> None:
    response = await client.post("/test/items", json={"title": "Thesis", "pageCount": 10})
    assert response.status_code == 200
    assert response.json() == {"title": "Thesis", "pageCount": 10}


async def test_unhandled_error_hides_details(client: AsyncClient) -> None:
    response = await client.get("/test/crash")
    assert response.status_code == 500
    body = response.json()
    assert body == {"error": {"code": "INTERNAL_ERROR", "message": "Internal server error"}}
    assert "secret" not in response.text



async def test_unknown_field_is_rejected(client: AsyncClient) -> None:
    response = await client.post("/test/items", json={"title": "Thesis", "pageCount": 1, "fullname": "x"})
    assert response.status_code == 422
    assert response.json()["error"]["fields"] == {"fullname": ["NOT_ALLOWED"]}
