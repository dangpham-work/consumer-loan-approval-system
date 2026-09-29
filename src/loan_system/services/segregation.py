"""SUC01 Kiểm tra phân tách nhiệm vụ (BR06): người tạo, người tiếp nhận, người thẩm định, người phê
duyệt và người giải ngân của cùng một Hồ sơ vay phải là những người khác nhau."""

import uuid
from collections.abc import Iterable

from sqlalchemy.orm import Session

from loan_system.adapters.sms import SmsGateway
from loan_system.clock import Clock
from loan_system.domain.access import AUDITOR
from loan_system.repositories.models import LoanApplication
from loan_system.services.audit_service import AuditService
from loan_system.services.auth_service import CurrentUser
from loan_system.services.notification_service import NotificationService


class SodViolation(Exception):
    """Vi phạm phân tách nhiệm vụ (BR06, SUC01)."""


class SegregationOfDuties:
    def __init__(self, db: Session, clock: Clock, sms: SmsGateway, ip: str | None) -> None:
        self._db = db
        self._audit = AuditService(db, clock)
        self._notifications = NotificationService(db, clock, sms)
        self._ip = ip

    def enforce(
        self,
        user: CurrentUser,
        application: LoanApplication,
        action: str,
        participants: Iterable[uuid.UUID | None],
    ) -> None:
        """Chặn khi người dùng đã tham gia một bước khác của hồ sơ vay: ghi SOD_VIOLATION mức
        WARNING và báo Kiểm soát viên (SUC01 2a), trong giao dịch riêng vì thao tác bị hủy."""
        if user.employee_id is None or user.employee_id not in set(participants):
            return
        self._db.rollback()
        self._audit.log(
            "SOD_VIOLATION", actor_id=user.user_id, target_type="LOAN_APPLICATION",
            target_id=application.id, ip_address=self._ip, level="WARNING", detail=action,
        )
        self._notifications.notify_role(
            AUDITOR,
            "SOD_VIOLATION",
            f"Phát hiện vi phạm phân tách nhiệm vụ ({action}) trên hồ sơ vay {application.code}.",
        )
        self._db.commit()
        raise SodViolation
