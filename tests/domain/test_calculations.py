"""Seam 2: các hàm tính toán của tầng miền.

Giá trị kỳ vọng lấy từ ví dụ số trong đề cương (mục 1.2.8, bảng 5.3d).
"""

from datetime import date
from decimal import Decimal

import pytest

from loan_system.domain.calculations import (
    accrued_interest,
    annuity_payment,
    calculate_dti,
    calculate_penalty,
    existing_monthly_obligation,
    generate_schedule,
    payoff_amount,
)

P = Decimal(30_000_000)
RATE_24 = Decimal("0.24")


def test_ut01_annuity_payment_matches_worked_example() -> None:
    # 30.000.000đ, 24%/năm, 12 kỳ -> 2.836.788đ
    assert annuity_payment(P, RATE_24, 12) == Decimal(2_836_788)


def test_ut02_schedule_matches_worked_example_and_ends_at_zero() -> None:
    schedule = generate_schedule(P, RATE_24, 12, disbursed_on=date(2026, 1, 15))

    # (kỳ, tiền trả, gốc, lãi, dư nợ cuối kỳ) theo bảng mục 1.2.8a
    expected = {
        1: (2_836_788, 2_236_788, 600_000, 27_763_212),
        2: (2_836_788, 2_281_524, 555_264, 25_481_688),
        3: (2_836_788, 2_327_154, 509_634, 23_154_534),
        6: (2_836_788, 2_469_595, 367_193, 15_890_071),
        12: (2_836_786, 2_781_163, 55_623, 0),
    }
    for number, (payment, principal, interest, balance) in expected.items():
        row = schedule[number - 1]
        assert row.number == number
        assert (row.payment, row.principal, row.interest, row.closing_balance) == (
            Decimal(payment),
            Decimal(principal),
            Decimal(interest),
            Decimal(balance),
        )

    assert len(schedule) == 12
    assert sum(row.principal for row in schedule) == P


def test_due_date_falls_back_to_last_day_of_short_months() -> None:
    schedule = generate_schedule(P, RATE_24, 13, disbursed_on=date(2027, 12, 31))

    assert [row.due_date for row in schedule[:3]] == [
        date(2028, 1, 31),
        date(2028, 2, 29),  # năm nhuận
        date(2028, 3, 31),
    ]
    assert schedule[12].due_date == date(2029, 1, 31)


def test_ut03_dti_matches_worked_example() -> None:
    # Thu nhập 12tr, đang trả 2tr/tháng, khoản vay mới A = 2.836.788 -> DTI ≈ 40,3%
    dti = calculate_dti(
        monthly_income=Decimal(12_000_000),
        existing_obligation=Decimal(2_000_000),
        new_payment=Decimal(2_836_788),
    )
    assert round(dti, 3) == Decimal("0.403")


def test_existing_obligation_takes_the_larger_of_declared_and_cic() -> None:
    # ADR 0002: max(khai báo, CIC); thiếu CIC thì dùng số khai báo
    assert existing_monthly_obligation(Decimal(0), Decimal(5_000_000)) == Decimal(5_000_000)
    assert existing_monthly_obligation(Decimal(3_000_000), Decimal(1_000_000)) == Decimal(3_000_000)
    assert existing_monthly_obligation(Decimal(2_000_000), None) == Decimal(2_000_000)


def test_ut04_penalty_matches_worked_example() -> None:
    # Kỳ 2.836.788đ quá hạn 15 ngày, lãi suất 24% -> 2.836.788 × 36% / 365 × 15 ≈ 41.969đ
    assert calculate_penalty(Decimal(2_836_788), RATE_24, days_overdue=15) == Decimal(41_969)


def test_penalty_is_zero_when_not_overdue() -> None:
    assert calculate_penalty(Decimal(2_836_788), RATE_24, days_overdue=0) == Decimal(0)


def test_accrued_interest_is_daily_actual_365() -> None:
    # 15.890.071 × 24% / 365 × 10 ngày = 104.482,66 -> 104.483
    assert accrued_interest(Decimal(15_890_071), RATE_24, days=10) == Decimal(104_483)
    assert accrued_interest(Decimal(15_890_071), RATE_24, days=0) == Decimal(0)


def test_payoff_right_after_installment_6_matches_worked_example() -> None:
    # 15.890.071 + 3% × 15.890.071 = 16.366.773 (chưa tính lãi phát sinh)
    amount = payoff_amount(
        outstanding_principal=Decimal(15_890_071),
        annual_rate=RATE_24,
        days_since_last_due=0,
        unpaid_penalty=Decimal(0),
        prepayment_fee_rate=Decimal("0.03"),
        in_final_installment=False,
    )
    assert amount == Decimal(16_366_773)


def test_payoff_includes_accrued_interest_and_unpaid_penalty() -> None:
    amount = payoff_amount(
        outstanding_principal=Decimal(15_890_071),
        annual_rate=RATE_24,
        days_since_last_due=10,
        unpaid_penalty=Decimal(41_969),
        prepayment_fee_rate=Decimal("0.03"),
        in_final_installment=False,
    )
    assert amount == Decimal(16_366_773 + 104_483 + 41_969)


def test_payoff_in_final_installment_waives_prepayment_fee() -> None:
    # BR10: tất toán trong kỳ cuối không còn là trả trước hạn
    amount = payoff_amount(
        outstanding_principal=Decimal(2_781_163),
        annual_rate=RATE_24,
        days_since_last_due=0,
        unpaid_penalty=Decimal(0),
        prepayment_fee_rate=Decimal("0.03"),
        in_final_installment=True,
    )
    assert amount == Decimal(2_781_163)


@pytest.mark.parametrize("principal", [5_000_000, 49_999_999, 100_000_000])
@pytest.mark.parametrize("term_months", [6, 9, 18, 36])
@pytest.mark.parametrize("annual_rate", ["0.20", "0.24", "0.28"])
def test_schedule_always_repays_exactly_the_principal(
    principal: int, term_months: int, annual_rate: str
) -> None:
    schedule = generate_schedule(
        Decimal(principal), Decimal(annual_rate), term_months, disbursed_on=date(2026, 1, 15)
    )

    assert len(schedule) == term_months
    assert sum(row.principal for row in schedule) == Decimal(principal)
    assert schedule[-1].closing_balance == Decimal(0)
    assert all(row.principal > 0 and row.interest >= 0 for row in schedule)
    # mọi kỳ trừ kỳ cuối có cùng số tiền trả (niên kim)
    assert len({row.payment for row in schedule[:-1]}) == 1
