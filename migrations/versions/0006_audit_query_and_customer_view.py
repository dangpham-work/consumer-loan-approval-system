"""Vai trò app_rw bị DENY UPDATE/DELETE trên audit_logs (4.1.2e); quyền CUSTOMER_VIEW (UC11, ticket #15, #17)

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-29
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mssql import NVARCHAR, UNIQUEIDENTIFIER

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CUSTOMER_VIEW = ("CUSTOMER_VIEW", "Tra cứu thông tin khách hàng", ["CREDIT_OFFICER", "APPRAISER"])

roles = sa.table("roles", sa.column("id", UNIQUEIDENTIFIER), sa.column("code", sa.String))
permissions = sa.table(
    "permissions",
    sa.column("id", UNIQUEIDENTIFIER),
    sa.column("code", sa.String),
    sa.column("description", NVARCHAR),
)
role_permissions = sa.table(
    "role_permissions",
    sa.column("role_id", UNIQUEIDENTIFIER),
    sa.column("permission_id", UNIQUEIDENTIFIER),
)


def upgrade() -> None:
    # Nhật ký kiểm toán chỉ ghi thêm: tầng CSDL từ chối UPDATE/DELETE cho vai trò app_rw, phòng khi
    # tầng ứng dụng bị qua mặt (domain/audit.py: xóa cuối chuỗi không phát hiện được bằng hash).
    op.execute("CREATE ROLE app_rw")
    op.execute("DENY UPDATE, DELETE ON dbo.audit_logs TO app_rw")

    bind = op.get_bind()
    code, description, granted_to = CUSTOMER_VIEW
    permission_id = uuid.uuid4()
    op.bulk_insert(permissions, [{"id": permission_id, "code": code, "description": description}])
    role_ids = bind.execute(sa.select(roles.c.id).where(roles.c.code.in_(granted_to))).scalars().all()
    op.bulk_insert(
        role_permissions,
        [{"role_id": role_id, "permission_id": permission_id} for role_id in role_ids],
    )


def downgrade() -> None:
    bind = op.get_bind()
    permission_id = bind.execute(
        sa.select(permissions.c.id).where(permissions.c.code == CUSTOMER_VIEW[0])
    ).scalar_one()
    op.execute(
        sa.delete(role_permissions).where(role_permissions.c.permission_id == permission_id)
    )
    op.execute(sa.delete(permissions).where(permissions.c.id == permission_id))

    op.execute("REVOKE UPDATE, DELETE ON dbo.audit_logs TO app_rw")
    op.execute("DROP ROLE app_rw")
