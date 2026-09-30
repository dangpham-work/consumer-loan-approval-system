"""Khung giao diện Jinja2 (mục 4.3a đề cương): trang khung, menu theo vai trò, CSRF, trang lỗi.

Trang HTML nằm dưới `/app` để không trùng đường dẫn REST API. Tầng giao diện gọi thẳng tầng dịch
vụ và dùng chung cookie phiên với API (`api/access.py`). Máy chủ vẫn kiểm tra quyền cho từng trang
(SR03); menu chỉ ẩn những mục không thuộc quyền, bổ sung chứ không thay thế kiểm tra đó.

CSRF theo kiểu double-submit: cookie `csrf` ngẫu nhiên, mọi biểu mẫu POST gửi kèm cùng giá trị
trong trường ẩn `csrf`.
"""

import hmac
import secrets
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Form, Request, status
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from loan_system.api import errors
from loan_system.api.access import FORBIDDEN_MESSAGE, Auth, SessionToken
from loan_system.api.deps import AppContext
from loan_system.services.auth_service import (
    AuthService,
    CurrentUser,
    NotAuthenticated,
    Stage,
)
from loan_system.web import labels

PREFIX = "/app"
CSRF_COOKIE = "csrf"
_HERE = Path(__file__).parent
TEMPLATES = Jinja2Templates(directory=_HERE / "templates")
TEMPLATES.env.globals.update(labels.GLOBALS)
TEMPLATES.env.filters.update(labels.FILTERS)

# Cùng giọng với thông điệp của REST API (mục 4.2.4): không lộ chi tiết kỹ thuật.
ERROR_MESSAGES = {
    status.HTTP_400_BAD_REQUEST: "Dữ liệu không hợp lệ",
    status.HTTP_403_FORBIDDEN: FORBIDDEN_MESSAGE,
    status.HTTP_404_NOT_FOUND: "Không tìm thấy trang hoặc dữ liệu bạn yêu cầu",
    status.HTTP_405_METHOD_NOT_ALLOWED: "Không tìm thấy trang hoặc dữ liệu bạn yêu cầu",
    status.HTTP_409_CONFLICT: "Dữ liệu đã thay đổi. Vui lòng tải lại trang rồi thử lại.",
    status.HTTP_429_TOO_MANY_REQUESTS: "Quá nhiều yêu cầu, vui lòng thử lại sau",
}
CSRF_MESSAGE = "Biểu mẫu đã hết hạn. Vui lòng tải lại trang rồi thử lại."

# Thông báo góc trên, chọn bằng khóa `?notice=` để không phản chiếu chuỗi tùy ý lên trang.
NOTICES = {
    "expired": "Phiên làm việc đã hết hạn. Vui lòng đăng nhập lại.",
    "login_required": "Vui lòng đăng nhập để tiếp tục.",
    "logged_out": "Bạn đã đăng xuất.",
    "registered": "Đăng ký thành công. Bạn có thể đăng nhập.",
    "activated": "Đã kích hoạt tài khoản.",
    "otp_reset": "Nhập sai mã OTP quá số lần cho phép. Vui lòng đăng nhập lại.",
    "submitted": "Đã nộp hồ sơ vay. Chúng tôi sẽ thông báo khi có kết quả.",
    "cancelled": "Đã hủy hồ sơ vay.",
    "profile_saved": "Đã lưu thông tin cá nhân.",
    "paid": "Đã ghi nhận thanh toán.",
    "settled": "Đã tất toán khoản vay.",
}


@dataclass(frozen=True)
class MenuItem:
    label: str
    path: str
    permission: str | None = None  # None: mọi người dùng đã đăng nhập
    kind: str | None = None  # chỉ loại tài khoản này (CUSTOMER, EMPLOYEE)


