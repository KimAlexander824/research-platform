"""Данные текущего HTTP-запроса, доступные в любом месте кода (например, IP для журнала действий).

Middleware записывает их в начале запроса. Вне HTTP-запроса (консольные команды, фоновые задачи)
значения пустые.
"""

from collections.abc import Awaitable, Callable
from contextvars import ContextVar

from fastapi import Request, Response

client_ip_var: ContextVar[str | None] = ContextVar("client_ip", default=None)


def current_client_ip() -> str | None:
    return client_ip_var.get()


async def request_context_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    token = client_ip_var.set(request.client.host if request.client else None)
    try:
        return await call_next(request)
    finally:
        client_ip_var.reset(token)
