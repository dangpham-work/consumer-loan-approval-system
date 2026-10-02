"""Ghi nhật ký kiểm toán có chuỗi băm (SR09), trong cùng giao dịch với thao tác nghiệp vụ."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from loan_system.clock import Clock
from loan_system.domain.audit import GENESIS_HASH, AuditContent, compute_hash
from loan_system.repositories.counters import lock_audit_chain
from loan_system.repositories.models import AuditLog
from loan_system.security.rate_limit import SlidingWindowLimiter


class AuditService:
    def __init__(
        self, db: Session, clock: Clock, pii_view_limiter: SlidingWindowLimiter | None = None
    ) -> None:
        self._db = db
        self._clock = clock
        self._pii_view_limiter = pii_view_limiter

    def log(
        self,
        action: str,
        *,
        actor_id: uuid.UUID | None = None,
        target_type: str | None = None,
        target_id: str | uuid.UUID | None = None,
        ip_address: str | None = None,
        level: str = "INFO",
        detail: str | None = None,
    ) -> None:
        # Khóa chuỗi đến hết giao dịch để hai giao dịch không cùng nối vào một prev_hash.
        lock_audit_chain(self._db)
        last = self._db.execute(
            select(AuditLog.seq, AuditLog.hash).order_by(AuditLog.seq.desc()).limit(1)
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
            detail=detail,
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
                detail=content.detail,
                prev_hash=prev_hash,
                hash=compute_hash(prev_hash, seq, content),
            )
        )
        self._db.flush()

    def log_pii_view(
        self,
        actor_id: uuid.UUID,
        *,
        target_type: str,
        target_id: str | uuid.UUID,
        ip_address: str | None = None,
    ) -> None:
        """Ghi VIEW_PII (nhân viên xem CCCD/thu nhập đầy đủ của Khách hàng, ma trận RBAC).

        Vượt ngưỡng lượt xem trong cửa sổ (SR09) thì ghi thêm cảnh báo CRITICAL, không chặn: nhân
        viên vẫn cần xem để làm việc, chỉ có Kiểm soát viên chú ý khi tra cứu nhật ký.
        """
        self.log("VIEW_PII", actor_id=actor_id, target_type=target_type, target_id=target_id,
                 ip_address=ip_address)
        if self._pii_view_limiter is not None and not self._pii_view_limiter.hit(str(actor_id)):
            self.log(
                "PII_VIEW_THRESHOLD_EXCEEDED", actor_id=actor_id, target_type=target_type,
                target_id=target_id, ip_address=ip_address, level="CRITICAL",
            )
