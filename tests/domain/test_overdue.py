"""Seam 2: nhóm nợ theo BR09 và phí phạt tính lại mỗi đêm (UC29, mục 1.2.8c)."""

from decimal import Decimal

import pytest

from loan_system.domain.overdue import (
    ReminderKind,
    debt_group,
    is_bad_debt,
    overdue_reminder,
    recalculated_penalty,
)

RATE = Decimal("0.24")


@pytest.mark.parametrize(
    ("days", "group"),
    [(0, 1), (1, 1), (9, 1), (10, 2), (90, 2), (91, 3), (180, 3), (181, 4), (360, 4), (361, 5)],
)
def test_debt_group_follows_br09_bands(days: int, group: int) -> None:
    assert debt_group(days) == group


def test_a_loan_becomes_bad_debt_only_after_more_than_90_days() -> None:
    assert not is_bad_debt(90)
    assert is_bad_debt(91)


@pytest.mark.parametrize(
    ("days", "kind"),
    [
        (1, ReminderKind.OVERDUE_1), (6, ReminderKind.OVERDUE_1), (7, ReminderKind.OVERDUE_7),
        (15, ReminderKind.OVERDUE_15), (29, ReminderKind.OVERDUE_15), (30, ReminderKind.OVERDUE_30),
        (200, ReminderKind.OVERDUE_30),
    ],
)
def test_overdue_reminder_is_the_latest_milestone_reached(days: int, kind: ReminderKind) -> None:
    # UC30: nhắc khi quá hạn 1/7/15/30 ngày; đêm bị lỡ thì lần sau vẫn gửi mốc vừa qua.
    assert overdue_reminder(days) == kind


def test_penalty_matches_the_worked_example_of_section_1_2_8c() -> None:
    # 2.836.788 × 36% / 365 × 15 ≈ 41.969 đồng.
    penalty = recalculated_penalty(
        interest_due=Decimal(600_000), principal_due=Decimal(2_236_788), penalty_paid=Decimal(0),
        paid_amount=Decimal(0), annual_rate=RATE, days_overdue=15,
    )

    assert penalty == Decimal(41_969)


def test_recalculating_on_the_same_day_gives_the_same_penalty_not_a_cumulative_one() -> None:
    first = recalculated_penalty(
        interest_due=Decimal(600_000), principal_due=Decimal(2_236_788), penalty_paid=Decimal(0),
        paid_amount=Decimal(0), annual_rate=RATE, days_overdue=15,
    )
    second = recalculated_penalty(
        interest_due=Decimal(600_000), principal_due=Decimal(2_236_788), penalty_paid=Decimal(0),
        paid_amount=Decimal(0), annual_rate=RATE, days_overdue=15,
    )

    assert second == first


def test_penalty_is_charged_only_on_the_principal_and_interest_still_owed() -> None:
    # Đã trả 20.000 phí phạt cũ và 1.836.788 lãi + gốc: còn nợ đúng 1.000.000.
    # 1.000.000 × 36% / 365 × 30 = 29.589,04 → 29.589.
    penalty = recalculated_penalty(
        interest_due=Decimal(600_000), principal_due=Decimal(2_236_788),
        penalty_paid=Decimal(20_000), paid_amount=Decimal(1_856_788), annual_rate=RATE,
        days_overdue=30,
    )

    assert penalty == Decimal(29_589)


def test_penalty_already_paid_is_never_taken_back() -> None:
    # Còn nợ 1.000.000 quá hạn 10 ngày: 9.863 đồng, thấp hơn 20.000 phí phạt đã trả.
    penalty = recalculated_penalty(
        interest_due=Decimal(600_000), principal_due=Decimal(2_236_788),
        penalty_paid=Decimal(20_000), paid_amount=Decimal(1_856_788), annual_rate=RATE,
        days_overdue=10,
    )

    assert penalty == Decimal(20_000)
