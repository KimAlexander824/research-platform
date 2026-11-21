"""Правила переходов статусов этапа (B5) — чистая логика без БД и HTTP, полностью покрыта тестами.

Кто и что может делать (решения заказчика):
- необязательный этап исследователь завершает сам;
- обязательный — завершает руководитель работы после проверки;
- если у работы нет руководителя на платформе, обязательный этап исследователь тоже завершает сам;
- если обязательный этап не завершён, следующие этапы нельзя начать (они «заблокированы»);
- «требует исправлений» — исследователь исправляет и снова отправляет на проверку;
- «отклонён» — отказ в принятии этапа; руководитель может пересмотреть решение и вернуть этап на доработку.

Переходы:

    Исследователь (владелец/редактор проекта):
        not_started    -> in_progress      начать (если этап не заблокирован)
        in_progress    -> pending_review   отправить на проверку (если у работы есть руководитель)
        in_progress    -> completed        завершить (если этап необязательный или руководителя нет)
        needs_revision -> in_progress      взять в исправление
        needs_revision -> pending_review   отправить на проверку повторно

    Руководитель работы:
        pending_review -> completed        подтвердить
        pending_review -> needs_revision   отправить на доработку
        pending_review -> rejected         отклонить
        rejected       -> needs_revision   пересмотреть отказ (решение команды: иначе работа застревает навсегда)
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from app.stages.models import StageStatus

S = StageStatus


class Actor(StrEnum):
    RESEARCHER = "researcher"  # владелец или редактор проекта
    SUPERVISOR = "supervisor"  # руководитель этой научной работы


@dataclass(frozen=True)
class StageState:
    status: StageStatus
    is_required: bool


@dataclass(frozen=True)
class Context:
    """Всё, что нужно правилам, чтобы решить, разрешён ли переход."""

    is_required: bool
    work_has_supervisor: bool
    blocked: bool  # есть незавершённый обязательный этап раньше этого


_RESEARCHER: dict[StageStatus, set[StageStatus]] = {
    S.NOT_STARTED: {S.IN_PROGRESS},
    S.IN_PROGRESS: {S.PENDING_REVIEW, S.COMPLETED},
    S.NEEDS_REVISION: {S.IN_PROGRESS, S.PENDING_REVIEW},
}

_SUPERVISOR: dict[StageStatus, set[StageStatus]] = {
    S.PENDING_REVIEW: {S.COMPLETED, S.NEEDS_REVISION, S.REJECTED},
    S.REJECTED: {S.NEEDS_REVISION},
}


class Denied(StrEnum):
    """Причина, по которой переход запрещён — уходит фронтенду кодом ошибки."""

    NOT_ALLOWED = "TRANSITION_NOT_ALLOWED"
    BLOCKED = "STAGE_BLOCKED"
    NO_SUPERVISOR = "NO_SUPERVISOR"
    REVIEW_REQUIRED = "SUPERVISOR_REVIEW_REQUIRED"


def check(actors: set[Actor], current: StageStatus, target: StageStatus, ctx: Context) -> Denied | None:
    """None — переход разрешён, иначе причина отказа."""
    allowed_by: set[Actor] = set()
    if Actor.RESEARCHER in actors and target in _RESEARCHER.get(current, set()):
        allowed_by.add(Actor.RESEARCHER)
    if Actor.SUPERVISOR in actors and target in _SUPERVISOR.get(current, set()):
        allowed_by.add(Actor.SUPERVISOR)
    if not allowed_by:
        return Denied.NOT_ALLOWED

    if allowed_by == {Actor.RESEARCHER}:
        if current == S.NOT_STARTED and target == S.IN_PROGRESS and ctx.blocked:
            return Denied.BLOCKED
        if target == S.PENDING_REVIEW and not ctx.work_has_supervisor:
            return Denied.NO_SUPERVISOR
        if target == S.COMPLETED and ctx.is_required and ctx.work_has_supervisor:
            # Обязательный этап при наличии руководителя завершает только он
            return Denied.REVIEW_REQUIRED
    return None


def available(actors: set[Actor], current: StageStatus, ctx: Context) -> list[StageStatus]:
    """Переходы, доступные пользователю прямо сейчас — для кнопок на фронтенде."""
    candidates = _RESEARCHER.get(current, set()) | _SUPERVISOR.get(current, set())
    return sorted((t for t in candidates if check(actors, current, t, ctx) is None), key=list(S).index)


def blocking_index(stages: Sequence[StageState]) -> list[int | None]:
    """Для каждого этапа (в порядке position) — индекс обязательного незавершённого этапа, который его блокирует.

    Блокирует первый незавершённый обязательный этап, стоящий раньше.
    """
    result: list[int | None] = []
    blocker: int | None = None
    for i, stage in enumerate(stages):
        result.append(blocker)
        if blocker is None and stage.is_required and stage.status != S.COMPLETED:
            blocker = i
    return result
