from app.core.errors import AppError, ErrorCode, NotFoundError


class WorkNotFoundError(NotFoundError):
    code = "WORK_NOT_FOUND"
    message = "Research work not found"


class WorkValidationError(AppError):
    """Ошибки, которые зависят от данных проекта (участники, роли) — в том же формате, что и валидация."""

    status_code = 422
    code = ErrorCode.VALIDATION_ERROR
    message = "Request validation failed"

    def __init__(self, fields: dict[str, list[str]]) -> None:
        super().__init__(fields=fields)
