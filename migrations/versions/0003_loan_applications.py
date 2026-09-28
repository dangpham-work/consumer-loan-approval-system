"""Hồ sơ vay, giấy tờ, thông tin tài chính của khách hàng (UC12, UC13)

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mssql import DATETIMEOFFSET, NVARCHAR, UNIQUEIDENTIFIER

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

HASH = sa.CHAR(64, collation="Latin1_General_BIN2")
ENCRYPTED = sa.LargeBinary(500)
MONEY = sa.DECIMAL(15, 0)
STATUSES = (
    "'DRAFT','SUBMITTED','NEED_INFO','VERIFIED','APPRAISING','PENDING_APPROVAL','APPROVED',"
    "'REJECTED','CANCELLED','DISBURSED','LOCKED'"
)


def upgrade() -> None:
    # Cho phép NULL cho đến khi khách hàng lập Hồ sơ vay đầu tiên (UC09 không thu thập CCCD).
    op.add_column("customers", sa.Column("national_id_enc", ENCRYPTED))
    op.add_column("customers", sa.Column("national_id_hash", HASH))
    op.add_column("customers", sa.Column("occupation", NVARCHAR(50)))
    op.add_column("customers", sa.Column("employer", NVARCHAR(100)))
    op.add_column("customers", sa.Column("employment_years", sa.SmallInteger))
    op.add_column("customers", sa.Column("monthly_income_enc", ENCRYPTED))
    op.add_column("customers", sa.Column("housing_type", sa.String(10)))
    op.add_column("customers", sa.Column("address", NVARCHAR(255)))
    op.create_check_constraint(
        "ck_customers_housing_type", "customers", "housing_type IN ('OWN','FAMILY','RENT')"
    )
    # Một CCCD chỉ thuộc về một khách hàng; tra cứu bằng blind index (4.1.2e).
    op.create_index(
        "ux_customers_national_id_hash",
        "customers",
        ["national_id_hash"],
        unique=True,
        mssql_where=sa.text("national_id_hash IS NOT NULL"),
    )

    op.create_table(
        "loan_applications",
        sa.Column("id", UNIQUEIDENTIFIER, primary_key=True),
        sa.Column("code", sa.String(20)),
        sa.Column("customer_id", UNIQUEIDENTIFIER, sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("requested_amount", MONEY, nullable=False),
        sa.Column("term_months", sa.SmallInteger, nullable=False),
        sa.Column("purpose", sa.String(20), nullable=False),
        sa.Column("existing_monthly_debt", MONEY),
        sa.Column("receiving_account_enc", ENCRYPTED),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("consent_at", DATETIMEOFFSET),
        sa.Column("consent_version", sa.String(10)),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("created_at", DATETIMEOFFSET, nullable=False),
        sa.Column("submitted_at", DATETIMEOFFSET),
        sa.CheckConstraint(
            "requested_amount BETWEEN 5000000 AND 100000000", name="ck_loan_applications_amount"
        ),
        sa.CheckConstraint("term_months BETWEEN 6 AND 36", name="ck_loan_applications_term"),
        sa.CheckConstraint(
            "existing_monthly_debt >= 0", name="ck_loan_applications_existing_debt"
        ),
        sa.CheckConstraint(f"status IN ({STATUSES})", name="ck_loan_applications_status"),
    )
    op.create_index(
        "ux_loan_applications_code",
        "loan_applications",
        ["code"],
        unique=True,
        mssql_where=sa.text("code IS NOT NULL"),
    )
    op.create_index(
        "ix_loan_applications_status_submitted", "loan_applications", ["status", "submitted_at"]
    )
    op.create_index("ix_loan_applications_customer", "loan_applications", ["customer_id"])
    # Số thứ tự trong mã hồ sơ vay HS<năm><6 chữ số>; SEQUENCE không cấp trùng khi nộp song song.
    op.execute("CREATE SEQUENCE loan_application_code_seq AS BIGINT START WITH 1 INCREMENT BY 1")

    op.create_table(
        "application_documents",
        sa.Column("id", UNIQUEIDENTIFIER, primary_key=True),
        sa.Column(
            "application_id",
            UNIQUEIDENTIFIER,
            sa.ForeignKey("loan_applications.id"),
            nullable=False,
        ),
        sa.Column("doc_type", sa.String(20), nullable=False),
        sa.Column("storage_path", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(50), nullable=False),
        sa.Column("size_bytes", sa.Integer, nullable=False),
        sa.Column("sha256", HASH, nullable=False),
        sa.Column("uploaded_by", UNIQUEIDENTIFIER, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("uploaded_at", DATETIMEOFFSET, nullable=False),
        sa.Column("replaced_at", DATETIMEOFFSET),
        sa.CheckConstraint(
            "doc_type IN ('ID_FRONT','ID_BACK','INCOME_PROOF','UTILITY_BILL')",
            name="ck_application_documents_type",
        ),
    )
    op.create_index(
        "ix_application_documents_application", "application_documents", ["application_id"]
    )


def downgrade() -> None:
    op.drop_table("application_documents")
    op.execute("DROP SEQUENCE loan_application_code_seq")
    op.drop_table("loan_applications")
    op.drop_index("ux_customers_national_id_hash", "customers")
    op.drop_constraint("ck_customers_housing_type", "customers")
    for column in (
        "address", "housing_type", "monthly_income_enc", "employment_years", "employer",
        "occupation", "national_id_hash", "national_id_enc",
    ):
        op.drop_column("customers", column)
