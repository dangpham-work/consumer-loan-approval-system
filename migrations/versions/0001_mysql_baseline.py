"""Lược đồ gốc trên MySQL (ADR 0004), gộp 12 migration trước đó

Revision ID: 0001
Revises:
Create Date: 2026-10-01
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TRIGGER = "trg_loan_applications_approved_immutable"
# Các trường của hồ sơ vay đã duyệt mà BR07 không cho đổi.
IMMUTABLE_COLUMNS = (
    "code", "customer_id", "requested_amount", "term_months", "purpose", "receiving_account_enc",
    "annual_rate", "policy_id", "approved_amount", "approved_term",
)

ROLES = {
    "CUSTOMER": "Khách hàng",
    "CREDIT_OFFICER": "Nhân viên tín dụng",
    "APPRAISER": "Chuyên viên thẩm định",
    "APPROVER": "Quản lý phê duyệt",
    "DISBURSER": "Nhân viên giải ngân",
    "ADMIN": "Quản trị viên",
    "AUDITOR": "Kiểm soát viên",
}

# Ma trận phân quyền mục 2.2.1c. Ô "O" (chỉ đối tượng của mình) được cấp quyền, phạm vi sở hữu
# kiểm tra ở tầng nghiệp vụ (SR04). Ô "M" (xem dữ liệu đã che) không được cấp CUSTOMER_VIEW_PII.
PERMISSIONS: dict[str, tuple[str, list[str]]] = {
    "APPLICATION_CREATE": ("Tạo và nộp hồ sơ vay", ["CUSTOMER", "CREDIT_OFFICER"]),
    "APPLICATION_VIEW": (
        "Xem hồ sơ vay",
        ["CUSTOMER", "CREDIT_OFFICER", "APPRAISER", "APPROVER", "DISBURSER"],
    ),
    "APPLICATION_VERIFY": ("Xác nhận hồ sơ vay hợp lệ", ["CREDIT_OFFICER"]),
    "APPLICATION_REQUEST_INFO": ("Yêu cầu bổ sung hồ sơ vay", ["CREDIT_OFFICER"]),
    "CUSTOMER_VIEW": ("Tra cứu thông tin khách hàng", ["CREDIT_OFFICER", "APPRAISER"]),
    "CUSTOMER_VIEW_PII": ("Xem CCCD, thu nhập đầy đủ", ["CUSTOMER", "APPRAISER"]),
    "CREDIT_SCORE_VIEW": ("Xem điểm tín dụng", ["APPRAISER", "APPROVER"]),
    "APPRAISAL_SUBMIT": ("Nộp tờ trình thẩm định", ["APPRAISER"]),
    "LOAN_APPROVE": ("Phê duyệt hồ sơ vay", ["APPROVER"]),
    "LOAN_REJECT": ("Từ chối hoặc trả về hồ sơ vay", ["APPROVER"]),
    "DISBURSE": ("Giải ngân", ["DISBURSER"]),
    "PAYMENT_RECORD": ("Ghi nhận thanh toán", ["CUSTOMER", "CREDIT_OFFICER"]),
    "LOAN_SETTLE": ("Tất toán khoản vay", ["CUSTOMER", "CREDIT_OFFICER"]),
    "REPORT_VIEW": ("Xem báo cáo thống kê", ["APPROVER"]),
    "USER_MANAGE": ("Quản lý tài khoản nhân viên", ["ADMIN"]),
    "ROLE_MANAGE": ("Quản lý vai trò và quyền", ["ADMIN"]),
    "POLICY_CONFIGURE": ("Cấu hình chính sách phê duyệt", ["ADMIN"]),
    "MODEL_UPDATE": ("Cập nhật mô hình chấm điểm", ["ADMIN"]),
    "AUDIT_VIEW": ("Tra cứu nhật ký kiểm toán", ["AUDITOR"]),
    "AUDIT_VERIFY": ("Kiểm tra toàn vẹn nhật ký", ["AUDITOR"]),
    "APPLICATION_LOCK_RESOLVE": ("Hủy hồ sơ vay bị khóa sau điều tra", ["AUDITOR"]),
}

# Thẻ điểm đi kèm mã nguồn. Checksum ghi cứng ở đây, không tính từ file lúc chạy migration: nếu
# file đã bị sửa trước đó thì checksum tính lại cũng sẽ "khớp" (SR13).
SCORECARD_VERSION = "SC-2026.1"
SCORECARD_FILE = "scorecard-2026.1.json"
SCORECARD_SHA256 = "6ad4d469fa7a5e7ce092c6fd8a8e7f0c568a6ddad634dcc950c17e391d8033fa"

# Bộ đếm một dòng thay cho SEQUENCE: số thứ tự mã hồ sơ vay, và dòng khóa của chuỗi băm nhật ký.
COUNTERS = ("loan_application_code", "audit_chain")


def create_immutability_trigger() -> str:
    """BR07: hồ sơ vay đã duyệt không được đổi các trường quan trọng, kể cả sửa thẳng trong CSDL
    (4.1.2e). Chỉ trạng thái được đổi tiếp (giải ngân, khóa, hủy). `<=>` so sánh được cả NULL."""
    unchanged = " AND ".join(f"NEW.{column} <=> OLD.{column}" for column in IMMUTABLE_COLUMNS)
    return (
        f"CREATE TRIGGER {TRIGGER} BEFORE UPDATE ON loan_applications FOR EACH ROW "
        f"BEGIN "
        f"IF OLD.status IN ('APPROVED','DISBURSED','LOCKED') AND NOT ({unchanged}) THEN "
        f"SIGNAL SQLSTATE '45000' "
        f"SET MESSAGE_TEXT = 'BR07: approved loan application is immutable'; "
        f"END IF; "
        f"END"
    )


def upgrade() -> None:
    op.create_table('approval_policies',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('rate_grade_a', sa.DECIMAL(precision=5, scale=4), nullable=False),
    sa.Column('rate_grade_b', sa.DECIMAL(precision=5, scale=4), nullable=False),
    sa.Column('rate_grade_c', sa.DECIMAL(precision=5, scale=4), nullable=False),
    sa.Column('prepayment_fee_rate', sa.DECIMAL(precision=5, scale=4), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.Column('active_marker', sa.SmallInteger(), sa.Computed('CASE WHEN is_active THEN 1 END', persisted=False), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('active_marker'),
    sa.UniqueConstraint('version')
    )
    op.create_table('counters',
    sa.Column('name', sa.String(length=40), nullable=False),
    sa.Column('value', sa.BigInteger(), nullable=False),
    sa.PrimaryKeyConstraint('name')
    )
    op.create_table('customers',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('full_name', sa.String(length=100), nullable=False),
    sa.Column('dob', sa.Date(), nullable=False),
    sa.Column('phone', sa.String(length=15), nullable=False),
    sa.Column('email', sa.String(length=100), nullable=False),
    sa.Column('consent_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.Column('consent_version', sa.String(length=10), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.Column('national_id_enc', sa.LargeBinary(length=500), nullable=True),
    sa.Column('national_id_hash', sa.CHAR(length=64, collation='ascii_bin'), nullable=True),
    sa.Column('occupation', sa.String(length=50), nullable=True),
    sa.Column('employer', sa.String(length=100), nullable=True),
    sa.Column('employment_years', sa.SmallInteger(), nullable=True),
    sa.Column('monthly_income_enc', sa.LargeBinary(length=500), nullable=True),
    sa.Column('housing_type', sa.String(length=10), nullable=True),
    sa.Column('address', sa.String(length=255), nullable=True),
    sa.CheckConstraint("housing_type IN ('OWN','FAMILY','RENT')", name='ck_customers_housing_type'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('email'),
    sa.UniqueConstraint('phone')
    )
    op.create_index('ux_customers_national_id_hash', 'customers', ['national_id_hash'], unique=True)
    op.create_table('employees',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('full_name', sa.String(length=100), nullable=False),
    sa.Column('email', sa.String(length=100), nullable=False),
    sa.Column('branch', sa.String(length=50), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('email')
    )
    op.create_table('permissions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('code', sa.String(length=50), nullable=False),
    sa.Column('description', sa.String(length=200), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code')
    )
    op.create_table('registration_requests',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('full_name', sa.String(length=100), nullable=False),
    sa.Column('dob', sa.Date(), nullable=False),
    sa.Column('phone', sa.String(length=15), nullable=False),
    sa.Column('email', sa.String(length=100), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('otp_hash', sa.CHAR(length=64, collation='ascii_bin'), nullable=False),
    sa.Column('otp_expires_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.Column('failed_attempts', sa.SmallInteger(), nullable=False),
    sa.Column('consent_version', sa.String(length=10), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_registration_requests_phone'), 'registration_requests', ['phone'], unique=False)
    op.create_table('roles',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('code', sa.String(length=30), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code')
    )
    op.create_table('scoring_models',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('version', sa.String(length=20), nullable=False),
    sa.Column('file_name', sa.String(length=100), nullable=False),
    sa.Column('checksum', sa.CHAR(length=64, collation='ascii_bin'), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.Column('active_marker', sa.SmallInteger(), sa.Computed('CASE WHEN is_active THEN 1 END', persisted=False), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('active_marker'),
    sa.UniqueConstraint('version')
    )
    op.create_table('approval_policy_tiers',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('policy_id', sa.Uuid(), nullable=False),
    sa.Column('min_amount', sa.DECIMAL(precision=15, scale=0), nullable=False),
    sa.Column('max_amount', sa.DECIMAL(precision=15, scale=0), nullable=False),
    sa.Column('required_approvals', sa.SmallInteger(), nullable=False),
    sa.CheckConstraint('min_amount <= max_amount', name='ck_approval_policy_tiers_range'),
    sa.CheckConstraint('required_approvals >= 1', name='ck_approval_policy_tiers_required_approvals'),
    sa.ForeignKeyConstraint(['policy_id'], ['approval_policies.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('loan_applications',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('code', sa.String(length=20), nullable=True),
    sa.Column('customer_id', sa.Uuid(), nullable=False),
    sa.Column('requested_amount', sa.DECIMAL(precision=15, scale=0), nullable=False),
    sa.Column('term_months', sa.SmallInteger(), nullable=False),
    sa.Column('purpose', sa.String(length=20), nullable=False),
    sa.Column('existing_monthly_debt', sa.DECIMAL(precision=15, scale=0), nullable=True),
    sa.Column('receiving_account_enc', sa.LargeBinary(length=500), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('consent_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('consent_version', sa.String(length=10), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.Column('submitted_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('received_by', sa.Uuid(), nullable=True),
    sa.Column('need_info_message', sa.String(length=500), nullable=True),
    sa.Column('need_info_items', sa.String(length=300), nullable=True),
    sa.Column('need_info_deadline', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('cancel_reason', sa.String(length=200), nullable=True),
    sa.Column('annual_rate', sa.DECIMAL(precision=5, scale=4), nullable=True),
    sa.Column('policy_id', sa.Uuid(), nullable=True),
    sa.Column('cic_missing', sa.Boolean(), nullable=False),
    sa.Column('fraud_suspected', sa.Boolean(), nullable=False),
    sa.Column('appraised_by', sa.Uuid(), nullable=True),
    sa.Column('required_approvals', sa.SmallInteger(), nullable=True),
    sa.Column('approved_amount', sa.DECIMAL(precision=15, scale=0), nullable=True),
    sa.Column('approved_term', sa.SmallInteger(), nullable=True),
    sa.CheckConstraint("status IN ('DRAFT','SUBMITTED','NEED_INFO','VERIFIED','APPRAISING','PENDING_APPROVAL','APPROVED','REJECTED','CANCELLED','DISBURSED','LOCKED')", name='ck_loan_applications_status'),
    sa.CheckConstraint('existing_monthly_debt >= 0', name='ck_loan_applications_existing_debt'),
    sa.CheckConstraint('requested_amount BETWEEN 5000000 AND 100000000', name='ck_loan_applications_amount'),
    sa.CheckConstraint('term_months BETWEEN 6 AND 36', name='ck_loan_applications_term'),
    sa.ForeignKeyConstraint(['appraised_by'], ['employees.id'], ),
    sa.ForeignKeyConstraint(['created_by'], ['employees.id'], ),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ),
    sa.ForeignKeyConstraint(['policy_id'], ['approval_policies.id'], ),
    sa.ForeignKeyConstraint(['received_by'], ['employees.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_loan_applications_customer', 'loan_applications', ['customer_id'], unique=False)
    op.create_index('ix_loan_applications_status_submitted', 'loan_applications', ['status', 'submitted_at'], unique=False)
    op.create_index('ux_loan_applications_code', 'loan_applications', ['code'], unique=True)
    op.create_table('role_permissions',
    sa.Column('role_id', sa.Uuid(), nullable=False),
    sa.Column('permission_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['permission_id'], ['permissions.id'], ),
    sa.ForeignKeyConstraint(['role_id'], ['roles.id'], ),
    sa.PrimaryKeyConstraint('role_id', 'permission_id')
    )
    op.create_table('users',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('username', sa.String(length=50), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('failed_attempts', sa.SmallInteger(), nullable=False),
    sa.Column('locked_until', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('customer_id', sa.Uuid(), nullable=True),
    sa.Column('employee_id', sa.Uuid(), nullable=True),
    sa.Column('last_login_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.Column('must_change_password', sa.Boolean(), nullable=False),
    sa.Column('totp_secret_enc', sa.LargeBinary(length=500), nullable=True),
    sa.Column('totp_last_step', sa.BigInteger(), nullable=True),
    sa.CheckConstraint("status IN ('PENDING','ACTIVE','LOCKED','DISABLED')", name='ck_users_status'),
    sa.CheckConstraint('(employee_id IS NULL AND customer_id IS NOT NULL) OR (employee_id IS NOT NULL AND customer_id IS NULL)', name='ck_users_owner'),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ),
    sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('username')
    )
    op.create_table('application_documents',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('application_id', sa.Uuid(), nullable=False),
    sa.Column('doc_type', sa.String(length=20), nullable=False),
    sa.Column('storage_path', sa.String(length=255), nullable=False),
    sa.Column('content_type', sa.String(length=50), nullable=False),
    sa.Column('size_bytes', sa.Integer(), nullable=False),
    sa.Column('sha256', sa.CHAR(length=64, collation='ascii_bin'), nullable=False),
    sa.Column('uploaded_by', sa.Uuid(), nullable=False),
    sa.Column('uploaded_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.Column('replaced_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('review_verdict', sa.String(length=4), nullable=True),
    sa.Column('review_note', sa.String(length=200), nullable=True),
    sa.Column('reviewed_by', sa.Uuid(), nullable=True),
    sa.Column('reviewed_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.CheckConstraint("doc_type IN ('ID_FRONT','ID_BACK','INCOME_PROOF','UTILITY_BILL')", name='ck_application_documents_type'),
    sa.CheckConstraint("review_verdict IN ('PASS','FAIL')", name='ck_application_documents_verdict'),
    sa.ForeignKeyConstraint(['application_id'], ['loan_applications.id'], ),
    sa.ForeignKeyConstraint(['reviewed_by'], ['employees.id'], ),
    sa.ForeignKeyConstraint(['uploaded_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_application_documents_application', 'application_documents', ['application_id'], unique=False)
    op.create_table('application_status_history',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('application_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('actor_id', sa.Uuid(), nullable=True),
    sa.Column('reason', sa.String(length=500), nullable=True),
    sa.Column('changed_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['application_id'], ['loan_applications.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_application_status_history_application', 'application_status_history', ['application_id', 'changed_at'], unique=False)
    op.create_table('appraisal_reports',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('seq', sa.BigInteger(), nullable=False),
    sa.Column('application_id', sa.Uuid(), nullable=False),
    sa.Column('appraiser_id', sa.Uuid(), nullable=False),
    sa.Column('recommendation', sa.String(length=10), nullable=False),
    sa.Column('proposed_amount', sa.DECIMAL(precision=15, scale=0), nullable=True),
    sa.Column('proposed_term', sa.SmallInteger(), nullable=True),
    sa.Column('dti', sa.DECIMAL(precision=9, scale=4), nullable=True),
    sa.Column('fraud_suspected', sa.Boolean(), nullable=False),
    sa.Column('comment', sa.String(length=1000), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.CheckConstraint("recommendation = 'REJECT' OR (proposed_amount IS NOT NULL AND proposed_term IS NOT NULL AND dti IS NOT NULL)", name='ck_appraisal_reports_proposal'),
    sa.CheckConstraint("recommendation IN ('APPROVE','REJECT')", name='ck_appraisal_reports_recommendation'),
    sa.ForeignKeyConstraint(['application_id'], ['loan_applications.id'], ),
    sa.ForeignKeyConstraint(['appraiser_id'], ['employees.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('seq')
    )
    op.create_index('ix_appraisal_reports_application', 'appraisal_reports', ['application_id', 'created_at'], unique=False)
    op.create_table('audit_logs',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('seq', sa.BigInteger(), nullable=False),
    sa.Column('actor_id', sa.Uuid(), nullable=True),
    sa.Column('action', sa.String(length=50), nullable=False),
    sa.Column('target_type', sa.String(length=30), nullable=True),
    sa.Column('target_id', sa.String(length=50), nullable=True),
    sa.Column('ip_address', sa.String(length=45), nullable=True),
    sa.Column('level', sa.String(length=10), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.Column('detail', sa.String(length=500), nullable=True),
    sa.Column('prev_hash', sa.CHAR(length=64, collation='ascii_bin'), nullable=False),
    sa.Column('hash', sa.CHAR(length=64, collation='ascii_bin'), nullable=False),
    sa.CheckConstraint("level IN ('INFO','WARNING','CRITICAL')", name='ck_audit_logs_level'),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('seq')
    )
    op.create_index('ix_audit_logs_actor_created', 'audit_logs', ['actor_id', 'created_at'], unique=False)
    op.create_index('ix_audit_logs_target', 'audit_logs', ['target_type', 'target_id'], unique=False)
    op.create_table('cic_reports',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('application_id', sa.Uuid(), nullable=False),
    sa.Column('highest_debt_group', sa.SmallInteger(), nullable=False),
    sa.Column('total_outstanding', sa.DECIMAL(precision=15, scale=0), nullable=False),
    sa.Column('lender_count', sa.SmallInteger(), nullable=False),
    sa.Column('monthly_obligation', sa.DECIMAL(precision=15, scale=0), nullable=False),
    sa.Column('utility_late_payments', sa.SmallInteger(), nullable=True),
    sa.Column('queried_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.CheckConstraint('highest_debt_group BETWEEN 0 AND 5', name='ck_cic_reports_debt_group'),
    sa.ForeignKeyConstraint(['application_id'], ['loan_applications.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_cic_reports_application', 'cic_reports', ['application_id'], unique=False)
    op.create_table('credit_scores',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('application_id', sa.Uuid(), nullable=False),
    sa.Column('score', sa.SmallInteger(), nullable=True),
    sa.Column('grade', sa.CHAR(length=1), nullable=True),
    sa.Column('knock_out_reason', sa.String(length=100), nullable=True),
    sa.Column('dti', sa.DECIMAL(precision=9, scale=4), nullable=False),
    sa.Column('factors_json', sa.Text(), nullable=False),
    sa.Column('model_version', sa.String(length=20), nullable=True),
    sa.Column('scored_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.CheckConstraint("grade IN ('A','B','C','D')", name='ck_credit_scores_grade'),
    sa.CheckConstraint('JSON_VALID(factors_json)', name='ck_credit_scores_factors_json'),
    sa.CheckConstraint('knock_out_reason IS NOT NULL OR (score IS NOT NULL AND grade IS NOT NULL AND model_version IS NOT NULL)', name='ck_credit_scores_result'),
    sa.CheckConstraint('score BETWEEN 0 AND 1000', name='ck_credit_scores_score'),
    sa.ForeignKeyConstraint(['application_id'], ['loan_applications.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_credit_scores_application', 'credit_scores', ['application_id', 'scored_at'], unique=False)
    op.create_table('loans',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('application_id', sa.Uuid(), nullable=False),
    sa.Column('customer_id', sa.Uuid(), nullable=False),
    sa.Column('principal', sa.DECIMAL(precision=15, scale=0), nullable=False),
    sa.Column('annual_rate', sa.DECIMAL(precision=5, scale=4), nullable=False),
    sa.Column('term_months', sa.SmallInteger(), nullable=False),
    sa.Column('monthly_payment', sa.DECIMAL(precision=15, scale=0), nullable=False),
    sa.Column('outstanding_principal', sa.DECIMAL(precision=15, scale=0), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('debt_group', sa.SmallInteger(), nullable=False),
    sa.Column('disbursed_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.Column('settled_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.CheckConstraint("status IN ('ACTIVE','OVERDUE','BAD_DEBT','SETTLED')", name='ck_loans_status'),
    sa.CheckConstraint('debt_group BETWEEN 1 AND 5', name='ck_loans_debt_group'),
    sa.CheckConstraint('outstanding_principal >= 0', name='ck_loans_outstanding'),
    sa.CheckConstraint('principal > 0', name='ck_loans_principal'),
    sa.ForeignKeyConstraint(['application_id'], ['loan_applications.id'], ),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('application_id')
    )
    op.create_index('ix_loans_customer', 'loans', ['customer_id'], unique=False)
    op.create_table('notifications',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('recipient_user_id', sa.Uuid(), nullable=False),
    sa.Column('type', sa.String(length=30), nullable=False),
    sa.Column('content', sa.String(length=500), nullable=False),
    sa.Column('channel', sa.String(length=10), nullable=False),
    sa.Column('is_read', sa.Boolean(), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.CheckConstraint("channel IN ('IN_APP','SMS','EMAIL')", name='ck_notifications_channel'),
    sa.ForeignKeyConstraint(['recipient_user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_notifications_recipient', 'notifications', ['recipient_user_id', 'created_at'], unique=False)
    op.create_table('otp_challenges',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('purpose', sa.String(length=30), nullable=False),
    sa.Column('phone', sa.String(length=15), nullable=False),
    sa.Column('subject_id', sa.String(length=50), nullable=True),
    sa.Column('payload_enc', sa.LargeBinary(), nullable=True),
    sa.Column('otp_hash', sa.CHAR(length=64, collation='ascii_bin'), nullable=False),
    sa.Column('expires_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.Column('failed_attempts', sa.SmallInteger(), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.Column('consumed_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('sessions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('token_hash', sa.CHAR(length=64, collation='ascii_bin'), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.Column('last_seen_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.Column('revoked_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('stage', sa.String(length=10), nullable=False),
    sa.Column('otp_failed_attempts', sa.SmallInteger(), nullable=False),
    sa.CheckConstraint("stage IN ('SETUP','MFA','FULL')", name='ck_sessions_stage'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('token_hash')
    )
    op.create_table('user_roles',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('role_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['role_id'], ['roles.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('user_id', 'role_id')
    )
    op.create_table('approval_decisions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('application_id', sa.Uuid(), nullable=False),
    sa.Column('appraisal_report_id', sa.Uuid(), nullable=False),
    sa.Column('approver_id', sa.Uuid(), nullable=False),
    sa.Column('result', sa.String(length=10), nullable=False),
    sa.Column('reason_group', sa.String(length=20), nullable=True),
    sa.Column('comment', sa.String(length=1000), nullable=True),
    sa.Column('snapshot_hash', sa.CHAR(length=64, collation='ascii_bin'), nullable=True),
    sa.Column('key_version', sa.SmallInteger(), nullable=True),
    sa.Column('decided_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.CheckConstraint("(snapshot_hash IS NULL AND key_version IS NULL) OR (snapshot_hash IS NOT NULL AND key_version IS NOT NULL AND result = 'APPROVE')", name='ck_approval_decisions_snapshot'),
    sa.CheckConstraint("reason_group IN ('FINANCIAL_CAPACITY','CREDIT_HISTORY','FRAUD_SUSPECTED','OTHER')", name='ck_approval_decisions_reason_group'),
    sa.CheckConstraint("result <> 'REJECT' OR reason_group IS NOT NULL", name='ck_approval_decisions_reject_reason'),
    sa.CheckConstraint("result IN ('APPROVE','REJECT','RETURN')", name='ck_approval_decisions_result'),
    sa.ForeignKeyConstraint(['application_id'], ['loan_applications.id'], ),
    sa.ForeignKeyConstraint(['appraisal_report_id'], ['appraisal_reports.id'], ),
    sa.ForeignKeyConstraint(['approver_id'], ['employees.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('appraisal_report_id', 'approver_id', name='uq_approval_decisions_report_approver')
    )
    op.create_index('ix_approval_decisions_application', 'approval_decisions', ['application_id', 'decided_at'], unique=False)
    op.create_table('disbursements',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('application_id', sa.Uuid(), nullable=False),
    sa.Column('open_application_id', sa.Uuid(), sa.Computed("CASE WHEN status IN ('PENDING','SUCCESS') THEN application_id END", persisted=False), nullable=True),
    sa.Column('loan_id', sa.Uuid(), nullable=True),
    sa.Column('amount', sa.DECIMAL(precision=15, scale=0), nullable=False),
    sa.Column('receiving_account_enc', sa.LargeBinary(length=500), nullable=False),
    sa.Column('transaction_ref', sa.String(length=50), nullable=True),
    sa.Column('idempotency_key', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('failure_reason', sa.String(length=200), nullable=True),
    sa.Column('performed_by', sa.Uuid(), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.Column('completed_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.CheckConstraint("status IN ('PENDING','SUCCESS','FAILED')", name='ck_disbursements_status'),
    sa.ForeignKeyConstraint(['application_id'], ['loan_applications.id'], ),
    sa.ForeignKeyConstraint(['loan_id'], ['loans.id'], ),
    sa.ForeignKeyConstraint(['performed_by'], ['employees.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('idempotency_key')
    )
    op.create_index('ux_disbursements_open', 'disbursements', ['open_application_id'], unique=True)
    op.create_table('installments',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('loan_id', sa.Uuid(), nullable=False),
    sa.Column('number', sa.SmallInteger(), nullable=False),
    sa.Column('due_date', sa.Date(), nullable=False),
    sa.Column('principal_due', sa.DECIMAL(precision=15, scale=0), nullable=False),
    sa.Column('interest_due', sa.DECIMAL(precision=15, scale=0), nullable=False),
    sa.Column('penalty', sa.DECIMAL(precision=15, scale=0), nullable=False),
    sa.Column('penalty_paid', sa.DECIMAL(precision=15, scale=0), nullable=False),
    sa.Column('paid_amount', sa.DECIMAL(precision=15, scale=0), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.CheckConstraint("status IN ('UPCOMING','DUE','PARTIAL','PAID','OVERDUE','CANCELLED')", name='ck_installments_status'),
    sa.CheckConstraint('penalty_paid BETWEEN 0 AND penalty', name='ck_installments_penalty_paid'),
    sa.ForeignKeyConstraint(['loan_id'], ['loans.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('loan_id', 'number', name='uq_installments_loan_number')
    )
    op.create_index('ix_installments_due_date', 'installments', ['due_date'], unique=False)
    op.create_table('loan_contracts',
    sa.Column('loan_id', sa.Uuid(), nullable=False),
    sa.Column('content', mysql.LONGBLOB(), nullable=False),
    sa.Column('sha256', sa.CHAR(length=64, collation='ascii_bin'), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.ForeignKeyConstraint(['loan_id'], ['loans.id'], ),
    sa.PrimaryKeyConstraint('loan_id')
    )
    op.create_table('payments',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('loan_id', sa.Uuid(), nullable=False),
    sa.Column('amount', sa.DECIMAL(precision=15, scale=0), nullable=False),
    sa.Column('channel', sa.String(length=10), nullable=False),
    sa.Column('external_ref', sa.String(length=50), nullable=False),
    sa.Column('paid_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.Column('recorded_by', sa.Uuid(), nullable=False),
    sa.CheckConstraint("channel IN ('ONLINE','COUNTER')", name='ck_payments_channel'),
    sa.CheckConstraint('amount > 0', name='ck_payments_amount'),
    sa.ForeignKeyConstraint(['loan_id'], ['loans.id'], ),
    sa.ForeignKeyConstraint(['recorded_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('external_ref')
    )
    op.create_index('ix_payments_loan', 'payments', ['loan_id'], unique=False)
    op.create_table('payment_allocations',
    sa.Column('payment_id', sa.Uuid(), nullable=False),
    sa.Column('installment_id', sa.Uuid(), nullable=False),
    sa.Column('component', sa.String(length=10), nullable=False),
    sa.Column('amount', sa.DECIMAL(precision=15, scale=0), nullable=False),
    sa.CheckConstraint("component IN ('PENALTY','INTEREST','PRINCIPAL','FEE')", name='ck_payment_allocations_component'),
    sa.CheckConstraint('amount > 0', name='ck_payment_allocations_amount'),
    sa.ForeignKeyConstraint(['installment_id'], ['installments.id'], ),
    sa.ForeignKeyConstraint(['payment_id'], ['payments.id'], ),
    sa.PrimaryKeyConstraint('payment_id', 'installment_id', 'component')
    )
    op.create_table('payment_reminders',
    sa.Column('installment_id', sa.Uuid(), nullable=False),
    sa.Column('kind', sa.String(length=12), nullable=False),
    sa.Column('sent_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.CheckConstraint("kind IN ('BEFORE_DUE','DUE','OVERDUE_1','OVERDUE_7','OVERDUE_15','OVERDUE_30')", name='ck_payment_reminders_kind'),
    sa.ForeignKeyConstraint(['installment_id'], ['installments.id'], ),
    sa.PrimaryKeyConstraint('installment_id', 'kind')
    )

    # SQLAlchemy chỉ sinh AUTO_INCREMENT cho cột khóa chính; seq là cột UNIQUE ngoài khóa chính.
    op.execute("ALTER TABLE appraisal_reports MODIFY seq BIGINT NOT NULL AUTO_INCREMENT")
    op.execute(create_immutability_trigger())

    seed()


def seed() -> None:
    """Dữ liệu gốc: ma trận RBAC, thẻ điểm, chính sách phê duyệt mặc định, bộ đếm."""
    roles = sa.table(
        "roles", sa.column("id", sa.Uuid), sa.column("code", sa.String), sa.column("name", sa.String)
    )
    permissions = sa.table(
        "permissions",
        sa.column("id", sa.Uuid),
        sa.column("code", sa.String),
        sa.column("description", sa.String),
    )
    role_permissions = sa.table(
        "role_permissions", sa.column("role_id", sa.Uuid), sa.column("permission_id", sa.Uuid)
    )
    role_ids = {code: uuid.uuid4() for code in ROLES}
    permission_ids = {code: uuid.uuid4() for code in PERMISSIONS}
    op.bulk_insert(
        roles, [{"id": role_ids[code], "code": code, "name": name} for code, name in ROLES.items()]
    )
    op.bulk_insert(
        permissions,
        [
            {"id": permission_ids[code], "code": code, "description": description}
            for code, (description, _) in PERMISSIONS.items()
        ],
    )
    op.bulk_insert(
        role_permissions,
        [
            {"role_id": role_ids[role], "permission_id": permission_ids[code]}
            for code, (_, granted_to) in PERMISSIONS.items()
            for role in granted_to
        ],
    )

    now = datetime.now(UTC).replace(tzinfo=None)  # DATETIME(6) lưu theo UTC
    scoring_models = sa.table(
        "scoring_models",
        sa.column("id", sa.Uuid),
        sa.column("version", sa.String),
        sa.column("file_name", sa.String),
        sa.column("checksum", sa.String),
        sa.column("is_active", sa.Boolean),
        sa.column("created_at", mysql.DATETIME(fsp=6)),
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
    rate = sa.DECIMAL(5, 4)
    approval_policies = sa.table(
        "approval_policies",
        sa.column("id", sa.Uuid),
        sa.column("version", sa.Integer),
        sa.column("rate_grade_a", rate),
        sa.column("rate_grade_b", rate),
        sa.column("rate_grade_c", rate),
        sa.column("prepayment_fee_rate", rate),
        sa.column("is_active", sa.Boolean),
        sa.column("created_at", mysql.DATETIME(fsp=6)),
    )
    policy_id = uuid.uuid4()
    # Chính sách mặc định: A = 20%, B = 24%, C = 28%/năm; phí trả trước hạn 3% (1.2.8d).
    op.bulk_insert(
        approval_policies,
        [
            {
                "id": policy_id, "version": 1, "rate_grade_a": Decimal("0.20"),
                "rate_grade_b": Decimal("0.24"), "rate_grade_c": Decimal("0.28"),
                "prepayment_fee_rate": Decimal("0.03"), "is_active": True, "created_at": now,
            }
        ],
    )
    money = sa.DECIMAL(15, 0)
    tiers = sa.table(
        "approval_policy_tiers",
        sa.column("id", sa.Uuid),
        sa.column("policy_id", sa.Uuid),
        sa.column("min_amount", money),
        sa.column("max_amount", money),
        sa.column("required_approvals", sa.SmallInteger),
    )
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
    counters = sa.table("counters", sa.column("name", sa.String), sa.column("value", sa.BigInteger))
    op.bulk_insert(counters, [{"name": name, "value": 0} for name in COUNTERS])


def downgrade() -> None:
    op.execute(f"DROP TRIGGER {TRIGGER}")
    for table in (
        "payment_reminders",
        "payment_allocations",
        "payments",
        "loan_contracts",
        "installments",
        "disbursements",
        "approval_decisions",
        "user_roles",
        "sessions",
        "otp_challenges",
        "notifications",
        "loans",
        "credit_scores",
        "cic_reports",
        "audit_logs",
        "appraisal_reports",
        "application_status_history",
        "application_documents",
        "users",
        "role_permissions",
        "loan_applications",
        "approval_policy_tiers",
        "scoring_models",
        "roles",
        "registration_requests",
        "permissions",
        "employees",
        "customers",
        "counters",
        "approval_policies",
    ):
        op.drop_table(table)
