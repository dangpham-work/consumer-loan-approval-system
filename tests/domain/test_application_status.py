"""Seam 2: bảng chuyển trạng thái của Hồ sơ vay (biểu đồ 3.4a, UT06)."""

import pytest

from loan_system.domain.applications import (
    ApplicationStatus as S,
)
from loan_system.domain.applications import (
    InvalidTransition,
    ensure_transition,
)


def test_ut06_pending_approval_cannot_jump_to_disbursed() -> None:
    with pytest.raises(InvalidTransition):
        ensure_transition(S.PENDING_APPROVAL, S.DISBURSED)


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (S.DRAFT, S.SUBMITTED),
        (S.SUBMITTED, S.VERIFIED),
        (S.SUBMITTED, S.NEED_INFO),
        (S.NEED_INFO, S.SUBMITTED),
        (S.NEED_INFO, S.CANCELLED),
        (S.VERIFIED, S.APPRAISING),
        (S.VERIFIED, S.REJECTED),
        (S.APPRAISING, S.PENDING_APPROVAL),
        (S.APPRAISING, S.NEED_INFO),
        (S.PENDING_APPROVAL, S.APPROVED),
        (S.PENDING_APPROVAL, S.REJECTED),
        (S.PENDING_APPROVAL, S.APPRAISING),
        (S.APPROVED, S.DISBURSED),
        (S.APPROVED, S.LOCKED),
        (S.APPROVED, S.CANCELLED),
        (S.LOCKED, S.CANCELLED),
    ],
)
def test_transitions_of_the_state_diagram_are_allowed(source: S, target: S) -> None:
    ensure_transition(source, target)


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (S.REJECTED, S.SUBMITTED),
        (S.CANCELLED, S.DRAFT),
        (S.DISBURSED, S.APPROVED),
        (S.LOCKED, S.DISBURSED),
        (S.DRAFT, S.APPROVED),
        (S.VERIFIED, S.CANCELLED),
    ],
)
def test_anything_else_is_rejected(source: S, target: S) -> None:
    with pytest.raises(InvalidTransition):
        ensure_transition(source, target)
