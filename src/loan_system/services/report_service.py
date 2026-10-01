"""UC32 Xem báo cáo thống kê (FR08.1, màn hình M11), quyền REPORT_VIEW (Quản lý phê duyệt).

Báo cáo gộp mọi chỉ tiêu của M11 vào một lần gọi: đề cương chỉ liệt kê một bộ biểu đồ cố định cho
màn hình này ("Biểu đồ hồ sơ theo trạng thái, tỷ lệ duyệt, dư nợ, tỷ lệ quá hạn"), không có khái
niệm "loại báo cáo" khác cần chọn riêng.
"""

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from loan_system.clock import Clock
from loan_system.domain.applications import ApplicationStatus
from loan_system.domain.loans import LoanStatus
from loan_system.domain.report import (
    APPLICATION_STATUSES,
    CREDIT_GRADES,
    DEBT_GROUPS,
    StatisticsReport,
    average_days,
    ensure_valid_range,
    rate,
    render_statistics_csv,
    render_statistics_pdf,
)
from loan_system.repositories.models import (
    ApplicationStatusHistory,
    CreditScoreRecord,
    Disbursement,
    Loan,
    LoanApplication,
)
from loan_system.services.audit_service import AuditService
from loan_system.services.auth_service import CurrentUser

# Một Hồ sơ vay coi là "đã duyệt" nếu đã từng vào APPROVED, kể cả khi sau đó đã giải ngân hoặc bị
# khóa vì đối chiếu HMAC không khớp (LOCKED, ticket #10): trạng thái đó vẫn bắt nguồn từ một quyết
# định duyệt.
_APPROVED_LIKE = frozenset({
    ApplicationStatus.APPROVED.value, ApplicationStatus.DISBURSED.value, ApplicationStatus.LOCKED.value,
})
_DECIDED_STATUSES = (ApplicationStatus.APPROVED.value, ApplicationStatus.REJECTED.value)
_OVERDUE_LOAN = frozenset({LoanStatus.OVERDUE.value, LoanStatus.BAD_DEBT.value})


def _bounds(from_date: date, to_date: date) -> tuple[datetime, datetime]:
    """Khoảng [from_date, to_date] theo UTC, chuyển thành [từ, đến) nửa mở để so sánh mốc giờ."""
    start = datetime.combine(from_date, time.min, tzinfo=UTC)
    end = datetime.combine(to_date + timedelta(days=1), time.min, tzinfo=UTC)
    return start, end


