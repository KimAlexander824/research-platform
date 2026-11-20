"""Логирование.

В development — читаемый текст, в production — JSON (удобно собирать в системы логов).
Каждый запрос логируется: метод, путь, статус, длительность.
"""

import json
import logging
import sys
import time
from collections.abc import Awaitable, Callable

from fastapi import Request, Response

from app.core.config import settings


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    if settings.is_production:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s"))

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.LOG_LEVEL.upper())

    # uvicorn пишет свои access-логи — отключаем, у нас свой middleware
    logging.getLogger("uvicorn.access").handlers = []
    logging.getLogger("uvicorn.access").propagate = False


request_logger = logging.getLogger("app.request")


async def log_requests(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    started = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - started) * 1000
    request_logger.info(
        "%s %s -> %s (%.1f ms)", request.method, request.url.path, response.status_code, duration_ms
    )
    return response
