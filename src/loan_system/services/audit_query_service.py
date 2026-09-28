"""Kiểm soát viên tra cứu, lọc, xuất và kiểm tra toàn vẹn nhật ký kiểm toán (SR09).

Chỉ đọc: Kiểm soát viên không sửa được nhật ký (AUDIT_VIEW, AUDIT_VERIFY trong ma trận RBAC),
và tầng CSDL cũng từ chối UPDATE/DELETE trên audit_logs cho vai trò app_rw (4.1.2e, migration 0006).
"""

import csv
import io
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from loan_system.domain.audit import AuditContent, AuditRecord, verify_chain
from loan_system.repositories.models import AuditLog

LIST_MAX = 200
EXPORT_MAX_ROWS = 5000

CSV_HEADER = (
    "seq", "created_at", "actor_id", "action", "target_type", "target_id", "ip_address",
    "level", "detail",
)


class ExportTooLarge(Exception):
    """Kết quả lọc vượt quá giới hạn xuất CSV (EXPORT_MAX_ROWS); cần thu hẹp bộ lọc."""


@dataclass(frozen=True)
class AuditLogFilter:
    actor_id: uuid.UUID | None = None
    action: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    level: str | None = None
    from_: datetime | None = None
    to: datetime | None = None


@dataclass(frozen=True)
class AuditLogEntry:
    seq: int
    actor_id: uuid.UUID | None
    action: str
    target_type: str | None
    target_id: str | None
    ip_address: str | None
    level: str
    detail: str | None
    created_at: datetime


class AuditQueryService:
    def __init__(self, db: Session) -> None:
        self._db = db

    def search(
        self, filters: AuditLogFilter, *, limit: int = LIST_MAX, offset: int = 0
    ) -> list[AuditLogEntry]:
        rows = self._db.scalars(
            self._filtered(filters).order_by(AuditLog.seq.desc()).limit(limit).offset(offset)
        ).all()
        return [self._to_entry(row) for row in rows]

    def count(self, filters: AuditLogFilter) -> int:
        return self._db.scalar(
            select(func.count()).select_from(self._filtered(filters).subquery())
        ) or 0

    def export_csv(self, filters: AuditLogFilter) -> str:
        """Xuất CSV có giới hạn (EXPORT_MAX_ROWS): báo lỗi thay vì âm thầm cắt bớt dữ liệu."""
        if self.count(filters) > EXPORT_MAX_ROWS:
            raise ExportTooLarge
        entries = self.search(filters, limit=EXPORT_MAX_ROWS, offset=0)
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(CSV_HEADER)
        for entry in entries:
            writer.writerow([
                entry.seq, entry.created_at.isoformat(), entry.actor_id or "", entry.action,
                entry.target_type or "", entry.target_id or "", entry.ip_address or "",
                entry.level, entry.detail or "",
            ])
        return buffer.getvalue()

    def verify_integrity(self) -> int | None:
        """Trả về seq đầu tiên bị phá vỡ, hoặc None nếu toàn bộ chuỗi còn nguyên vẹn."""
        rows = self._db.scalars(select(AuditLog).order_by(AuditLog.seq)).all()
        return verify_chain([self._to_record(row) for row in rows])

    @staticmethod
    def _filtered(filters: AuditLogFilter) -> Select[AuditLog]:
        query = select(AuditLog)
        if filters.actor_id is not None:
            query = query.where(AuditLog.actor_id == filters.actor_id)
        if filters.action is not None:
            query = query.where(AuditLog.action == filters.action)
        if filters.target_type is not None:
            query = query.where(AuditLog.target_type == filters.target_type)
        if filters.target_id is not None:
            query = query.where(AuditLog.target_id == filters.target_id)
        if filters.level is not None:
            query = query.where(AuditLog.level == filters.level)
        if filters.from_ is not None:
            query = query.where(AuditLog.created_at >= filters.from_)
        if filters.to is not None:
            query = query.where(AuditLog.created_at <= filters.to)
        return query

    @staticmethod
    def _to_entry(row: AuditLog) -> AuditLogEntry:
        return AuditLogEntry(
            seq=row.seq, actor_id=row.actor_id, action=row.action, target_type=row.target_type,
            target_id=row.target_id, ip_address=row.ip_address, level=row.level,
            detail=row.detail, created_at=row.created_at,
        )

    @staticmethod
    def _to_record(row: AuditLog) -> AuditRecord:
        content = AuditContent(
            actor_id=str(row.actor_id) if row.actor_id else None,
            action=row.action,
            target_type=row.target_type,
            target_id=row.target_id,
            ip_address=row.ip_address,
            level=row.level,
            created_at=row.created_at,
            detail=row.detail,
        )
        return AuditRecord(seq=row.seq, content=content, prev_hash=row.prev_hash, hash=row.hash)