class ReportService:
    def __init__(self, db: Session, clock: Clock, ip: str | None) -> None:
        self._db = db
        self._clock = clock
        self._audit = AuditService(db, clock)
        self._ip = ip

    def statistics(self, from_date: date, to_date: date) -> StatisticsReport:
        """UC32 bước 1–2: tổng hợp chỉ tiêu hoạt động cho vay trong khoảng thời gian đã chọn."""
        ensure_valid_range(from_date, to_date)
        start, end = _bounds(from_date, to_date)

        by_status = {
            status: count
            for status, count in self._db.execute(
                select(LoanApplication.status, func.count())
                .where(LoanApplication.submitted_at >= start, LoanApplication.submitted_at < end)
                .group_by(LoanApplication.status)
            ).all()
        }
        total_applications = sum(by_status.values())
        approved_count = sum(by_status.get(s, 0) for s in _APPROVED_LIKE)
        rejected_count = by_status.get(ApplicationStatus.REJECTED.value, 0)
        avg_processing_days = average_days(self._processing_days(start, end))

        total_disbursed = self._db.scalar(
            select(func.coalesce(func.sum(Disbursement.amount), 0)).where(
                Disbursement.status == "SUCCESS",
                Disbursement.completed_at >= start, Disbursement.completed_at < end,
            )
        ) or Decimal(0)

        loans = self._db.execute(
            select(Loan.status, Loan.debt_group, Loan.outstanding_principal)
            .where(Loan.disbursed_at >= start, Loan.disbursed_at < end)
        ).all()
        total_loans = len(loans)
        outstanding_principal = sum((loan.outstanding_principal for loan in loans), Decimal(0))
        loans_by_debt_group = {group: 0 for group in DEBT_GROUPS}
        overdue_loan_count = 0
        for loan in loans:
            loans_by_debt_group[loan.debt_group] = loans_by_debt_group.get(loan.debt_group, 0) + 1
            if loan.status in _OVERDUE_LOAN:
                overdue_loan_count += 1

        credit_grade_distribution = {grade: 0 for grade in CREDIT_GRADES}
        for grade in self._latest_grades(start, end):
            if grade is not None:
                credit_grade_distribution[grade] = credit_grade_distribution.get(grade, 0) + 1

        return StatisticsReport(
            from_date=from_date, to_date=to_date, total_applications=total_applications,
            applications_by_status={s: by_status.get(s, 0) for s in APPLICATION_STATUSES},
            approved_count=approved_count, rejected_count=rejected_count,
            approval_rate=rate(approved_count, approved_count + rejected_count),
            avg_processing_days=avg_processing_days,
            total_disbursed=total_disbursed, total_loans=total_loans,
            outstanding_principal=outstanding_principal, loans_by_debt_group=loans_by_debt_group,
            overdue_loan_count=overdue_loan_count,
            overdue_loan_rate=rate(overdue_loan_count, total_loans),
            credit_grade_distribution=credit_grade_distribution,
        )

    def _processing_days(self, start: datetime, end: datetime) -> list[Decimal]:
        """Thời gian xử lý = từ khi nộp đến khi có quyết định đầu tiên (Đã duyệt/Từ chối)."""
        rows = self._db.execute(
            select(LoanApplication.submitted_at, func.min(ApplicationStatusHistory.changed_at))
            .join(
                ApplicationStatusHistory,
                ApplicationStatusHistory.application_id == LoanApplication.id,
            )
            .where(
                LoanApplication.submitted_at >= start, LoanApplication.submitted_at < end,
                ApplicationStatusHistory.status.in_(_DECIDED_STATUSES),
            )
            .group_by(LoanApplication.id, LoanApplication.submitted_at)
        ).all()
        return [
            Decimal((decided_at - submitted_at).total_seconds()) / Decimal(86400)
            for submitted_at, decided_at in rows
            if submitted_at is not None and decided_at is not None
        ]

    def _latest_grades(self, start: datetime, end: datetime) -> list[str | None]:
        """Hạng tín dụng hiệu lực (bản chấm điểm mới nhất) của các hồ sơ vay nộp trong kỳ."""
        latest = (
            select(
                CreditScoreRecord.application_id,
                func.max(CreditScoreRecord.scored_at).label("scored_at"),
            )
            .group_by(CreditScoreRecord.application_id)
            .subquery()
        )
        rows = self._db.scalars(
            select(CreditScoreRecord.grade)
            .join(
                latest,
                (CreditScoreRecord.application_id == latest.c.application_id)
                & (CreditScoreRecord.scored_at == latest.c.scored_at),
            )
            .join(LoanApplication, LoanApplication.id == CreditScoreRecord.application_id)
            .where(LoanApplication.submitted_at >= start, LoanApplication.submitted_at < end)
        ).all()
        return list(rows)

    def export(
        self, actor: CurrentUser, report: StatisticsReport, fmt: Literal["CSV", "PDF"]
    ) -> bytes:
        """UC32 3a: xuất Excel/PDF, ghi log REPORT_EXPORT (chỉ số liệu tổng hợp, SR07)."""
        self._audit.log(
            "REPORT_EXPORT", actor_id=actor.user_id, target_type="REPORT", ip_address=self._ip,
            detail=f"{fmt} {report.from_date.isoformat()}..{report.to_date.isoformat()}",
        )
        self._db.commit()
        if fmt == "CSV":
            return render_statistics_csv(report).encode("utf-8")
        return render_statistics_pdf(report)
