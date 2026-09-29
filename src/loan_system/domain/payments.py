"""UC28 Thanh toán kỳ: phân bổ khoản thanh toán vào các kỳ trả nợ (mục 1.2.8, SD07).

Chỉ tính toán thuần; đọc/ghi CSDL nằm ở `services/payment_service.py`.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

Component = Literal["PENALTY", "INTEREST", "PRINCIPAL"]


@dataclass(frozen=True)
class InstallmentBalance:
    """Phần một kỳ còn thiếu, sau khi trừ đi số đã trả trước đó."""

    installment_id: uuid.UUID
    penalty_due: Decimal
    interest_due: Decimal
    principal_due: Decimal

    @property
    def total_due(self) -> Decimal:
        return self.penalty_due + self.interest_due + self.principal_due


@dataclass(frozen=True)
class Allocation:
    installment_id: uuid.UUID
    component: Component
    amount: Decimal


def remaining_balance(
    installment_id: uuid.UUID,
    *,
    penalty: Decimal,
    interest_due: Decimal,
    principal_due: Decimal,
    penalty_paid: Decimal,
    paid_amount: Decimal,
) -> InstallmentBalance:
    """Phần còn thiếu của từng thành phần, từ tổng đã trả `paid_amount` và phần đã trả phí phạt.

    Phí phạt được tính lại mỗi đêm (mục 1.2.8c) và có thể phát sinh sau khi kỳ đã được trả một
    phần, nên phần đã trả phí phạt được lưu riêng (`penalty_paid`); phần còn lại của `paid_amount`
    luôn trả lãi trước, gốc sau (UC28 bước 4), nên suy ngược được lãi và gốc đã trả.
    """
    interest_paid = min(paid_amount - penalty_paid, interest_due)
    principal_paid = min(paid_amount - penalty_paid - interest_paid, principal_due)
    return InstallmentBalance(
        installment_id=installment_id,
        penalty_due=penalty - penalty_paid,
        interest_due=interest_due - interest_paid,
        principal_due=principal_due - principal_paid,
    )


def allocate_payment(
    balances: Sequence[InstallmentBalance], amount: Decimal
) -> list[Allocation]:
    """UC28 bước 4: phí phạt → lãi quá hạn → gốc quá hạn → lãi kỳ hiện tại → gốc kỳ hiện tại.

    `balances` phải theo thứ tự kỳ tăng dần: kỳ quá hạn luôn có số kỳ nhỏ hơn kỳ hiện tại và các kỳ
    tương lai, nên chỉ cần duyệt tuần tự, mỗi kỳ trả hết phạt rồi lãi rồi gốc trước khi sang kỳ kế
    tiếp. Trả thừa vì vậy tự nhiên chuyển thành trả trước cho kỳ sau (CONTEXT.md, RepaymentSchedule)
    bằng cách tiếp tục phân bổ vào kỳ kế tiếp trong cùng vòng lặp.
    """
    remaining = amount
    allocations: list[Allocation] = []
    for balance in balances:
        if remaining <= 0:
            break
        components: tuple[tuple[Component, Decimal], ...] = (
            ("PENALTY", balance.penalty_due),
            ("INTEREST", balance.interest_due),
            ("PRINCIPAL", balance.principal_due),
        )
        for component, due in components:
            if remaining <= 0:
                break
            take = min(remaining, due)
            if take > 0:
                allocations.append(Allocation(balance.installment_id, component, take))
                remaining -= take
    return allocations
