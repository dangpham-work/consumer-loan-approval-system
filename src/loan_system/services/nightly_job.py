"""Tác vụ hằng đêm do Bộ lập lịch kích hoạt lúc 00:30 (AD06a, SD08).

- UC29: chuyển kỳ quá hạn, tính lại phí phạt từ đầu (mục 1.2.8c), cập nhật trạng thái và nhóm nợ
  của khoản vay (BR09), chuyển Nợ xấu khi quá hạn trên 90 ngày và báo Quản lý phê duyệt.
- UC30: nhắc nợ trước hạn 3 ngày, đúng ngày đến hạn và khi quá hạn 1/7/15/30 ngày.
- BR11: hủy hồ sơ vay "Yêu cầu bổ sung" đã quá hạn bổ sung.
- UC18 4a: chấm lại hồ sơ vay kẹt ở "Hợp lệ" quá 1 giờ.

Chạy lại trong cùng đêm (hoặc chạy bù sau khi lỗi giữa chừng) không cộng dồn: phí phạt được tính
lại chứ không cộng thêm, mỗi mốc nhắc nợ được ghi ở `payment_reminders` nên chỉ gửi một lần, còn
các chuyển trạng thái chỉ xảy ra một lần. Khoản vay được xử lý theo lô, mỗi lô một giao dịch
(UC29 ngoại lệ).
"""

import uuid
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, sessionmaker

from loan_system.adapters.cic import CicGateway
from loan_system.adapters.sms import SmsGateway
from loan_system.clock import Clock
from loan_system.config import Settings
from loan_system.domain.access import APPROVER
from loan_system.domain.applications import ApplicationStatus, mask
from loan_system.domain.loans import UNPAID_INSTALLMENT, UNSETTLED, InstallmentStatus, LoanStatus
from loan_system.domain.overdue import (
    ReminderKind,
    debt_group,
    is_bad_debt,
    overdue_reminder,
    recalculated_penalty,
)
from loan_system.domain.text import vnd
from loan_system.repositories.models import (
    ApplicationStatusHistory,
    Customer,
    Installment,
    Loan,
    LoanApplication,
    PaymentReminder,
)
from loan_system.services.application_service import ApplicationService
from loan_system.services.audit_service import AuditService
from loan_system.services.notification_service import NotificationService
from loan_system.services.scoring_service import ScoringService

BATCH_SIZE = 500  # UC29 bước 2
REMIND_DAYS_BEFORE = 3  # UC30 bước 1
RESCORE_AFTER = timedelta(hours=1)  # UC18 4a (docs/de-cuong-thay-doi.md, Q14)
NEED_INFO_EXPIRED_REASON = "Quá hạn bổ sung hồ sơ (BR11)"


@dataclass
class NightlyReport:
    run_on: date
    overdue_installments: int = 0
    bad_debts: int = 0
    reminders: int = 0
    sms_failed: int = 0
    cancelled_applications: int = 0
    rescored_applications: int = 0

    def summary(self) -> str:
        return (
            f"run_on={self.run_on} overdue_installments={self.overdue_installments} "
            f"bad_debts={self.bad_debts} reminders={self.reminders} sms_failed={self.sms_failed} "
            f"cancelled_applications={self.cancelled_applications} "
            f"rescored_applications={self.rescored_applications}"
        )


class _Batch:
    """Một lô xử lý trong một giao dịch: thông báo và nhật ký ghi cùng giao dịch với thay đổi."""

    def __init__(self, db: Session, clock: Clock, sms: SmsGateway, report: NightlyReport) -> None:
        self.db = db
        self.clock = clock
        self.notifications = NotificationService(db, clock, sms)
        self.audit = AuditService(db, clock)
        self.report = report

    def commit(self) -> None:
        self.db.commit()
        self.report.sms_failed += self.notifications.deliver()

    def loan_code(self, loan: Loan) -> str:
        """Mã khoản vay che bớt trong thông báo (UC30 bước 2): mã hồ sơ vay, ví dụ HS2******001."""
        return mask(self.db.get_one(LoanApplication, loan.application_id).code or "")

    def remind(self, loan: Loan, installment: Installment, kind: ReminderKind, content: str) -> None:
        """Gửi một mốc nhắc nợ nếu chưa gửi. Nội dung chỉ có mã khoản vay đã che, kỳ, số tiền và
        hạn thanh toán, không có liên kết đăng nhập (UC30, SR07)."""
        if self.db.get(PaymentReminder, (installment.id, kind)) is not None:
            return
        self.db.add(
            PaymentReminder(installment_id=installment.id, kind=kind, sent_at=self.clock.now())
        )
        customer = self.db.get_one(Customer, loan.customer_id)
        notification_type = (
            "PAYMENT_REMINDER" if kind in (ReminderKind.BEFORE_DUE, ReminderKind.DUE)
            else "PAYMENT_OVERDUE"
        )
        self.notifications.notify_customer(
            customer.id, notification_type, content, phone=customer.phone
        )
        self.report.reminders += 1


