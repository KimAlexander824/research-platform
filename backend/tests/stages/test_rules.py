"""Правила переходов статусов — без БД (B5 + решения заказчика)."""

import pytest

from app.stages.models import StageStatus as S
from app.stages.rules import Actor, Context, Denied, StageState, available, blocking_index, check

R = {Actor.RESEARCHER}
SUP = {Actor.SUPERVISOR}


def ctx(required: bool = True, supervisor: bool = True, blocked: bool = False) -> Context:
    return Context(is_required=required, work_has_supervisor=supervisor, blocked=blocked)


# --- Исследователь ---


def test_start_stage() -> None:
    assert check(R, S.NOT_STARTED, S.IN_PROGRESS, ctx()) is None


def test_blocked_stage_cannot_start() -> None:
    assert check(R, S.NOT_STARTED, S.IN_PROGRESS, ctx(blocked=True)) == Denied.BLOCKED


def test_required_stage_goes_to_review_when_supervisor_exists() -> None:
    assert check(R, S.IN_PROGRESS, S.PENDING_REVIEW, ctx()) is None
    assert check(R, S.IN_PROGRESS, S.COMPLETED, ctx()) == Denied.REVIEW_REQUIRED


def test_optional_stage_completed_by_researcher() -> None:
    assert check(R, S.IN_PROGRESS, S.COMPLETED, ctx(required=False)) is None


def test_required_stage_completed_by_researcher_without_supervisor() -> None:
    assert check(R, S.IN_PROGRESS, S.COMPLETED, ctx(supervisor=False)) is None
    assert check(R, S.IN_PROGRESS, S.PENDING_REVIEW, ctx(supervisor=False)) == Denied.NO_SUPERVISOR


def test_resubmit_after_revision() -> None:
    assert check(R, S.NEEDS_REVISION, S.PENDING_REVIEW, ctx()) is None
    assert check(R, S.NEEDS_REVISION, S.IN_PROGRESS, ctx()) is None


@pytest.mark.parametrize("target", [S.COMPLETED, S.NEEDS_REVISION, S.REJECTED])
def test_researcher_cannot_review(target: S) -> None:
    assert check(R, S.PENDING_REVIEW, target, ctx()) == Denied.NOT_ALLOWED


@pytest.mark.parametrize("target", list(S))
def test_completed_is_final(target: S) -> None:
    assert check(R | SUP, S.COMPLETED, target, ctx()) == Denied.NOT_ALLOWED


def test_supervisor_can_reconsider_rejection() -> None:
    assert check(SUP, S.REJECTED, S.NEEDS_REVISION, ctx()) is None
    assert available(SUP, S.REJECTED, ctx()) == [S.NEEDS_REVISION]


@pytest.mark.parametrize("target", list(S))
def test_researcher_cannot_change_rejected(target: S) -> None:
    assert check(R, S.REJECTED, target, ctx()) == Denied.NOT_ALLOWED


# --- Руководитель ---


@pytest.mark.parametrize("target", [S.COMPLETED, S.NEEDS_REVISION, S.REJECTED])
def test_supervisor_reviews(target: S) -> None:
    assert check(SUP, S.PENDING_REVIEW, target, ctx()) is None


@pytest.mark.parametrize(
    ("current", "target"),
    [(S.NOT_STARTED, S.IN_PROGRESS), (S.IN_PROGRESS, S.COMPLETED), (S.IN_PROGRESS, S.PENDING_REVIEW)],
)
def test_supervisor_does_not_do_researcher_work(current: S, target: S) -> None:
    assert check(SUP, current, target, ctx()) == Denied.NOT_ALLOWED


def test_no_role_no_transitions() -> None:
    for current in S:
        assert available(set(), current, ctx()) == []


# --- Доступные переходы для кнопок ---


def test_available_transitions() -> None:
    assert available(R, S.IN_PROGRESS, ctx()) == [S.PENDING_REVIEW]
    assert available(R, S.IN_PROGRESS, ctx(required=False)) == [S.PENDING_REVIEW, S.COMPLETED]
    assert available(R, S.IN_PROGRESS, ctx(supervisor=False)) == [S.COMPLETED]
    assert available(R, S.NOT_STARTED, ctx(blocked=True)) == []
    assert available(SUP, S.PENDING_REVIEW, ctx()) == [S.NEEDS_REVISION, S.COMPLETED, S.REJECTED]


# --- Блокировки ---


def test_blocking_index() -> None:
    stages = [
        StageState(S.COMPLETED, True),  # 0 — завершён, никого не блокирует
        StageState(S.IN_PROGRESS, False),  # 1 — необязательный, не блокирует
        StageState(S.NEEDS_REVISION, True),  # 2 — обязательный незавершённый: блокирует всё дальше
        StageState(S.NOT_STARTED, True),  # 3
        StageState(S.NOT_STARTED, False),  # 4
    ]
    assert blocking_index(stages) == [None, None, None, 2, 2]


def test_rejected_required_stage_keeps_blocking() -> None:
    assert blocking_index([StageState(S.REJECTED, True), StageState(S.NOT_STARTED, True)]) == [None, 0]
