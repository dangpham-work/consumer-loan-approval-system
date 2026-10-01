"""UC18 Chấm điểm tín dụng tự động, UC19 Tra cứu CIC, UC20 Giải thích kết quả chấm điểm (AD03, SD03).

Chạy ngay sau khi Hồ sơ vay được xác nhận hợp lệ, trong giao dịch riêng: lỗi ở bước chấm điểm không
làm mất việc xác nhận của NV tín dụng, và Hồ sơ vay ở lại "Hợp lệ" để được chấm lại (UC18 4a).
"""

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select, true
from sqlalchemy.orm import Session

from loan_system.adapters.cic import CicGateway, CicReport, CicTimeout
from loan_system.adapters.sms import SmsGateway
from loan_system.clock import Clock
from loan_system.config import Settings
from loan_system.domain.access import ADMIN, APPRAISER
from loan_system.domain.applications import ApplicationStatus
from loan_system.domain.eligibility import age_on
from loan_system.domain.scoring import (
    ApplicantFeatures,
    CreditScore,
    FactorScore,
    RuleBasedScoringModel,
    fraud_suspected,
    knock_out,
    loan_dti,
)
from loan_system.repositories.models import (
    ApprovalPolicy,
    CicReportRecord,
    CreditScoreRecord,
    Customer,
    LoanApplication,
    ScoringModelVersion,
)
from loan_system.services.application_service import ApplicationService
from loan_system.services.audit_service import AuditService
from loan_system.services.auth_service import CurrentUser
from loan_system.services.notification_service import NotificationService

GRADE_D_REASON = "Điểm tín dụng chưa đạt yêu cầu"


class ScoreNotFound(Exception):
    """Hồ sơ vay chưa được chấm điểm."""


@dataclass(frozen=True)
class CicView:
    highest_debt_group: int
    total_outstanding: Decimal
    lender_count: int
    monthly_obligation: Decimal
    queried_at: datetime


@dataclass(frozen=True)
class ScoreView:
    score: int | None
    grade: str | None
    knock_out_reason: str | None
    dti: Decimal
    factors: list[FactorScore]
    top_factors: list[str]
    model_version: str | None
    scored_at: datetime
    annual_rate: Decimal | None
    cic_missing: bool
    fraud_suspected: bool
    cic: CicView | None


