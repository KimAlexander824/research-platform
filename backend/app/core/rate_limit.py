"""Ограничение частоты запросов (B2, B12).

Счётчик в Redis на фиксированное окно: не больше `limit` запросов за `window_seconds`
с одного IP-адреса для заданной группы эндпоинтов.
"""

from collections.abc import Awaitable, Callable

from fastapi import Request

from app.core.errors import TooManyRequestsError
from app.core.redis import get_redis


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


async def hit(key: str, limit: int, window_seconds: int) -> int | None:
    """Учитывает запрос. Возвращает None, если лимит не превышен, иначе — сколько секунд ждать."""
    redis = get_redis()
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, window_seconds)
    if count > limit:
        ttl = await redis.ttl(key)
        return max(ttl, 1)
    return None


def rate_limit(scope: str, limit: int, window_seconds: int = 60) -> Callable[[Request], Awaitable[None]]:
    """Зависимость FastAPI: `dependencies=[Depends(rate_limit("auth", 20))]`."""

    async def dependency(request: Request) -> None:
        retry_after = await hit(f"rate:{scope}:{client_ip(request)}", limit, window_seconds)
        if retry_after is not None:
            raise TooManyRequestsError(headers={"Retry-After": str(retry_after)})

    return dependency
