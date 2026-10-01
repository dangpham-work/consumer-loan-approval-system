"""UC04 Quản lý tài khoản nhân viên: tạo tài khoản PENDING với mật khẩu tạm, gán vai trò."""

import secrets
import uuid
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from loan_system.adapters.email import EmailGateway
from loan_system.clock import Clock
from loan_system.domain.access import (
    ADMIN,
    CUSTOMER,
    AccountStatus,
    is_self_escalation,
    mixes_admin_and_lending,
)
from loan_system.repositories.models import Employee, Role, User, UserRole
from loan_system.security.secrets import hash_password
from loan_system.services.audit_service import AuditService
from loan_system.services.auth_service import CurrentUser


class DuplicateAccount(Exception):
    """Tên đăng nhập hoặc email đã được dùng (UC04 3a)."""


class UnknownRole(Exception):
    """Vai trò không tồn tại hoặc không gán được cho nhân viên."""


class StaffNotFound(Exception):
    pass


class SelfEscalation(Exception):
    """Quản trị viên tự gán vai trò nghiệp vụ cho chính mình (UC04 2d)."""


class ConflictingRoles(Exception):
    """Tập vai trò kết hợp ADMIN với vai trò nghiệp vụ cho vay."""


@dataclass(frozen=True)
class NewStaff:
    username: str
    full_name: str
    email: str
    branch: str
    roles: frozenset[str]


@dataclass(frozen=True)
class StaffView:
    user_id: uuid.UUID
    username: str
    full_name: str
    email: str
    branch: str
    status: str
    roles: list[str]


def new_temporary_password() -> str:
    return secrets.token_urlsafe(12)  # 16 ký tự ngẫu nhiên, dài hơn MIN_PASSWORD_LENGTH (SR01)


def _insert_staff(db: Session, clock: Clock, data: NewStaff, password: str) -> User:
    role_ids = _staff_role_ids(db, data.roles)
    taken = db.scalars(
        select(User.id).where(User.username == data.username).union(
            select(Employee.id).where(Employee.email == data.email)
        )
    ).first()
    if taken is not None:
        raise DuplicateAccount
    now = clock.now()
    employee = Employee(
        full_name=data.full_name, email=data.email, branch=data.branch, created_at=now
    )
    db.add(employee)
    db.flush()
    user = User(
        username=data.username,
        password_hash=hash_password(password),
        status=AccountStatus.PENDING,
        failed_attempts=0,
        employee_id=employee.id,
        must_change_password=True,
        created_at=now,
    )
    db.add(user)
    db.flush()
    db.add_all(UserRole(user_id=user.id, role_id=role_id) for role_id in role_ids)
    try:
        db.flush()
    except IntegrityError as exc:
        # Hai yêu cầu cùng tên đăng nhập/email chạy song song: chỉ một cái thắng.
        db.rollback()
        raise DuplicateAccount from exc
    return user


def _staff_role_ids(db: Session, codes: Iterable[str]) -> list[uuid.UUID]:
    """Mã định danh của các vai trò gán được cho nhân viên; kiểm tra tập vai trò hợp lệ."""
    wanted = set(codes)
    if CUSTOMER in wanted:
        raise UnknownRole
    if mixes_admin_and_lending(wanted):
        raise ConflictingRoles
    rows = db.execute(select(Role.code, Role.id).where(Role.code.in_(wanted))).all()
    if not wanted or len(rows) != len(wanted):
        raise UnknownRole
    return [row.id for row in rows]


def create_first_admin(
    db: Session, clock: Clock, *, username: str, full_name: str, email: str
) -> str:
    """Tạo Quản trị viên đầu tiên khi triển khai; trả về mật khẩu tạm để trao tay."""
    password = new_temporary_password()
    user = _insert_staff(
        db, clock, NewStaff(username, full_name, email, "Hội sở", frozenset({ADMIN})), password
    )
    AuditService(db, clock).log("USER_CREATE", target_type="USER", target_id=user.id)
    db.commit()
    return password


class StaffService:
    def __init__(self, db: Session, clock: Clock, email: EmailGateway, ip: str | None) -> None:
        self._db = db
        self._clock = clock
        self._email = email
        self._audit = AuditService(db, clock)
        self._ip = ip

    def list_staff(self) -> list[StaffView]:
        """UC04 bước 1 (M09): danh sách tài khoản nhân viên kèm vai trò."""
        rows = self._db.execute(
            select(User, Employee)
            .join(Employee, Employee.id == User.employee_id)
            .order_by(User.username)
        ).all()
        views = [self._view(user, employee) for user, employee in rows]
        self._db.rollback()  # chỉ đọc
        return views

    def get(self, user_id: uuid.UUID) -> StaffView:
        row = self._db.execute(
            select(User, Employee)
            .join(Employee, Employee.id == User.employee_id)
            .where(User.id == user_id)
        ).one_or_none()
        if row is None:
            self._db.rollback()
            raise StaffNotFound
        view = self._view(*row)
        self._db.rollback()  # chỉ đọc
        return view

    def create(self, actor: CurrentUser, data: NewStaff) -> uuid.UUID:
        password = new_temporary_password()
        user = _insert_staff(self._db, self._clock, data, password)
        self._audit.log(
            "USER_CREATE", actor_id=actor.user_id, target_type="USER", target_id=user.id,
            ip_address=self._ip, detail=f"roles: {','.join(sorted(data.roles))}",
        )
        self._db.commit()
        # UC04 bước 4: mật khẩu tạm chỉ gửi qua email công việc, không trả về trong API.
        self._email.send(
            data.email,
            "Tài khoản hệ thống xét duyệt vay",
            f"Tên đăng nhập: {data.username}\nMật khẩu tạm: {password}\n"
            "Bạn phải đổi mật khẩu và đăng ký ứng dụng xác thực ở lần đăng nhập đầu tiên.",
        )
        return user.id

    def set_roles(self, actor: CurrentUser, user_id: uuid.UUID, roles: frozenset[str]) -> None:
        user = self._db.get(User, user_id)
        if user is None or user.employee_id is None:
            raise StaffNotFound
        if is_self_escalation(actor.user_id, user_id, set(roles)):
            self._audit.log(
                "ROLE_ASSIGN_DENIED", actor_id=actor.user_id, target_type="USER",
                target_id=user_id, ip_address=self._ip, level="WARNING",
            )
            self._db.commit()
            raise SelfEscalation
        role_ids = _staff_role_ids(self._db, roles)
        before = self._db.scalars(
            select(Role.code)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user_id)
            .order_by(Role.code)
        ).all()
        self._db.execute(delete(UserRole).where(UserRole.user_id == user_id))
        self._db.add_all(UserRole(user_id=user_id, role_id=role_id) for role_id in role_ids)
        # UC04: ghi nhật ký kèm giá trị trước/sau.
        self._audit.log(
            "ROLE_ASSIGN", actor_id=actor.user_id, target_type="USER", target_id=user_id,
            ip_address=self._ip, detail=f"{','.join(before)} -> {','.join(sorted(roles))}",
        )
        self._db.commit()

    def _view(self, user: User, employee: Employee) -> StaffView:
        roles = self._db.scalars(
            select(Role.code)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user.id)
            .order_by(Role.code)
        ).all()
        return StaffView(
            user_id=user.id, username=user.username, full_name=employee.full_name,
            email=employee.email, branch=employee.branch, status=user.status, roles=list(roles),
        )
