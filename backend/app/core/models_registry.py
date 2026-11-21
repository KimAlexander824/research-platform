"""Регистрация всех моделей в одном месте.

Alembic видит только те модели, которые импортированы здесь.
Каждый новый модуль добавляет сюда импорт своих моделей, например:

    from app.accounts import models as accounts_models  # noqa: F401
from app.audit import models as audit_models  # noqa: F401
from app.projects import models as projects_models  # noqa: F401
"""

from app.accounts import models as accounts_models  # noqa: F401
from app.audit import models as audit_models  # noqa: F401
from app.projects import models as projects_models  # noqa: F401
from app.core.database import Base

__all__ = ["Base"]
