"""Màn hình M01: UC01 Đăng nhập, UC02 Xác thực OTP, đổi mật khẩu tạm và đăng ký TOTP khi nhân viên
đăng nhập lần đầu (UC01 3b, UC03), UC09 Đăng ký tài khoản khách hàng.

Cùng tầng nghiệp vụ và cùng thông điệp với `api/auth.py`, `api/customers.py`.
"""

import re
import uuid
from typing import Annotated

from fastapi import APIRouter, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import ValidationError

from loan_system.api.access import Auth, SessionToken
from loan_system.api.auth import LOCKED_MESSAGE, clear_session_cookie, set_session_cookie
from loan_system.api.customers import DUPLICATE_MESSAGE, RegisterRequest
from loan_system.api.deps import ClientIp, Ctx, Db
from loan_system.domain.access import MIN_PASSWORD_LENGTH
from loan_system.domain.eligibility import MAX_AGE, MIN_AGE
from loan_system.services.auth_service import (
    AccountLocked,
    InvalidCredentials,
    InvalidOtp,
    NextStep,
    NotAuthenticated,
    PasswordRejected,
    SetupOutOfOrder,
    Stage,
)
from loan_system.services.registration_service import (
    DuplicateIdentity,
    NewRegistration,
    RegistrationFailed,
    RegistrationService,
)
from loan_system.web.pages import (
    ERROR_MESSAGES,
    PREFIX,
    Csrf,
    redirect,
    render,
    session_alive,
)

router = APIRouter(prefix=PREFIX, include_in_schema=False)

WRONG_CREDENTIALS = "Thông tin đăng nhập không đúng"
WRONG_OTP = "Mã OTP không đúng"
MAX_PASSWORD_LENGTH = 128  # SR01, như `api/auth.py`

_NEXT_PAGE = {
    NextStep.HOME: PREFIX,
    NextStep.OTP: f"{PREFIX}/login/otp",
    NextStep.SETUP: f"{PREFIX}/setup/password",
}

# UC09: thông điệp cho từng trường của biểu mẫu đăng ký (lỗi kiểm tra của pydantic là tiếng Anh).
_REGISTER_FIELD_ERRORS = {
    "full_name": "Họ tên từ 2 đến 100 ký tự.",
    "date_of_birth": "Ngày sinh không hợp lệ.",
    "phone": "Số điện thoại gồm 10 chữ số, bắt đầu bằng 0.",
    "email": "Email không hợp lệ.",
    "password": f"Mật khẩu từ {MIN_PASSWORD_LENGTH} đến {MAX_PASSWORD_LENGTH} ký tự.",
    "accept_terms": "Bạn cần đồng ý điều khoản sử dụng.",
}

Text = Annotated[str, Form()]


def _is_otp(code: str) -> bool:
    return re.fullmatch(r"\d{6}", code) is not None


# --- UC01, UC02 -------------------------------------------------------------------------------


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request) -> HTMLResponse:
    return render(request, "login.html")


@router.post("/login", dependencies=[Csrf], response_model=None)
def login(
    request: Request, auth: Auth, ctx: Ctx, ip: ClientIp, username: Text, password: Text
) -> HTMLResponse | RedirectResponse:
    def failed(code: int, error: str) -> HTMLResponse:
        return render(request, "login.html", {"error": error, "username": username},
                      status_code=code)

    # UC01 bước 2: giới hạn tần suất theo địa chỉ IP (SR12), dùng chung bộ đếm với API.
    if not ctx.limits.login.hit(f"{ip}"):
        return failed(status.HTTP_429_TOO_MANY_REQUESTS,
                      ERROR_MESSAGES[status.HTTP_429_TOO_MANY_REQUESTS])
    try:
        result = auth.login(username, password)
    except AccountLocked:
        return failed(status.HTTP_401_UNAUTHORIZED,
                      LOCKED_MESSAGE.format(minutes=ctx.settings.lockout_minutes))
    except InvalidCredentials:
        return failed(status.HTTP_401_UNAUTHORIZED, WRONG_CREDENTIALS)
    response = redirect(_NEXT_PAGE[result.next_step])
    set_session_cookie(response, result.token)
    return response


@router.get("/login/otp", response_class=HTMLResponse)
def otp_page(request: Request) -> HTMLResponse:
    return render(request, "otp.html")


