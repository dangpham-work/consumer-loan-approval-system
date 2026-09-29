"""Thẩm định hồ sơ vay: tờ trình, người thẩm định, số lượt phê duyệt theo hạn mức (ticket #7)

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-29
"""

import uuid
from collections.abc import Sequence
from decimal import Decimal

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mssql import DATETIMEOFFSET, NVARCHAR, UNIQUEIDENTIFIER

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MONEY = sa.DECIMAL(15, 0)


def upgrade() -> None:
    # Tờ trình thẩm định (UC22). Không UNIQUE theo hồ sơ vay: bị Trả về thì thẩm định lại và lập
    # tờ trình mới, tờ trình mới nhất có hiệu lực.
    op.create_table(
        "appraisal_reports",
        sa.Column("id", UNIQUEIDENTIFIER, primary_key=True),
        sa.Column(
            "application_id", UNIQUEIDENTIFIER, sa.ForeignKey("loan_applications.id"),
            nullable=False,
        ),
        sa.Column("appraiser_id", UNIQUEIDENTIFIER, sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("recommendation", sa.String(10), nullable=False),
        sa.Column("proposed_amount", MONEY),
        sa.Column("proposed_term", sa.SmallInteger),
        sa.Column("dti", sa.DECIMAL(9, 4)),
        sa.Column("fraud_suspected", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("comment", NVARCHAR(1000), nullable=False),
        sa.Column("created_at", DATETIMEOFFSET, nullable=False),
        sa.CheckConstraint(
            "recommendation IN ('APPROVE','REJECT')", name="ck_appraisal_reports_recommendation"
        ),
        sa.CheckConstraint(
            "recommendation = 'REJECT'"
            " OR (proposed_amount IS NOT NULL AND proposed_term IS NOT NULL AND dti IS NOT NULL)",
            name="ck_appraisal_reports_proposal",
        ),
    )
    op.create_index(
        "ix_appraisal_reports_application", "appraisal_reports", ["application_id", "created_at"]
    )

    # Số lượt phê duyệt theo khoảng hạn mức của từng phiên bản chính sách (BR05).
    op.create_table(
        "approval_policy_tiers",
        sa.Column("id", UNIQUEIDENTIFIER, primary_key=True),
        sa.Column(
            "policy_id", UNIQUEIDENTIFIER, sa.ForeignKey("approval_policies.id"), nullable=False
        ),
        sa.Column("min_amount", MONEY, nullable=False),
        sa.Column("max_amount", MONEY, nullable=False),
        sa.Column("required_approvals", sa.SmallInteger, nullable=False),
        sa.CheckConstraint(
            "required_approvals >= 1", name="ck_approval_policy_tiers_required_approvals"
        ),
        sa.CheckConstraint("min_amount <= max_amount", name="ck_approval_policy_tiers_range"),
    )

    op.add_column(
        "loan_applications",
        sa.Column("appraised_by", UNIQUEIDENTIFIER, sa.ForeignKey("employees.id")),
    )
    # Chốt khi nộp tờ trình, theo hạn mức đề xuất (UC22 bước 6).
    op.add_column("loan_applications", sa.Column("required_approvals", sa.SmallInteger))

    tiers = sa.table(
        "approval_policy_tiers",
        sa.column("id", UNIQUEIDENTIFIER),
        sa.column("policy_id", UNIQUEIDENTIFIER),
        sa.column("min_amount", MONEY),
        sa.column("max_amount", MONEY),
        sa.column("required_approvals", sa.SmallInteger),
    )
    policy_id = op.get_bind().execute(
        sa.text("SELECT id FROM approval_policies WHERE version = 1")
    ).scalar_one()
    # Chính sách mặc định: ≤ 50 triệu cần 1 Quản lý phê duyệt, > 50 triệu cần 2 (BR05).
    op.bulk_insert(
        tiers,
        [
            {
                "id": uuid.uuid4(), "policy_id": policy_id, "min_amount": Decimal(5_000_000),
                "max_amount": Decimal(50_000_000), "required_approvals": 1,
            },
            {
                "id": uuid.uuid4(), "policy_id": policy_id, "min_amount": Decimal(50_000_001),
                "max_amount": Decimal(100_000_000), "required_approvals": 2,
            },
        ],
    )


def downgrade() -> None:
    op.drop_column("loan_applications", "required_approvals")
    op.drop_column("loan_applications", "appraised_by", mssql_drop_foreign_key=True)
    op.drop_table("approval_policy_tiers")
    op.drop_table("appraisal_reports")
