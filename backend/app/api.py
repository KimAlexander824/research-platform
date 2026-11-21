"""Подключение роутеров всех модулей.

Каждый новый модуль добавляет сюда свой роутер, например:

    from app.accounts.router import router as accounts_router
    api_router.include_router(accounts_router)
"""

from fastapi import APIRouter

from app.accounts.router import auth_router, me_router
from app.projects.router import invitations_router
from app.projects.router import router as projects_router
from app.stages.router import router as stages_router
from app.works.router import router as works_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth_router)
api_router.include_router(me_router)
api_router.include_router(projects_router)
api_router.include_router(invitations_router)
api_router.include_router(works_router)
api_router.include_router(stages_router)
