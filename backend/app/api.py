"""Подключение роутеров всех модулей.

Каждый новый модуль добавляет сюда свой роутер, например:

    from app.accounts.router import router as accounts_router
    api_router.include_router(accounts_router)
"""

from fastapi import APIRouter

api_router = APIRouter(prefix="/api/v1")
