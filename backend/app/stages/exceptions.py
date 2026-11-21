from app.core.errors import AppError, ConflictError, NotFoundError
from app.stages.rules import Denied


class StageNotFoundError(NotFoundError):
    code = "STAGE_NOT_FOUND"
    message = "Stage not found"


class TransitionDeniedError(ConflictError):
    """Переход статуса запрещён правилами. code объясняет причину (см. rules.Denied)."""

    _MESSAGES = {
        Denied.NOT_ALLOWED: "This status change is not allowed for you",
        Denied.BLOCKED: "Previous required stage is not completed",
        Denied.NO_SUPERVISOR: "Work has no supervisor on the platform to review the stage",
        Denied.REVIEW_REQUIRED: "Required stage must be confirmed by the work supervisor",
    }

    def __init__(self, reason: Denied) -> None:
        super().__init__(self._MESSAGES[reason], code=reason.value)


class StageLockedFieldError(ConflictError):
    code = "STAGE_REQUIRED_LOCKED"
    message = "Required flag can be changed and a required stage deleted only before it is started"


class InvalidStageOrderError(AppError):
    status_code = 422
    code = "VALIDATION_ERROR"
    message = "stageIds must contain every stage of the work exactly once"

    def __init__(self) -> None:
        super().__init__(fields={"stageIds": ["INVALID"]})


class ResponsibleNotMemberError(AppError):
    status_code = 422
    code = "VALIDATION_ERROR"
    message = "Responsible must be a project member"

    def __init__(self) -> None:
        super().__init__(fields={"responsibleId": ["NOT_PROJECT_MEMBER"]})
