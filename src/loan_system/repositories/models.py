"""Ánh xạ lớp thực thể sang bảng SQL Server (mục 4.1.2 đề cương, kiểu theo ADR 0003)."""

import uuid
from datetime import date, datetime

from sqlalchemy import CHAR, BigInteger, CheckConstraint, Date, ForeignKey, Identity, SmallInteger, String
from sqlalchemy.dialects.mssql import DATETIMEOFFSET, NVARCHAR, UNIQUEIDENTIFIER
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Cột mã băm so sánh chính xác từng byte, không phụ thuộc collation tiếng Việt.
HASH_COLLATION = "Latin1_General_BIN2"


def Hash64() -> CHAR:  # noqa: N802 - dùng như một kiểu cột
    return CHAR(64, collation=HASH_COLLATION)


class Base(DeclarativeBase):
    pass


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[uuid.UUID] = mapped_column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4)
    full_name: Mapped[str] = mapped_column(NVARCHAR(100))
    dob: Mapped[date] = mapped_column(Date)
    phone: Mapped[str] = mapped_column(String(15), unique=True)
    email: Mapped[str] = mapped_column(NVARCHAR(100), unique=True)
    consent_at: Mapped[datetime] = mapped_column(DATETIMEOFFSET)
    consent_version: Mapped[str] = mapped_column(String(10))
    created_at: Mapped[datetime] = mapped_column(DATETIMEOFFSET)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING','ACTIVE','LOCKED','DISABLED')", name="ck_users_status"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(NVARCHAR(50), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(10))
    failed_attempts: Mapped[int] = mapped_column(SmallInteger, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DATETIMEOFFSET)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("customers.id"))
    last_login_at: Mapped[datetime | None] = mapped_column(DATETIMEOFFSET)
    created_at: Mapped[datetime] = mapped_column(DATETIMEOFFSET)


class RegistrationRequest(Base):
    """Yêu cầu đăng ký đang chờ xác minh OTP (UC09 bước 3–4)."""

    __tablename__ = "registration_requests"

    id: Mapped[uuid.UUID] = mapped_column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4)
    full_name: Mapped[str] = mapped_column(NVARCHAR(100))
    dob: Mapped[date] = mapped_column(Date)
    phone: Mapped[str] = mapped_column(String(15), index=True)
    email: Mapped[str] = mapped_column(NVARCHAR(100))
    password_hash: Mapped[str] = mapped_column(String(255))
    otp_hash: Mapped[str] = mapped_column(Hash64())
    otp_expires_at: Mapped[datetime] = mapped_column(DATETIMEOFFSET)
    failed_attempts: Mapped[int] = mapped_column(SmallInteger, default=0)
    consent_version: Mapped[str] = mapped_column(String(10))
    created_at: Mapped[datetime] = mapped_column(DATETIMEOFFSET)


class UserSession(Base):
    """Phiên đăng nhập phía máy chủ; chỉ lưu mã băm của token."""

    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4)
    token_hash: Mapped[str] = mapped_column(Hash64(), unique=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DATETIMEOFFSET)
    last_seen_at: Mapped[datetime] = mapped_column(DATETIMEOFFSET)
    revoked_at: Mapped[datetime | None] = mapped_column(DATETIMEOFFSET)


class AuditLog(Base):
    """Nhật ký kiểm toán chỉ ghi thêm, có chuỗi băm (SR09)."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        CheckConstraint("level IN ('INFO','WARNING','CRITICAL')", name="ck_audit_logs_level"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(start=1, increment=1), primary_key=True)
    # Số thứ tự liên tục do ứng dụng cấp; là thứ tự của chuỗi băm (IDENTITY có thể nhảy số).
    seq: Mapped[int] = mapped_column(BigInteger, unique=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(50))
    target_type: Mapped[str | None] = mapped_column(String(30))
    target_id: Mapped[str | None] = mapped_column(String(50))
    ip_address: Mapped[str | None] = mapped_column(String(45))
    level: Mapped[str] = mapped_column(String(10))
    created_at: Mapped[datetime] = mapped_column(DATETIMEOFFSET)
    prev_hash: Mapped[str] = mapped_column(Hash64())
    hash: Mapped[str] = mapped_column(Hash64())