class NightlyJob:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        clock: Clock,
        settings: Settings,
        sms: SmsGateway,
        cic: CicGateway,
    ) -> None:
        self._sessions = session_factory
        self._clock = clock
        self._settings = settings
        self._sms = sms
        self._cic = cic

    def run(self) -> NightlyReport:
        today = self._clock.now().date()
        report = NightlyReport(run_on=today)
        self._scan_overdue(today, report)
        self._remind_upcoming(today, report)
        self._cancel_expired_need_info(report)
        self._rescore_stuck_verified(report)
        with self._sessions() as db:
            # UC29 bước 6, SD08 bước 9: nhật ký tổng hợp kết quả.
            AuditService(db, self._clock).log(
                "OVERDUE_JOB", target_type="JOB", detail=report.summary()
            )
            db.commit()
        return report

    # --- UC29 ---------------------------------------------------------------------------------

    def _scan_overdue(self, today: date, report: NightlyReport) -> None:
        loan_ids = self._ids(
            select(Installment.loan_id)
            .join(Loan, Loan.id == Installment.loan_id)
            .where(Loan.status.in_(UNSETTLED))
            .where(Installment.status.in_(UNPAID_INSTALLMENT))
            .where(Installment.due_date < today)
            .distinct()
        )
        for ids in _batches(loan_ids):
            with self._sessions() as db:
                batch = _Batch(db, self._clock, self._sms, report)
                for loan_id in ids:
                    self._process_loan(batch, loan_id, today)
                batch.commit()

    def _process_loan(self, batch: _Batch, loan_id: uuid.UUID, today: date) -> None:
        loan = batch.db.scalars(
            select(Loan).with_hint(Loan, "WITH (UPDLOCK, ROWLOCK)", "mssql").where(Loan.id == loan_id)
        ).one()
        installments = batch.db.scalars(
            select(Installment)
            .with_hint(Installment, "WITH (UPDLOCK, ROWLOCK)", "mssql")
            .where(Installment.loan_id == loan_id)
            .where(Installment.status.in_(UNPAID_INSTALLMENT))
            .where(Installment.due_date < today)
            .order_by(Installment.number)
        ).all()
        code = batch.loan_code(loan)
        max_days = 0
        for installment in installments:
            days = (today - installment.due_date).days
            # 3.4c T06, T07; kỳ Chưa đến hạn cũng chuyển thẳng nếu đêm đến hạn bị lỡ.
            installment.status = InstallmentStatus.OVERDUE
            installment.penalty = recalculated_penalty(
                interest_due=installment.interest_due,
                principal_due=installment.principal_due,
                penalty_paid=installment.penalty_paid,
                paid_amount=installment.paid_amount,
                annual_rate=loan.annual_rate,
                days_overdue=days,
            )
            max_days = max(max_days, days)
            batch.report.overdue_installments += 1
            batch.remind(
                loan, installment, overdue_reminder(days),
                f"Kỳ {installment.number} khoản vay {code} đã quá hạn {days} ngày. Số tiền cần "
                f"thanh toán {vnd(installment.amount_remaining())} đồng, gồm phí phạt chậm trả.",
            )

        # Nhóm nợ theo kỳ quá hạn lâu nhất, tính lại mỗi đêm (BR09, Q4).
        before = (loan.status, loan.debt_group)
        loan.debt_group = debt_group(max_days)
        if loan.status == LoanStatus.ACTIVE:
            loan.status = LoanStatus.OVERDUE  # 3.4b T02
        if is_bad_debt(max_days) and loan.status != LoanStatus.BAD_DEBT:
            loan.status = LoanStatus.BAD_DEBT  # 3.4b T04
            batch.report.bad_debts += 1
            batch.notifications.notify_role(
                APPROVER, "LOAN_BAD_DEBT",
                f"Khoản vay {code} đã quá hạn {max_days} ngày, chuyển Nợ xấu "
                f"(nhóm {loan.debt_group}).",
            )
        if (loan.status, loan.debt_group) != before:
            batch.audit.log(
                "LOAN_STATUS_CHANGE", target_type="LOAN", target_id=loan.id,
                level="WARNING" if loan.status == LoanStatus.BAD_DEBT else "INFO",
                detail=f"{before[0]}->{loan.status} debt_group {before[1]}->{loan.debt_group} "
                f"days_overdue={max_days}",
            )

    # --- UC30: nhắc trước hạn và đúng ngày đến hạn -----------------------------------------------

    def _remind_upcoming(self, today: date, report: NightlyReport) -> None:
        remind_on = today + timedelta(days=REMIND_DAYS_BEFORE)
        installment_ids = self._ids(
            select(Installment.id)
            .join(Loan, Loan.id == Installment.loan_id)
            .where(Loan.status.in_(UNSETTLED))
            .where(Installment.status.in_(UNPAID_INSTALLMENT))
            .where(Installment.due_date.in_((today, remind_on)))
        )
        for ids in _batches(installment_ids):
            with self._sessions() as db:
                batch = _Batch(db, self._clock, self._sms, report)
                for installment_id in ids:
                    installment = db.get_one(Installment, installment_id)
                    loan = db.get_one(Loan, installment.loan_id)
                    code = batch.loan_code(loan)
                    amount = vnd(installment.amount_remaining())
                    due = installment.due_date.strftime("%d/%m/%Y")
                    if installment.due_date == today:
                        if installment.status == InstallmentStatus.UPCOMING:
                            installment.status = InstallmentStatus.DUE  # 3.4c T02
                        batch.remind(
                            loan, installment, ReminderKind.DUE,
                            f"Hôm nay {due} là hạn thanh toán kỳ {installment.number} khoản vay "
                            f"{code}. Số tiền cần thanh toán {amount} đồng.",
                        )
                    else:
                        batch.remind(
                            loan, installment, ReminderKind.BEFORE_DUE,
                            f"Kỳ {installment.number} khoản vay {code} đến hạn ngày {due}. "
                            f"Số tiền cần thanh toán {amount} đồng.",
                        )
                batch.commit()

    # --- BR11 ---------------------------------------------------------------------------------

    def _cancel_expired_need_info(self, report: NightlyReport) -> None:
        application_ids = self._ids(
            select(LoanApplication.id)
            .where(LoanApplication.status == ApplicationStatus.NEED_INFO)
            .where(LoanApplication.need_info_deadline < self._clock.now())
        )
        for application_id in application_ids:
            with self._sessions() as db:
                application = db.scalars(
                    select(LoanApplication)
                    .with_hint(LoanApplication, "WITH (UPDLOCK, ROWLOCK)", "mssql")
                    .where(LoanApplication.id == application_id)
                ).one()
                # Khách hàng vừa bổ sung xong ngay trước khi tác vụ khóa được hồ sơ vay.
                if application.status != ApplicationStatus.NEED_INFO:
                    continue
                batch = _Batch(db, self._clock, self._sms, report)
                application.cancel_reason = NEED_INFO_EXPIRED_REASON
                ApplicationService(db, self._clock, self._settings, self._sms, None).transition(
                    application, ApplicationStatus.CANCELLED, None, NEED_INFO_EXPIRED_REASON
                )
                batch.audit.log(
                    "APPLICATION_AUTO_CANCEL", target_type="LOAN_APPLICATION",
                    target_id=application.id, detail="BR11",
                )
                customer = db.get_one(Customer, application.customer_id)
                batch.notifications.notify_customer(
                    customer.id, "APPLICATION_CANCELLED",
                    f"Hồ sơ vay {application.code} đã bị hủy do quá hạn bổ sung hồ sơ.",
                    phone=customer.phone,
                )
                batch.commit()
                report.cancelled_applications += 1

    # --- UC18 4a ------------------------------------------------------------------------------

    def _rescore_stuck_verified(self, report: NightlyReport) -> None:
        verified_at = (
            select(func.max(ApplicationStatusHistory.changed_at))
            .where(ApplicationStatusHistory.application_id == LoanApplication.id)
            .where(ApplicationStatusHistory.status == ApplicationStatus.VERIFIED)
            .scalar_subquery()
        )
        application_ids = self._ids(
            select(LoanApplication.id)
            .where(LoanApplication.status == ApplicationStatus.VERIFIED)
            .where(verified_at <= self._clock.now() - RESCORE_AFTER)
        )
        for application_id in application_ids:
            with self._sessions() as db:
                # File mô hình vẫn sai checksum thì ScoringService tiếp tục cảnh báo Quản trị viên
                # và hồ sơ vay ở lại "Hợp lệ" cho đêm sau.
                ScoringService(
                    db, self._clock, self._settings, self._sms, self._cic, None
                ).score_or_record_failure(application_id)
                status = db.scalars(
                    select(LoanApplication.status).where(LoanApplication.id == application_id)
                ).one()
                if status != ApplicationStatus.VERIFIED:
                    report.rescored_applications += 1

    # --- Nội bộ -------------------------------------------------------------------------------

    def _ids(self, query: Select[uuid.UUID]) -> list[uuid.UUID]:
        with self._sessions() as db:
            return list(db.scalars(query))


def _batches(ids: Sequence[uuid.UUID]) -> Iterator[Sequence[uuid.UUID]]:
    for start in range(0, len(ids), BATCH_SIZE):
        yield ids[start:start + BATCH_SIZE]
