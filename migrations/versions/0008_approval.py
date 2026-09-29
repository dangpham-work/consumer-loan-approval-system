"""Phê duyệt, từ chối, trả về hồ sơ vay và snapshot HMAC có phiên bản khóa (ticket #8)

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mssql import DATETIMEOFFSET, NVARCHAR, UNIQUEIDENTIFIER

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MONEY = sa.DECIMAL(15, 0)


def upgrade() -> None:
    # Quyết định phê duyệt gắn với tờ trình được quyết định: bị Trả về thì có tờ trình mới, các
    # quyết định cũ tự hết hiệu lực mà không phải sửa bản ghi (bảng chỉ ghi thêm, 4.1.2e).
    op.create_table(
        "approval_decisions",
        sa.Column("id", UNIQUEIDENTIFIER, primary_key=True),
        sa.Column(
            "application_id", UNIQUEIDENTIFIER, sa.ForeignKey("loan_applications.id"),
            nullable=False,
        ),
        sa.Column(
            "appraisal_report_id", UNIQUEIDENTIFIER, sa.ForeignKey("appraisal_reports.id"),
            nullable=False,
        ),
        sa.Column("approver_id", UNIQUEIDENTIFIER, sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("result", sa.String(10), nullable=False),
        sa.Column("reason_group", sa.String(20)),
        sa.Column("comment", NVARCHAR(1000)),
        # HMAC-SHA256 của snapshot (SR08) trên quyết định làm hồ sơ vay được duyệt, kèm phiên bản
        # khóa HMAC_INTEGRITY_KEY đã dùng (4.2.5).
        sa.Column("snapshot_hash", sa.CHAR(64, collation="Latin1_General_BIN2")),
        sa.Column("key_version", sa.SmallInteger),
        sa.Column("decided_at", DATETIMEOFFSET, nullable=False),
        sa.CheckConstraint(
            "result IN ('APPROVE','REJECT','RETURN')", name="ck_approval_decisions_result"
        ),
        sa.CheckConstraint(
            "reason_group IN ('FINANCIAL_CAPACITY','CREDIT_HISTORY','FRAUD_SUSPECTED','OTHER')",
            name="ck_approval_decisions_reason_group",
        ),
        sa.CheckConstraint(
            "result <> 'REJECT' OR reason_group IS NOT NULL",
            name="ck_approval_decisions_reject_reason",
        ),
        sa.CheckConstraint(
            "(snapshot_hash IS NULL AND key_version IS NULL)"
            " OR (snapshot_hash IS NOT NULL AND key_version IS NOT NULL AND result = 'APPROVE')",
            name="ck_approval_decisions_snapshot",
        ),
        # BR05: mỗi Quản lý phê duyệt quyết định một lần trên một tờ trình.
        sa.UniqueConstraint(
            "appraisal_report_id", "approver_id", name="uq_approval_decisions_report_approver"
        ),
    )
    op.create_index(
        "ix_approval_decisions_application", "approval_decisions", ["application_id", "decided_at"]
    )
    op.execute("DENY UPDATE, DELETE ON dbo.approval_decisions TO app_rw")

    # Thứ tự tờ trình của một hồ sơ vay không dựa vào thời điểm (hai tờ trình có thể cùng thời
    # điểm theo đồng hồ); tờ trình có seq lớn nhất là tờ trình có hiệu lực.
    op.add_column(
        "appraisal_reports",
        sa.Column("seq", sa.BigInteger, sa.Identity(start=1, increment=1), nullable=False),
    )

    # Hạn mức, kỳ hạn được duyệt (theo tờ trình): số tiền sẽ giải ngân, nằm trong snapshot.
    op.add_column("loan_applications", sa.Column("approved_amount", MONEY))
    op.add_column("loan_applications", sa.Column("approved_term", sa.SmallInteger))


def downgrade() -> None:
    op.drop_column("loan_applications", "approved_term")
    op.drop_column("loan_applications", "approved_amount")
    op.drop_column("appraisal_reports", "seq")
    op.execute("REVOKE UPDATE, DELETE ON dbo.approval_decisions TO app_rw")
    op.drop_index("ix_approval_decisions_application", "approval_decisions")
    op.drop_table("approval_decisions")
