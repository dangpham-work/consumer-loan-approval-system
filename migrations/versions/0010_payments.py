"""Thanh toán kỳ: payments, payment_allocations, installments.penalty_paid (ticket #12)

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mssql import DATETIMEOFFSET, UNIQUEIDENTIFIER

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MONEY = sa.DECIMAL(15, 0)


def upgrade() -> None:
    # Phí phạt tính lại mỗi đêm (1.2.8c) có thể phát sinh sau khi kỳ đã được trả một phần, nên phần
    # đã trả phí phạt lưu riêng thay vì suy ra từ paid_amount.
    op.add_column(
        "installments",
        sa.Column("penalty_paid", MONEY, nullable=False, server_default="0"),
    )
    op.create_check_constraint(
        "ck_installments_penalty_paid", "installments", "penalty_paid BETWEEN 0 AND penalty"
    )
    op.create_table(
        "payments",
        sa.Column("id", UNIQUEIDENTIFIER, primary_key=True),
        sa.Column("loan_id", UNIQUEIDENTIFIER, sa.ForeignKey("loans.id"), nullable=False),
        sa.Column("amount", MONEY, nullable=False),
        sa.Column("channel", sa.String(10), nullable=False),
        # Mã giao dịch cổng thanh toán hoặc mã phiếu thu tại quầy; chống ghi nhận trùng (UC28 3b).
        sa.Column("external_ref", sa.String(50), nullable=False, unique=True),
        sa.Column("paid_at", DATETIMEOFFSET, nullable=False),
        sa.Column("recorded_by", UNIQUEIDENTIFIER, sa.ForeignKey("users.id"), nullable=False),
        sa.CheckConstraint("amount > 0", name="ck_payments_amount"),
        sa.CheckConstraint("channel IN ('ONLINE','COUNTER')", name="ck_payments_channel"),
    )
    op.create_index("ix_payments_loan", "payments", ["loan_id"])

    op.create_table(
        "payment_allocations",
        sa.Column(
            "payment_id", UNIQUEIDENTIFIER, sa.ForeignKey("payments.id"), primary_key=True
        ),
        sa.Column(
            "installment_id", UNIQUEIDENTIFIER, sa.ForeignKey("installments.id"),
            primary_key=True,
        ),
        sa.Column("component", sa.String(10), primary_key=True),
        sa.Column("amount", MONEY, nullable=False),
        sa.CheckConstraint(
            "component IN ('PENALTY','INTEREST','PRINCIPAL')",
            name="ck_payment_allocations_component",
        ),
        sa.CheckConstraint("amount > 0", name="ck_payment_allocations_amount"),
    )


def downgrade() -> None:
    op.drop_table("payment_allocations")
    op.drop_index("ix_payments_loan", "payments")
    op.drop_table("payments")
    op.drop_constraint("ck_installments_penalty_paid", "installments")
    op.drop_column("installments", "penalty_paid", mssql_drop_default=True)
