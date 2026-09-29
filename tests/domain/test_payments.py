"""Seam 2: phân bổ khoản thanh toán vào các kỳ trả nợ (UC28 bước 4, SD07)."""

import uuid
from decimal import Decimal

from loan_system.domain.payments import Allocation, allocate_payment, remaining_balance

KY1 = uuid.uuid4()
KY2 = uuid.uuid4()
KY3 = uuid.uuid4()


def test_remaining_balance_is_the_full_installment_when_nothing_paid() -> None:
    balance = remaining_balance(
        KY1, penalty=Decimal(50_000), interest_due=Decimal(600_000),
        principal_due=Decimal(2_200_000), penalty_paid=Decimal(0), paid_amount=Decimal(0),
    )

    assert (balance.penalty_due, balance.interest_due, balance.principal_due) == (
        Decimal(50_000), Decimal(600_000), Decimal(2_200_000),
    )


def test_remaining_balance_consumes_penalty_then_interest_then_principal() -> None:
    # Đã trả 620.000: hết 50.000 phí phạt, hết 570.000 lãi, còn thiếu 30.000 lãi.
    balance = remaining_balance(
        KY1, penalty=Decimal(50_000), interest_due=Decimal(600_000),
        principal_due=Decimal(2_200_000), penalty_paid=Decimal(50_000),
        paid_amount=Decimal(620_000),
    )

    assert (balance.penalty_due, balance.interest_due, balance.principal_due) == (
        Decimal(0), Decimal(30_000), Decimal(2_200_000),
    )


def test_penalty_added_after_an_earlier_payment_does_not_count_as_already_paid() -> None:
    # Trả trước 1.000.000 khi kỳ chưa có phí phạt (hết lãi, 400.000 gốc); sau đó kỳ quá hạn và
    # tác vụ hằng đêm tính phí phạt 30.000: phí phạt này vẫn còn nợ nguyên vẹn (mục 1.2.8c).
    balance = remaining_balance(
        KY1, penalty=Decimal(30_000), interest_due=Decimal(600_000),
        principal_due=Decimal(2_200_000), penalty_paid=Decimal(0), paid_amount=Decimal(1_000_000),
    )

    assert (balance.penalty_due, balance.interest_due, balance.principal_due) == (
        Decimal(30_000), Decimal(0), Decimal(1_800_000),
    )


def test_fully_paid_installment_has_zero_remaining_balance() -> None:
    balance = remaining_balance(
        KY1, penalty=Decimal(0), interest_due=Decimal(600_000), principal_due=Decimal(2_200_000),
        penalty_paid=Decimal(0), paid_amount=Decimal(2_800_000),
    )

    assert (balance.penalty_due, balance.interest_due, balance.principal_due) == (
        Decimal(0), Decimal(0), Decimal(0),
    )


def test_allocation_order_is_penalty_then_interest_then_principal_within_one_installment() -> None:
    balance = remaining_balance(
        KY1, penalty=Decimal(50_000), interest_due=Decimal(600_000),
        principal_due=Decimal(2_200_000), penalty_paid=Decimal(0), paid_amount=Decimal(0),
    )

    allocations = allocate_payment([balance], Decimal(100_000))

    assert allocations == [
        Allocation(KY1, "PENALTY", Decimal(50_000)),
        Allocation(KY1, "INTEREST", Decimal(50_000)),
    ]


def test_overdue_installment_is_settled_before_the_current_one() -> None:
    # Kỳ 1 quá hạn (còn phí phạt), kỳ 2 là kỳ hiện tại: UC28 bước 4. Đủ trả hết kỳ 1 và lãi kỳ 2,
    # còn thiếu gốc kỳ 2 (dừng lại đúng nơi tiền hết, không phải vì đã đi hết danh sách kỳ).
    overdue = remaining_balance(
        KY1, penalty=Decimal(20_000), interest_due=Decimal(500_000),
        principal_due=Decimal(2_300_000), penalty_paid=Decimal(0), paid_amount=Decimal(0),
    )
    current = remaining_balance(
        KY2, penalty=Decimal(0), interest_due=Decimal(480_000),
        principal_due=Decimal(2_350_000), penalty_paid=Decimal(0), paid_amount=Decimal(0),
    )

    allocations = allocate_payment([overdue, current], Decimal(3_300_000))

    assert allocations == [
        Allocation(KY1, "PENALTY", Decimal(20_000)),
        Allocation(KY1, "INTEREST", Decimal(500_000)),
        Allocation(KY1, "PRINCIPAL", Decimal(2_300_000)),
        Allocation(KY2, "INTEREST", Decimal(480_000)),
    ]


def test_overpayment_is_carried_forward_as_an_advance_on_the_next_installment() -> None:
    # Trả thừa ghi là trả trước cho kỳ sau (CONTEXT.md, RepaymentSchedule).
    ky1 = remaining_balance(
        KY1, penalty=Decimal(0), interest_due=Decimal(500_000), principal_due=Decimal(2_300_000),
        penalty_paid=Decimal(0), paid_amount=Decimal(0),
    )
    ky2 = remaining_balance(
        KY2, penalty=Decimal(0), interest_due=Decimal(480_000), principal_due=Decimal(2_350_000),
        penalty_paid=Decimal(0), paid_amount=Decimal(0),
    )
    ky3 = remaining_balance(
        KY3, penalty=Decimal(0), interest_due=Decimal(460_000), principal_due=Decimal(2_400_000),
        penalty_paid=Decimal(0), paid_amount=Decimal(0),
    )

    # Đủ trả hết kỳ 1 (2.800.000) và kỳ 2 (2.830.000), dư 1.000.000 trả trước cho kỳ 3.
    allocations = allocate_payment([ky1, ky2, ky3], Decimal(2_800_000 + 2_830_000 + 1_000_000))

    ky1_total = sum(a.amount for a in allocations if a.installment_id == KY1)
    ky2_total = sum(a.amount for a in allocations if a.installment_id == KY2)
    ky3_total = sum(a.amount for a in allocations if a.installment_id == KY3)
    assert ky1_total == Decimal(2_800_000)
    assert ky2_total == Decimal(2_830_000)
    assert ky3_total == Decimal(1_000_000)  # phần dư trả trước cho kỳ 3, chưa hết kỳ 3


def test_payment_that_exactly_covers_every_remaining_installment_leaves_nothing_unallocated() -> None:
    ky1 = remaining_balance(
        KY1, penalty=Decimal(0), interest_due=Decimal(500_000), principal_due=Decimal(2_300_000),
        penalty_paid=Decimal(0), paid_amount=Decimal(0),
    )
    ky2 = remaining_balance(
        KY2, penalty=Decimal(0), interest_due=Decimal(480_000), principal_due=Decimal(2_350_000),
        penalty_paid=Decimal(0), paid_amount=Decimal(0),
    )

    total = ky1.total_due + ky2.total_due
    allocations = allocate_payment([ky1, ky2], total)

    assert sum(a.amount for a in allocations) == total
    assert sum(a.amount for a in allocations if a.installment_id == KY2) == ky2.total_due
