"""Kiểm tra hồ sơ vay, yêu cầu bổ sung, nộp hộ, lịch sử trạng thái, thông báo, thử thách OTP (ticket #5)

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mssql import DATETIMEOFFSET, NVARCHAR, UNIQUEIDENTIFIER

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

HASH = sa.CHAR(64, collation="Latin1_General_BIN2")


def upgrade() -> None:
    # Người tạo (nộp hộ) và Người tiếp nhận: dữ liệu cho kiểm tra phân tách nhiệm vụ (BR06).
    op.add_column(
        "loan_applications",
        sa.Column("created_by", UNIQUEIDENTIFIER, sa.ForeignKey("employees.id")),
    )
    op.add_column(
        "loan_applications",
        sa.Column("received_by", UNIQUEIDENTIFIER, sa.ForeignKey("employees.id")),
    )
    op.add_column("loan_applications", sa.Column("need_info_message", NVARCHAR(500)))
    op.add_column("loan_applications", sa.Column("need_info_items", sa.String(300)))
    op.add_column("loan_applications", sa.Column("need_info_deadline", DATETIMEOFFSET))
    op.add_column("loan_applications", sa.Column("cancel_reason", NVARCHAR(200)))

    op.add_column("application_documents", sa.Column("review_verdict", sa.String(4)))
    op.add_column("application_documents", sa.Column("review_note", NVARCHAR(200)))
    op.add_column(
        "application_documents",
        sa.Column("reviewed_by", UNIQUEIDENTIFIER, sa.ForeignKey("employees.id")),
    )
    op.add_column("application_documents", sa.Column("reviewed_at", DATETIMEOFFSET))
    op.create_check_constraint(
        "ck_application_documents_verdict",
        "application_documents",
        "review_verdict IN ('PASS','FAIL')",
    )

    op.create_table(
        "application_status_history",
        sa.Column("id", sa.BigInteger, sa.Identity(start=1, increment=1), primary_key=True),
        sa.Column(
            "application_id",
            UNIQUEIDENTIFIER,
            sa.ForeignKey("loan_applications.id"),
            nullable=False,
        ),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("actor_id", UNIQUEIDENTIFIER, sa.ForeignKey("users.id")),
        sa.Column("reason", NVARCHAR(500)),
        sa.Column("changed_at", DATETIMEOFFSET, nullable=False),
    )
    op.create_index(
        "ix_application_status_history_application",
        "application_status_history",
        ["application_id", "changed_at"],
    )
    # Hồ sơ vay đã có từ trước: dựng lại lịch sử từ các mốc thời gian đang lưu.
    op.execute(
        "INSERT INTO application_status_history (application_id, status, changed_at) "
        "SELECT id, 'DRAFT', created_at FROM loan_applications"
    )
    op.execute(
        "INSERT INTO application_status_history (application_id, status, changed_at) "
        "SELECT id, 'SUBMITTED', submitted_at FROM loan_applications "
        "WHERE submitted_at IS NOT NULL"
    )

    op.create_table(
        "notifications",
        sa.Column("id", UNIQUEIDENTIFIER, primary_key=True),
        sa.Column(
            "recipient_user_id", UNIQUEIDENTIFIER, sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("type", sa.String(30), nullable=False),
        sa.Column("content", NVARCHAR(500), nullable=False),
        sa.Column("channel", sa.String(10), nullable=False),
        sa.Column("is_read", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", DATETIMEOFFSET, nullable=False),
        sa.CheckConstraint("channel IN ('IN_APP','SMS','EMAIL')", name="ck_notifications_channel"),
    )
    op.create_index(
        "ix_notifications_recipient", "notifications", ["recipient_user_id", "created_at"]
    )

    op.create_table(
        "otp_challenges",
        sa.Column("id", UNIQUEIDENTIFIER, primary_key=True),
        sa.Column("purpose", sa.String(30), nullable=False),
        sa.Column("phone", sa.String(15), nullable=False),
        sa.Column("subject_id", sa.String(50)),
        # Dữ liệu cá nhân chờ xác nhận, mã hóa AES-GCM (SR06); xóa khi thử thách kết thúc.
        sa.Column("payload_enc", sa.LargeBinary(None)),
        sa.Column("otp_hash", HASH, nullable=False),
        sa.Column("expires_at", DATETIMEOFFSET, nullable=False),
        sa.Column("failed_attempts", sa.SmallInteger, nullable=False, server_default="0"),
        sa.Column("created_by", UNIQUEIDENTIFIER, sa.ForeignKey("users.id")),
        sa.Column("created_at", DATETIMEOFFSET, nullable=False),
        sa.Column("consumed_at", DATETIMEOFFSET),
    )


def downgrade() -> None:
    op.drop_table("otp_challenges")
    op.drop_table("notifications")
    op.drop_table("application_status_history")
    op.drop_constraint("ck_application_documents_verdict", "application_documents")
    op.drop_column("application_documents", "reviewed_at")
    op.drop_column("application_documents", "reviewed_by", mssql_drop_foreign_key=True)
    op.drop_column("application_documents", "review_note")
    op.drop_column("application_documents", "review_verdict")
    op.drop_column("loan_applications", "cancel_reason")
    op.drop_column("loan_applications", "need_info_deadline")
    op.drop_column("loan_applications", "need_info_items")
    op.drop_column("loan_applications", "need_info_message")
    op.drop_column("loan_applications", "received_by", mssql_drop_foreign_key=True)
    op.drop_column("loan_applications", "created_by", mssql_drop_foreign_key=True)
