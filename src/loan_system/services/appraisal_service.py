"""UC22 Thẩm định hồ sơ vay (màn hình M06, SD04).

Chuyên viên mở hồ sơ vay "Đang thẩm định" thì trở thành người thẩm định duy nhất của nó (sau kiểm
tra phân tách nhiệm vụ). Màn hình thẩm định hiển thị CCCD và thu nhập đầy đủ, nên mỗi lần mở đều
ghi VIEW_PII. Nộp tờ trình thì DTI được tính lại theo lãi suất của Hạng thật với hạn mức, kỳ hạn đề
xuất (ADR 0001), số lượt phê duyệt được chốt theo hạn mức đề xuất (BR05), và hồ sơ vay chuyển "Chờ
phê duyệt" kể cả khi đề xuất từ chối (UC22 4b).
"""

import uuid
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from loan_system.adapters.sms import SmsGateway
from loan_system.clock import Clock
from loan_system.config import Settings
from loan_system.domain.access import APPROVER
from loan_system.domain.applications import ApplicationStatus
from loan_system.domain.appraisal import (
    ApprovalTier,
    InvalidProposal,
    Proposal,
    Recommendation,
    required_approvals,
)
from loan_system.domain.calculations import annuity_payment
from loan_system.domain.scoring import MAX_DTI, loan_dti
from loan_system.repositories.models import (
    ApplicationDocument,
    AppraisalReport,
    ApprovalPolicyTier,
    Customer,
    Employee,
    LoanApplication,
)
from loan_system.security.rate_limit import SlidingWindowLimiter
from loan_system.security.watermark import stamp_image, watermark_text
from loan_system.services.application_service import ApplicationService, ApplicationView
from loan_system.services.audit_service import AuditService
from loan_system.services.auth_service import CurrentUser
from loan_system.services.notification_service import NotificationService
from loan_system.services.review_service import DocumentNotFound
from loan_system.services.scoring_service import ScoreView, explain_score, latest_cic_report
from loan_system.services.segregation import SegregationOfDuties


PII_PERMISSION = "CUSTOMER_VIEW_PII"


class NotAppraisable(Exception):
    """Hồ sơ vay không ở trạng thái Đang thẩm định."""


class AlreadyAppraised(Exception):
    """Hồ sơ vay đã có chuyên viên khác thẩm định."""


class NotTheAppraiser(Exception):
    """Chỉ người thẩm định của hồ sơ vay (đã mở hồ sơ) mới thực hiện được."""


class DtiTooHigh(Exception):
    """UC22 5a: DTI với hạn mức, kỳ hạn đề xuất vượt 50%."""


class DocumentNotViewable(Exception):
    """Không đọc được ảnh để in watermark; không trả file gốc thay thế."""


@dataclass(frozen=True)
class DocumentContent:
    content: bytes
    content_type: str
    watermark: str
    stamped: bool  # watermark đã in vào nội dung file (PDF: trình xem tự phủ lên)


@dataclass(frozen=True)
class ReportView:
    recommendation: str
    proposed_amount: Decimal | None
    proposed_term: int | None
    dti: Decimal | None
    fraud_suspected: bool
    comment: str
    created_at: datetime


@dataclass(frozen=True)
class AppraisalView:
    application: ApplicationView
    score: ScoreView
    annual_rate: Decimal | None
    required_approvals: int | None
    report: ReportView | None


@dataclass(frozen=True)
class DtiPreview:
    annual_rate: Decimal
    monthly_payment: Decimal
    dti: Decimal
    within_limit: bool