# Danh sách màn hình mục 4.3b. M06, M07, M08 mở từ hàng đợi hồ sơ vay (M05), không có mục riêng.
MENU = (
    MenuItem("Trang chủ", PREFIX),
    MenuItem("Nộp hồ sơ vay", f"{PREFIX}/applications/new", "APPLICATION_CREATE", "CUSTOMER"),
    MenuItem("Khoản vay của tôi", f"{PREFIX}/loans", "PAYMENT_RECORD", "CUSTOMER"),
    MenuItem("Thông tin cá nhân", f"{PREFIX}/profile", kind="CUSTOMER"),
    MenuItem("Hàng đợi hồ sơ vay", f"{PREFIX}/queue", "APPLICATION_VIEW", "EMPLOYEE"),
    MenuItem("Nộp hộ hồ sơ vay", f"{PREFIX}/counter", "APPLICATION_CREATE", "EMPLOYEE"),
    MenuItem("Quản trị", f"{PREFIX}/admin", "USER_MANAGE"),
    MenuItem("Nhật ký kiểm toán", f"{PREFIX}/audit", "AUDIT_VIEW"),
    MenuItem("Báo cáo thống kê", f"{PREFIX}/reports", "REPORT_VIEW"),
)


def menu_for(user: CurrentUser) -> list[MenuItem]:
    return [
        item
        for item in MENU
        if (item.permission is None or item.permission in user.permissions)
        and (item.kind is None or item.kind == user.kind)
    ]


class PageError(Exception):
    """Lỗi hiển thị bằng trang lỗi chung, thông điệp theo mã trạng thái."""

    def __init__(self, status_code: int, message: str | None = None) -> None:
        super().__init__(status_code)
        self.status_code = status_code
        self.message = message or ERROR_MESSAGES[status_code]


class LoginRequired(Exception):
    """Chưa có phiên đầy đủ: chuyển về màn hình đăng nhập, hoặc về bước còn dở (nhập OTP, đổi
    mật khẩu tạm) nếu phiên vẫn còn hiệu lực ở giai đoạn đó."""

    def __init__(self, path: str, notice: str | None = None) -> None:
        super().__init__(path)
        self.path = path
        self.notice = notice


def render(
    request: Request,
    template: str,
    context: Mapping[str, Any] | None = None,
    *,
    user: CurrentUser | None = None,
    status_code: int = status.HTTP_200_OK,
) -> HTMLResponse:
    token = request.cookies.get(CSRF_COOKIE) or secrets.token_urlsafe(32)
    ctx: AppContext = request.app.state.ctx
    notice = NOTICES.get(request.query_params.get("notice", ""))
    response = TEMPLATES.TemplateResponse(
        request,
        template,
        {
            "csrf": token,
            "user": user,
            "menu": menu_for(user) if user else [],
            "notice": notice,
            # Đếm ngược cảnh báo hết phiên (SR11), chỉ khi đã đăng nhập.
            "idle_seconds": ctx.settings.session_idle_minutes * 60 if user else None,
            **(context or {}),
        },
        status_code=status_code,
    )
    if request.cookies.get(CSRF_COOKIE) != token:
        response.set_cookie(
            CSRF_COOKIE, token, httponly=True, secure=True, samesite="strict", path=PREFIX
        )
    return response


def redirect(path: str) -> RedirectResponse:
    return RedirectResponse(path, status_code=status.HTTP_303_SEE_OTHER)


# Ô biểu mẫu có thể để trống; kiểm tra bằng schema của REST API (`validate`).
Entry = Annotated[str, Form()]


def validate[M: BaseModel](
    model: type[M], data: Mapping[str, object], messages: Mapping[str, str],
    keep: Collection[str] = (),
) -> tuple[M | None, list[str]]:
    """Kiểm tra biểu mẫu bằng schema của REST API. Ô chữ để trống coi như không nhập (trừ các ô
    trong `keep`); lỗi tiếng Anh của pydantic đổi thành `messages` theo từng trường."""
    entered = {
        k: v for k, v in data.items()
        if k in keep or not isinstance(v, str) or v.strip()
    }
    try:
        return model.model_validate(entered), []
    except ValidationError as exc:
        fields = {str(err["loc"][0]) for err in exc.errors()}
        return None, [message for field, message in messages.items() if field in fields]


def check_csrf(request: Request, csrf: Annotated[str, Form()] = "") -> None:
    expected = request.cookies.get(CSRF_COOKIE)
    if not expected or not hmac.compare_digest(expected.encode(), csrf.encode()):
        raise PageError(status.HTTP_403_FORBIDDEN, CSRF_MESSAGE)