@router.post("/login/otp", dependencies=[Csrf], response_model=None)
def verify_otp(
    request: Request, auth: Auth, ctx: Ctx, ip: ClientIp, code: Text,
    session: SessionToken = None,
) -> HTMLResponse | RedirectResponse:
    if not ctx.limits.otp.hit(f"{ip}"):
        return render(request, "otp.html",
                      {"error": ERROR_MESSAGES[status.HTTP_429_TOO_MANY_REQUESTS]},
                      status_code=status.HTTP_429_TOO_MANY_REQUESTS)
    if not _is_otp(code):
        return render(request, "otp.html", {"error": WRONG_OTP},
                      status_code=status.HTTP_400_BAD_REQUEST)
    try:
        auth.verify_login_otp(session, code)
    except NotAuthenticated:
        return redirect(f"{PREFIX}/login?notice=expired")
    except InvalidOtp:
        if not session_alive(auth, session, Stage.MFA):
            # UC02 3b: sai quá số lần thì phiên đã bị hủy, phải đăng nhập lại từ đầu.
            return redirect(f"{PREFIX}/login?notice=otp_reset")
        return render(request, "otp.html", {"error": WRONG_OTP},
                      status_code=status.HTTP_400_BAD_REQUEST)
    return redirect(PREFIX)


@router.post("/logout", dependencies=[Csrf])
def logout(auth: Auth, session: SessionToken = None) -> RedirectResponse:
    try:
        auth.logout(session)
    except NotAuthenticated:
        pass  # phiên đã hết hạn: vẫn xóa cookie và về màn hình đăng nhập
    response = redirect(f"{PREFIX}/login?notice=logged_out")
    clear_session_cookie(response)
    return response


# --- Đăng nhập lần đầu của nhân viên (UC01 3b) ------------------------------------------------


@router.get("/setup/password", response_class=HTMLResponse)
def setup_password_page(request: Request) -> HTMLResponse:
    return render(request, "setup_password.html", {"min_length": MIN_PASSWORD_LENGTH})


@router.post("/setup/password", dependencies=[Csrf], response_model=None)
def change_initial_password(
    request: Request, auth: Auth, current_password: Text, new_password: Text,
    confirm_password: Text, session: SessionToken = None,
) -> HTMLResponse | RedirectResponse:
    def rejected(error: str) -> HTMLResponse:
        return render(request, "setup_password.html",
                      {"error": error, "min_length": MIN_PASSWORD_LENGTH},
                      status_code=status.HTTP_400_BAD_REQUEST)

    if new_password != confirm_password:
        return rejected("Mật khẩu nhập lại không khớp.")
    if len(new_password) > MAX_PASSWORD_LENGTH:
        return rejected(f"Mật khẩu mới tối đa {MAX_PASSWORD_LENGTH} ký tự.")
    try:
        auth.change_initial_password(session, current_password, new_password)
    except NotAuthenticated:
        return redirect(f"{PREFIX}/login?notice=expired")
    except SetupOutOfOrder:
        return redirect(f"{PREFIX}/setup/totp")  # đã đổi mật khẩu ở lượt trước
    except PasswordRejected as exc:
        return rejected(str(exc))
    return redirect(f"{PREFIX}/setup/totp")


@router.get("/setup/totp", response_class=HTMLResponse)
def setup_totp_page(request: Request) -> HTMLResponse:
    return render(request, "setup_totp.html")


@router.post("/setup/totp", dependencies=[Csrf], response_model=None)
def start_totp_enrollment(
    request: Request, auth: Auth, session: SessionToken = None
) -> HTMLResponse | RedirectResponse:
    try:
        enrollment = auth.start_totp_enrollment(session)
    except NotAuthenticated:
        return redirect(f"{PREFIX}/login?notice=expired")
    except SetupOutOfOrder:
        return redirect(f"{PREFIX}/setup/password")
    return render(request, "setup_totp.html",
                  {"secret": enrollment.secret, "otpauth_uri": enrollment.provisioning_uri})


