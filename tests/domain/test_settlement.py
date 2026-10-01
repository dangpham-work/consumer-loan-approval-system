"""Seam 2: báo giá và phân bổ Tất toán (UC31, BR10, mục 1.2.8d, TC05)."""

import uuid
from datetime import date, timedelta
from decimal import Decimal

from loan_system.domain.calculations import ScheduledInstallment, generate_schedule
from loan_system.domain.payments import Allocation, InstallmentBalance
from loan_system.domain.settlement import OpenInstallment, quote_payoff

RATE_24 = Decimal("0.24")
FEE_3 = Decimal("0.03")
# Niên kim 30 triệu, 24%/năm, 12 kỳ, giải ngân 28/09/2026 (như TC01, TC05).
SCHEDULE = generate_schedule(Decimal(30_000_000), RATE_24, 12, date(2026, 9, 28))
IDS = [uuid.uuid4() for _ in SCHEDULE]


def unpaid(row: ScheduledInstallment, *, penalty: Decimal = Decimal(0)) -> OpenInstallment:
    return OpenInstallment(
        balance=InstallmentBalance(IDS[row.number - 1], penalty, row.interest, row.principal),
        due_date=row.due_date,
        interest_paid=Decimal(0),
    )


def test_tc05_payoff_ten_days_after_installment_6() -> None:
    ky6 = SCHEDULE[5]
    today = ky6.due_date + timedelta(days=10)

    quote = quote_payoff(
        [unpaid(row) for row in SCHEDULE[6:]], today=today, period_start=ky6.due_date,
        annual_rate=RATE_24, prepayment_fee_rate=FEE_3, in_final_installment=False,
    )

    assert quote.principal == Decimal(15_890_071)
    assert quote.due_interest == Decimal(0)
    assert quote.accrued_interest == Decimal(104_483)  # 15.890.071 × 24% / 365 × 10
    assert quote.penalty == Decimal(0)
    assert quote.prepayment_fee == Decimal(476_702)  # 3% × 15.890.071
    assert quote.total == Decimal(15_890_071 + 104_483 + 476_702)
    assert quote.cancelled == tuple(IDS[6:])
    ky7 = IDS[6]
    assert quote.allocations[:2] == (
        Allocation(ky7, "INTEREST", Decimal(104_483)),
        Allocation(ky7, "PRINCIPAL", SCHEDULE[6].principal),
    )
    assert Allocation(ky7, "FEE", Decimal(476_702)) in quote.allocations
    assert sum((a.amount for a in quote.allocations), Decimal(0)) == quote.total


def test_payoff_in_the_final_installment_waives_the_prepayment_fee() -> None:
    ky11, ky12 = SCHEDULE[10], SCHEDULE[11]

    quote = quote_payoff(
        [unpaid(ky12)], today=ky11.due_date + timedelta(days=5), period_start=ky11.due_date,
        annual_rate=RATE_24, prepayment_fee_rate=FEE_3, in_final_installment=True,
    )

    assert quote.prepayment_fee == Decimal(0)  # BR10
    assert quote.principal == ky12.principal
    assert not any(a.component == "FEE" for a in quote.allocations)


def test_overdue_installment_is_owed_in_full_and_only_future_principal_accrues_interest() -> None:
    ky1 = SCHEDULE[0]
    today = ky1.due_date + timedelta(days=10)

    quote = quote_payoff(
        [unpaid(ky1, penalty=Decimal(20_000))] + [unpaid(row) for row in SCHEDULE[1:]],
        today=today, period_start=ky1.due_date, annual_rate=RATE_24, prepayment_fee_rate=FEE_3,
        in_final_installment=False,
    )

    future_principal = Decimal(30_000_000) - ky1.principal
    assert quote.principal == Decimal(30_000_000)
    assert quote.due_interest == ky1.interest
    # 27.763.212 × 24% / 365 × 10 = 182.552,63 -> 182.553; kỳ quá hạn đã chịu phí phạt.
    assert quote.accrued_interest == Decimal(182_553)
    assert quote.penalty == Decimal(20_000)
    assert quote.prepayment_fee == Decimal(900_000)  # 3% dư nợ gốc còn lại
    assert quote.cancelled == tuple(IDS[1:])  # kỳ quá hạn được trả đủ, không bị hủy
    assert quote.allocations[:3] == (
        Allocation(IDS[0], "PENALTY", Decimal(20_000)),
        Allocation(IDS[0], "INTEREST", ky1.interest),
        Allocation(IDS[0], "PRINCIPAL", ky1.principal),
    )
    assert future_principal == sum(
        (a.amount for a in quote.allocations if a.component == "PRINCIPAL" and a.installment_id != IDS[0]),
        Decimal(0),
    )


def test_interest_prepaid_on_the_next_installment_is_credited_against_accrued_interest() -> None:
    # Trả thừa trước đó đã trả trước 50.000 lãi của kỳ 7 (UC28 4a).
    ky6, ky7 = SCHEDULE[5], SCHEDULE[6]
    prepaid = OpenInstallment(
        balance=InstallmentBalance(IDS[6], Decimal(0), ky7.interest - 50_000, ky7.principal),
        due_date=ky7.due_date,
        interest_paid=Decimal(50_000),
    )

    quote = quote_payoff(
        [prepaid] + [unpaid(row) for row in SCHEDULE[7:]],
        today=ky6.due_date + timedelta(days=10), period_start=ky6.due_date,
        annual_rate=RATE_24, prepayment_fee_rate=FEE_3, in_final_installment=False,
    )

    assert quote.accrued_interest == Decimal(104_483 - 50_000)


def test_prepaid_interest_beyond_the_accrued_interest_leaves_no_interest_to_pay() -> None:
    ky6, ky7 = SCHEDULE[5], SCHEDULE[6]
    prepaid = OpenInstallment(
        balance=InstallmentBalance(IDS[6], Decimal(0), Decimal(0), ky7.principal),
        due_date=ky7.due_date,
        interest_paid=ky7.interest,
    )

    quote = quote_payoff(
        [prepaid] + [unpaid(row) for row in SCHEDULE[7:]],
        today=ky6.due_date + timedelta(days=1), period_start=ky6.due_date,
        annual_rate=RATE_24, prepayment_fee_rate=FEE_3, in_final_installment=False,
    )

    assert quote.accrued_interest == Decimal(0)
    assert not any(a.component == "INTEREST" for a in quote.allocations)
