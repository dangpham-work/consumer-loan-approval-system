"""UC01 Đăng nhập, UC02 Xác thực OTP, đăng nhập lần đầu của nhân viên, phiên làm việc (SR11).

Phiên đi qua các giai đoạn: nhân viên PENDING bắt đầu ở SETUP (đổi mật khẩu tạm, đăng ký TOTP);
nhân viên ACTIVE bắt đầu ở MFA và chỉ lên FULL sau khi nhập đúng mã TOTP; khách hàng vào thẳng
FULL. Chỉ phiên FULL mới dùng được các chức năng nghiệp vụ.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from loan_system.clock import Clock
from loan_system.config import Settings
from loan_system.domain.access import MIN_PASSWORD_LENGTH, AccountStatus
from loan_system.repositories.atomic import increment, update_matched
from loan_system.repositories.models import (
    Permission,
    Role,
    RolePermission,
    User,
    UserRole,
    UserSession,
)
from loan_system.security.crypto import FieldCipher
from loan_system.security.secrets import (
    hash_password,
    keyed_hash,
    new_session_token,
    verify_password,
)
from loan_system.security.totp import new_totp_secret, provisioning_uri, verify_totp
from loan_system.services.audit_service import AuditService

TOTP_ISSUER = "LoanSystem"


class InvalidCredentials(Exception):
    """Sai tên đăng nhập hoặc mật khẩu; thông báo luôn chung chung (UC01 3a)."""


class AccountLocked(Exception):
    """Tài khoản đang bị khóa tạm vì đăng nhập sai nhiều lần (UC01 3c)."""


class NotAuthenticated(Exception):
    pass


class InvalidOtp(Exception):
    pass


class PasswordRejected(Exception):
    """Mật khẩu mới không đạt chính sách; thông điệp an toàn để hiển thị."""


class SetupOutOfOrder(Exception):
    """Bước đăng nhập lần đầu bị gọi sai thứ tự."""


class Stage(StrEnum):
    SETUP = "SETUP"
    MFA = "MFA"
    FULL = "FULL"


class NextStep(StrEnum):
    HOME = "HOME"
    OTP = "OTP"
    SETUP = "SETUP"


_NEXT_STEP = {Stage.FULL: NextStep.HOME, Stage.MFA: NextStep.OTP, Stage.SETUP: NextStep.SETUP}


@dataclass(frozen=True)
class CurrentUser:
    user_id: uuid.UUID
    session_id: uuid.UUID
    username: str
    customer_id: uuid.UUID | None
    employee_id: uuid.UUID | None
    roles: tuple[str, ...]
    permissions: frozenset[str]

    @property
    def kind(self) -> str:
        return "CUSTOMER" if self.customer_id else "EMPLOYEE"


@dataclass(frozen=True)
class LoginResult:
    token: str
    next_step: NextStep


@dataclass(frozen=True)
class TotpEnrollment:
    secret: str
    provisioning_uri: str


def totp_context(user_id: uuid.UUID) -> str:
    return f"users.totp_secret:{user_id}"


class AuthService:
    def __init__(self, db: Session, clock: Clock, settings: Settings, ip: str | None) -> None:
        self._db = db
        self._clock = clock
        self._settings = settings
        self._audit = AuditService(db, clock)
        self._cipher = FieldCipher(settings.data_enc_key)
        self._ip = ip

    # --- UC01 ---------------------------------------------------------------------------------

    def login(self, username: str, password: str) -> LoginResult:
        """Trả về token phiên và bước tiếp theo; chỉ mã băm của token được lưu."""
        user = self._db.scalars(select(User).where(User.username == username)).one_or_none()
        # Luôn chạy Argon2 (kể cả khi tài khoản không tồn tại) để thời gian phản hồi không lộ
        # tên đăng nhập nào có thật.
        password_ok = verify_password(user.password_hash if user else None, password)
        now = self._clock.now()
        if user is not None and user.locked_until is not None and user.locked_until > now:
            self._fail(user)
            raise AccountLocked
        stage = self._initial_stage(user)
        if user is None or not password_ok or stage is None:
            locked = user is not None and not password_ok and self._count_failure(user, now)
            self._fail(user)
            raise AccountLocked if locked else InvalidCredentials
        token = new_session_token()
        self._db.add(
            UserSession(
                token_hash=self._token_hash(token),
                user_id=user.id,
                created_at=now,
                last_seen_at=now,
                stage=stage,
                otp_failed_attempts=0,
            )
        )
        if stage is Stage.FULL:
            self._record_login(user, now)
        self._db.commit()
        return LoginResult(token, _NEXT_STEP[stage])

    def _initial_stage(self, user: User | None) -> Stage | None:
        if user is None:
            return None
        if user.status == AccountStatus.ACTIVE:
            return Stage.MFA if user.employee_id else Stage.FULL
        if user.status == AccountStatus.PENDING and user.employee_id:
            return Stage.SETUP
        return None  # LOCKED, DISABLED (UC01 3d)

    def _count_failure(self, user: User, now: datetime) -> bool:
        """Tăng bộ đếm sai bằng một câu UPDATE nguyên tử; trả về True nếu vừa khóa tài khoản.

        Sai mật khẩu và sai mã TOTP dùng chung bộ đếm, và bộ đếm chỉ về 0 khi đăng nhập xong hẳn:
        biết mật khẩu mà đoán mã TOTP qua nhiều lần đăng nhập vẫn bị khóa sau 5 lần sai (SR01).
        """
        failures = increment(self._db, User.failed_attempts, User.id == user.id)
        if failures < self._settings.login_max_failures:
            return False
        self._db.execute(
            update(User)
            .where(User.id == user.id)
            .values(
                failed_attempts=0,
                locked_until=now + timedelta(minutes=self._settings.lockout_minutes),
            )
        )
        self._audit.log(
            "ACCOUNT_LOCKED", target_type="USER", target_id=user.id, ip_address=self._ip,
            level="WARNING",
        )
        return True

    def _fail(self, user: User | None) -> None:
        self._audit.log(
            "LOGIN_FAIL", target_type="USER", target_id=user.id if user else None,
            ip_address=self._ip, level="WARNING",
        )
        self._db.commit()

    def _record_login(self, user: User, now: datetime) -> None:
        self._db.execute(
            update(User)
            .where(User.id == user.id)
            .values(failed_attempts=0, locked_until=None, last_login_at=now)
        )
        self._audit.log(
            "LOGIN_SUCCESS", actor_id=user.id, target_type="USER", target_id=user.id,
            ip_address=self._ip,
        )

    # --- Phiên --------------------------------------------------------------------------------

    def authenticate(self, token: str | None, stage: Stage = Stage.FULL) -> CurrentUser:
        session, user = self._load_session(token, stage)
        return CurrentUser(
            user_id=user.id,
            session_id=session.id,
            username=user.username,
            customer_id=user.customer_id,
            employee_id=user.employee_id,
            roles=self._roles_of(user.id),
            permissions=self._permissions_of(user.id),
        )

    def _load_session(self, token: str | None, stage: Stage) -> tuple[UserSession, User]:
        if not token:
            raise NotAuthenticated
        row = self._db.execute(
            select(UserSession, User)
            .join(User, User.id == UserSession.user_id)
            .where(UserSession.token_hash == self._token_hash(token))
            .where(UserSession.revoked_at.is_(None))
            .where(UserSession.stage == stage)
            .where(
                User.status
                == (AccountStatus.PENDING if stage is Stage.SETUP else AccountStatus.ACTIVE)
            )
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
        return session, user

    def _roles_of(self, user_id: uuid.UUID) -> tuple[str, ...]:
        codes = self._db.scalars(
            select(Role.code)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user_id)
            .order_by(Role.code)
        )
        return tuple(codes)

    def _permissions_of(self, user_id: uuid.UUID) -> frozenset[str]:
        codes = self._db.scalars(
            select(Permission.code)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .join(UserRole, UserRole.role_id == RolePermission.role_id)
            .where(UserRole.user_id == user_id)
        )
        return frozenset(codes)

    def logout(self, token: str | None) -> None:
        session, user = self._load_session(token, Stage.FULL)
        session.revoked_at = self._clock.now()
        self._audit.log("LOGOUT", actor_id=user.id, target_type="USER", target_id=user.id,
                        ip_address=self._ip)
        self._db.commit()

    def record_access_denied(
        self, user: CurrentUser, target_type: str, target_id: str | uuid.UUID
    ) -> None:
        """Ghi lại lần bị từ chối truy cập (SR03, SR04); chỉ ghi, không thay đổi dữ liệu."""
        self._audit.log(
            "ACCESS_DENIED", actor_id=user.user_id, target_type=target_type, target_id=target_id,
            ip_address=self._ip, level="WARNING",
        )
        self._db.commit()

    # --- UC02 ---------------------------------------------------------------------------------

    def verify_login_otp(self, token: str | None, code: str) -> None:
        session, user = self._load_session(token, Stage.MFA)
        self._check_otp(session, user, code)
        session.stage = Stage.FULL
        session.otp_failed_attempts = 0
        self._record_login(user, self._clock.now())
        self._db.commit()

    def confirm_step_up(self, current: CurrentUser, code: str) -> None:
        """Xác thực lại bằng TOTP trước thao tác nhạy cảm (SR02 step-up, UC04 2a)."""
        session = self._db.get_one(UserSession, current.session_id)
        user = self._db.get_one(User, current.user_id)
        self._check_otp(session, user, code)
        session.otp_failed_attempts = 0
        self._audit.log("STEP_UP_OK", actor_id=user.id, target_type="USER", target_id=user.id,
                        ip_address=self._ip)
        self._db.commit()

    def _check_otp(self, session: UserSession, user: User, code: str) -> None:
        if user.totp_secret_enc is None:
            raise InvalidOtp
        secret = self._cipher.decrypt(user.totp_secret_enc, context=totp_context(user.id))
        step = verify_totp(secret, code, self._clock.now(), user.totp_last_step)
        # Cập nhật có điều kiện: hai yêu cầu song song cùng một mã thì chỉ một yêu cầu thắng.
        if step is not None and update_matched(
            self._db,
            update(User)
            .where(User.id == user.id)
            .where(or_(User.totp_last_step.is_(None), User.totp_last_step < step))
            .values(totp_last_step=step),
        ):
            return
        attempts = increment(
            self._db, UserSession.otp_failed_attempts, UserSession.id == session.id
        )
        self._audit.log(
            "OTP_FAIL", actor_id=user.id, target_type="USER", target_id=user.id,
            ip_address=self._ip, level="WARNING",
        )
        locked = self._count_failure(user, self._clock.now())
        if locked or attempts >= self._settings.otp_max_attempts:
            # UC02 3b: sai quá 3 lần thì hủy phiên, phải đăng nhập lại từ đầu.
            session.revoked_at = self._clock.now()
        self._db.commit()
        raise InvalidOtp

    # --- Đăng nhập lần đầu (UC01 3b) ------------------------------------------------------------

    def change_initial_password(self, token: str | None, current: str, new: str) -> None:
        session, user = self._load_session(token, Stage.SETUP)
        if not user.must_change_password:
            raise SetupOutOfOrder
        if not verify_password(user.password_hash, current):
            raise PasswordRejected("Mật khẩu hiện tại không đúng.")
        if len(new) < MIN_PASSWORD_LENGTH:
            raise PasswordRejected(f"Mật khẩu mới phải có ít nhất {MIN_PASSWORD_LENGTH} ký tự.")
        if new == current:
            raise PasswordRejected("Mật khẩu mới phải khác mật khẩu tạm.")
        user.password_hash = hash_password(new)
        user.must_change_password = False
        # UC03: đổi mật khẩu thì hủy mọi phiên khác.
        self._db.execute(
            update(UserSession)
            .where(UserSession.user_id == user.id)
            .where(UserSession.id != session.id)
            .where(UserSession.revoked_at.is_(None))
            .values(revoked_at=self._clock.now())
        )
        self._audit.log("PASSWORD_CHANGE", actor_id=user.id, target_type="USER",
                        target_id=user.id, ip_address=self._ip)
        self._db.commit()

    def start_totp_enrollment(self, token: str | None) -> TotpEnrollment:
        _, user = self._load_session(token, Stage.SETUP)
        if user.must_change_password:
            raise SetupOutOfOrder
        secret = new_totp_secret()
        user.totp_secret_enc = self._cipher.encrypt(secret, context=totp_context(user.id))
        user.totp_last_step = None
        self._audit.log("TOTP_ENROLL_START", actor_id=user.id, target_type="USER",
                        target_id=user.id, ip_address=self._ip)
        self._db.commit()
        return TotpEnrollment(secret, provisioning_uri(secret, user.username, TOTP_ISSUER))

    def confirm_totp_enrollment(self, token: str | None, code: str) -> None:
        session, user = self._load_session(token, Stage.SETUP)
        if user.must_change_password or user.totp_secret_enc is None:
            raise SetupOutOfOrder
        self._check_otp(session, user, code)
        user.status = AccountStatus.ACTIVE
        session.stage = Stage.FULL
        session.otp_failed_attempts = 0
        self._audit.log("TOTP_ENROLL", actor_id=user.id, target_type="USER", target_id=user.id,
                        ip_address=self._ip)
        self._record_login(user, self._clock.now())
        self._db.commit()

    def _token_hash(self, token: str) -> str:
        return keyed_hash(self._settings.session_secret, token)
