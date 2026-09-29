"""UC25 Giải ngân, UC26 Sinh hợp đồng và lịch trả nợ (màn hình M08, SD06).

Trước khi hiển thị thông tin giải ngân và trước khi chuyển tiền: kiểm tra phân tách nhiệm vụ
(SUC01) rồi đối chiếu snapshot (SUC02); không khớp thì hồ sơ vay bị khóa, ghi INTEGRITY_FAIL mức
CRITICAL và báo Kiểm soát viên, Quản lý phê duyệt. Chỉ sau hai bước đó NV giải ngân mới phải xác
thực lại bằng TOTP (thứ tự SD06, AD05).

Lệnh giải ngân được lưu (kèm idempotency key) và commit trước khi gọi cổng thanh toán, vì không thể
giữ giao dịch CSDL trong lúc chờ hệ thống ngoài. Thử lại dùng lại đúng lệnh đang chờ và khóa của
nó, nên tiền không bị chuyển hai lần; hai yêu cầu song song cũng gửi cùng khóa, nên cổng thanh
toán thật phải bảo đảm mỗi khóa chỉ được thực hiện một lần kể cả khi nhận đồng thời. Chuyển tiền thành công thì khoản vay, lịch trả nợ, hợp đồng
và trạng thái Đã giải ngân được ghi trong cùng một giao dịch (UC26: lỗi giữa chừng thì hoàn tác).
"""

import hashlib
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from loan_system.adapters.payment import PaymentGateway, PaymentUnavailable, TransferResult
from loan_system.adapters.sms import SmsGateway
from loan_system.clock import Clock
from loan_system.config import Settings
from loan_system.domain.access import APPROVER, AUDITOR
from loan_system.domain.applications import ApplicationStatus, mask
from loan_system.domain.calculations import generate_schedule
from loan_system.domain.contract import ContractTerms, render_contract
from loan_system.domain.loans import DisbursementStatus, InstallmentStatus, LoanStatus
from loan_system.domain.text import vnd
from loan_system.repositories.models import (
    ApprovalDecision,
    Customer,
    Disbursement,
    Installment,
    Loan,
    LoanApplication,
    LoanContract,
)
from loan_system.security.crypto import FieldCipher
from loan_system.services.application_service import ApplicationService
from loan_system.services.audit_service import AuditService
from loan_system.services.auth_service import AuthService, CurrentUser
from loan_system.services.integrity_service import IntegrityService
from loan_system.services.notification_service import NotificationService
from loan_system.services.segregation import SegregationOfDuties


class NotApproved(Exception):
    """Hồ sơ vay không ở trạng thái Đã phê duyệt."""


class IntegrityFailure(Exception):
    """SUC02 4a: snapshot không khớp; hồ sơ vay đã bị khóa."""


class PreviouslyFailed(Exception):
    """UC25 7b: lệnh giải ngân trước bị cổng thanh toán từ chối; hủy hồ sơ vay để lập lại (Q13)."""


class PaymentPending(Exception):
    """UC25 7a: cổng thanh toán lỗi tạm thời; lệnh giải ngân đang chờ, thử lại được."""


class TransferRejected(Exception):
    """UC25 7b: cổng thanh toán từ chối lệnh (lý do gốc lưu ở lệnh giải ngân và nhật ký)."""


@dataclass(frozen=True)
class InstallmentView:
    number: int
    due_date: date
    principal_due: Decimal
    interest_due: Decimal
    penalty: Decimal
    paid_amount: Decimal
    status: str


@dataclass(frozen=True)
class LoanView:
    id: uuid.UUID
    principal: Decimal
    annual_rate: Decimal
    term_months: int
    monthly_payment: Decimal
    outstanding_principal: Decimal
    status: str
    disbursed_at: datetime
    contract_sha256: str
    installments: list[InstallmentView]


@dataclass(frozen=True)
class DisbursementScreen:
    """M08: khối kiểm tra toàn vẹn và thông tin chuyển tiền (đã che)."""

    integrity: str  # INTACT: khớp với quyết định phê duyệt lúc approved_at
    approved_at: datetime
    recipient: str
    receiving_account: str
    amount: Decimal
    annual_rate: Decimal
    term_months: int
    pending: bool  # đang có lệnh giải ngân chờ thử lại


@dataclass(frozen=True)
class DisbursementResult:
    status: str
    transaction_ref: str | None
    loan: LoanView | None


