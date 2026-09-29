"""Khách hàng, tài khoản, phiên đăng nhập, yêu cầu đăng ký và nhật ký kiểm toán

Revision ID: 0001
Revises:
Create Date: 2026-09-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mssql import DATETIMEOFFSET, NVARCHAR, UNIQUEIDENTIFIER

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

HASH = sa.CHAR(64, collation="Latin1_General_BIN2")


def upgrade() -> None:
    op.create_table(
        "customers",
        sa.Column("id", UNIQUEIDENTIFIER, primary_key=True),
        sa.Column("full_name", NVARCHAR(100), nullable=False),
        sa.Column("dob", sa.Date, nullable=False),
        sa.Column("phone", sa.String(15), nullable=False, unique=True),
        sa.Column("email", NVARCHAR(100), nullable=False, unique=True),
        sa.Column("consent_at", DATETIMEOFFSET, nullable=False),
        sa.Column("consent_version", sa.String(10), nullable=False),
        sa.Column("created_at", DATETIMEOFFSET, nullable=False),
    )
    op.create_table(
        "users",
        sa.Column("id", UNIQUEIDENTIFIER, primary_key=True),
        sa.Column("username", NVARCHAR(50), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("failed_attempts", sa.SmallInteger, nullable=False, server_default="0"),
        sa.Column("locked_until", DATETIMEOFFSET),
        sa.Column("customer_id", UNIQUEIDENTIFIER, sa.ForeignKey("customers.id")),
        sa.Column("last_login_at", DATETIMEOFFSET),
        sa.Column("created_at", DATETIMEOFFSET, nullable=False),
        sa.CheckConstraint(
            "status IN ('PENDING','ACTIVE','LOCKED','DISABLED')", name="ck_users_status"
        ),
    )
    op.create_table(
        "registration_requests",
        sa.Column("id", UNIQUEIDENTIFIER, primary_key=True),
        sa.Column("full_name", NVARCHAR(100), nullable=False),
        sa.Column("dob", sa.Date, nullable=False),
        sa.Column("phone", sa.String(15), nullable=False, index=True),
        sa.Column("email", NVARCHAR(100), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("otp_hash", HASH, nullable=False),
        sa.Column("otp_expires_at", DATETIMEOFFSET, nullable=False),
        sa.Column("failed_attempts", sa.SmallInteger, nullable=False, server_default="0"),
        sa.Column("consent_version", sa.String(10), nullable=False),
        sa.Column("created_at", DATETIMEOFFSET, nullable=False),
    )
    op.create_table(
        "sessions",
        sa.Column("id", UNIQUEIDENTIFIER, primary_key=True),
        sa.Column("token_hash", HASH, nullable=False, unique=True),
        sa.Column("user_id", UNIQUEIDENTIFIER, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", DATETIMEOFFSET, nullable=False),
        sa.Column("last_seen_at", DATETIMEOFFSET, nullable=False),
        sa.Column("revoked_at", DATETIMEOFFSET),
    )
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger, sa.Identity(start=1, increment=1), primary_key=True),
        sa.Column("seq", sa.BigInteger, nullable=False, unique=True),
        sa.Column("actor_id", UNIQUEIDENTIFIER, sa.ForeignKey("users.id")),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("target_type", sa.String(30)),
        sa.Column("target_id", sa.String(50)),
        sa.Column("ip_address", sa.String(45)),
        sa.Column("level", sa.String(10), nullable=False),
        sa.Column("created_at", DATETIMEOFFSET, nullable=False),
        sa.Column("prev_hash", HASH, nullable=False),
        sa.Column("hash", HASH, nullable=False),
        sa.CheckConstraint("level IN ('INFO','WARNING','CRITICAL')", name="ck_audit_logs_level"),
    )
    op.create_index("ix_audit_logs_actor_created", "audit_logs", ["actor_id", "created_at"])
    op.create_index("ix_audit_logs_target", "audit_logs", ["target_type", "target_id"])


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("sessions")
    op.drop_table("registration_requests")
    op.drop_table("users")
    op.drop_table("customers")
