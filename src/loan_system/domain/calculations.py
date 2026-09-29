"""Các phép tính nghiệp vụ thuần (mục 1.2.8 đề cương).

Mọi số tiền là Decimal tính bằng đồng, làm tròn đến đồng theo quy tắc nửa lên.
Lãi suất truyền vào là lãi suất năm dạng thập phân (24% -> Decimal("0.24")).
"""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal


@dataclass(frozen=True)
class ScheduledInstallment:
    number: int
    due_date: date
    payment: Decimal
    principal: Decimal
    interest: Decimal
    closing_balance: Decimal


def round_vnd(amount: Decimal) -> Decimal:
    return amount.quantize(Decimal(1), rounding=ROUND_HALF_UP)


def annuity_payment(principal: Decimal, annual_rate: Decimal, term_months: int) -> Decimal:
    """Số tiền trả mỗi kỳ theo niên kim: A = P × r / (1 − (1 + r)^(−n)), r = lãi suất năm / 12."""
    r = annual_rate / 12
    return round_vnd(principal * r / (1 - (1 + r) ** -term_months))


def existing_monthly_obligation(declared: Decimal, from_cic: Decimal | None) -> Decimal:
    """Nghĩa vụ nợ hiện có = max(khai báo, CIC); thiếu Báo cáo CIC thì dùng số khai báo (ADR 0002)."""
    return declared if from_cic is None else max(declared, from_cic)


def calculate_dti(
    monthly_income: Decimal, existing_obligation: Decimal, new_payment: Decimal
) -> Decimal:
    """DTI = (nghĩa vụ nợ hiện có + số tiền trả mỗi kỳ của khoản vay mới) / thu nhập hằng tháng."""
    return (existing_obligation + new_payment) / monthly_income


PENALTY_RATE_MULTIPLIER = Decimal("1.5")
DAYS_IN_YEAR = 365


def calculate_penalty(outstanding: Decimal, annual_rate: Decimal, days_overdue: int) -> Decimal:
    """Phí phạt chậm trả trên phần gốc và lãi còn nợ của kỳ, lãi suất 150%, actual/365 (1.2.8c)."""
    return round_vnd(
        outstanding * PENALTY_RATE_MULTIPLIER * annual_rate / DAYS_IN_YEAR * days_overdue
    )


def accrued_interest(outstanding_principal: Decimal, annual_rate: Decimal, days: int) -> Decimal:
    """Lãi phát sinh theo ngày trên dư nợ gốc còn lại, actual/365 (1.2.8d)."""
    return round_vnd(outstanding_principal * annual_rate / DAYS_IN_YEAR * days)


def payoff_amount(
    *,
    outstanding_principal: Decimal,
    annual_rate: Decimal,
    days_since_last_due: int,
    unpaid_penalty: Decimal,
    prepayment_fee_rate: Decimal,
    in_final_installment: bool,
) -> Decimal:
    """Số tiền tất toán = dư nợ gốc + lãi phát sinh + phí phạt chưa trả + phí trả trước hạn.

    Phí trả trước hạn được miễn khi tất toán trong kỳ cuối (BR10).
    """
    fee = Decimal(0) if in_final_installment else round_vnd(outstanding_principal * prepayment_fee_rate)
    return (
        outstanding_principal
        + accrued_interest(outstanding_principal, annual_rate, days_since_last_due)
        + unpaid_penalty
        + fee
    )


def add_months(start: date, months: int) -> date:
    """Cộng tháng; ngày không tồn tại trong tháng đích thì lấy ngày cuối tháng (UC26 2a)."""
    month_index = start.month - 1 + months
    year, month = start.year + month_index // 12, month_index % 12 + 1
    next_month_first = date(year + month // 12, month % 12 + 1, 1)
    last_day = (next_month_first - date.resolution).day
    return date(year, month, min(start.day, last_day))


def generate_schedule(
    principal: Decimal, annual_rate: Decimal, term_months: int, disbursed_on: date
) -> list[ScheduledInstallment]:
    """Lịch trả nợ niên kim trên dư nợ giảm dần (BR08); kỳ cuối điều chỉnh để dư nợ về 0."""
    r = annual_rate / 12
    payment = annuity_payment(principal, annual_rate, term_months)
    balance = principal
    rows: list[ScheduledInstallment] = []
    for number in range(1, term_months + 1):
        interest = round_vnd(balance * r)
        principal_part = balance if number == term_months else payment - interest
        balance -= principal_part
        rows.append(
            ScheduledInstallment(
                number=number,
                due_date=add_months(disbursed_on, number),
                payment=principal_part + interest,
                principal=principal_part,
                interest=interest,
                closing_balance=balance,
            )
        )
    return rows
