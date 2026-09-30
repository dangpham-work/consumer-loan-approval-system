"""Màn hình M09 Quản trị người dùng và chính sách: ba thẻ Tài khoản nhân viên, Vai trò – quyền,
Chính sách phê duyệt.

UC04 Quản lý tài khoản nhân viên, UC05 Quản lý vai trò – quyền, UC06 Cấu hình chính sách phê duyệt
(UC21 dùng chung bảng chính sách). Cùng tầng nghiệp vụ, schema và thông điệp với `api/admin.py`. Mọi
thao tác ghi yêu cầu nhập lại mã TOTP ngay trong biểu mẫu (step-up, SR02); sai mã thì không lưu gì,
sai quá số lần cho phép thì phiên bị hủy như ở REST API.
"""

import uuid
from collections.abc import Callable, Mapping
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from loan_system.api.access import FORBIDDEN_MESSAGE, Auth
from loan_system.api.admin import (
    CONFLICTING_PERMISSIONS,
    CONFLICTING_ROLES,
    CreatePolicyRequest,
    CreateRoleRequest,
    CreateStaffRequest,
    Policies,
    Roles,
    SetPermissionsRequest,
    SetRolesRequest,
    Staff,
)
from loan_system.domain.access import CUSTOMER
from loan_system.domain.appraisal import InvalidPolicyTiers
from loan_system.services.auth_service import AuthService, CurrentUser, InvalidOtp
from loan_system.services.policy_service import NewPolicy, PolicyView, TierInput
from loan_system.services.role_service import (
    AdminCannotHoldLendingPermission,
    ConflictingPermissions,
    DuplicateRole,
    RoleNotFound,
    RoleService,
    RoleView,
    UnknownPermission,
)
from loan_system.services.staff_service import (
    ConflictingRoles,
    DuplicateAccount,
    NewStaff,
    SelfEscalation,
    StaffNotFound,
    UnknownRole,
)
from loan_system.web.pages import (
    PREFIX,
    Csrf,
    Entry,
    PageError,
    code_of,
    message_of,
    redirect,
    render,
    require_page,
    validate,
)

ADMIN_PREFIX = f"{PREFIX}/admin"
router = APIRouter(prefix=ADMIN_PREFIX, include_in_schema=False)

UserManagerPage = Annotated[CurrentUser, Depends(require_page("USER_MANAGE"))]
RoleManagerPage = Annotated[CurrentUser, Depends(require_page("ROLE_MANAGE"))]
PolicyManagerPage = Annotated[CurrentUser, Depends(require_page("POLICY_CONFIGURE"))]
# Ô đánh dấu chọn nhiều giá trị (vai trò, quyền, các hàng của bảng hạn mức).
Entries = Annotated[list[str], Form()]

INVALID_OTP = "Mã OTP gồm 6 chữ số."
RATE_ERROR = "phải lớn hơn 0% và nhỏ hơn 100%, tối đa 2 chữ số thập phân."
FIELD_ERRORS = {
    "username": ("Tên đăng nhập từ 3 đến 50 ký tự, bắt đầu bằng chữ thường; chỉ gồm chữ thường, "
                 "chữ số và các dấu . _ -."),
    "full_name": "Họ tên từ 2 đến 100 ký tự.",
    "email": "Email không hợp lệ.",
    "branch": "Nhập chi nhánh, tối đa 50 ký tự.",
    "roles": "Chọn ít nhất một vai trò.",
    "code": "Mã vai trò từ 2 đến 30 ký tự: chữ in hoa, chữ số, dấu gạch dưới, bắt đầu bằng chữ.",
    "name": "Tên vai trò từ 2 đến 100 ký tự.",
    "permissions": "Danh sách quyền không hợp lệ.",
    "rate_grade_a": f"Lãi suất hạng A {RATE_ERROR}",
    "rate_grade_b": f"Lãi suất hạng B {RATE_ERROR}",
    "rate_grade_c": f"Lãi suất hạng C {RATE_ERROR}",
    "prepayment_fee_rate": f"Phí trả trước hạn {RATE_ERROR}",
    "tiers": ("Bảng hạn mức cần ít nhất một khoảng; số tiền là số nguyên đồng từ 5.000.000 đến "
              "100.000.000 đ, số người phê duyệt từ 1 đến 10."),
    "otp": INVALID_OTP,
}

def _conflicting_permissions(exc: Exception) -> str:
    assert isinstance(exc, ConflictingPermissions)
    return CONFLICTING_PERMISSIONS.format(*exc.pair)


