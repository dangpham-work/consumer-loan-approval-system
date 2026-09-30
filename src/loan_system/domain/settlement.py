"""UC31 Tất toán khoản vay: báo giá số tiền tất toán và phân bổ vào các kỳ (BR10, mục 1.2.8d).

Chỉ tính toán thuần; đọc/ghi CSDL nằm ở `services/payment_service.py`.

Số tiền tất toán = dư nợ gốc + lãi phát sinh + phí phạt chưa trả + phí trả trước hạn. Kỳ đã đến
hạn mà chưa trả đủ (kể cả quá hạn) phải trả đủ lãi theo lịch cùng phí phạt; lãi phát sinh chỉ tính
trên gốc của các kỳ chưa đến hạn, từ ngày đến hạn gần nhất đến hôm nay, vì phần gốc quá hạn đã chịu
phí phạt. Lãi đã trả trước cho các kỳ chưa đến hạn (UC28 4a) được trừ vào lãi phát sinh; phần trả
trước vượt quá lãi phát sinh không được hoàn. Các kỳ chưa đến hạn bị hủy sau khi tất toán.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from loan_system.domain.calculations import accrued_interest, round_vnd
from loan_system.domain.payments import Allocation, InstallmentBalance, allocate_payment


@dataclass(frozen=True)
class OpenInstallment:
    """Một kỳ còn phải trả: phần còn thiếu, ngày đến hạn và phần lãi đã trả trước."""

    balance: InstallmentBalance
    due_date: date
    interest_paid: Decimal


@dataclass(frozen=True)
class PayoffQuote:
    principal: Decimal
    due_interest: Decimal  # lãi còn nợ của các kỳ đã đến hạn
    accrued_interest: Decimal
    penalty: Decimal
    prepayment_fee: Decimal
    allocations: tuple[Allocation, ...]
    cancelled: tuple[uuid.UUID, ...]  # các kỳ chưa đến hạn, hủy khi tất toán

    @property
    def total(self) -> Decimal:
        return (
            self.principal + self.due_interest + self.accrued_interest + self.penalty
            + self.prepayment_fee
        )


def quote_payoff(
    open_installments: Sequence[OpenInstallment],
    *,
    today: date,
    period_start: date,
    annual_rate: Decimal,
    prepayment_fee_rate: Decimal,
    in_final_installment: bool,
) -> PayoffQuote:
    """`open_installments` theo thứ tự kỳ tăng dần; `period_start` là ngày đến hạn gần nhất không
    sau hôm nay (hoặc ngày giải ngân). Tất toán trong kỳ cuối được miễn phí trả trước hạn (BR10)."""
    due = [i.balance for i in open_installments if i.due_date <= today]
    future = [i for i in open_installments if i.due_date > today]

    due_total = sum((b.total_due for b in due), Decimal(0))
    allocations = allocate_payment(due, due_total)

    future_principal = sum((i.balance.principal_due for i in future), Decimal(0))
    prepaid_interest = sum((i.interest_paid for i in future), Decimal(0))
    accrued = max(
        accrued_interest(future_principal, annual_rate, (today - period_start).days)
        - prepaid_interest,
        Decimal(0),
    )
    principal = sum((b.principal_due for b in due), Decimal(0)) + future_principal
    # Không còn kỳ nào chưa đến hạn thì cũng không còn là trả trước hạn.
    prepaying = future and not in_final_installment
    fee = round_vnd(principal * prepayment_fee_rate) if prepaying else Decimal(0)

    if future:
        first = future[0].balance.installment_id
        if accrued > 0:
            allocations.append(Allocation(first, "INTEREST", accrued))
        allocations.extend(
            Allocation(i.balance.installment_id, "PRINCIPAL", i.balance.principal_due)
            for i in future
            if i.balance.principal_due > 0
        )
        if fee > 0:
            allocations.append(Allocation(first, "FEE", fee))

    return PayoffQuote(
        principal=principal,
        due_interest=sum((b.interest_due for b in due), Decimal(0)),
        accrued_interest=accrued,
        penalty=sum((b.penalty_due for b in due), Decimal(0)),
        prepayment_fee=fee,
        allocations=tuple(allocations),
        cancelled=tuple(i.balance.installment_id for i in future),
    )
