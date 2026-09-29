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
    UniqueConstraint,
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


def Rate() -> DECIMAL[Decimal]:  # noqa: N802 - lãi suất năm dạng thập phân (0.2400)
    return DECIMAL(5, 4)


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
        # Bảng có trigger (BR07): SQL Server không cho OUTPUT không kèm INTO trên bảng có trigger.
        {"implicit_returning": False},
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
    # Chốt khi chấm điểm (UC18): lãi suất theo hạng lấy từ đúng phiên bản chính sách này.
    annual_rate: Mapped[Decimal | None] = mapped_column(Rate())
    policy_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("approval_policies.id"))
    cic_missing: Mapped[bool] = mapped_column(Boolean, default=False)  # Thiếu dữ liệu CIC
    fraud_suspected: Mapped[bool] = mapped_column(Boolean, default=False)  # ADR 0002
    # Người thẩm định (UC22 bước 1) và số lượt phê duyệt chốt theo hạn mức đề xuất (bước 6).
    appraised_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("employees.id"))
    required_approvals: Mapped[int | None] = mapped_column(SmallInteger)
    # Hạn mức, kỳ hạn theo tờ trình được duyệt (UC23 bước 6): số tiền sẽ giải ngân.
    approved_amount: Mapped[Decimal | None] = mapped_column(Money())
    approved_term: Mapped[int | None] = mapped_column(SmallInteger)

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


class ScoringModelVersion(Base):
    """Phiên bản mô hình chấm điểm đã đăng ký, kèm checksum file (SR13, UC21)."""

    __tablename__ = "scoring_models"

    id: Mapped[uuid.UUID] = mapped_column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4)
    version: Mapped[str] = mapped_column(String(20), unique=True)
    file_name: Mapped[str] = mapped_column(String(100))
    checksum: Mapped[str] = mapped_column(Hash64())
    is_active: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DATETIMEOFFSET)


class ApprovalPolicy(Base):
    """Chính sách phê duyệt có phiên bản; bản cũ không bị ghi đè."""

    __tablename__ = "approval_policies"

    id: Mapped[uuid.UUID] = mapped_column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4)
    version: Mapped[int] = mapped_column(Integer, unique=True)
    rate_grade_a: Mapped[Decimal] = mapped_column(Rate())
    rate_grade_b: Mapped[Decimal] = mapped_column(Rate())
    rate_grade_c: Mapped[Decimal] = mapped_column(Rate())
    prepayment_fee_rate: Mapped[Decimal] = mapped_column(Rate())
    is_active: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DATETIMEOFFSET)

    def rate_for(self, grade: str) -> Decimal:
        """Lãi suất theo hạng (ADR 0001); hạng D bị từ chối nên không có lãi suất."""
        return {"A": self.rate_grade_a, "B": self.rate_grade_b, "C": self.rate_grade_c}[grade]

    @property
    def ceiling_rate(self) -> Decimal:
        """Lãi suất trần: lãi suất của hạng rủi ro nhất chưa bị từ chối (hạng C)."""
        return self.rate_grade_c