# Lỗi nghiệp vụ hiện lại biểu mẫu cùng mã trạng thái và câu thông báo với `api/admin.py`; mã OTP
# sai theo `api/errors.py`.
_ERRORS: dict[type[Exception], tuple[int, Callable[[Exception], str]]] = {
    UnknownRole: (status.HTTP_400_BAD_REQUEST, lambda _: "Vai trò không hợp lệ"),
    ConflictingRoles: (status.HTTP_400_BAD_REQUEST, lambda _: CONFLICTING_ROLES),
    DuplicateAccount: (status.HTTP_409_CONFLICT,
                       lambda _: "Tên đăng nhập hoặc email đã được dùng"),
    SelfEscalation: (status.HTTP_403_FORBIDDEN, lambda _: FORBIDDEN_MESSAGE),
    UnknownPermission: (status.HTTP_400_BAD_REQUEST, lambda _: "Quyền không hợp lệ"),
    ConflictingPermissions: (status.HTTP_400_BAD_REQUEST, _conflicting_permissions),
    AdminCannotHoldLendingPermission: (status.HTTP_400_BAD_REQUEST, str),
    DuplicateRole: (status.HTTP_409_CONFLICT, lambda _: "Mã vai trò đã tồn tại"),
    InvalidPolicyTiers: (status.HTTP_400_BAD_REQUEST, str),
}
_HANDLED: tuple[type[Exception], ...] = (*_ERRORS, InvalidOtp)


def _failure(exc: Exception) -> tuple[int, str]:
    if type(exc) in _ERRORS:
        code, message = _ERRORS[type(exc)]
        return code, message(exc)
    return code_of(exc), message_of(exc)


def _save[M: BaseModel](
    auth: AuthService, user: CurrentUser, model: type[M], form: Mapping[str, object],
    call: Callable[[M], None], show: Callable[[int, dict[str, Any]], HTMLResponse],
    done: str,
) -> HTMLResponse | RedirectResponse:
    """Kiểm tra biểu mẫu bằng schema của REST API, xác thực lại TOTP (ô `otp`) rồi lưu; lỗi thì
    `show` hiện lại trang với mã trạng thái và thông báo, thành công thì chuyển tới `done`."""
    body, field_errors = validate(model, form, FIELD_ERRORS)
    if body is None:
        return show(status.HTTP_400_BAD_REQUEST, {"field_errors": field_errors})
    try:
        auth.confirm_step_up(user, str(form["otp"]))
        call(body)
    except _HANDLED as exc:
        code, message = _failure(exc)
        return show(code, {"error": message})
    return redirect(done)


def _chosen(values: list[str]) -> list[str]:
    return [value for value in values if value]


# --- UC04: tài khoản nhân viên ----------------------------------------------------------------


def _staff_roles(roles: RoleService) -> list[RoleView]:
    return [role for role in roles.list_roles() if role.code != CUSTOMER]


def users_page(
    request: Request, user: CurrentUser, staff: Staff, roles: RoleService,
    status_code: int = status.HTTP_200_OK, **context: Any,
) -> HTMLResponse:
    return render(
        request, "admin_users.html",
        {"tab": "users", "staff": staff.list_staff(), "roles": _staff_roles(roles),
         "form": context.pop("form", {}), **context},
        user=user, status_code=status_code,
    )


@router.get("", response_class=HTMLResponse)
def users(request: Request, user: UserManagerPage, staff: Staff, roles: Roles) -> HTMLResponse:
    return users_page(request, user, staff, roles)


@router.post("/users", dependencies=[Csrf], response_model=None)
def create_user(
    request: Request, user: UserManagerPage, auth: Auth, staff: Staff, roles: Roles,
    username: Entry = "", full_name: Entry = "", email: Entry = "", branch: Entry = "",
    otp: Entry = "", role: Annotated[list[str], Form(alias="roles")] = [],  # noqa: B006
) -> HTMLResponse | RedirectResponse:
    form = {"username": username.strip(), "full_name": full_name.strip(),
            "email": email.strip(), "branch": branch.strip(), "roles": _chosen(role), "otp": otp}

    def call(body: CreateStaffRequest) -> None:
        staff.create(user, NewStaff(body.username, body.full_name, str(body.email), body.branch,
                                    frozenset(body.roles)))

    def show(code: int, context: dict[str, Any]) -> HTMLResponse:
        return users_page(request, user, staff, roles, code, form={**form, "otp": ""}, **context)

    return _save(auth, user, CreateStaffRequest, form, call, show,
                 f"{ADMIN_PREFIX}?notice=staff_created")


def user_page(
    request: Request, user: CurrentUser, staff: Staff, roles: RoleService, user_id: uuid.UUID,
    status_code: int = status.HTTP_200_OK, **context: Any,
) -> HTMLResponse:
    try:
        member = staff.get(user_id)
    except StaffNotFound as exc:
        raise PageError(status.HTTP_404_NOT_FOUND) from exc
    return render(
        request, "admin_user.html",
        {"tab": "users", "member": member, "roles": _staff_roles(roles),
         "chosen": context.pop("chosen", member.roles), **context},
        user=user, status_code=status_code,
    )


