"""UC04 Quản lý tài khoản nhân viên (màn hình M09)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field

from loan_system.api.access import FORBIDDEN_MESSAGE, Auth, require
from loan_system.api.deps import ClientIp, Ctx, Db
from loan_system.services.auth_service import AuthService, CurrentUser, InvalidOtp
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
RoleList = Annotated[list[Annotated[str, Field(max_length=30)]], Field(min_length=1, max_length=10)]


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


def _confirm_step_up(auth: AuthService, actor: CurrentUser, code: str) -> None:
    """SR02: thao tác quản trị cần nhập lại mã TOTP; sai thì từ chối như thiếu quyền."""
    try:
        auth.confirm_step_up(actor, code)
    except InvalidOtp as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Mã OTP không đúng") from exc


def _service(db: Db, ctx: Ctx, ip: ClientIp) -> StaffService:
    return StaffService(db, ctx.clock, ctx.email, ip)


Staff = Annotated[StaffService, Depends(_service)]


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
