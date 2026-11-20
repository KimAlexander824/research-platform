"""Точка входа приложения."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.admin import setup_admin
from app.api import api_router
from app.core.config import settings
from app.core.errors import register_error_handlers
from app.core.log import log_requests, setup_logging
from app.core.redis import close_redis
from app.core.request_context import request_context_middleware
from app.core.storage import get_storage

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    if settings.S3_AUTO_CREATE_BUCKET:
        try:
            await get_storage().ensure_bucket()
        except Exception:
            logger.exception("Storage is not available: bucket %s was not checked", settings.S3_BUCKET)
    yield
    await close_redis()


def create_app() -> FastAPI:
    setup_logging()

    app = FastAPI(
        title=settings.APP_NAME,
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.middleware("http")(log_requests)
    app.middleware("http")(request_context_middleware)

    register_error_handlers(app)
    app.include_router(api_router)
    setup_admin(app)

    return app


app = create_app()