@router.get("/users/{user_id}", response_class=HTMLResponse)
def edit_user(
    request: Request, user_id: uuid.UUID, user: UserManagerPage, staff: Staff, roles: Roles,
) -> HTMLResponse:
    return user_page(request, user, staff, roles, user_id)


@router.post("/users/{user_id}/roles", dependencies=[Csrf], response_model=None)
def set_user_roles(
    request: Request, user_id: uuid.UUID, user: UserManagerPage, auth: Auth, staff: Staff,
    roles: Roles, otp: Entry = "",
    role: Annotated[list[str], Form(alias="roles")] = [],  # noqa: B006
) -> HTMLResponse | RedirectResponse:
    chosen = _chosen(role)

    def call(body: SetRolesRequest) -> None:
        try:
            staff.set_roles(user, user_id, frozenset(body.roles))
        except StaffNotFound as exc:
            raise PageError(status.HTTP_404_NOT_FOUND) from exc

    def show(code: int, context: dict[str, Any]) -> HTMLResponse:
        return user_page(request, user, staff, roles, user_id, code, chosen=chosen, **context)

    return _save(auth, user, SetRolesRequest, {"roles": chosen, "otp": otp}, call, show,
                 f"{ADMIN_PREFIX}/users/{user_id}?notice=roles_saved")


# --- UC05: vai trò – quyền --------------------------------------------------------------------


def roles_page(
    request: Request, user: CurrentUser, roles: RoleService,
    status_code: int = status.HTTP_200_OK, **context: Any,
) -> HTMLResponse:
    return render(
        request, "admin_roles.html",
        {"tab": "roles", "roles": roles.list_roles(), "permissions": roles.list_permissions(),
         "form": context.pop("form", {}), **context},
        user=user, status_code=status_code,
    )


@router.get("/roles", response_class=HTMLResponse)
def role_list(request: Request, user: RoleManagerPage, roles: Roles) -> HTMLResponse:
    return roles_page(request, user, roles)


@router.post("/roles", dependencies=[Csrf], response_model=None)
def create_role(
    request: Request, user: RoleManagerPage, auth: Auth, roles: Roles,
    code: Entry = "", name: Entry = "", otp: Entry = "",
    permissions: Entries = [],  # noqa: B006
) -> HTMLResponse | RedirectResponse:
    form = {"code": code.strip(), "name": name.strip(), "permissions": _chosen(permissions),
            "otp": otp}

    def call(body: CreateRoleRequest) -> None:
        roles.create(user, body.code, body.name, frozenset(body.permissions))

    def show(status_code: int, context: dict[str, Any]) -> HTMLResponse:
        return roles_page(request, user, roles, status_code, form={**form, "otp": ""}, **context)

    return _save(auth, user, CreateRoleRequest, form, call, show,
                 f"{ADMIN_PREFIX}/roles?notice=role_created")


def role_page(
    request: Request, user: CurrentUser, roles: RoleService, code: str,
    status_code: int = status.HTTP_200_OK, **context: Any,
) -> HTMLResponse:
    role = next((r for r in roles.list_roles() if r.code == code), None)
    if role is None:
        raise PageError(status.HTTP_404_NOT_FOUND)
    return render(
        request, "admin_role.html",
        {"tab": "roles", "role": role, "permissions": roles.list_permissions(),
         "chosen": context.pop("chosen", role.permissions), **context},
        user=user, status_code=status_code,
    )


@router.get("/roles/{code}", response_class=HTMLResponse)
def edit_role(request: Request, code: str, user: RoleManagerPage, roles: Roles) -> HTMLResponse:
    return role_page(request, user, roles, code)


@router.post("/roles/{code}/permissions", dependencies=[Csrf], response_model=None)
def set_role_permissions(
    request: Request, code: str, user: RoleManagerPage, auth: Auth, roles: Roles,
    otp: Entry = "", permissions: Entries = [],  # noqa: B006
) -> HTMLResponse | RedirectResponse:
    chosen = _chosen(permissions)

    def call(body: SetPermissionsRequest) -> None:
        try:
            roles.set_permissions(user, code, frozenset(body.permissions))
        except RoleNotFound as exc:
            raise PageError(status.HTTP_404_NOT_FOUND) from exc

    def show(status_code: int, context: dict[str, Any]) -> HTMLResponse:
        return role_page(request, user, roles, code, status_code, chosen=chosen, **context)

    # Bỏ hết quyền của một vai trò là hợp lệ (danh sách rỗng), nên giữ ô `permissions` khi trống.
    body_form = {"permissions": chosen, "otp": otp}
    return _save(auth, user, SetPermissionsRequest, body_form, call, show,
                 f"{ADMIN_PREFIX}/roles/{code}?notice=permissions_saved")


