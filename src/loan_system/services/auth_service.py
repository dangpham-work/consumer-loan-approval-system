"""UC01 Đăng nhập, phiên làm việc phía máy chủ (SR11) và đăng xuất."""

import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from loan_system.clock import Clock
from loan_system.config import Settings
from loan_system.repositories.models import User, UserSession
from loan_system.security.secrets import keyed_hash, new_session_token, verify_password
from loan_system.services.audit_service import AuditService


class InvalidCredentials(Exception):
    """Sai tên đăng nhập hoặc mật khẩu; thông báo luôn chung chung (UC01 3a)."""


class NotAuthenticated(Exception):
    pass


@dataclass(frozen=True)
class CurrentUser:
    user_id: uuid.UUID
    username: str
    role: str


class AuthService:
    def __init__(self, db: Session, clock: Clock, settings: Settings, ip: str | None) -> None:
        self._db = db
        self._clock = clock
        self._settings = settings
        self._audit = AuditService(db, clock)
        self._ip = ip

    def login(self, username: str, password: str) -> str:
        """Trả về token phiên; chỉ mã băm của token được lưu."""
        user = self._db.scalars(select(User).where(User.username == username)).one_or_none()
        # Luôn chạy Argon2 (kể cả khi tài khoản không tồn tại) để thời gian phản hồi không lộ
        # số điện thoại nào đã đăng ký.
        password_ok = verify_password(user.password_hash if user else None, password)
        # Chỉ tài khoản ACTIVE được đăng nhập; khóa tạm sau 5 lần sai (SR01) làm ở ticket #3.
        if user is None or not password_ok or user.status != "ACTIVE":
            self._audit.log(
                "LOGIN_FAIL", target_type="USER", target_id=user.id if user else None,
                ip_address=self._ip, level="WARNING",
            )
            self._db.commit()
            raise InvalidCredentials
        now = self._clock.now()
        token = new_session_token()
        user.last_login_at = now
        self._db.add(
            UserSession(
                token_hash=keyed_hash(self._settings.session_secret, token),
                user_id=user.id,
                created_at=now,
                last_seen_at=now,
            )
        )
        self._audit.log("LOGIN_SUCCESS", actor_id=user.id, target_type="USER", target_id=user.id,
                        ip_address=self._ip)
        self._db.commit()
        return token

    def authenticate(self, token: str | None) -> CurrentUser:
        if not token:
            raise NotAuthenticated
        row = self._db.execute(
            select(UserSession, User)
            .join(User, User.id == UserSession.user_id)
            .where(UserSession.token_hash == keyed_hash(self._settings.session_secret, token))
            .where(UserSession.revoked_at.is_(None))
            .where(User.status == "ACTIVE")
        ).one_or_none()
        if row is None:
            raise NotAuthenticated
        session, user = row
        now = self._clock.now()
        if now - session.last_seen_at > timedelta(minutes=self._settings.session_idle_minutes):
            session.revoked_at = now
            self._db.commit()
            raise NotAuthenticated
        session.last_seen_at = now
        self._db.commit()
        return CurrentUser(user.id, user.username, "CUSTOMER" if user.customer_id else "EMPLOYEE")

    def logout(self, token: str | None) -> None:
        current = self.authenticate(token)
        session = self._db.scalars(
            select(UserSession).where(
                UserSession.token_hash == keyed_hash(self._settings.session_secret, token or "")
            )
        ).one()
        session.revoked_at = self._clock.now()
        self._audit.log("LOGOUT", actor_id=current.user_id, target_type="USER",
                        target_id=current.user_id, ip_address=self._ip)
        self._db.commit()
