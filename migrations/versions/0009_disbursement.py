"""Giải ngân: khoản vay, lịch trả nợ, hợp đồng, lệnh giải ngân; trigger chặn sửa hồ sơ vay đã duyệt (ticket #10)

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mssql import DATETIMEOFFSET, UNIQUEIDENTIFIER

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MONEY = sa.DECIMAL(15, 0)
HASH = sa.CHAR(64, collation="Latin1_General_BIN2")
TRIGGER = "trg_loan_applications_approved_immutable"


def upgrade() -> None:
    op.create_table(
        "loans",
        sa.Column("id", UNIQUEIDENTIFIER, primary_key=True),
        sa.Column(
            "application_id", UNIQUEIDENTIFIER, sa.ForeignKey("loan_applications.id"),
            nullable=False, unique=True,
        ),
        sa.Column("customer_id", UNIQUEIDENTIFIER, sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("principal", MONEY, nullable=False),
        sa.Column("annual_rate", sa.DECIMAL(5, 4), nullable=False),
        sa.Column("term_months", sa.SmallInteger, nullable=False),
        sa.Column("monthly_payment", MONEY, nullable=False),
        sa.Column("outstanding_principal", MONEY, nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("debt_group", sa.SmallInteger, nullable=False),
        sa.Column("disbursed_at", DATETIMEOFFSET, nullable=False),
        sa.Column("settled_at", DATETIMEOFFSET),
        sa.CheckConstraint("principal > 0", name="ck_loans_principal"),
        sa.CheckConstraint("outstanding_principal >= 0", name="ck_loans_outstanding"),
        sa.CheckConstraint(
            "status IN ('ACTIVE','OVERDUE','BAD_DEBT','SETTLED')", name="ck_loans_status"
        ),
        sa.CheckConstraint("debt_group BETWEEN 1 AND 5", name="ck_loans_debt_group"),
    )
    op.create_index("ix_loans_customer", "loans", ["customer_id"])

    op.create_table(
        "installments",
        sa.Column("id", UNIQUEIDENTIFIER, primary_key=True),
        sa.Column("loan_id", UNIQUEIDENTIFIER, sa.ForeignKey("loans.id"), nullable=False),
        sa.Column("number", sa.SmallInteger, nullable=False),
        sa.Column("due_date", sa.Date, nullable=False),
        sa.Column("principal_due", MONEY, nullable=False),
        sa.Column("interest_due", MONEY, nullable=False),
        sa.Column("penalty", MONEY, nullable=False, server_default=sa.text("0")),
        sa.Column("paid_amount", MONEY, nullable=False, server_default=sa.text("0")),
        sa.Column("status", sa.String(10), nullable=False),
        sa.CheckConstraint(
            "status IN ('UPCOMING','DUE','PARTIAL','PAID','OVERDUE','CANCELLED')",
            name="ck_installments_status",
        ),
        sa.UniqueConstraint("loan_id", "number", name="uq_installments_loan_number"),
    )
    op.create_index("ix_installments_due_date", "installments", ["due_date"])

    # Hợp đồng lưu trong CSDL cùng giao dịch tạo khoản vay (UC26: lỗi giữa chừng thì hoàn tác hết).
    op.create_table(
        "loan_contracts",
        sa.Column(
            "loan_id", UNIQUEIDENTIFIER, sa.ForeignKey("loans.id"), primary_key=True
        ),
        sa.Column("content", sa.LargeBinary, nullable=False),
        sa.Column("sha256", HASH, nullable=False),
        sa.Column("created_at", DATETIMEOFFSET, nullable=False),
    )

    op.create_table(
        "disbursements",
        sa.Column("id", UNIQUEIDENTIFIER, primary_key=True),
        sa.Column(
            "application_id", UNIQUEIDENTIFIER, sa.ForeignKey("loan_applications.id"),
            nullable=False,
        ),
        sa.Column("loan_id", UNIQUEIDENTIFIER, sa.ForeignKey("loans.id")),
        sa.Column("amount", MONEY, nullable=False),
        sa.Column("receiving_account_enc", sa.LargeBinary(500), nullable=False),
        sa.Column("transaction_ref", sa.String(50)),
        sa.Column("idempotency_key", sa.String(64), nullable=False, unique=True),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("failure_reason", sa.NVARCHAR(200)),
        sa.Column("performed_by", UNIQUEIDENTIFIER, sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("created_at", DATETIMEOFFSET, nullable=False),
        sa.Column("completed_at", DATETIMEOFFSET),
        sa.CheckConstraint(
            "status IN ('PENDING','SUCCESS','FAILED')", name="ck_disbursements_status"
        ),
    )
    # Mỗi hồ sơ vay có tối đa một lệnh giải ngân đang chờ hoặc thành công: hai NV giải ngân bấm
    # cùng lúc cũng không tạo được hai lệnh chuyển tiền.
    op.create_index(
        "ux_disbursements_open",
        "disbursements",
        ["application_id"],
        unique=True,
        mssql_where=sa.text("status IN ('PENDING','SUCCESS')"),
    )

    # BR07: hồ sơ vay đã duyệt không được đổi các trường quan trọng, kể cả sửa thẳng trong CSDL
    # (4.1.2e). Chỉ trạng thái được đổi tiếp (giải ngân, khóa, hủy).
    op.execute(
        f"""
CREATE TRIGGER {TRIGGER} ON dbo.loan_applications AFTER UPDATE AS
BEGIN
    SET NOCOUNT ON;
    IF EXISTS (
        SELECT 1 FROM inserted i JOIN deleted d ON d.id = i.id
        WHERE d.status IN ('APPROVED', 'DISBURSED', 'LOCKED')
          AND EXISTS (
              SELECT i.code, i.customer_id, i.requested_amount, i.term_months, i.purpose,
                     i.receiving_account_enc, i.annual_rate, i.policy_id, i.approved_amount,
                     i.approved_term
              EXCEPT
              SELECT d.code, d.customer_id, d.requested_amount, d.term_months, d.purpose,
                     d.receiving_account_enc, d.annual_rate, d.policy_id, d.approved_amount,
                     d.approved_term
          )
    )
        THROW 51007, 'BR07: approved loan application is immutable', 1;
END
"""
    )


def downgrade() -> None:
    op.execute(f"DROP TRIGGER {TRIGGER}")
    op.drop_index("ux_disbursements_open", "disbursements")
    op.drop_table("disbursements")
    op.drop_table("loan_contracts")
    op.drop_index("ix_installments_due_date", "installments")
    op.drop_table("installments")
    op.drop_index("ix_loans_customer", "loans")
    op.drop_table("loans")