# --- UC06: chính sách phê duyệt ---------------------------------------------------------------

_BLANK_TIER_ROWS = 2  # hàng trống để thêm khoảng hạn mức


def _percent_text(ratio: Decimal) -> str:
    """0,1900 → "19"; ô nhập lãi suất và phí theo phần trăm."""
    text = f"{ratio * 100:.2f}".rstrip("0").rstrip(".")
    return text


def _ratio(text: str) -> Decimal | str:
    """Phần trăm người dùng nhập ("19" hoặc "19,5") thành tỷ lệ như REST API nhận; nhập sai thì
    giữ nguyên chuỗi để schema báo lỗi đúng ô."""
    try:
        value = Decimal(text.strip().replace(",", "."))
    except InvalidOperation:
        return text
    return value / 100 if value.is_finite() else text


def _policy_form(policy: PolicyView | None) -> dict[str, Any]:
    """Biểu mẫu phiên bản mới điền sẵn từ phiên bản đang hiệu lực."""
    if policy is None:
        return {"tiers": [("", "", "")] * _BLANK_TIER_ROWS}
    return {
        "rate_grade_a": _percent_text(policy.rate_grade_a),
        "rate_grade_b": _percent_text(policy.rate_grade_b),
        "rate_grade_c": _percent_text(policy.rate_grade_c),
        "prepayment_fee_rate": _percent_text(policy.prepayment_fee_rate),
        "tiers": [
            (str(int(t.min_amount)), str(int(t.max_amount)), str(t.required_approvals))
            for t in policy.tiers
        ] + [("", "", "")] * _BLANK_TIER_ROWS,
    }


def policies_page(
    request: Request, user: CurrentUser, policies: Policies,
    status_code: int = status.HTTP_200_OK, **context: Any,
) -> HTMLResponse:
    versions = policies.list_versions()
    active = next((v for v in versions if v.is_active), None)
    return render(
        request, "admin_policies.html",
        {"tab": "policies", "versions": versions,
         "form": context.pop("form", None) or _policy_form(active), **context},
        user=user, status_code=status_code,
    )


@router.get("/policies", response_class=HTMLResponse)
def policy_list(request: Request, user: PolicyManagerPage, policies: Policies) -> HTMLResponse:
    return policies_page(request, user, policies)


@router.post("/policies", dependencies=[Csrf], response_model=None)
def create_policy(
    request: Request, user: PolicyManagerPage, auth: Auth, policies: Policies,
    rate_grade_a: Entry = "", rate_grade_b: Entry = "", rate_grade_c: Entry = "",
    prepayment_fee_rate: Entry = "", otp: Entry = "",
    tier_min: Entries = [], tier_max: Entries = [], tier_approvals: Entries = [],  # noqa: B006
) -> HTMLResponse | RedirectResponse:
    rates = {"rate_grade_a": rate_grade_a, "rate_grade_b": rate_grade_b,
             "rate_grade_c": rate_grade_c, "prepayment_fee_rate": prepayment_fee_rate}
    # Hàng để trống cả ba ô là hàng thêm chưa dùng, bỏ qua.
    rows = [row for row in zip(tier_min, tier_max, tier_approvals, strict=False)
            if any(cell.strip() for cell in row)]
    form: dict[str, Any] = {
        **{field: _ratio(value) if value.strip() else "" for field, value in rates.items()},
        "tiers": [
            {"min_amount": low.strip(), "max_amount": high.strip(),
             "required_approvals": approvals.strip()}
            for low, high, approvals in rows
        ],
        "otp": otp,
    }

    def call(body: CreatePolicyRequest) -> None:
        policies.create_version(user, NewPolicy(
            rate_grade_a=body.rate_grade_a, rate_grade_b=body.rate_grade_b,
            rate_grade_c=body.rate_grade_c, prepayment_fee_rate=body.prepayment_fee_rate,
            tiers=[TierInput(t.min_amount, t.max_amount, t.required_approvals)
                   for t in body.tiers],
        ))

    def show(status_code: int, context: dict[str, Any]) -> HTMLResponse:
        shown = {**rates, "tiers": rows + [("", "", "")] * _BLANK_TIER_ROWS}
        return policies_page(request, user, policies, status_code, form=shown, **context)

    return _save(auth, user, CreatePolicyRequest, form, call, show,
                 f"{ADMIN_PREFIX}/policies?notice=policy_saved")