class CicReportRecord(Base):
    """Báo cáo CIC gắn với Hồ sơ vay (UC19); không chứa số CCCD."""

    __tablename__ = "cic_reports"
    __table_args__ = (
        CheckConstraint("highest_debt_group BETWEEN 0 AND 5", name="ck_cic_reports_debt_group"),
        Index("ix_cic_reports_application", "application_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("loan_applications.id"))
    highest_debt_group: Mapped[int] = mapped_column(SmallInteger)
    total_outstanding: Mapped[Decimal] = mapped_column(Money())
    lender_count: Mapped[int] = mapped_column(SmallInteger)
    monthly_obligation: Mapped[Decimal] = mapped_column(Money())
    utility_late_payments: Mapped[int | None] = mapped_column(SmallInteger)
    # Thời điểm CIC trả kết quả; báo cáo dùng lại (UC19 1a) giữ thời điểm của lần tra cứu gốc.
    queried_at: Mapped[datetime] = mapped_column(DATETIMEOFFSET)


class CreditScoreRecord(Base):
    """Kết quả chấm điểm (UC18); một Hồ sơ vay có thể được chấm lại, bản mới nhất có hiệu lực."""

    __tablename__ = "credit_scores"
    __table_args__ = (
        CheckConstraint("score BETWEEN 0 AND 1000", name="ck_credit_scores_score"),
        CheckConstraint("grade IN ('A','B','C','D')", name="ck_credit_scores_grade"),
        CheckConstraint("ISJSON(factors_json) = 1", name="ck_credit_scores_factors_json"),
        CheckConstraint(
            "knock_out_reason IS NOT NULL"
            " OR (score IS NOT NULL AND grade IS NOT NULL AND model_version IS NOT NULL)",
            name="ck_credit_scores_result",
        ),
        Index("ix_credit_scores_application", "application_id", "scored_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("loan_applications.id"))
    score: Mapped[int | None] = mapped_column(SmallInteger)
    grade: Mapped[str | None] = mapped_column(CHAR(1))
    knock_out_reason: Mapped[str | None] = mapped_column(NVARCHAR(100))
    dti: Mapped[Decimal] = mapped_column(DECIMAL(9, 4))  # theo lãi suất trần (ADR 0001)
    # Điểm từng yếu tố so với điểm tối đa (FR04.4); rỗng khi bị loại trừ.
    factors_json: Mapped[str] = mapped_column(NVARCHAR(None))
    model_version: Mapped[str | None] = mapped_column(String(20))  # SR13
    scored_at: Mapped[datetime] = mapped_column(DATETIMEOFFSET)


class ApprovalPolicyTier(Base):
    """Số lượt phê duyệt theo khoảng hạn mức của một phiên bản chính sách (BR05)."""

    __tablename__ = "approval_policy_tiers"
    __table_args__ = (
        CheckConstraint(
            "required_approvals >= 1", name="ck_approval_policy_tiers_required_approvals"
        ),
        CheckConstraint("min_amount <= max_amount", name="ck_approval_policy_tiers_range"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4)
    policy_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("approval_policies.id"))
    min_amount: Mapped[Decimal] = mapped_column(Money())
    max_amount: Mapped[Decimal] = mapped_column(Money())
    required_approvals: Mapped[int] = mapped_column(SmallInteger)


class AppraisalReport(Base):
    """Tờ trình thẩm định (UC22); bị Trả về thì lập tờ trình mới, bản mới nhất có hiệu lực."""

    __tablename__ = "appraisal_reports"
    __table_args__ = (
        CheckConstraint(
            "recommendation IN ('APPROVE','REJECT')", name="ck_appraisal_reports_recommendation"
        ),
        CheckConstraint(
            "recommendation = 'REJECT'"
            " OR (proposed_amount IS NOT NULL AND proposed_term IS NOT NULL AND dti IS NOT NULL)",
            name="ck_appraisal_reports_proposal",
        ),
        Index("ix_appraisal_reports_application", "application_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4)
    # Thứ tự các tờ trình của một hồ sơ vay (không dựa vào thời điểm); seq lớn nhất có hiệu lực.
    seq: Mapped[int] = mapped_column(BigInteger, Identity(start=1, increment=1))
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("loan_applications.id"))
    appraiser_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("employees.id"))
    recommendation: Mapped[str] = mapped_column(String(10))
    proposed_amount: Mapped[Decimal | None] = mapped_column(Money())
    proposed_term: Mapped[int | None] = mapped_column(SmallInteger)
    dti: Mapped[Decimal | None] = mapped_column(DECIMAL(9, 4))  # theo lãi suất của Hạng thật
    fraud_suspected: Mapped[bool] = mapped_column(Boolean, default=False)  # UC22 3a
    comment: Mapped[str] = mapped_column(NVARCHAR(1000))
    created_at: Mapped[datetime] = mapped_column(DATETIMEOFFSET)


class ApprovalDecision(Base):
    """Quyết định phê duyệt (UC23, UC24) trên một tờ trình; bảng chỉ ghi thêm (4.1.2e)."""

    __tablename__ = "approval_decisions"
    __table_args__ = (
        CheckConstraint(
            "result IN ('APPROVE','REJECT','RETURN')", name="ck_approval_decisions_result"
        ),
        CheckConstraint(
            "reason_group IN ('FINANCIAL_CAPACITY','CREDIT_HISTORY','FRAUD_SUSPECTED','OTHER')",
            name="ck_approval_decisions_reason_group",
        ),
        CheckConstraint(
            "result <> 'REJECT' OR reason_group IS NOT NULL",
            name="ck_approval_decisions_reject_reason",
        ),
        CheckConstraint(
            "(snapshot_hash IS NULL AND key_version IS NULL)"
            " OR (snapshot_hash IS NOT NULL AND key_version IS NOT NULL AND result = 'APPROVE')",
            name="ck_approval_decisions_snapshot",
        ),
        UniqueConstraint(
            "appraisal_report_id", "approver_id", name="uq_approval_decisions_report_approver"
        ),
        Index("ix_approval_decisions_application", "application_id", "decided_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("loan_applications.id"))
    appraisal_report_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("appraisal_reports.id"))
    approver_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("employees.id"))
    result: Mapped[str] = mapped_column(String(10))
    reason_group: Mapped[str | None] = mapped_column(String(20))  # UC24 bước 2
    comment: Mapped[str | None] = mapped_column(NVARCHAR(1000))
    # HMAC-SHA256 của snapshot (SR08) và phiên bản khóa đã dùng (4.2.5), trên quyết định làm hồ
    # sơ vay được duyệt.
    snapshot_hash: Mapped[str | None] = mapped_column(Hash64())
    key_version: Mapped[int | None] = mapped_column(SmallInteger)
    decided_at: Mapped[datetime] = mapped_column(DATETIMEOFFSET)


class Loan(Base):
    """Khoản vay sinh ra khi giải ngân thành công (UC25), cùng Lịch trả nợ (BR08)."""

    __tablename__ = "loans"
    __table_args__ = (
        CheckConstraint("principal > 0", name="ck_loans_principal"),
        CheckConstraint("outstanding_principal >= 0", name="ck_loans_outstanding"),
        CheckConstraint(
            "status IN ('ACTIVE','OVERDUE','BAD_DEBT','SETTLED')", name="ck_loans_status"
        ),
        CheckConstraint("debt_group BETWEEN 1 AND 5", name="ck_loans_debt_group"),
        Index("ix_loans_customer", "customer_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("loan_applications.id"), unique=True
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"))
    principal: Mapped[Decimal] = mapped_column(Money())
    annual_rate: Mapped[Decimal] = mapped_column(Rate())
    term_months: Mapped[int] = mapped_column(SmallInteger)
    monthly_payment: Mapped[Decimal] = mapped_column(Money())
    outstanding_principal: Mapped[Decimal] = mapped_column(Money())
    status: Mapped[str] = mapped_column(String(10))
    debt_group: Mapped[int] = mapped_column(SmallInteger)  # BR09, tách khỏi status
    disbursed_at: Mapped[datetime] = mapped_column(DATETIMEOFFSET)
    settled_at: Mapped[datetime | None] = mapped_column(DATETIMEOFFSET)


class Installment(Base):
    """Kỳ trả nợ (UC26 bước 4)."""

    __tablename__ = "installments"
    __table_args__ = (
        CheckConstraint(
            "status IN ('UPCOMING','DUE','PARTIAL','PAID','OVERDUE','CANCELLED')",
            name="ck_installments_status",
        ),
        UniqueConstraint("loan_id", "number", name="uq_installments_loan_number"),
        Index("ix_installments_due_date", "due_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4)
    loan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("loans.id"))
    number: Mapped[int] = mapped_column(SmallInteger)
    due_date: Mapped[date] = mapped_column(Date)
    principal_due: Mapped[Decimal] = mapped_column(Money())
    interest_due: Mapped[Decimal] = mapped_column(Money())
    penalty: Mapped[Decimal] = mapped_column(Money(), default=Decimal(0))
    paid_amount: Mapped[Decimal] = mapped_column(Money(), default=Decimal(0))
    status: Mapped[str] = mapped_column(String(10))


class LoanContract(Base):
    """Hợp đồng tín dụng PDF kèm mã băm SHA-256 (UC26 bước 5)."""

    __tablename__ = "loan_contracts"

    loan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("loans.id"), primary_key=True)
    content: Mapped[bytes] = mapped_column(LargeBinary(None))
    sha256: Mapped[str] = mapped_column(Hash64())
    created_at: Mapped[datetime] = mapped_column(DATETIMEOFFSET)


class Disbursement(Base):
    """Một lệnh chuyển tiền vay (UC25); thất bại thì có thể có lệnh sau."""

    __tablename__ = "disbursements"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING','SUCCESS','FAILED')", name="ck_disbursements_status"
        ),
        Index(
            "ux_disbursements_open",
            "application_id",
            unique=True,
            mssql_where=text("status IN ('PENDING','SUCCESS')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("loan_applications.id"))
    loan_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("loans.id"))
    amount: Mapped[Decimal] = mapped_column(Money())
    receiving_account_enc: Mapped[bytes] = mapped_column(Encrypted())  # SR06
    transaction_ref: Mapped[str | None] = mapped_column(String(50))
    # Gửi lại cùng khóa thì cổng thanh toán không chuyển tiền lần hai (UC25 7a).
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(10))
    failure_reason: Mapped[str | None] = mapped_column(NVARCHAR(200))
    performed_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("employees.id"))  # SoD
    created_at: Mapped[datetime] = mapped_column(DATETIMEOFFSET)
    completed_at: Mapped[datetime | None] = mapped_column(DATETIMEOFFSET)
