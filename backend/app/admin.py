"""Подключение админ-панели (/admin).

Каждый модуль описывает свои разделы в своём admin.py; здесь они собираются вместе.
"""

from fastapi import FastAPI
from sqladmin import Admin

from app.accounts.admin import AdminAuth, UserAdmin
from app.audit.admin import AuditLogAdmin
from app.core.config import settings
from app.core.database import engine


def setup_admin(app: FastAPI) -> Admin:
    auth = AdminAuth(
        secret_key=settings.JWT_SECRET,
        session_cookie="admin_session",
        max_age=8 * 60 * 60,
        same_site="strict",
        https_only=settings.is_production,
    )
    admin = Admin(
        app,
        engine=engine,
        base_url="/admin",
        title="Research Platform",
        authentication_backend=auth,
    )
    admin.add_view(UserAdmin)
    admin.add_view(AuditLogAdmin)
    return admin
