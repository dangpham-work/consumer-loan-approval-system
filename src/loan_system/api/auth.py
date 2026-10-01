from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field

from loan_system.api.access import SESSION_COOKIE, Auth, SessionToken, User, enforce_rate_limit
from loan_system.api.deps import ClientIp, Ctx
from loan_system.domain.access import MIN_PASSWORD_LENGTH
from loan_system.services.auth_service import (
    AccountLocked,
    InvalidCredentials,
    InvalidOtp,
    NotAuthenticated,
    PasswordRejected,
    SetupOutOfOrder,
)

router = APIRouter(prefix="/auth", tags=["Xác thực"])

NOT_AUTHENTICATED = "Chưa đăng nhập"
LOCKED_MESSAGE = (
    "Tài khoản đang bị khóa tạm thời do đăng nhập sai nhiều lần. "
    "Vui lòng thử lại sau {minutes} phút hoặc liên hệ quản trị viên."
)


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    message: str
    next: str  # HOME, OTP (nhập mã TOTP) hoặc SETUP (đăng nhập lần đầu)


class OtpRequest(BaseModel):
    code: str = Field(pattern=r"^\d{6}$")


class InitialPasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=128)  # SR01


class TotpEnrollmentResponse(BaseModel):
    secret: str
    otpauth_uri: str


class SessionInfo(BaseModel):
    user_id: str
    username: str
    kind: str
    roles: list[str]
    permissions: list[str]


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE, token, httponly=True, secure=True, samesite="strict", path="/"
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, httponly=True, secure=True, samesite="strict", path="/")


def _unauthenticated() -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, NOT_AUTHENTICATED)


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, auth: Auth, ctx: Ctx, ip: ClientIp, response: Response) -> LoginResponse:
    # UC01 bước 2: giới hạn tần suất theo địa chỉ IP (SR12); khóa theo tài khoản nằm ở tầng nghiệp vụ.
    enforce_rate_limit(ctx.limits.login, f"{ip}")
    try:
        result = auth.login(body.username, body.password)
    except AccountLocked as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, LOCKED_MESSAGE.format(minutes=ctx.settings.lockout_minutes)
        ) from exc
    except InvalidCredentials as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Thông tin đăng nhập không đúng") from exc
    set_session_cookie(response, result.token)
    return LoginResponse(message="Đăng nhập thành công", next=result.next_step)


@router.post("/otp/verify")
def verify_otp(
    body: OtpRequest, auth: Auth, ctx: Ctx, ip: ClientIp, session: SessionToken = None
) -> dict[str, str]:
    enforce_rate_limit(ctx.limits.otp, f"{ip}")
    try:
        auth.verify_login_otp(session, body.code)
    except NotAuthenticated as exc:
        raise _unauthenticated() from exc
    except InvalidOtp as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Mã OTP không đúng") from exc
    return {"message": "Xác thực thành công"}


@router.post("/setup/password")
def change_initial_password(
    body: InitialPasswordRequest, auth: Auth, session: SessionToken = None
) -> dict[str, str]:
    try:
        auth.change_initial_password(session, body.current_password, body.new_password)
    except NotAuthenticated as exc:
        raise _unauthenticated() from exc
    except SetupOutOfOrder as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "Mật khẩu đã được đổi") from exc
    except PasswordRejected as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return {"message": "Đã đổi mật khẩu. Tiếp theo, đăng ký ứng dụng xác thực."}


@router.post("/setup/totp", response_model=TotpEnrollmentResponse)
def start_totp_enrollment(auth: Auth, session: SessionToken = None) -> TotpEnrollmentResponse:
    try:
        enrollment = auth.start_totp_enrollment(session)
    except NotAuthenticated as exc:
        raise _unauthenticated() from exc
    except SetupOutOfOrder as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "Hãy đổi mật khẩu tạm trước") from exc
    return TotpEnrollmentResponse(secret=enrollment.secret, otpauth_uri=enrollment.provisioning_uri)


@router.post("/setup/totp/confirm")
def confirm_totp_enrollment(
    body: OtpRequest, auth: Auth, ctx: Ctx, ip: ClientIp, session: SessionToken = None
) -> dict[str, str]:
    enforce_rate_limit(ctx.limits.otp, f"{ip}")
    try:
        auth.confirm_totp_enrollment(session, body.code)
    except NotAuthenticated as exc:
        raise _unauthenticated() from exc
    except SetupOutOfOrder as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "Hãy đổi mật khẩu tạm trước") from exc
    except InvalidOtp as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Mã OTP không đúng") from exc
    return {"message": "Đã kích hoạt tài khoản"}


@router.get("/session", response_model=SessionInfo)
def whoami(user: User) -> SessionInfo:
    return SessionInfo(
        user_id=str(user.user_id),
        username=user.username,
        kind=user.kind,
        roles=list(user.roles),
        permissions=sorted(user.permissions),
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(auth: Auth, response: Response, session: SessionToken = None) -> None:
    try:
        auth.logout(session)
    except NotAuthenticated as exc:
        raise _unauthenticated() from exc
    clear_session_cookie(response)
