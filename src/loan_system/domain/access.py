"""Tài khoản, vai trò và quy tắc gán vai trò (ma trận RBAC mục 2.2.1c, UC04, SR01)."""

from enum import StrEnum

CUSTOMER = "CUSTOMER"
ADMIN = "ADMIN"
# Vai trò tham gia nghiệp vụ cho vay; Quản trị viên không được giữ vai trò nào trong số này.
LENDING_ROLES = frozenset({"CREDIT_OFFICER", "APPRAISER", "APPROVER", "DISBURSER"})

MIN_PASSWORD_LENGTH = 10  # SR01


class AccountStatus(StrEnum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    LOCKED = "LOCKED"
    DISABLED = "DISABLED"


def is_self_escalation(actor_id: object, target_id: object, roles: set[str]) -> bool:
    """UC04 2d: Quản trị viên không được tự gán cho mình vai trò nào khác ngoài ADMIN."""
    return actor_id == target_id and bool(roles - {ADMIN})


def mixes_admin_and_lending(roles: set[str]) -> bool:
    """Quản trị viên không có quyền nghiệp vụ (ma trận RBAC), với mọi tài khoản chứ không chỉ chính
    mình: nếu không, hai quản trị viên có thể gán chéo cho nhau rồi tự duyệt (BR06)."""
    return ADMIN in roles and bool(roles & LENDING_ROLES)
