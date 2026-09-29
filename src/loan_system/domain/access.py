"""Tài khoản, vai trò và quy tắc gán vai trò (ma trận RBAC mục 2.2.1c, UC04, SR01)."""

from enum import StrEnum

CUSTOMER = "CUSTOMER"
ADMIN = "ADMIN"
CREDIT_OFFICER = "CREDIT_OFFICER"
APPRAISER = "APPRAISER"
APPROVER = "APPROVER"
DISBURSER = "DISBURSER"
AUDITOR = "AUDITOR"
# Vai trò tham gia nghiệp vụ cho vay; Quản trị viên không được giữ vai trò nào trong số này.
LENDING_ROLES = frozenset({CREDIT_OFFICER, APPRAISER, APPROVER, DISBURSER})

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


# UC05 bước 4/4a: một vai trò không được giữ từ hai quyền trở lên trong dây chuyền thẩm định →
# phê duyệt → giải ngân của BR06, để một vai trò không thể tự đi từ đầu đến cuối một hồ sơ vay.
SOD_STAGE_PERMISSIONS = frozenset({"APPRAISAL_SUBMIT", "LOAN_APPROVE", "DISBURSE"})


def conflicting_permission_pair(permissions: set[str]) -> tuple[str, str] | None:
    """UC05 bước 4: cặp quyền xung đột đầu tiên trong tập quyền định gán cho một vai trò, nếu có."""
    hit = sorted(permissions & SOD_STAGE_PERMISSIONS)
    return (hit[0], hit[1]) if len(hit) >= 2 else None


# Quyền nghiệp vụ cho vay theo ma trận RBAC (gán cho CREDIT_OFFICER, APPRAISER, APPROVER,
# DISBURSER), mà vai trò ADMIN không được giữ, kể cả khi được gán trực tiếp qua UC05 thay vì qua
# gán vai trò: nếu không, mixes_admin_and_lending có thể bị lách bằng cách sửa thẳng quyền của
# chính vai trò ADMIN thay vì gán một vai trò nghiệp vụ khác.
LENDING_PERMISSIONS = frozenset({
    "APPLICATION_CREATE", "APPLICATION_VIEW", "APPLICATION_VERIFY", "APPLICATION_REQUEST_INFO",
    "CUSTOMER_VIEW_PII", "CREDIT_SCORE_VIEW", "APPRAISAL_SUBMIT", "LOAN_APPROVE", "LOAN_REJECT",
    "DISBURSE", "PAYMENT_RECORD", "LOAN_SETTLE", "REPORT_VIEW",
})


def admin_role_lending_permission(code: str, permissions: set[str]) -> str | None:
    """UC05: quyền nghiệp vụ đầu tiên (nếu có) mà vai trò ADMIN không được giữ."""
    if code != ADMIN:
        return None
    hit = sorted(permissions & LENDING_PERMISSIONS)
    return hit[0] if hit else None