class DisbursementService:
    def __init__(
        self,
        db: Session,
        clock: Clock,
        settings: Settings,
        sms: SmsGateway,
        payments: PaymentGateway,
        ip: str | None,
    ) -> None:
        self._db = db
        self._clock = clock
        self._payments = payments
        self._cipher = FieldCipher(settings.data_enc_key)
        self._applications = ApplicationService(db, clock, settings, sms, ip)
        self._integrity = IntegrityService(db, settings, self._applications)
        self._notifications = NotificationService(db, clock, sms)
        self._audit = AuditService(db, clock)
        self._sod = SegregationOfDuties(db, clock, sms, ip)
        self._auth = AuthService(db, clock, settings, ip)
        self._ip = ip

    def screen(self, user: CurrentUser, application_id: uuid.UUID) -> DisbursementScreen:
        """SD06 bước 1–10, UC25 bước 1–4."""
        application = self._ready(user, application_id)
        customer = self._db.get_one(Customer, application.customer_id)
        assert application.approved_amount is not None and application.approved_term is not None
        assert application.annual_rate is not None
        screen = DisbursementScreen(
            integrity="INTACT",
            approved_at=self._approved_at(application),
            recipient=customer.full_name,
            receiving_account=self._applications.receiving_account_masked(application),
            amount=application.approved_amount,
            annual_rate=application.annual_rate,
            term_months=application.approved_term,
            pending=self._pending(application) is not None,
        )
        self._db.rollback()  # chỉ đọc: nhả khóa dòng
        return screen

    def disburse(
        self, user: CurrentUser, application_id: uuid.UUID, otp: str
    ) -> DisbursementResult:
        """SD06 bước 2–24: SUC01, SUC02, xác thực lại bằng TOTP (UC02), rồi chuyển tiền."""
        self._ready(user, application_id)
        # Xác thực TOTP tự commit, nên nhả khóa dòng trước rồi kiểm tra lại sau khi xác thực.
        self._db.rollback()
        self._auth.confirm_step_up(user, otp)  # sai: InvalidOtp; sai 3 lần thì hủy phiên
        application = self._ready(user, application_id)
        if self._has_failed(application):
            raise PreviouslyFailed
        disbursement = self._pending(application)
        if disbursement is None:
            account = self._applications.receiving_account_of(application)
            assert application.approved_amount is not None and user.employee_id is not None
            disbursement_id = uuid.uuid4()
            disbursement = Disbursement(
                id=disbursement_id,
                application_id=application.id,
                amount=application.approved_amount,
                receiving_account_enc=self._cipher.encrypt(
                    account, context=_account_context(disbursement_id)
                ),
                idempotency_key=uuid.uuid4().hex,
                status=DisbursementStatus.PENDING,
                performed_by=user.employee_id,
                created_at=self._clock.now(),
            )
            self._db.add(disbursement)
        self._log("DISBURSE_REQUEST", user, application, disbursement.idempotency_key)
        disbursement_id, amount, key = disbursement.id, disbursement.amount, disbursement.idempotency_key
        # Chuyển đúng số tài khoản đã ghi trên lệnh (khớp snapshot lúc tạo lệnh).
        account = self._cipher.decrypt(
            disbursement.receiving_account_enc, context=_account_context(disbursement_id)
        )
        self._applications.commit()
        try:
            result = self._payments.transfer(account, amount, key)
        except PaymentUnavailable:
            self._log("DISBURSE_PENDING", user, application, key, level="WARNING")
            self._db.commit()
            raise PaymentPending from None
        return self._complete(user, application_id, disbursement_id, result)

    # --- Nội bộ -------------------------------------------------------------------------------

    def _ready(self, user: CurrentUser, application_id: uuid.UUID) -> LoanApplication:
        """Hồ sơ vay Đã phê duyệt (khóa dòng), qua SUC01 và SUC02."""
        application = self._applications.load(user, application_id, lock=True)
        if application.status != ApplicationStatus.APPROVED:
            raise NotApproved
        approvers = self._db.scalars(
            select(ApprovalDecision.approver_id)
            .where(ApprovalDecision.application_id == application.id)
        ).all()
        # SUC01: người giải ngân khác mọi người đã tham gia các bước trước (BR06).
        self._sod.enforce(
            user, application, "DISBURSE",
            [application.created_by, application.received_by, application.appraised_by, *approvers],
        )
        if not self._integrity.verify(application):
            self._lock_and_raise(user, application)
        return application

    def _lock_and_raise(self, user: CurrentUser, application: LoanApplication) -> None:
        """SUC02 4a: khóa hồ sơ vay, cảnh báo CRITICAL, báo Kiểm soát viên và Quản lý phê duyệt."""
        self._applications.transition(
            application, ApplicationStatus.LOCKED, user.user_id, "Snapshot không khớp"
        )
        self._log("INTEGRITY_FAIL", user, application, None, level="CRITICAL")
        message = (
            f"Hồ sơ vay {application.code} bị thay đổi sau khi phê duyệt và đã bị khóa, "
            "cần điều tra trước khi xử lý tiếp."
        )
        self._notifications.notify_role(AUDITOR, "INTEGRITY_FAIL", message)
        self._notifications.notify_role(APPROVER, "INTEGRITY_FAIL", message)
        self._applications.commit()
        raise IntegrityFailure

    def _complete(
        self,
        user: CurrentUser,
        application_id: uuid.UUID,
        disbursement_id: uuid.UUID,
        result: TransferResult,
    ) -> DisbursementResult:
        application = self._applications.load(user, application_id, lock=True)
        disbursement = self._db.get_one(Disbursement, disbursement_id, populate_existing=True)
        if disbursement.status == DisbursementStatus.SUCCESS:
            # Một yêu cầu song song với cùng lệnh đã hoàn tất trước.
            assert disbursement.loan_id is not None
            loan = self._db.get_one(Loan, disbursement.loan_id)
            outcome = DisbursementResult(
                disbursement.status, disbursement.transaction_ref, self._loan_view(loan)
            )
            self._db.rollback()
            return outcome
        now = self._clock.now()
        if application.status != ApplicationStatus.APPROVED:
            if result.succeeded:
                self._record_orphan_transfer(user, application, disbursement, result, now)
            raise NotApproved
        if not result.succeeded:
            disbursement.status = DisbursementStatus.FAILED
            disbursement.failure_reason = result.reason
            disbursement.completed_at = now
            self._log("DISBURSE_FAILED", user, application, result.reason, level="WARNING")
            self._applications.commit()
            raise TransferRejected
        loan = self._create_loan(application, now)
        disbursement.status = DisbursementStatus.SUCCESS
        disbursement.transaction_ref = result.transaction_ref
        disbursement.loan_id = loan.id
        disbursement.completed_at = now
        self._applications.transition(application, ApplicationStatus.DISBURSED, user.user_id)
        self._log("DISBURSE", user, application, result.transaction_ref)
        self._notify_customer(application, loan)
        self._applications.commit()
        self._notifications.deliver()
        view = self._loan_view(loan)
        return DisbursementResult(disbursement.status, disbursement.transaction_ref, view)

    def _record_orphan_transfer(
        self,
        user: CurrentUser,
        application: LoanApplication,
        disbursement: Disbursement,
        result: TransferResult,
        now: datetime,
    ) -> None:
        """Tiền đã chuyển nhưng hồ sơ vay vừa đổi trạng thái (bị khóa hay bị hủy) trong lúc gọi cổng
        thanh toán: ghi nhận giao dịch để không mất dấu tiền, cảnh báo CRITICAL để đối soát."""
        disbursement.status = DisbursementStatus.SUCCESS
        disbursement.transaction_ref = result.transaction_ref
        disbursement.completed_at = now
        self._log("DISBURSE_ORPHAN", user, application, result.transaction_ref, level="CRITICAL")
        self._notifications.notify_role(
            AUDITOR,
            "DISBURSE_ORPHAN",
            f"Đã chuyển tiền cho hồ sơ vay {application.code} nhưng hồ sơ vay không còn ở trạng "
            "thái Đã phê duyệt; cần đối soát.",
        )
        self._applications.commit()

    def _create_loan(self, application: LoanApplication, now: datetime) -> Loan:
        """UC26: khoản vay, lịch trả nợ niên kim (BR08) và hợp đồng PDF kèm SHA-256."""
        principal, term = application.approved_amount, application.approved_term
        assert principal is not None and term is not None and application.annual_rate is not None
        assert application.code is not None
        schedule = generate_schedule(principal, application.annual_rate, term, now.date())
        loan = Loan(
            id=uuid.uuid4(),
            application_id=application.id,
            customer_id=application.customer_id,
            principal=principal,
            annual_rate=application.annual_rate,
            term_months=term,
            monthly_payment=schedule[0].payment,
            outstanding_principal=principal,
            status=LoanStatus.ACTIVE,
            debt_group=1,
            disbursed_at=now,
        )
        self._db.add(loan)
        self._db.flush()  # không có relationship: phải ghi khoản vay trước các kỳ trả nợ
        for row in schedule:
            self._db.add(
                Installment(
                    loan_id=loan.id,
                    number=row.number,
                    due_date=row.due_date,
                    principal_due=row.principal,
                    interest_due=row.interest,
                    penalty=Decimal(0),
                    paid_amount=Decimal(0),
                    status=InstallmentStatus.UPCOMING,
                )
            )
        customer = self._db.get_one(Customer, application.customer_id)
        pdf = render_contract(
            ContractTerms(
                contract_no=f"HD-{application.code}",
                customer_name=customer.full_name,
                national_id=mask(self._applications.national_id_of(customer)),
                address=customer.address or "",
                receiving_account=self._applications.receiving_account_masked(application),
                principal=principal,
                annual_rate=application.annual_rate,
                term_months=term,
                monthly_payment=loan.monthly_payment,
                disbursed_on=now.date(),
                schedule=schedule,
            )
        )
        self._db.add(
            LoanContract(
                loan_id=loan.id, content=pdf, sha256=hashlib.sha256(pdf).hexdigest(),
                created_at=now,
            )
        )
        self._db.flush()
        return loan

    def _notify_customer(self, application: LoanApplication, loan: Loan) -> None:
        customer = self._db.get_one(Customer, application.customer_id)
        first_due = self._db.scalars(
            select(Installment.due_date)
            .where(Installment.loan_id == loan.id)
            .where(Installment.number == 1)
        ).one()
        self._notifications.notify_customer(
            customer.id,
            "LOAN_DISBURSED",
            f"Hồ sơ vay {application.code} đã được giải ngân {vnd(loan.principal)} đồng vào tài "
            f"khoản {self._applications.receiving_account_masked(application)}. Kỳ trả nợ đầu "
            f"tiên: {vnd(loan.monthly_payment)} đồng, hạn {first_due:%d/%m/%Y}.",
            phone=customer.phone,
        )

    def _loan_view(self, loan: Loan) -> LoanView:
        installments = self._db.scalars(
            select(Installment).where(Installment.loan_id == loan.id).order_by(Installment.number)
        ).all()
        contract = self._db.get_one(LoanContract, loan.id)
        return LoanView(
            id=loan.id,
            principal=loan.principal,
            annual_rate=loan.annual_rate,
            term_months=loan.term_months,
            monthly_payment=loan.monthly_payment,
            outstanding_principal=loan.outstanding_principal,
            status=loan.status,
            disbursed_at=loan.disbursed_at,
            contract_sha256=contract.sha256,
            installments=[
                InstallmentView(
                    i.number, i.due_date, i.principal_due, i.interest_due, i.penalty,
                    i.paid_amount, i.status,
                )
                for i in installments
            ],
        )

    def _pending(self, application: LoanApplication) -> Disbursement | None:
        return self._db.scalars(
            select(Disbursement)
            .where(Disbursement.application_id == application.id)
            .where(Disbursement.status == DisbursementStatus.PENDING)
        ).first()

    def _has_failed(self, application: LoanApplication) -> bool:
        return self._db.scalars(
            select(Disbursement.id)
            .where(Disbursement.application_id == application.id)
            .where(Disbursement.status == DisbursementStatus.FAILED)
        ).first() is not None

    def _approved_at(self, application: LoanApplication) -> datetime:
        decision = self._integrity.approving_decision(application)
        assert decision is not None  # đã qua SUC02
        return decision.decided_at

    def _log(
        self,
        action: str,
        user: CurrentUser,
        application: LoanApplication,
        detail: str | None,
        *,
        level: str = "INFO",
    ) -> None:
        self._audit.log(
            action, actor_id=user.user_id, target_type="LOAN_APPLICATION",
            target_id=application.id, ip_address=self._ip, level=level, detail=detail,
        )


def _account_context(disbursement_id: uuid.UUID) -> str:
    return f"disbursements.receiving_account:{disbursement_id}"
