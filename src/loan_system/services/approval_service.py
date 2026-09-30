"""UC23 Phê duyệt, UC24 Từ chối / Trả về hồ sơ vay (màn hình M07, SD05).

Quản lý phê duyệt quyết định trên tờ trình có hiệu lực của hồ sơ vay "Chờ phê duyệt", sau kiểm
tra phân tách nhiệm vụ (SUC01): không là Người tạo, Người tiếp nhận, người thẩm định, và chưa quyết
định trên tờ trình này. Các quyết định được gộp theo AD04. Khi đủ số lượt phê duyệt đã chốt, hạn
mức và kỳ hạn của tờ trình được chốt vào hồ sơ vay, snapshot các trường quan trọng được ký
HMAC-SHA256 bằng khóa toàn vẹn hiện hành và lưu kèm phiên bản khóa trên quyết định cuối (SR08).
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from loan_system.adapters.sms import SmsGateway
from loan_system.clock import Clock
from loan_system.config import Settings
from loan_system.domain.access import APPROVER, DISBURSER
from loan_system.domain.applications import ApplicationStatus
from loan_system.domain.appraisal import Recommendation
from loan_system.domain.text import vnd
from loan_system.domain.approval import (
    Decision,
    Outcome,
    RejectionReason,
    outcome_of,
)
from loan_system.repositories.models import (
    AppraisalReport,
    ApprovalDecision,
    Customer,
    Employee,
    LoanApplication,
)
from loan_system.services.application_service import (
    ApplicationService,
    ApplicationView,
    ConcurrentModification,
)
from loan_system.services.appraisal_service import ReportView, latest_report, report_view
from loan_system.services.audit_service import AuditService
from loan_system.services.integrity_service import IntegrityService
from loan_system.services.auth_service import CurrentUser
from loan_system.services.notification_service import NotificationService
from loan_system.services.scoring_service import ScoreView, explain_score
from loan_system.services.segregation import SegregationOfDuties


AUDIT_ACTIONS = {
    Decision.APPROVE: "LOAN_APPROVE",
    Decision.REJECT: "LOAN_REJECT",
    Decision.RETURN: "LOAN_RETURN",
}


class NotAwaitingApproval(Exception):
    """Hồ sơ vay không ở trạng thái Chờ phê duyệt."""


class NotAppraised(Exception):
    """Hồ sơ vay chưa có tờ trình thẩm định nên chưa có gì để phê duyệt."""


class ReportNotApprovable(Exception):
    """Tờ trình đề xuất từ chối (không có hạn mức, kỳ hạn): chỉ Từ chối hoặc Trả về được."""


@dataclass(frozen=True)
class DecisionView:
    decision: str
    approver: str
    reason_group: str | None
    comment: str | None
    snapshot_hash: str | None
    key_version: int | None
    decided_at: datetime
    superseded: bool  # thuộc tờ trình cũ, đã hết hiệu lực vì bị Trả về


@dataclass(frozen=True)
class ApprovalView:
    application: ApplicationView
    score: ScoreView
    report: ReportView
    annual_rate: Decimal | None
    required_approvals: int | None
    approvals: int  # số lượt Phê duyệt trên tờ trình có hiệu lực ("Cần 2/2 – đã có 1")
    approved_amount: Decimal | None
    approved_term: int | None
    decisions: list[DecisionView]
    can_decide: bool  # M07 ẩn nút quyết định; việc chặn thực sự nằm ở máy chủ
    version: int  # khóa lạc quan: Quản lý gửi lại khi quyết định (UC23 6b)


class ApprovalService:
    def __init__(
        self, db: Session, clock: Clock, settings: Settings, sms: SmsGateway, ip: str | None
    ) -> None:
        self._db = db
        self._clock = clock
        self._applications = ApplicationService(db, clock, settings, sms, ip)
        self._integrity = IntegrityService(db, settings, self._applications)
        self._notifications = NotificationService(db, clock, sms)
        self._audit = AuditService(db, clock)
        self._sod = SegregationOfDuties(db, clock, sms, ip)
        self._ip = ip

    def view(self, user: CurrentUser, application_id: uuid.UUID) -> ApprovalView:
        """M07: hồ sơ vay (dữ liệu đã che), điểm tín dụng, tờ trình, lịch sử quyết định."""
        application = self._applications.load(user, application_id)
        report = latest_report(self._db, application.id)
        if report is None:
            raise NotAppraised
        view = self._view(user, application, report)
        self._db.rollback()  # chỉ đọc
        return view

    def approve(
        self, user: CurrentUser, application_id: uuid.UUID, version: int, comment: str | None
    ) -> ApprovalView:
        return self._decide(user, application_id, version, Decision.APPROVE, None, comment)

    def reject(
        self, user: CurrentUser, application_id: uuid.UUID, version: int,
        reason: RejectionReason, description: str,
    ) -> ApprovalView:
        return self._decide(user, application_id, version, Decision.REJECT, reason, description)

    def return_to_appraisal(
        self, user: CurrentUser, application_id: uuid.UUID, version: int, clarification: str
    ) -> ApprovalView:
        return self._decide(user, application_id, version, Decision.RETURN, None, clarification)

    # --- Nội bộ -------------------------------------------------------------------------------

    def _decide(
        self,
        user: CurrentUser,
        application_id: uuid.UUID,
        version: int,
        decision: Decision,
        reason: RejectionReason | None,
        comment: str | None,
    ) -> ApprovalView:
        """SD05: kiểm tra SoD, lưu quyết định, gộp theo AD04 rồi chuyển trạng thái."""
        # Khóa dòng: hai Quản lý quyết định đồng thời trên cùng hồ sơ vay thì chạy tuần tự.
        application = self._applications.load(user, application_id, lock=True)
        if application.status != ApplicationStatus.PENDING_APPROVAL:
            raise NotAwaitingApproval
        report = latest_report(self._db, application.id)
        assert report is not None  # Chờ phê duyệt chỉ sau khi nộp tờ trình
        decided = self._decisions_on(report)
        participants = self._participants(application, decided)
        # SUC01 (UC23 bước 2): người đã quyết định trên tờ trình này cũng không được quyết định lại.
        # Kiểm tra trước phiên bản, để vi phạm luôn được ghi nhận dù màn hình đã cũ.
        self._sod.enforce(user, application, decision, participants)
        if application.version != version:
            # UC23 6b (khóa lạc quan): hồ sơ vay đã đổi từ khi Quản lý mở M07, ví dụ Quản lý kia
            # vừa quyết định; phải tải lại để thấy lịch sử quyết định mới rồi mới quyết định.
            raise ConcurrentModification
        if decision == Decision.APPROVE and report.recommendation != Recommendation.APPROVE:
            raise ReportNotApprovable
        assert user.employee_id is not None and application.required_approvals is not None
        outcome = outcome_of(
            [Decision(d.result) for d in decided] + [decision], application.required_approvals
        )
        # Ký trước khi tạo bản ghi: approval_decisions chỉ ghi thêm (app_rw không có UPDATE), nên
        # mã băm phải có ngay trong câu INSERT.
        signature = None
        if outcome == Outcome.APPROVED:
            # SD05 bước 10–12: chốt hạn mức, kỳ hạn của tờ trình rồi ký snapshot.
            assert report.proposed_amount is not None and report.proposed_term is not None
            application.approved_amount = report.proposed_amount
            application.approved_term = report.proposed_term
            signature = self._integrity.sign(application)
        record = ApprovalDecision(
            application_id=application.id,
            appraisal_report_id=report.id,
            approver_id=user.employee_id,
            result=decision,
            reason_group=reason,
            comment=(comment or "").strip() or None,
            snapshot_hash=signature.digest if signature else None,
            key_version=signature.key_version if signature else None,
            decided_at=self._clock.now(),
        )
        self._db.add(record)
        self._bump_version(application)
        self._apply(user, application, report, record, outcome, reason, participants)
        self._audit.log(
            AUDIT_ACTIONS[decision], actor_id=user.user_id, target_type="LOAN_APPLICATION",
            target_id=application.id, ip_address=self._ip,
            detail=" ".join(filter(None, [outcome, reason])),
        )
        self._applications.commit()
        self._notifications.deliver()
        return self._view(user, application, report)

    def _apply(
        self,
        user: CurrentUser,
        application: LoanApplication,
        report: AppraisalReport,
        record: ApprovalDecision,
        outcome: Outcome,
        reason: RejectionReason | None,
        participants: list[uuid.UUID | None],
    ) -> None:
        customer = self._db.get_one(Customer, application.customer_id)
        if outcome == Outcome.APPROVED:
            self._approve(user, application, report, customer)
        elif outcome == Outcome.REJECTED:
            assert reason is not None
            self._applications.transition(
                application, ApplicationStatus.REJECTED, user.user_id, reason.label
            )
            # UC24 bước 4: khách hàng chỉ được báo nhóm lý do, không kèm mô tả nội bộ.
            self._notifications.notify_customer(
                customer.id,
                "APPLICATION_REJECTED",
                f"Hồ sơ vay {application.code} không được chấp thuận. Lý do: {reason.label}.",
                phone=customer.phone,
            )
        elif outcome == Outcome.RETURNED:
            # UC24 1a: về Đang thẩm định; người thẩm định giữ nguyên và lập tờ trình mới, nên các
            # quyết định trên tờ trình cũ hết hiệu lực.
            self._applications.transition(
                application, ApplicationStatus.APPRAISING, user.user_id, record.comment
            )
            if application.appraised_by is not None:
                self._notifications.notify_employee(
                    application.appraised_by,
                    "APPLICATION_RETURNED",
                    f"Hồ sơ vay {application.code} được trả về để làm rõ: {record.comment}",
                )
        else:
            # UC23 6a: chưa đủ số lượt, báo các Quản lý phê duyệt còn được quyết định (SUC01).
            self._notifications.notify_role(
                APPROVER,
                "APPROVAL_NEEDED",
                f"Hồ sơ vay {application.code} đã có một phê duyệt, cần thêm Quản lý phê duyệt.",
                except_employees=[*participants, user.employee_id],
            )

    def _approve(
        self,
        user: CurrentUser,
        application: LoanApplication,
        report: AppraisalReport,
        customer: Customer,
    ) -> None:
        """SD05 bước 13–14: chuyển Đã phê duyệt; thông báo."""
        assert report.proposed_amount is not None
        self._applications.transition(application, ApplicationStatus.APPROVED, user.user_id)
        self._notifications.notify_customer(
            customer.id,
            "APPLICATION_APPROVED",
            f"Hồ sơ vay {application.code} đã được phê duyệt: "
            f"{vnd(report.proposed_amount)} đồng, {report.proposed_term} tháng.",
            phone=customer.phone,
        )
        self._notifications.notify_role(
            DISBURSER,
            "APPLICATION_APPROVED",
            f"Hồ sơ vay {application.code} đã được phê duyệt, chờ giải ngân.",
        )

    @staticmethod
    def _bump_version(application: LoanApplication) -> None:
        """Mọi quyết định đều tăng phiên bản hồ sơ vay, kể cả khi trạng thái chưa đổi (UC23 6a),
        để màn hình M07 mà Quản lý kia đang mở trở thành cũ. Cột phiên bản do SQLAlchemy quản lý
        (`version_id_col`) chỉ tăng khi dòng có thay đổi, nên đánh dấu trạng thái là đã sửa."""
        flag_modified(application, "status")

    def _decisions_on(self, report: AppraisalReport) -> Sequence[ApprovalDecision]:
        return self._db.scalars(
            select(ApprovalDecision).where(ApprovalDecision.appraisal_report_id == report.id)
        ).all()

    @staticmethod
    def _participants(
        application: LoanApplication, decided: Sequence[ApprovalDecision]
    ) -> list[uuid.UUID | None]:
        return [
            application.created_by,
            application.received_by,
            application.appraised_by,
            *(d.approver_id for d in decided),
        ]

    def _view(
        self, user: CurrentUser, application: LoanApplication, report: AppraisalReport
    ) -> ApprovalView:
        rows = self._db.execute(
            select(ApprovalDecision, Employee.full_name)
            .join(Employee, Employee.id == ApprovalDecision.approver_id)
            .join(AppraisalReport, AppraisalReport.id == ApprovalDecision.appraisal_report_id)
            .where(ApprovalDecision.application_id == application.id)
            # Thời điểm có thể trùng nhau; thứ tự tờ trình thì không.
            .order_by(AppraisalReport.seq, ApprovalDecision.decided_at)
        ).all()
        current = [d for d, _ in rows if d.appraisal_report_id == report.id]
        can_decide = (
            application.status == ApplicationStatus.PENDING_APPROVAL
            and user.employee_id not in set(self._participants(application, current))
        )
        return ApprovalView(
            application=self._applications.view(application, user),
            score=explain_score(self._db, application),
            report=report_view(report),
            annual_rate=application.annual_rate,
            required_approvals=application.required_approvals,
            approvals=sum(1 for d in current if d.result == Decision.APPROVE),
            approved_amount=application.approved_amount,
            approved_term=application.approved_term,
            decisions=[
                DecisionView(
                    decision=d.result,
                    approver=name,
                    reason_group=d.reason_group,
                    comment=d.comment,
                    snapshot_hash=d.snapshot_hash,
                    key_version=d.key_version,
                    decided_at=d.decided_at,
                    superseded=d.appraisal_report_id != report.id,
                )
                for d, name in rows
            ],
            can_decide=can_decide,
            version=application.version,
        )
