"""UC05 Quản lý vai trò – quyền: xem, tạo vai trò và gán/bỏ quyền theo ma trận RBAC."""

import uuid
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from loan_system.clock import Clock
from loan_system.domain.access import admin_role_lending_permission, conflicting_permission_pair
from loan_system.repositories.models import Permission, Role, RolePermission
from loan_system.services.audit_service import AuditService
from loan_system.services.auth_service import CurrentUser


class DuplicateRole(Exception):
    """Mã vai trò đã tồn tại."""


class RoleNotFound(Exception):
    pass


class UnknownPermission(Exception):
    """Một hoặc nhiều mã quyền không tồn tại."""


class ConflictingPermissions(Exception):
    """UC05 4a: cặp quyền xung đột trong tập quyền định gán cho vai trò."""

    def __init__(self, pair: tuple[str, str]) -> None:
        self.pair = pair
        super().__init__(f"Quyền {pair[0]} và {pair[1]} không được gán cho cùng một vai trò")


class AdminCannotHoldLendingPermission(Exception):
    """Vai trò ADMIN không được có quyền nghiệp vụ cho vay (ma trận RBAC)."""

    def __init__(self, permission: str) -> None:
        self.permission = permission
        super().__init__(f"Vai trò ADMIN không được có quyền nghiệp vụ cho vay: {permission}")


@dataclass(frozen=True)
class RoleView:
    code: str
    name: str
    permissions: list[str]


class RoleService:
    def __init__(self, db: Session, clock: Clock, ip: str | None) -> None:
        self._db = db
        self._clock = clock
        self._audit = AuditService(db, clock)
        self._ip = ip

    def list_roles(self) -> list[RoleView]:
        roles = self._db.scalars(select(Role).order_by(Role.code)).all()
        return [RoleView(role.code, role.name, self._permissions_of(role.id)) for role in roles]

    def list_permissions(self) -> list[tuple[str, str]]:
        rows = self._db.execute(
            select(Permission.code, Permission.description).order_by(Permission.code)
        ).all()
        return [(row.code, row.description) for row in rows]

    def create(
        self, actor: CurrentUser, code: str, name: str, permissions: frozenset[str]
    ) -> None:
        """UC05 bước 2–5: tạo vai trò mới kèm tập quyền ban đầu."""
        pair = conflicting_permission_pair(set(permissions))
        if pair is not None:
            raise ConflictingPermissions(pair)
        lending = admin_role_lending_permission(code, set(permissions))
        if lending is not None:
            raise AdminCannotHoldLendingPermission(lending)
        permission_ids = self._permission_ids(permissions)
        role = Role(id=uuid.uuid4(), code=code, name=name)
        self._db.add(role)
        try:
            self._db.flush()
        except IntegrityError as exc:
            self._db.rollback()
            raise DuplicateRole from exc
        self._db.add_all(
            RolePermission(role_id=role.id, permission_id=pid) for pid in permission_ids
        )
        self._audit.log(
            "ROLE_CREATE", actor_id=actor.user_id, target_type="ROLE", target_id=role.id,
            ip_address=self._ip, detail=f"{code}: {','.join(sorted(permissions))}",
        )
        self._db.commit()

    def set_permissions(self, actor: CurrentUser, code: str, permissions: frozenset[str]) -> None:
        """UC05 bước 2–5: thay tập quyền hiện có của một vai trò."""
        role = self._db.scalars(select(Role).where(Role.code == code)).one_or_none()
        if role is None:
            raise RoleNotFound
        pair = conflicting_permission_pair(set(permissions))
        if pair is not None:
            raise ConflictingPermissions(pair)
        lending = admin_role_lending_permission(code, set(permissions))
        if lending is not None:
            raise AdminCannotHoldLendingPermission(lending)
        permission_ids = self._permission_ids(permissions)
        before = self._permissions_of(role.id)
        self._db.execute(delete(RolePermission).where(RolePermission.role_id == role.id))
        self._db.add_all(
            RolePermission(role_id=role.id, permission_id=pid) for pid in permission_ids
        )
        # UC05 hậu điều kiện: có hiệu lực từ yêu cầu kế tiếp (quyền tính lại mỗi lần xác thực).
        self._audit.log(
            "ROLE_PERMISSIONS_UPDATE", actor_id=actor.user_id, target_type="ROLE",
            target_id=role.id, ip_address=self._ip,
            detail=f"{','.join(before)} -> {','.join(sorted(permissions))}",
        )
        self._db.commit()

    def _permission_ids(self, codes: frozenset[str]) -> list[uuid.UUID]:
        if not codes:
            return []
        rows = self._db.execute(select(Permission.id).where(Permission.code.in_(codes))).all()
        if len(rows) != len(codes):
            raise UnknownPermission
        return [row.id for row in rows]

    def _permissions_of(self, role_id: uuid.UUID) -> list[str]:
        codes = self._db.scalars(
            select(Permission.code)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .where(RolePermission.role_id == role_id)
            .order_by(Permission.code)
        )
        return list(codes)