class AppraisalService:
    def __init__(
        self,
        db: Session,
        clock: Clock,
        settings: Settings,
        sms: SmsGateway,
        pii_view_limiter: SlidingWindowLimiter,
        ip: str | None,
    ) -> None:
        self._db = db
        self._clock = clock
        self._settings = settings
        self._applications = ApplicationService(db, clock, settings, sms, ip)
        self._notifications = NotificationService(db, clock, sms)
        self._audit = AuditService(db, clock, pii_view_limiter)
        self._sod = SegregationOfDuties(db, clock, sms, ip)
        self._ip = ip

    def open(self, user: CurrentUser, application_id: uuid.UUID) -> AppraisalView:
        """SD04 bước 2–9: kiểm tra SoD, nhận thẩm định, hiển thị hồ sơ vay với PII đầy đủ."""
        application = self._appraising(user, application_id)
        if application.appraised_by not in (None, user.employee_id):
            raise AlreadyAppraised
        if application.appraised_by is None:
            application.appraised_by = user.employee_id
            self._applications.log("APPRAISAL_ASSIGN", user, application.id)
        # M06: CCCD và thu nhập hiển thị đầy đủ nên mỗi lần mở hồ sơ vay đều ghi VIEW_PII.
        reveal = PII_PERMISSION in user.permissions
        if reveal:
            self._audit.log_pii_view(
                user.user_id, target_type="CUSTOMER", target_id=application.customer_id,
                ip_address=self._ip,
            )
        self._applications.commit()
        return self._view(user, application, reveal_pii=reveal)

    def preview_dti(
        self, user: CurrentUser, application_id: uuid.UUID, amount: Decimal, term_months: int
    ) -> DtiPreview:
        """M06: DTI tính lại khi chuyên viên đổi hạn mức hoặc kỳ hạn đề xuất."""
        application = self._assigned(user, application_id)
        if amount > application.requested_amount:
            raise InvalidProposal("Hạn mức đề xuất vượt số tiền yêu cầu")
        rate = self._rate(application)
        dti = self._dti(application, amount, term_months)
        self._db.rollback()  # chỉ đọc: nhả khóa dòng
        return DtiPreview(rate, annuity_payment(amount, rate, term_months), _ratio(dti),
                          dti <= MAX_DTI)

    def submit(
        self, user: CurrentUser, application_id: uuid.UUID, proposal: Proposal,
        fraud_suspected: bool,
    ) -> AppraisalView:
        """SD04 bước 11–19: lưu tờ trình, chốt số lượt phê duyệt, chuyển Chờ phê duyệt."""
        application = self._assigned(user, application_id)
        proposal.validate_against(application.requested_amount)
        dti: Decimal | None = None
        amount = application.requested_amount
        if proposal.recommendation == Recommendation.APPROVE:
            assert proposal.amount is not None and proposal.term_months is not None
            dti = self._dti(application, proposal.amount, proposal.term_months)
            if dti > MAX_DTI:
                raise DtiTooHigh
            amount = proposal.amount
        tiers = self._db.scalars(
            select(ApprovalPolicyTier).where(ApprovalPolicyTier.policy_id == application.policy_id)
        ).all()
        application.required_approvals = required_approvals(
            [ApprovalTier(t.min_amount, t.max_amount, t.required_approvals) for t in tiers], amount
        )
        assert user.employee_id is not None
        self._db.add(
            AppraisalReport(
                application_id=application.id,
                appraiser_id=user.employee_id,
                recommendation=proposal.recommendation,
                proposed_amount=proposal.amount if dti is not None else None,
                proposed_term=proposal.term_months if dti is not None else None,
                dti=_ratio(dti) if dti is not None else None,
                fraud_suspected=fraud_suspected,
                comment=proposal.comment.strip(),
                created_at=self._clock.now(),
            )
        )
        self._applications.transition(application, ApplicationStatus.PENDING_APPROVAL, user.user_id)
        self._audit.log(
            "APPRAISE", actor_id=user.user_id, target_type="LOAN_APPLICATION",
            target_id=application.id, ip_address=self._ip, detail=proposal.recommendation,
        )
        self._notifications.notify_role(
            APPROVER,
            "APPLICATION_APPRAISED",
            f"Hồ sơ vay {application.code} đã có tờ trình thẩm định, đang chờ phê duyệt.",
        )
        self._applications.commit()
        return self._view(user, application, reveal_pii=False)

    def document(
        self, user: CurrentUser, application_id: uuid.UUID, document_id: uuid.UUID
    ) -> DocumentContent:
        """Trình xem giấy tờ của M06 (MUC06): chỉ người thẩm định, trong lúc thẩm định. Ảnh được in
        watermark người xem; mỗi lượt xem giấy tờ (CCCD, sao kê lương) tính là một lượt VIEW_PII."""
        application = self._assigned(user, application_id)
        if PII_PERMISSION not in user.permissions:
            raise NotTheAppraiser
        document = self._db.get(ApplicationDocument, document_id)
        if document is None or document.application_id != application.id:
            raise DocumentNotFound
        assert user.employee_id is not None
        employee = self._db.get_one(Employee, user.employee_id)
        text = watermark_text(user.username, employee.full_name, self._clock.now())
        raw = (self._settings.document_storage_dir / document.storage_path).read_bytes()
        is_pdf = document.content_type == "application/pdf"
        content = raw if is_pdf else stamp_image(raw, document.content_type, text)
        if content is None:
            raise DocumentNotViewable
        self._audit.log_pii_view(
            user.user_id, target_type="APPLICATION_DOCUMENT", target_id=document.id,
            ip_address=self._ip,
        )
        self._applications.commit()
        return DocumentContent(content, document.content_type, text, stamped=not is_pdf)

    # --- Nội bộ -------------------------------------------------------------------------------

    def _appraising(self, user: CurrentUser, application_id: uuid.UUID) -> LoanApplication:
        application = self._applications.load(user, application_id, lock=True)
        if application.status != ApplicationStatus.APPRAISING:
            raise NotAppraisable
        # SUC01: Người tạo và Người tiếp nhận không được thẩm định chính hồ sơ vay đó.
        self._sod.enforce(
            user, application, "APPRAISE", [application.created_by, application.received_by]
        )
        return application

    def _assigned(self, user: CurrentUser, application_id: uuid.UUID) -> LoanApplication:
        application = self._appraising(user, application_id)
        if application.appraised_by != user.employee_id:
            raise NotTheAppraiser
        return application

    @staticmethod
    def _rate(application: LoanApplication) -> Decimal:
        assert application.annual_rate is not None  # đã chốt khi chấm điểm
        return application.annual_rate

    def _dti(self, application: LoanApplication, amount: Decimal, term_months: int) -> Decimal:
        customer = self._db.get_one(Customer, application.customer_id)
        cic = latest_cic_report(self._db, application)
        return loan_dti(
            monthly_income=self._applications.monthly_income_of(customer),
            declared_debt=application.existing_monthly_debt or Decimal(0),
            cic_obligation=cic.monthly_obligation if cic else None,
            amount=amount,
            term_months=term_months,
            annual_rate=self._rate(application),
        )

    def _view(
        self, user: CurrentUser, application: LoanApplication, *, reveal_pii: bool
    ) -> AppraisalView:
        view = self._applications.view(application, user)
        if reveal_pii:
            customer = self._db.get_one(Customer, application.customer_id)
            view = replace(
                view,
                applicant=replace(
                    view.applicant,
                    national_id=self._applications.national_id_of(customer) or None,
                    monthly_income=self._applications.monthly_income_of(customer),
                ),
            )
        latest = self._db.scalars(
            select(AppraisalReport)
            .where(AppraisalReport.application_id == application.id)
            .order_by(AppraisalReport.created_at.desc())
        ).first()
        return AppraisalView(
            application=view,
            score=explain_score(self._db, application),
            annual_rate=application.annual_rate,
            required_approvals=application.required_approvals,
            report=(
                ReportView(
                    latest.recommendation, latest.proposed_amount, latest.proposed_term,
                    latest.dti, latest.fraud_suspected, latest.comment, latest.created_at,
                )
                if latest is not None
                else None
            ),
        )


def _ratio(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
