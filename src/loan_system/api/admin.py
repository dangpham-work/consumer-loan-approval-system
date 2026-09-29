"""UC04 Quản lý tài khoản nhân viên, UC05 Quản lý vai trò – quyền, UC06 Cấu hình chính sách phê
duyệt (màn hình M09)."""

import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field

from loan_system.api.access import FORBIDDEN_MESSAGE, Auth, require
from loan_system.api.applications import Amount
from loan_system.api.deps import ClientIp, Ctx, Db
from loan_system.domain.appraisal import InvalidPolicyTiers
from loan_system.services.auth_service import AuthService, CurrentUser, InvalidOtp
from loan_system.services.policy_service import NewPolicy, PolicyService, PolicyView
from loan_system.services.policy_service import TierInput as PolicyTier
from loan_system.services.role_service import (
    AdminCannotHoldLendingPermission,
    ConflictingPermissions,
    DuplicateRole,
    RoleNotFound,
    RoleService,
    UnknownPermission,
)
from loan_system.services.staff_service import (
    ConflictingRoles,
    DuplicateAccount,
    NewStaff,
    SelfEscalation,
    StaffNotFound,
    StaffService,
    UnknownRole,
)

router = APIRouter(prefix="/admin", tags=["Quản trị"])

CONFLICTING_ROLES = "Vai trò ADMIN không được kết hợp với vai trò nghiệp vụ cho vay"

UserManager = Annotated[CurrentUser, Depends(require("USER_MANAGE"))]
RoleManager = Annotated[CurrentUser, Depends(require("ROLE_MANAGE"))]
PolicyManager = Annotated[CurrentUser, Depends(require("POLICY_CONFIGURE"))]
RoleList = Annotated[list[Annotated[str, Field(max_length=30)]], Field(min_length=1, max_length=10)]
PermissionList = Annotated[list[Annotated[str, Field(max_length=50)]], Field(max_length=30)]
PolicyRate = Annotated[Decimal, Field(gt=0, lt=1, decimal_places=4)]
Otp = Annotated[str, Field(pattern=r"^\d{6}$")]


class CreateStaffRequest(BaseModel):
    # Chỉ nhận các trường khai báo ở đây; trạng thái và mật khẩu do hệ thống đặt (SR10).
    # Bắt đầu bằng chữ cái để không trùng với tên đăng nhập của khách hàng (số điện thoại).
    username: str = Field(pattern=r"^[a-z][a-z0-9._-]{2,49}$")
    full_name: str = Field(min_length=2, max_length=100)
    email: EmailStr
    branch: str = Field(min_length=1, max_length=50)
    roles: RoleList
    otp: str = Field(pattern=r"^\d{6}$")  # xác thực lại trước thao tác quản trị (4.2.4)


class CreateStaffResponse(BaseModel):
    user_id: uuid.UUID
    status: str


class SetRolesRequest(BaseModel):
    roles: RoleList
    otp: str = Field(pattern=r"^\d{6}$")  # UC04 2a: xác thực lại khi đổi vai trò


# --- UC05: vai trò – quyền -----------------------------------------------------------------

class CreateRoleRequest(BaseModel):
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{1,29}$")
    name: str = Field(min_length=2, max_length=100)
    permissions: PermissionList
    otp: Otp  # UC05 bước 5: xác thực lại khi lưu


class SetPermissionsRequest(BaseModel):
    permissions: PermissionList
    otp: Otp


class RoleResponse(BaseModel):
    code: str
    name: str
    permissions: list[str]


class PermissionResponse(BaseModel):
    code: str
    description: str


# --- UC06: chính sách phê duyệt ------------------------------------------------------------

class TierRequest(BaseModel):
    min_amount: Amount
    max_amount: Amount
    required_approvals: int = Field(ge=1, le=10)


class CreatePolicyRequest(BaseModel):
    rate_grade_a: PolicyRate
    rate_grade_b: PolicyRate
    rate_grade_c: PolicyRate
    prepayment_fee_rate: PolicyRate
    tiers: Annotated[list[TierRequest], Field(min_length=1, max_length=20)]
    otp: Otp  # UC06 bước 4: xác thực lại khi lưu


class TierResponse(BaseModel):
    min_amount: Decimal
    max_amount: Decimal
    required_approvals: int


class PolicyResponse(BaseModel):
    version: int
    rate_grade_a: Decimal
    rate_grade_b: Decimal
    rate_grade_c: Decimal
    prepayment_fee_rate: Decimal
    is_active: bool
    tiers: list[TierResponse]


def _confirm_step_up(auth: AuthService, actor: CurrentUser, code: str) -> None:
    """SR02: thao tác quản trị cần nhập lại mã TOTP; sai thì từ chối như thiếu quyền."""
    try:
        auth.confirm_step_up(actor, code)
    except InvalidOtp as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Mã OTP không đúng") from exc


def _service(db: Db, ctx: Ctx, ip: ClientIp) -> StaffService:
    return StaffService(db, ctx.clock, ctx.email, ip)


Staff = Annotated[StaffService, Depends(_service)]


def _roles(db: Db, ctx: Ctx, ip: ClientIp) -> RoleService:
    return RoleService(db, ctx.clock, ip)


Roles = Annotated[RoleService, Depends(_roles)]


def _policies(db: Db, ctx: Ctx, ip: ClientIp) -> PolicyService:
    return PolicyService(db, ctx.clock, ip)


