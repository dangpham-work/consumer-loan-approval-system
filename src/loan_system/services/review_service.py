"""UC14 Kiểm tra hồ sơ vay và UC15 Yêu cầu bổ sung (phía NV tín dụng).

Một Hồ sơ vay chỉ có một Người tiếp nhận: NV nhận xử lý trước sẽ giữ hồ sơ vay, kể cả khi hồ sơ vay
quay lại sau khi khách hàng bổ sung. Người tạo (nộp hộ) không được làm Người tiếp nhận (BR06).
"""

import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.orm import Session

from loan_system.adapters.cic import CicGateway
from loan_system.adapters.sms import SmsGateway
from loan_system.clock import Clock
from loan_system.config import Settings
from loan_system.domain.applications import (
    DOCUMENT_TYPES,
    NEED_INFO_DAYS,
    ApplicationStatus,
    DocumentVerdict,
)
from loan_system.repositories.models import ApplicationDocument, Customer, LoanApplication
from loan_system.services.application_service import ApplicationService, ApplicationView
from loan_system.services.audit_service import AuditService
from loan_system.services.auth_service import CurrentUser
from loan_system.services.notification_service import NotificationService
from loan_system.services.scoring_service import ScoringService
from loan_system.services.segregation import SegregationOfDuties


class NotReviewable(Exception):
    """Hồ sơ vay không ở trạng thái Đã nộp."""


class AlreadyReceived(Exception):
    """Hồ sơ vay đã được NV khác nhận xử lý (UC14 2a)."""


class NotTheReceiver(Exception):
    """Chỉ Người tiếp nhận mới được kiểm tra hồ sơ vay này."""


class DocumentNotFound(Exception):
    pass


class DocumentsNotAccepted(Exception):
    """Còn giấy tờ thiếu, chưa xem hoặc không đạt."""


@dataclass(frozen=True)
class InfoRequest:
    message: str
    items: list[str]


class ReviewService:
    def __init__(
        self,
        db: Session,
        clock: Clock,
        settings: Settings,
        sms: SmsGateway,
        cic: CicGateway,
        ip: str | None,
    ) -> None:
        self._db = db
        self._clock = clock
        self._applications = ApplicationService(db, clock, settings, sms, ip)
        self._notifications = NotificationService(db, clock, sms)
        self._scoring = ScoringService(db, clock, settings, sms, cic, ip)
        self._sod = SegregationOfDuties(db, clock, sms, ip)
        self._audit = AuditService(db, clock)
        self._ip = ip

    def claim(self, user: CurrentUser, application_id: uuid.UUID) -> ApplicationView:
        application = self._submitted(user, application_id)
        self._sod.enforce(user, application, "RECEIVE", [application.created_by])
        if application.received_by not in (None, user.employee_id):
            raise AlreadyReceived
        application.received_by = user.employee_id
        self._applications.log("APPLICATION_CLAIM", user, application.id)
        self._applications.commit()
        return self._applications.view(application, user)

    def review_document(
        self,
        user: CurrentUser,
        application_id: uuid.UUID,
        document_id: uuid.UUID,
        verdict: DocumentVerdict,
        note: str | None,
    ) -> ApplicationView:
        application = self._received(user, application_id)
        document = self._db.get(ApplicationDocument, document_id)
        if (
            document is None
            or document.application_id != application.id
            or document.replaced_at is not None
        ):
            raise DocumentNotFound
        document.review_verdict = verdict
        document.review_note = note
        document.reviewed_by = user.employee_id
        document.reviewed_at = self._clock.now()
        self._audit.log(
            "DOCUMENT_REVIEW", actor_id=user.user_id, target_type="APPLICATION_DOCUMENT",
            target_id=document.id, ip_address=self._ip, detail=verdict,
        )
        self._applications.commit()
        return self._applications.view(application, user)

    def verify(self, user: CurrentUser, application_id: uuid.UUID) -> ApplicationView:
        application = self._received(user, application_id)
        documents = self._applications.active_documents(application.id)
        passed = {d.doc_type for d in documents if d.review_verdict == DocumentVerdict.PASS}
        if (
            any(d.review_verdict != DocumentVerdict.PASS for d in documents)
            or passed < set(DOCUMENT_TYPES)
        ):
            raise DocumentsNotAccepted
        self._applications.transition(application, ApplicationStatus.VERIFIED, user.user_id)
        self._applications.log("APPLICATION_VERIFY", user, application.id)
        self._applications.commit()
        # Hồ sơ vay "Hợp lệ" kích hoạt chấm điểm (AD02 A14, UC18), trong giao dịch riêng: việc
        # xác nhận đã lưu dù chấm điểm lỗi.
        self._scoring.score_or_record_failure(application.id)
        return self._applications.view(application, user)

    def request_info(
        self, user: CurrentUser, application_id: uuid.UUID, request: InfoRequest
    ) -> ApplicationView:
        application = self._received(user, application_id)
        deadline = self._clock.now() + timedelta(days=NEED_INFO_DAYS)
        application.need_info_message = request.message
        application.need_info_items = ",".join(request.items)
        application.need_info_deadline = deadline
        self._applications.transition(
            application, ApplicationStatus.NEED_INFO, user.user_id, request.message
        )
        self._applications.log("APPLICATION_REQUEST_INFO", user, application.id)
        customer = self._db.get_one(Customer, application.customer_id)
        self._notifications.notify_customer(
            customer.id,
            "NEED_INFO",
            f"Hồ sơ vay {application.code} cần bổ sung thông tin. "
            f"Hạn chót {deadline:%d/%m/%Y}. Vui lòng mở ứng dụng để xem chi tiết.",
            phone=customer.phone,
        )
        self._applications.commit()
        self._notifications.deliver()
        return self._applications.view(application, user)

    def _submitted(self, user: CurrentUser, application_id: uuid.UUID) -> LoanApplication:
        application = self._applications.load(user, application_id, lock=True)
        if application.status != ApplicationStatus.SUBMITTED:
            raise NotReviewable
        return application

    def _received(self, user: CurrentUser, application_id: uuid.UUID) -> LoanApplication:
        application = self._submitted(user, application_id)
        if application.received_by != user.employee_id:
            raise NotTheReceiver
        return application