@router.post("/setup/totp/confirm", dependencies=[Csrf], response_model=None)
def confirm_totp_enrollment(
    request: Request, auth: Auth, ctx: Ctx, ip: ClientIp, code: Text,
    session: SessionToken = None,
) -> HTMLResponse | RedirectResponse:
    def failed(code_: int, error: str) -> HTMLResponse:
        return render(request, "setup_totp.html", {"error": error, "started": True},
                      status_code=code_)

    if not ctx.limits.otp.hit(f"{ip}"):
        return failed(status.HTTP_429_TOO_MANY_REQUESTS,
                      ERROR_MESSAGES[status.HTTP_429_TOO_MANY_REQUESTS])
    if not _is_otp(code):
        return failed(status.HTTP_400_BAD_REQUEST, WRONG_OTP)
    try:
        auth.confirm_totp_enrollment(session, code)
    except NotAuthenticated:
        return redirect(f"{PREFIX}/login?notice=expired")
    except SetupOutOfOrder:
        return redirect(f"{PREFIX}/setup/password")
    except InvalidOtp:
        if not session_alive(auth, session, Stage.SETUP):
            return redirect(f"{PREFIX}/login?notice=otp_reset")
        return failed(status.HTTP_400_BAD_REQUEST, WRONG_OTP)
    return redirect(f"{PREFIX}?notice=activated")


# --- UC09 -------------------------------------------------------------------------------------


def _registrations(db: Db, ctx: Ctx, ip: ClientIp) -> RegistrationService:
    return RegistrationService(db, ctx.clock, ctx.sms, ctx.settings, ip)


@router.get("/register", response_class=HTMLResponse)
def register_page(request: Request) -> HTMLResponse:
    return render(request, "register.html", {"form": {}, "min_length": MIN_PASSWORD_LENGTH})


@router.post("/register", dependencies=[Csrf], response_class=HTMLResponse)
def register(
    request: Request, db: Db, ctx: Ctx, ip: ClientIp, full_name: Text, date_of_birth: Text,
    phone: Text, email: Text, password: Text, accept_terms: Annotated[bool, Form()] = False,
) -> HTMLResponse:
    form = {"full_name": full_name, "date_of_birth": date_of_birth, "phone": phone, "email": email}

    def failed(code: int, **context: object) -> HTMLResponse:
        return render(request, "register.html",
                      {"form": form, "min_length": MIN_PASSWORD_LENGTH, **context},
                      status_code=code)

    try:
        body = RegisterRequest.model_validate(
            {**form, "password": password, "accept_terms": accept_terms}
        )
    except ValidationError as exc:
        fields = {str(err["loc"][0]) for err in exc.errors()}
        errors = [message for field, message in _REGISTER_FIELD_ERRORS.items() if field in fields]
        return failed(status.HTTP_400_BAD_REQUEST, field_errors=errors)
    try:
        started = _registrations(db, ctx, ip).start(
            NewRegistration(
                full_name=body.full_name, date_of_birth=body.date_of_birth, phone=body.phone,
                email=str(body.email), password=body.password,
            )
        )
    except DuplicateIdentity:
        return failed(status.HTTP_409_CONFLICT, error=DUPLICATE_MESSAGE)
    return render(request, "register_verify.html", {
        "registration_id": started.registration_id,
        "eligible_for_loan": started.eligible_for_loan,
        "min_age": MIN_AGE,
        "max_age": MAX_AGE,
    })


@router.post("/register/verify", dependencies=[Csrf], response_model=None)
def verify_registration(
    request: Request, db: Db, ctx: Ctx, ip: ClientIp, registration_id: Text, otp: Text
) -> HTMLResponse | RedirectResponse:
    def failed(code: int, error: str) -> HTMLResponse:
        return render(request, "register_verify.html",
                      {"registration_id": registration_id, "error": error}, status_code=code)

    try:
        parsed_id = uuid.UUID(registration_id)
    except ValueError:
        return failed(status.HTTP_400_BAD_REQUEST, ERROR_MESSAGES[status.HTTP_400_BAD_REQUEST])
    if not _is_otp(otp):
        return failed(status.HTTP_400_BAD_REQUEST, WRONG_OTP)
    try:
        _registrations(db, ctx, ip).verify(parsed_id, otp)
    except RegistrationFailed as exc:
        return failed(status.HTTP_400_BAD_REQUEST, str(exc))
    except DuplicateIdentity:
        return failed(status.HTTP_409_CONFLICT, DUPLICATE_MESSAGE)
    return redirect(f"{PREFIX}/login?notice=registered")

