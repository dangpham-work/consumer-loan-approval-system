"""Phụ thuộc xác thực và kiểm tra quyền cho các endpoint (SR03: kiểm tra ở máy chủ cho mọi yêu cầu)."""

from collections.abc import Callable
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, status

from loan_system.api.deps import ClientIp, Ctx, Db
from loan_system.security.rate_limit import SlidingWindowLimiter
from loan_system.services.auth_service import AuthService, CurrentUser, NotAuthenticated

SESSION_COOKIE = "session"
FORBIDDEN_MESSAGE = "Bạn không có quyền thực hiện thao tác này"


def _auth_service(db: Db, ctx: Ctx, ip: ClientIp) -> AuthService:
    return AuthService(db, ctx.clock, ctx.settings, ip)


Auth = Annotated[AuthService, Depends(_auth_service)]
SessionToken = Annotated[str | None, Cookie(alias=SESSION_COOKIE)]


def current_user(auth: Auth, session: SessionToken = None) -> CurrentUser:
    try:
        return auth.authenticate(session)
    except NotAuthenticated as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Chưa đăng nhập") from exc


User = Annotated[CurrentUser, Depends(current_user)]


def enforce_rate_limit(limiter: SlidingWindowLimiter, key: str) -> None:
    """SR12: trả 429 khi vượt giới hạn tần suất (mục 4.2.4)."""
    if not limiter.hit(key):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "Quá nhiều yêu cầu, vui lòng thử lại sau"
        )


def require(permission: str) -> Callable[..., CurrentUser]:
    """Endpoint chỉ dành cho người dùng có quyền `permission` theo ma trận RBAC."""

    def check(user: User, auth: Auth) -> CurrentUser:
        if permission not in user.permissions:
            auth.record_access_denied(user, "PERMISSION", permission)
            raise HTTPException(status.HTTP_403_FORBIDDEN, FORBIDDEN_MESSAGE)
        return user

    return check