Csrf = Depends(check_csrf)


# Phiên chưa đầy đủ còn hiệu lực thì quay lại đúng bước đang dở.
_UNFINISHED_STAGES = (
    (Stage.MFA, f"{PREFIX}/login/otp"),
    (Stage.SETUP, f"{PREFIX}/setup/password"),
)


def session_alive(auth: AuthService, session: str | None, stage: Stage) -> bool:
    try:
        auth.authenticate(session, stage)
    except NotAuthenticated:
        return False
    return True


def page_user(auth: Auth, session: SessionToken = None) -> CurrentUser:
    try:
        return auth.authenticate(session)
    except NotAuthenticated as exc:
        for stage, path in _UNFINISHED_STAGES:
            if session_alive(auth, session, stage):
                raise LoginRequired(path) from exc
        notice = "expired" if session else "login_required"
        raise LoginRequired(f"{PREFIX}/login", notice) from exc


PageUser = Annotated[CurrentUser, Depends(page_user)]


def require_page(permission: str, kind: str | None = None) -> Callable[..., CurrentUser]:
    """Trang chỉ dành cho người dùng có quyền `permission`, và nếu có `kind` thì chỉ loại tài khoản
    đó; như `api.access.require` và `api.applications.restricted_to`."""

    def check(user: PageUser, auth: Auth) -> CurrentUser:
        if permission not in user.permissions or (kind is not None and user.kind != kind):
            auth.record_access_denied(user, "PERMISSION", permission)
            raise PageError(status.HTTP_403_FORBIDDEN)
        return user

    return check


def is_page(request: Request) -> bool:
    return request.url.path == PREFIX or request.url.path.startswith(f"{PREFIX}/")


def error_page(request: Request, status_code: int, message: str | None = None) -> HTMLResponse:
    return render(
        request,
        "error.html",
        {"status_code": status_code, "message": message or ERROR_MESSAGES.get(status_code)},
        status_code=status_code,
    )


def message_of(exc: Exception) -> str:
    """Thông điệp của lỗi nghiệp vụ, cùng câu với REST API (`api/errors.py`)."""
    fixed = errors.FIXED.get(type(exc))
    return fixed[1] if fixed else str(exc)


def code_of(exc: Exception) -> int:
    """Mã trạng thái của lỗi nghiệp vụ, như REST API."""
    fixed = errors.FIXED.get(type(exc))
    return fixed[0] if fixed else errors.OWN_MESSAGE.get(type(exc), status.HTTP_400_BAD_REQUEST)


def _page_or_api(api_handler: Callable[..., Any], status_code: int) -> Callable[..., Any]:
    async def handle(request: Request, exc: Exception) -> Response:
        if is_page(request):
            return error_page(request, status_code, message_of(exc))
        response: Response = await api_handler(request, exc)
        return response

    return handle


def register(app: FastAPI) -> None:
    app.mount(f"{PREFIX}/static", StaticFiles(directory=_HERE / "static"), name="static")

    # Lỗi nghiệp vụ không được trang tự xử lý (ví dụ hồ sơ vay không tồn tại, ST01): trang lỗi
    # HTML dưới /app, JSON như cũ cho REST API. Gọi sau `errors.register`.
    handled: dict[type[Exception], int] = {
        **{exc_type: code for exc_type, (code, _) in errors.FIXED.items()},
        **errors.OWN_MESSAGE,
    }
    for exc_type, code in handled.items():
        app.add_exception_handler(exc_type, _page_or_api(app.exception_handlers[exc_type], code))

    @app.exception_handler(PageError)
    async def page_error(request: Request, exc: PageError) -> HTMLResponse:
        return error_page(request, exc.status_code, exc.message)

    @app.exception_handler(LoginRequired)
    async def login_required(_: Request, exc: LoginRequired) -> RedirectResponse:
        return redirect(f"{exc.path}?notice={exc.notice}" if exc.notice else exc.path)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> Response:
        # Đường dẫn trang không tồn tại (404, 405) dưới /app: trang lỗi thay cho JSON của API.
        if is_page(request) and exc.status_code in ERROR_MESSAGES:
            return error_page(request, exc.status_code)
        return await http_exception_handler(request, exc)
