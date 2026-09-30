"""Tác vụ hằng đêm: payment_reminders (ticket #13)

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mssql import DATETIMEOFFSET, UNIQUEIDENTIFIER

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # UC30 bước 4: lưu trạng thái gửi. Khóa chính (kỳ, mốc nhắc) bảo đảm mỗi mốc chỉ nhắc một lần
    # dù tác vụ chạy lại trong cùng đêm hoặc chạy bù.
    op.create_table(
        "payment_reminders",
        sa.Column(
            "installment_id", UNIQUEIDENTIFIER, sa.ForeignKey("installments.id"),
            primary_key=True,
        ),
        sa.Column("kind", sa.String(12), primary_key=True),
        sa.Column("sent_at", DATETIMEOFFSET, nullable=False),
        sa.CheckConstraint(
            "kind IN ('BEFORE_DUE','DUE','OVERDUE_1','OVERDUE_7','OVERDUE_15','OVERDUE_30')",
            name="ck_payment_reminders_kind",
        ),
    )


def downgrade() -> None:
    op.drop_table("payment_reminders")
