"""Nhân viên, vai trò và quyền theo ma trận RBAC (2.2.1c), 2FA TOTP, giai đoạn của phiên đăng nhập

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-29
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mssql import DATETIMEOFFSET, NVARCHAR, UNIQUEIDENTIFIER

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

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


def upgrade() -> None:
    op.create_table(
        "employees",
        sa.Column("id", UNIQUEIDENTIFIER, primary_key=True),
        sa.Column("full_name", NVARCHAR(100), nullable=False),
        sa.Column("email", NVARCHAR(100), nullable=False, unique=True),
        sa.Column("branch", NVARCHAR(50), nullable=False),
        sa.Column("created_at", DATETIMEOFFSET, nullable=False),
    )
    roles = op.create_table(
        "roles",
        sa.Column("id", UNIQUEIDENTIFIER, primary_key=True),
        sa.Column("code", sa.String(30), nullable=False, unique=True),
        sa.Column("name", NVARCHAR(100), nullable=False),
    )
    permissions = op.create_table(
        "permissions",
        sa.Column("id", UNIQUEIDENTIFIER, primary_key=True),
        sa.Column("code", sa.String(50), nullable=False, unique=True),
        sa.Column("description", NVARCHAR(200), nullable=False),
    )
    op.create_table(
        "user_roles",
        sa.Column("user_id", UNIQUEIDENTIFIER, sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("role_id", UNIQUEIDENTIFIER, sa.ForeignKey("roles.id"), primary_key=True),
    )
    role_permissions = op.create_table(
        "role_permissions",
        sa.Column("role_id", UNIQUEIDENTIFIER, sa.ForeignKey("roles.id"), primary_key=True),
        sa.Column(
            "permission_id", UNIQUEIDENTIFIER, sa.ForeignKey("permissions.id"), primary_key=True
        ),
    )

    op.add_column("users", sa.Column("employee_id", UNIQUEIDENTIFIER, sa.ForeignKey("employees.id")))
    op.add_column(
        "users",
        sa.Column("must_change_password", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.add_column("users", sa.Column("totp_secret_enc", sa.LargeBinary(500)))
    op.add_column("users", sa.Column("totp_last_step", sa.BigInteger))
    op.create_check_constraint(
        "ck_users_owner",
        "users",
        "(employee_id IS NULL AND customer_id IS NOT NULL)"
        " OR (employee_id IS NOT NULL AND customer_id IS NULL)",
    )
    op.add_column(
        "sessions", sa.Column("stage", sa.String(10), nullable=False, server_default="FULL")
    )
    op.add_column(
        "sessions",
        sa.Column("otp_failed_attempts", sa.SmallInteger, nullable=False, server_default="0"),
    )
    op.create_check_constraint("ck_sessions_stage", "sessions", "stage IN ('SETUP','MFA','FULL')")
    # Chi tiết không nhạy cảm của bản ghi nhật ký, ví dụ vai trò trước/sau (UC04).
    op.add_column("audit_logs", sa.Column("detail", NVARCHAR(500)))

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
    # Tài khoản khách hàng đã có từ trước nhận vai trò CUSTOMER.
    op.execute(
        "INSERT INTO user_roles (user_id, role_id) "
        "SELECT u.id, r.id FROM users u CROSS JOIN roles r "
        "WHERE u.customer_id IS NOT NULL AND r.code = 'CUSTOMER'"
    )


def downgrade() -> None:
    op.drop_column("audit_logs", "detail")
    op.drop_constraint("ck_sessions_stage", "sessions")
    op.drop_column("sessions", "otp_failed_attempts", mssql_drop_default=True)
    op.drop_column("sessions", "stage", mssql_drop_default=True)
    op.drop_constraint("ck_users_owner", "users")
    op.drop_column("users", "totp_last_step")
    op.drop_column("users", "totp_secret_enc")
    op.drop_column("users", "must_change_password", mssql_drop_default=True)
    op.drop_column("users", "employee_id", mssql_drop_foreign_key=True)
    op.drop_table("role_permissions")
    op.drop_table("user_roles")
    op.drop_table("permissions")
    op.drop_table("roles")
    op.drop_table("employees")
