"""Ánh xạ lớp thực thể sang bảng SQL Server (mục 4.1.2 đề cương, kiểu theo ADR 0003)."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CHAR,
    DECIMAL,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Identity,
    Index,
    Integer,
    LargeBinary,
    SmallInteger,
    String,
    text,
)
from sqlalchemy.dialects.mssql import DATETIMEOFFSET, NVARCHAR, UNIQUEIDENTIFIER
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Cột mã băm so sánh chính xác từng byte, không phụ thuộc collation tiếng Việt.
HASH_COLLATION = "Latin1_General_BIN2"


def Hash64() -> CHAR:  # noqa: N802 - dùng như một kiểu cột
    return CHAR(64, collation=HASH_COLLATION)


def Money() -> DECIMAL[Decimal]:  # noqa: N802 - tiền tính bằng đồng (4.1.2a)
    return DECIMAL(15, 0)


def Encrypted() -> LargeBinary:  # noqa: N802 - bản mã AES-GCM (SR06)
    # 1 byte phiên bản khóa + 12 byte nonce + dữ liệu + 16 byte tag.
    return LargeBinary(500)


class Base(DeclarativeBase):
    pass


class Customer(Base):
    __tablename__ = "customers"
    __table_args__ = (
        CheckConstraint(
            "housing_type IN ('OWN','FAMILY','RENT')", name="ck_customers_housing_type"
        ),
        Index(
            "ux_customers_national_id_hash",
            "national_id_hash",
            unique=True,
            mssql_where=text("national_id_hash IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4)
    full_name: Mapped[str] = mapped_column(NVARCHAR(100))
    dob: Mapped[date] = mapped_column(Date)
    phone: Mapped[str] = mapped_column(String(15), unique=True)
    email: Mapped[str] = mapped_column(NVARCHAR(100), unique=True)
    consent_at: Mapped[datetime] = mapped_column(DATETIMEOFFSET)
    consent_version: Mapped[str] = mapped_column(String(10))
    created_at: Mapped[datetime] = mapped_column(DATETIMEOFFSET)
    # Thu thập khi khách hàng lập Hồ sơ vay đầu tiên, không có lúc đăng ký (UC09).
    national_id_enc: Mapped[bytes | None] = mapped_column(Encrypted())
    national_id_hash: Mapped[str | None] = mapped_column(Hash64())  # blind index
    occupation: Mapped[str | None] = mapped_column(NVARCHAR(50))
    employer: Mapped[str | None] = mapped_column(NVARCHAR(100))
    employment_years: Mapped[int | None] = mapped_column(SmallInteger)
    monthly_income_enc: Mapped[bytes | None] = mapped_column(Encrypted())
    housing_type: Mapped[str | None] = mapped_column(String(10))
    address: Mapped[str | None] = mapped_column(NVARCHAR(255))


class Employee(Base):
    __tablename__ = "employees"

    id: Mapped[uuid.UUID] = mapped_column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4)
    full_name: Mapped[str] = mapped_column(NVARCHAR(100))
    email: Mapped[str] = mapped_column(NVARCHAR(100), unique=True)
    branch: Mapped[str] = mapped_column(NVARCHAR(50))
    created_at: Mapped[datetime] = mapped_column(DATETIMEOFFSET)


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[uuid.UUID] = mapped_column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(NVARCHAR(100))


class Permission(Base):
    __tablename__ = "permissions"

    id: Mapped[uuid.UUID] = mapped_column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(50), unique=True)
    description: Mapped[str] = mapped_column(NVARCHAR(200))


class UserRole(Base):
    __tablename__ = "user_roles"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("roles.id"), primary_key=True)


class RolePermission(Base):
    __tablename__ = "role_permissions"

    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("roles.id"), primary_key=True)
    permission_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("permissions.id"), primary_key=True)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING','ACTIVE','LOCKED','DISABLED')", name="ck_users_status"
        ),
        CheckConstraint(
            "(employee_id IS NULL AND customer_id IS NOT NULL)"
            " OR (employee_id IS NOT NULL AND customer_id IS NULL)",
            name="ck_users_owner",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(NVARCHAR(50), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(10))
    failed_attempts: Mapped[int] = mapped_column(SmallInteger, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DATETIMEOFFSET)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("customers.id"))
    employee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("employees.id"))
    last_login_at: Mapped[datetime | None] = mapped_column(DATETIMEOFFSET)
    created_at: Mapped[datetime] = mapped_column(DATETIMEOFFSET)
    # Tài khoản PENDING phải đổi mật khẩu tạm rồi đăng ký TOTP trước khi dùng (UC01 3b).
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    totp_secret_enc: Mapped[bytes | None] = mapped_column(Encrypted())  # SR02, SR06
    # Bước thời gian của mã TOTP dùng gần nhất, để một mã không dùng được hai lần (UC02 bước 3).
    totp_last_step: Mapped[int | None] = mapped_column(BigInteger)


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
    # SETUP: đăng nhập lần đầu; MFA: đã qua mật khẩu, chờ TOTP; FULL: phiên làm việc đầy đủ.
    stage: Mapped[str] = mapped_column(String(10))
    otp_failed_attempts: Mapped[int] = mapped_column(SmallInteger, default=0)


class LoanApplication(Base):
    __tablename__ = "loan_applications"
    __table_args__ = (
        CheckConstraint(
            "requested_amount BETWEEN 5000000 AND 100000000", name="ck_loan_applications_amount"
        ),
        CheckConstraint("term_months BETWEEN 6 AND 36", name="ck_loan_applications_term"),
        CheckConstraint(
            "existing_monthly_debt >= 0", name="ck_loan_applications_existing_debt"
        ),
        CheckConstraint(
            "status IN ('DRAFT','SUBMITTED','NEED_INFO','VERIFIED','APPRAISING',"
            "'PENDING_APPROVAL','APPROVED','REJECTED','CANCELLED','DISBURSED','LOCKED')",
            name="ck_loan_applications_status",
        ),
        # Mã hồ sơ vay chỉ được cấp khi nộp; bản nháp chưa có mã.
        Index(
            "ux_loan_applications_code", "code", unique=True, mssql_where=text("code IS NOT NULL")
        ),
        Index("ix_loan_applications_status_submitted", "status", "submitted_at"),
        Index("ix_loan_applications_customer", "customer_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4)
    code: Mapped[str | None] = mapped_column(String(20))
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"))
    requested_amount: Mapped[Decimal] = mapped_column(Money())
    term_months: Mapped[int] = mapped_column(SmallInteger)
    purpose: Mapped[str] = mapped_column(String(20))
    existing_monthly_debt: Mapped[Decimal | None] = mapped_column(Money())
    receiving_account_enc: Mapped[bytes | None] = mapped_column(Encrypted())
    status: Mapped[str] = mapped_column(String(20))
    consent_at: Mapped[datetime | None] = mapped_column(DATETIMEOFFSET)  # SR14
    consent_version: Mapped[str | None] = mapped_column(String(10))
    version: Mapped[int] = mapped_column(Integer)  # khóa lạc quan
    created_at: Mapped[datetime] = mapped_column(DATETIMEOFFSET)
    submitted_at: Mapped[datetime | None] = mapped_column(DATETIMEOFFSET)
    # Người tạo: NV tín dụng nộp hộ tại quầy (UC12 1a); Người tiếp nhận: NV đã nhận kiểm tra (UC14).
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("employees.id"))
    received_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("employees.id"))
    need_info_message: Mapped[str | None] = mapped_column(NVARCHAR(500))  # UC15
    need_info_items: Mapped[str | None] = mapped_column(String(300))  # mã cố định, phân cách dấu phẩy
    need_info_deadline: Mapped[datetime | None] = mapped_column(DATETIMEOFFSET)  # BR11
    cancel_reason: Mapped[str | None] = mapped_column(NVARCHAR(200))

    __mapper_args__ = {"version_id_col": version}


class ApplicationStatusHistory(Base):
    """Dòng thời gian trạng thái của Hồ sơ vay (UC16 bước 3)."""

    __tablename__ = "application_status_history"
    __table_args__ = (
        Index("ix_application_status_history_application", "application_id", "changed_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(start=1, increment=1), primary_key=True)
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("loan_applications.id"))
    status: Mapped[str] = mapped_column(String(20))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    reason: Mapped[str | None] = mapped_column(NVARCHAR(500))
    changed_at: Mapped[datetime] = mapped_column(DATETIMEOFFSET)


class Notification(Base):
    """Thông báo tới người dùng; nội dung không chứa dữ liệu nhạy cảm (SR07)."""

    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint("channel IN ('IN_APP','SMS','EMAIL')", name="ck_notifications_channel"),
        Index("ix_notifications_recipient", "recipient_user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4)
    recipient_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    type: Mapped[str] = mapped_column(String(30))
    content: Mapped[str] = mapped_column(NVARCHAR(500))
    channel: Mapped[str] = mapped_column(String(10))
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DATETIMEOFFSET)


class OtpChallenge(Base):
    """Mã OTP gửi qua SMS để một người xác nhận thao tác do người khác khởi tạo (UC12 1a)."""

    __tablename__ = "otp_challenges"

    id: Mapped[uuid.UUID] = mapped_column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4)
    purpose: Mapped[str] = mapped_column(String(30))
    phone: Mapped[str] = mapped_column(String(15))
    subject_id: Mapped[str | None] = mapped_column(String(50))
    # Dữ liệu chờ xác nhận, mã hóa AES-GCM (SR06); xóa khi thử thách kết thúc.
    payload_enc: Mapped[bytes | None] = mapped_column(LargeBinary(None))
    otp_hash: Mapped[str] = mapped_column(Hash64())
    expires_at: Mapped[datetime] = mapped_column(DATETIMEOFFSET)
    failed_attempts: Mapped[int] = mapped_column(SmallInteger, default=0)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DATETIMEOFFSET)
    consumed_at: Mapped[datetime | None] = mapped_column(DATETIMEOFFSET)


class ApplicationDocument(Base):
    __tablename__ = "application_documents"
    __table_args__ = (
        CheckConstraint(
            "doc_type IN ('ID_FRONT','ID_BACK','INCOME_PROOF','UTILITY_BILL')",
            name="ck_application_documents_type",
        ),
        CheckConstraint(
            "review_verdict IN ('PASS','FAIL')", name="ck_application_documents_verdict"
        ),
        Index("ix_application_documents_application", "application_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("loan_applications.id"))
    doc_type: Mapped[str] = mapped_column(String(20))
    storage_path: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(50))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(Hash64())
    uploaded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    uploaded_at: Mapped[datetime] = mapped_column(DATETIMEOFFSET)
    # UC13 2a: file cũ cùng loại được đánh dấu thay thế, không xóa.
    replaced_at: Mapped[datetime | None] = mapped_column(DATETIMEOFFSET)
    # UC14 bước 4: NV tiếp nhận đánh dấu từng giấy tờ Đạt/Không đạt.
    review_verdict: Mapped[str | None] = mapped_column(String(4))
    review_note: Mapped[str | None] = mapped_column(NVARCHAR(200))
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("employees.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DATETIMEOFFSET)


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
    detail: Mapped[str | None] = mapped_column(NVARCHAR(500))
    prev_hash: Mapped[str] = mapped_column(Hash64())
    hash: Mapped[str] = mapped_column(Hash64())