Policies = Annotated[PolicyService, Depends(_policies)]


def _role_response(role: object) -> RoleResponse:
    return RoleResponse.model_validate(role, from_attributes=True)


def _policy_response(policy: PolicyView) -> PolicyResponse:
    return PolicyResponse(
        version=policy.version, rate_grade_a=policy.rate_grade_a,
        rate_grade_b=policy.rate_grade_b, rate_grade_c=policy.rate_grade_c,
        prepayment_fee_rate=policy.prepayment_fee_rate, is_active=policy.is_active,
        tiers=[
            TierResponse(
                min_amount=t.min_amount, max_amount=t.max_amount,
                required_approvals=t.required_approvals,
            )
            for t in policy.tiers
        ],
    )


@router.post("/users", status_code=status.HTTP_201_CREATED, response_model=CreateStaffResponse)
def create_staff(
    body: CreateStaffRequest, actor: UserManager, auth: Auth, staff: Staff
) -> CreateStaffResponse:
    _confirm_step_up(auth, actor, body.otp)
    try:
        user_id = staff.create(
            actor,
            NewStaff(
                username=body.username,
                full_name=body.full_name,
                email=str(body.email),
                branch=body.branch,
                roles=frozenset(body.roles),
            ),
        )
    except UnknownRole as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Vai trò không hợp lệ") from exc
    except ConflictingRoles as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, CONFLICTING_ROLES) from exc
    except DuplicateAccount as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "Tên đăng nhập hoặc email đã được dùng") from exc
    return CreateStaffResponse(user_id=user_id, status="PENDING")


@router.put("/users/{user_id}/roles")
def set_roles(
    user_id: uuid.UUID, body: SetRolesRequest, actor: UserManager, auth: Auth, staff: Staff
) -> dict[str, str]:
    _confirm_step_up(auth, actor, body.otp)
    try:
        staff.set_roles(actor, user_id, frozenset(body.roles))
    except StaffNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy nhân viên") from exc
    except UnknownRole as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Vai trò không hợp lệ") from exc
    except ConflictingRoles as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, CONFLICTING_ROLES) from exc
    except SelfEscalation as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, FORBIDDEN_MESSAGE) from exc
    return {"message": "Đã cập nhật vai trò"}


# --- UC05: vai trò – quyền -----------------------------------------------------------------

CONFLICTING_PERMISSIONS = "Cặp quyền xung đột không được gán cho cùng một vai trò: {} và {}"


@router.get("/roles", response_model=list[RoleResponse])
def list_roles(actor: RoleManager, roles: Roles) -> list[RoleResponse]:
    return [_role_response(role) for role in roles.list_roles()]


@router.get("/permissions", response_model=list[PermissionResponse])
def list_permissions(actor: RoleManager, roles: Roles) -> list[PermissionResponse]:
    return [
        PermissionResponse(code=code, description=description)
        for code, description in roles.list_permissions()
    ]


@router.post("/roles", status_code=status.HTTP_201_CREATED)
def create_role(
    body: CreateRoleRequest, actor: RoleManager, auth: Auth, roles: Roles
) -> dict[str, str]:
    _confirm_step_up(auth, actor, body.otp)
    try:
        roles.create(actor, body.code, body.name, frozenset(body.permissions))
    except UnknownPermission as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Quyền không hợp lệ") from exc
    except ConflictingPermissions as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, CONFLICTING_PERMISSIONS.format(*exc.pair)
        ) from exc
    except AdminCannotHoldLendingPermission as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except DuplicateRole as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "Mã vai trò đã tồn tại") from exc
    return {"message": "Đã tạo vai trò"}


@router.put("/roles/{code}/permissions")
def set_role_permissions(
    code: str, body: SetPermissionsRequest, actor: RoleManager, auth: Auth, roles: Roles
) -> dict[str, str]:
    _confirm_step_up(auth, actor, body.otp)
    try:
        roles.set_permissions(actor, code, frozenset(body.permissions))
    except RoleNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy vai trò") from exc
    except UnknownPermission as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Quyền không hợp lệ") from exc
    except ConflictingPermissions as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, CONFLICTING_PERMISSIONS.format(*exc.pair)
        ) from exc
    except AdminCannotHoldLendingPermission as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return {"message": "Đã cập nhật quyền"}


# --- UC06: chính sách phê duyệt ------------------------------------------------------------


@router.get("/policies", response_model=list[PolicyResponse])
def list_policies(actor: PolicyManager, policies: Policies) -> list[PolicyResponse]:
    return [_policy_response(view) for view in policies.list_versions()]


@router.post(
    "/policies", status_code=status.HTTP_201_CREATED, response_model=PolicyResponse
)
def create_policy(
    body: CreatePolicyRequest, actor: PolicyManager, auth: Auth, policies: Policies
) -> PolicyResponse:
    _confirm_step_up(auth, actor, body.otp)
    try:
        view = policies.create_version(
            actor,
            NewPolicy(
                rate_grade_a=body.rate_grade_a,
                rate_grade_b=body.rate_grade_b,
                rate_grade_c=body.rate_grade_c,
                prepayment_fee_rate=body.prepayment_fee_rate,
                tiers=[
                    PolicyTier(t.min_amount, t.max_amount, t.required_approvals)
                    for t in body.tiers
                ],
            ),
        )
    except InvalidPolicyTiers as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return _policy_response(view)
