"""Chấm điểm tín dụng: báo cáo CIC, điểm tín dụng, mô hình chấm điểm, chính sách mặc định (ticket #6)

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-29
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mssql import DATETIMEOFFSET, NVARCHAR, UNIQUEIDENTIFIER

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

HASH = sa.CHAR(64, collation="Latin1_General_BIN2")
MONEY = sa.DECIMAL(15, 0)
RATE = sa.DECIMAL(5, 4)

# Thẻ điểm đi kèm mã nguồn. Checksum ghi cứng ở đây, không tính từ file lúc chạy migration: nếu
# file đã bị sửa trước đó thì checksum tính lại cũng sẽ "khớp" (SR13).
SCORECARD_VERSION = "SC-2026.1"
SCORECARD_FILE = "scorecard-2026.1.json"
SCORECARD_SHA256 = "6ad4d469fa7a5e7ce092c6fd8a8e7f0c568a6ddad634dcc950c17e391d8033fa"


def upgrade() -> None:
    op.create_table(
        "scoring_models",
        sa.Column("id", UNIQUEIDENTIFIER, primary_key=True),
        sa.Column("version", sa.String(20), nullable=False, unique=True),
        sa.Column("file_name", sa.String(100), nullable=False),
        sa.Column("checksum", HASH, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False),
        sa.Column("created_at", DATETIMEOFFSET, nullable=False),
    )
    # Chỉ một mô hình hiệu lực tại một thời điểm.
    op.create_index(
        "ux_scoring_models_active", "scoring_models", ["is_active"], unique=True,
        mssql_where=sa.text("is_active = 1"),
    )

    # Chính sách phê duyệt có phiên bản; bảng lãi suất theo hạng và phí trả trước hạn (ADR 0001).
    # Số lượt phê duyệt theo khoảng hạn mức thêm ở ticket phê duyệt.
    op.create_table(
        "approval_policies",
        sa.Column("id", UNIQUEIDENTIFIER, primary_key=True),
        sa.Column("version", sa.Integer, nullable=False, unique=True),
        sa.Column("rate_grade_a", RATE, nullable=False),
        sa.Column("rate_grade_b", RATE, nullable=False),
        sa.Column("rate_grade_c", RATE, nullable=False),
        sa.Column("prepayment_fee_rate", RATE, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False),
        sa.Column("created_at", DATETIMEOFFSET, nullable=False),
    )
    op.create_index(
        "ux_approval_policies_active", "approval_policies", ["is_active"], unique=True,
        mssql_where=sa.text("is_active = 1"),
    )

    op.create_table(
        "cic_reports",
        sa.Column("id", UNIQUEIDENTIFIER, primary_key=True),
        sa.Column(
            "application_id", UNIQUEIDENTIFIER, sa.ForeignKey("loan_applications.id"),
            nullable=False,
        ),
        sa.Column("highest_debt_group", sa.SmallInteger, nullable=False),
        sa.Column("total_outstanding", MONEY, nullable=False),
        sa.Column("lender_count", sa.SmallInteger, nullable=False),
        sa.Column("monthly_obligation", MONEY, nullable=False),
        sa.Column("utility_late_payments", sa.SmallInteger),
        sa.Column("queried_at", DATETIMEOFFSET, nullable=False),
        sa.CheckConstraint(
            "highest_debt_group BETWEEN 0 AND 5", name="ck_cic_reports_debt_group"
        ),
    )
    op.create_index("ix_cic_reports_application", "cic_reports", ["application_id"])

    op.create_table(
        "credit_scores",
        sa.Column("id", UNIQUEIDENTIFIER, primary_key=True),
        sa.Column(
            "application_id", UNIQUEIDENTIFIER, sa.ForeignKey("loan_applications.id"),
            nullable=False,
        ),
        sa.Column("score", sa.SmallInteger),
        sa.Column("grade", sa.CHAR(1)),
        sa.Column("knock_out_reason", NVARCHAR(100)),
        sa.Column("dti", sa.DECIMAL(9, 4), nullable=False),
        sa.Column("factors_json", NVARCHAR(None), nullable=False),
        sa.Column("model_version", sa.String(20)),
        sa.Column("scored_at", DATETIMEOFFSET, nullable=False),
        sa.CheckConstraint("score BETWEEN 0 AND 1000", name="ck_credit_scores_score"),
        sa.CheckConstraint("grade IN ('A','B','C','D')", name="ck_credit_scores_grade"),
        sa.CheckConstraint("ISJSON(factors_json) = 1", name="ck_credit_scores_factors_json"),
        # Bị loại trừ thì không chấm điểm; ngược lại phải có điểm, hạng, phiên bản mô hình.
        sa.CheckConstraint(
            "knock_out_reason IS NOT NULL"
            " OR (score IS NOT NULL AND grade IS NOT NULL AND model_version IS NOT NULL)",
            name="ck_credit_scores_result",
        ),
    )
    op.create_index(
        "ix_credit_scores_application", "credit_scores", ["application_id", "scored_at"]
    )

    op.add_column("loan_applications", sa.Column("annual_rate", RATE))
    op.add_column(
        "loan_applications",
        sa.Column("policy_id", UNIQUEIDENTIFIER, sa.ForeignKey("approval_policies.id")),
    )
    op.add_column(
        "loan_applications",
        sa.Column("cic_missing", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "loan_applications",
        sa.Column("fraud_suspected", sa.Boolean, nullable=False, server_default=sa.false()),
    )

    now = datetime.now(UTC)
    scoring_models = sa.table(
        "scoring_models",
        sa.column("id", UNIQUEIDENTIFIER),
        sa.column("version", sa.String),
        sa.column("file_name", sa.String),
        sa.column("checksum", sa.String),
        sa.column("is_active", sa.Boolean),
        sa.column("created_at", DATETIMEOFFSET),
    )
    op.bulk_insert(
        scoring_models,
        [
            {
                "id": uuid.uuid4(), "version": SCORECARD_VERSION, "file_name": SCORECARD_FILE,
                "checksum": SCORECARD_SHA256, "is_active": True, "created_at": now,
            }
        ],
    )
    approval_policies = sa.table(
        "approval_policies",
        sa.column("id", UNIQUEIDENTIFIER),
        sa.column("version", sa.Integer),
        sa.column("rate_grade_a", RATE),
        sa.column("rate_grade_b", RATE),
        sa.column("rate_grade_c", RATE),
        sa.column("prepayment_fee_rate", RATE),
        sa.column("is_active", sa.Boolean),
        sa.column("created_at", DATETIMEOFFSET),
    )
    # Chính sách mặc định: A = 20%, B = 24%, C = 28%/năm; phí trả trước hạn 3% (1.2.8d).
    op.bulk_insert(
        approval_policies,
        [
            {
                "id": uuid.uuid4(), "version": 1, "rate_grade_a": Decimal("0.20"),
                "rate_grade_b": Decimal("0.24"), "rate_grade_c": Decimal("0.28"),
                "prepayment_fee_rate": Decimal("0.03"), "is_active": True, "created_at": now,
            }
        ],
    )


def downgrade() -> None:
    op.drop_column("loan_applications", "fraud_suspected", mssql_drop_default=True)
    op.drop_column("loan_applications", "cic_missing", mssql_drop_default=True)
    op.drop_column("loan_applications", "policy_id", mssql_drop_foreign_key=True)
    op.drop_column("loan_applications", "annual_rate")
    op.drop_table("credit_scores")
    op.drop_table("cic_reports")
    op.drop_table("approval_policies")
    op.drop_table("scoring_models")