class ScoringService:
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
        self._settings = settings
        self._cic = cic
        self._applications = ApplicationService(db, clock, settings, sms, ip)
        self._notifications = NotificationService(db, clock, sms)
        self._audit = AuditService(db, clock)

    # --- UC18 ---------------------------------------------------------------------------------

    def score(self, application_id: uuid.UUID) -> None:
        """Chấm điểm một Hồ sơ vay đang ở "Hợp lệ"; trạng thái khác thì bỏ qua."""
        application = self._db.scalars(
            select(LoanApplication)
            .where(LoanApplication.id == application_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).one_or_none()
        if application is None or application.status != ApplicationStatus.VERIFIED:
            return
        customer = self._db.get_one(Customer, application.customer_id)
        report = self._cic_report(application, customer)
        application.cic_missing = report is None
        declared = application.existing_monthly_debt or Decimal(0)
        obligation = report.monthly_obligation if report else None
        application.fraud_suspected = fraud_suspected(declared, obligation)
        income = self._applications.monthly_income_of(customer)
        policy = self._db.scalars(
            select(ApprovalPolicy).where(ApprovalPolicy.is_active == true())
        ).one()
        features = ApplicantFeatures(
            # BR01: tuổi tại thời điểm nộp hồ sơ vay.
            age=age_on(customer.dob, (application.submitted_at or self._clock.now()).date()),
            monthly_income=income,
            dti=loan_dti(
                monthly_income=income,
                declared_debt=declared,
                cic_obligation=obligation,
                amount=application.requested_amount,
                term_months=application.term_months,
                annual_rate=policy.ceiling_rate,
            ),
            cic_debt_group=report.highest_debt_group if report else None,
            employment_years=customer.employment_years or 0,
            utility_late_payments=report.utility_late_payments if report else None,
            housing_type=customer.housing_type or "",
        )
        reason = knock_out(features)
        if reason is not None:
            self._save(application, features, CreditScore(None, None, reason, (), None))
            self._reject(application, customer, reason)
        else:
            model = self._active_model()
            if model is None:
                self._integrity_failure(application)
                return
            result = model.score(features)
            self._save(application, features, result)
            if result.is_rejected:
                self._reject(application, customer, GRADE_D_REASON)
            else:
                assert result.grade is not None
                application.policy_id = policy.id
                application.annual_rate = policy.rate_for(result.grade)
                self._applications.transition(application, ApplicationStatus.APPRAISING, None)
                self._notifications.notify_role(
                    APPRAISER,
                    "APPLICATION_SCORED",
                    f"Hồ sơ vay {application.code} đã được chấm điểm, đang chờ thẩm định.",
                )
        self._applications.commit()
        self._notifications.deliver()

    def score_or_record_failure(self, application_id: uuid.UUID) -> None:
        """Chấm điểm; lỗi bất ngờ thì hoàn tác phần chấm điểm, ghi `SCORING_FAILED` mức CRITICAL và
        để Hồ sơ vay ở lại "Hợp lệ" cho tác vụ hằng đêm chấm lại (UC18 4a)."""
        try:
            self.score(application_id)
        except Exception:
            self._db.rollback()
            self._audit.log(
                "SCORING_FAILED", target_type="LOAN_APPLICATION", target_id=application_id,
                level="CRITICAL",
            )
            self._db.commit()

    def _active_model(self) -> RuleBasedScoringModel | None:
        """Mô hình hiệu lực nếu file của nó khớp checksum đã đăng ký (UC18 bước 4)."""
        registered = self._db.scalars(
            select(ScoringModelVersion).where(ScoringModelVersion.is_active == true())
        ).one()
        try:
            content = (self._settings.scoring_model_dir / registered.file_name).read_bytes()
        except OSError:
            return None
        model = RuleBasedScoringModel(content, registered.checksum)
        return model if model.verify_integrity() else None

    def _integrity_failure(self, application: LoanApplication) -> None:
        """UC18 4a: dừng chấm điểm, cảnh báo Quản trị viên; Hồ sơ vay giữ nguyên "Hợp lệ"."""
        self._audit.log(
            "MODEL_INTEGRITY_FAIL", target_type="LOAN_APPLICATION", target_id=application.id,
            level="CRITICAL",
        )
        self._notifications.notify_role(
            ADMIN,
            "MODEL_INTEGRITY_FAIL",
            "File mô hình chấm điểm không khớp checksum, việc chấm điểm đã dừng. "
            f"Hồ sơ vay {application.code} đang chờ chấm lại.",
        )
        self._applications.commit()

    def _save(
        self, application: LoanApplication, features: ApplicantFeatures, result: CreditScore
    ) -> None:
        factors = [
            {"code": f.code, "label": f.label, "points": f.points, "max_points": f.max_points}
            for f in result.factors
        ]
        self._db.add(
            CreditScoreRecord(
                application_id=application.id,
                score=result.score,
                grade=result.grade,
                knock_out_reason=result.knock_out_reason,
                dti=features.dti.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
                factors_json=json.dumps(factors, ensure_ascii=False),
                model_version=result.model_version,
                scored_at=self._clock.now(),
            )
        )
        detail = result.knock_out_reason or f"{result.score} {result.grade} {result.model_version}"
        self._audit.log(
            "SCORED", target_type="LOAN_APPLICATION", target_id=application.id,
            detail=detail[:500],
        )

    def _reject(self, application: LoanApplication, customer: Customer, reason: str) -> None:
        self._applications.transition(application, ApplicationStatus.REJECTED, None, reason)
        self._notifications.notify_customer(
            customer.id,
            "APPLICATION_REJECTED",
            f"Hồ sơ vay {application.code} không được chấp thuận. Lý do: {reason}.",
            phone=customer.phone,
        )

    # --- UC19 ---------------------------------------------------------------------------------

    def _cic_report(self, application: LoanApplication, customer: Customer) -> CicReport | None:
        """Báo cáo CIC dưới 30 ngày của Khách hàng thì dùng lại (1a); không thì tra cứu, hết thời
        gian chờ thì thử lại với thời gian chờ tăng dần (2a). None = Thiếu dữ liệu CIC."""
        now = self._clock.now()
        recent = self._db.scalars(
            select(CicReportRecord)
            .join(LoanApplication, LoanApplication.id == CicReportRecord.application_id)
            .where(LoanApplication.customer_id == customer.id)
            .where(CicReportRecord.queried_at >= now - timedelta(days=self._settings.cic_reuse_days))
            .order_by(CicReportRecord.queried_at.desc())
        ).first()
        if recent is not None:
            report = CicReport(
                recent.highest_debt_group, recent.total_outstanding, recent.lender_count,
                recent.monthly_obligation, recent.utility_late_payments,
            )
            if recent.application_id != application.id:
                self._record(application, report, recent.queried_at)
            self._log_cic("CIC_REUSE", application)
            return report
        # UC19 bước 1: giải mã CCCD trong bộ nhớ, chỉ gửi tới cổng CIC, không ghi nhật ký.
        national_id = self._applications.national_id_of(customer)
        reference = application.code or str(application.id)
        for timeout in self._settings.cic_timeouts_seconds:
            try:
                report = self._cic.query(national_id, reference, timeout)
            except CicTimeout:
                continue
            self._record(application, report, self._clock.now())
            self._log_cic("CIC_QUERY", application)
            return report
        self._log_cic("CIC_UNAVAILABLE", application, level="WARNING")
        return None

    def _record(self, application: LoanApplication, report: CicReport, at: datetime) -> None:
        self._db.add(
            CicReportRecord(
                application_id=application.id,
                highest_debt_group=report.highest_debt_group,
                total_outstanding=report.total_outstanding,
                lender_count=report.lender_count,
                monthly_obligation=report.monthly_obligation,
                utility_late_payments=report.utility_late_payments,
                queried_at=at,
            )
        )

    def _log_cic(self, action: str, application: LoanApplication, level: str = "INFO") -> None:
        self._audit.log(action, target_type="LOAN_APPLICATION", target_id=application.id,
                        level=level)

    # --- UC20 ---------------------------------------------------------------------------------

    def explain(self, user: CurrentUser, application_id: uuid.UUID) -> ScoreView:
        return explain_score(self._db, self._applications.load(user, application_id))


def latest_cic_report(db: Session, application: LoanApplication) -> CicReportRecord | None:
    """Báo cáo CIC đang dùng cho hồ sơ vay; None khi Thiếu dữ liệu CIC."""
    if application.cic_missing:
        return None
    return db.scalars(
        select(CicReportRecord)
        .where(CicReportRecord.application_id == application.id)
        .order_by(CicReportRecord.queried_at.desc())
    ).first()


def explain_score(db: Session, application: LoanApplication) -> ScoreView:
    """Kết quả chấm điểm mới nhất kèm giải thích (UC20); người gọi đã kiểm tra quyền xem."""
    record = db.scalars(
        select(CreditScoreRecord)
        .where(CreditScoreRecord.application_id == application.id)
        .order_by(CreditScoreRecord.scored_at.desc())
    ).first()
    if record is None:
        raise ScoreNotFound
    cic = latest_cic_report(db, application)
    factors = tuple(FactorScore(**f) for f in json.loads(record.factors_json))
    result = CreditScore(
        record.score, record.grade, record.knock_out_reason, factors, record.model_version
    )
    return ScoreView(
        score=record.score,
        grade=record.grade,
        knock_out_reason=record.knock_out_reason,
        dti=record.dti,
        factors=list(factors),
        top_factors=[f.code for f in result.top_factors],
        model_version=record.model_version,
        scored_at=record.scored_at,
        annual_rate=application.annual_rate,
        cic_missing=application.cic_missing,
        fraud_suspected=application.fraud_suspected,
        cic=(
            CicView(
                cic.highest_debt_group, cic.total_outstanding, cic.lender_count,
                cic.monthly_obligation, cic.queried_at,
            )
            if cic is not None
            else None
        ),
    )
