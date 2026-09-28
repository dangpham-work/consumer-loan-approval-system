"""Ghi nhật ký kiểm toán có chuỗi băm (SR09), trong cùng giao dịch với thao tác nghiệp vụ."""

import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from loan_system.clock import Clock
from loan_system.domain.audit import GENESIS_HASH, AuditContent, compute_hash
from loan_system.repositories.models import AuditLog


class AuditService:
    def __init__(self, db: Session, clock: Clock) -> None:
        self._db = db
        self._clock = clock

    def log(
        self,
        action: str,
        *,
        actor_id: uuid.UUID | None = None,
        target_type: str | None = None,
        target_id: str | uuid.UUID | None = None,
        ip_address: str | None = None,
        level: str = "INFO",
    ) -> None:
        # Khóa bản ghi cuối đến hết giao dịch để hai giao dịch không cùng nối vào một prev_hash.
        last = self._db.execute(
            text("SELECT TOP 1 seq, hash FROM audit_logs WITH (UPDLOCK, HOLDLOCK) ORDER BY seq DESC")
        ).one_or_none()
        seq, prev_hash = (last.seq + 1, last.hash) if last else (1, GENESIS_HASH)
        content = AuditContent(
            actor_id=str(actor_id) if actor_id else None,
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id else None,
            ip_address=ip_address,
            level=level,
            created_at=self._clock.now(),
        )
        self._db.add(
            AuditLog(
                seq=seq,
                actor_id=actor_id,
                action=content.action,
                target_type=content.target_type,
                target_id=content.target_id,
                ip_address=content.ip_address,
                level=content.level,
                created_at=content.created_at,
                prev_hash=prev_hash,
                hash=compute_hash(prev_hash, seq, content),
            )
        )
        self._db.flush()
