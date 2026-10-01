"""Tất toán: phân bổ phí trả trước hạn (ticket #14)

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-30
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSTRAINT = "ck_payment_allocations_component"


def upgrade() -> None:
    # UC31: phí trả trước hạn (BR10) là một thành phần phân bổ riêng của khoản thanh toán tất toán.
    op.drop_constraint(CONSTRAINT, "payment_allocations", type_="check")
    op.create_check_constraint(
        CONSTRAINT, "payment_allocations", "component IN ('PENALTY','INTEREST','PRINCIPAL','FEE')"
    )


def downgrade() -> None:
    op.drop_constraint(CONSTRAINT, "payment_allocations", type_="check")
    op.create_check_constraint(
        CONSTRAINT, "payment_allocations", "component IN ('PENALTY','INTEREST','PRINCIPAL')"
    )
