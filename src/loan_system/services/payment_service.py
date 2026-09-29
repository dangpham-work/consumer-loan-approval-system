"""UC27 Xem lịch trả nợ, UC28 Thanh toán kỳ (màn hình M04, SD07).

Khách hàng thanh toán trực tuyến qua cổng thanh toán giả lập; NV tín dụng ghi nhận thanh toán tại
quầy bằng mã phiếu thu do chính họ nhập (kênh suy ra từ loại người dùng, không phải trường client
gửi lên, để khách hàng không tự khai là "đã nộp tại quầy"). Một khoản thanh toán được phân bổ tuần
tự vào các kỳ theo thứ tự tăng dần (phí phạt → lãi → gốc mỗi kỳ, UC28 bước 4); phần dư tự nhiên
chuyển thành trả trước cho kỳ sau vì vòng lặp tiếp tục sang kỳ kế tiếp (CONTEXT.md, RepaymentSchedule).
Không cho trả vượt quá tổng còn lại của mọi kỳ: lịch trả nợ không đổi sau khi giải ngân, chỉ Tất
toán (ticket #14) mới tính lại số tiền dựa trên lãi phát sinh thực tế để giảm gốc trước hạn.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from loan_system.adapters.payment import PaymentGateway, PaymentUnavailable
from loan_system.adapters.sms import SmsGateway
from loan_system.clock import Clock
from loan_system.domain.contract import ScheduleRow, ScheduleTerms, render_schedule
from loan_system.domain.loans import (
    UNPAID_INSTALLMENT,
    InstallmentStatus,
    LoanStatus,
    PaymentChannel,
)
from loan_system.domain.payments import Allocation, allocate_payment, remaining_balance
from loan_system.domain.text import vnd
from loan_system.repositories.models import (
    Customer,
    Installment,
    Loan,
    Payment,
    PaymentAllocation,
)
from loan_system.services.audit_service import AuditService
from loan_system.services.auth_service import CurrentUser
from loan_system.services.notification_service import NotificationService

# UC28 tiền điều kiện: chỉ khoản vay Đang hoạt động hoặc Quá hạn. Nợ xấu (BAD_DEBT) không nằm
# trong luồng này; SETTLED thì không còn gì để trả.
_PAYABLE_LOAN_STATUSES = frozenset({LoanStatus.ACTIVE, LoanStatus.OVERDUE})


class LoanNotFound(Exception):
    """Khoản vay không tồn tại hoặc không thuộc quyền xem của người gọi."""


class LoanNotPayable(Exception):
    """UC28: khoản vay không ở trạng thái Đang hoạt động hoặc Quá hạn."""


class ReceiptRequired(Exception):
    """UC28 bước 3 (tại quầy): NV tín dụng phải nhập mã phiếu thu."""


class AmountExceedsDue(Exception):
    """Số tiền vượt quá tổng còn lại của mọi kỳ; lịch trả nợ không đổi sau khi giải ngân."""


class ReferenceReused(Exception):
    """Mã phiếu thu/mã giao dịch đã gắn với một khoản thanh toán khác (khác khoản vay hoặc số tiền):
    không phải xác nhận trùng của UC28 3b nên không được coi là đã xử lý."""


class ChargeFailed(Exception):
    """UC28 3a: cổng thanh toán từ chối giao dịch; không ghi nhận gì."""


class ChargeUnavailable(Exception):
    """Cổng thanh toán tạm thời không phản hồi; chưa ghi nhận gì, thử lại được."""


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
class ScheduleView:
    """M04: bảng kỳ, tổng dư nợ, kỳ kế tiếp và số tiền cần thanh toán hiện tại (UC27)."""

    loan_id: uuid.UUID
    status: str
    debt_group: int  # BR09, tách khỏi status
    principal: Decimal
    annual_rate: Decimal
    term_months: int
    outstanding_principal: Decimal
    amount_due: Decimal  # kể cả phí phạt, chỉ tính các kỳ đã đến hạn (UC28 bước 1)
    next_due_date: date | None
    installments: list[InstallmentView]


@dataclass(frozen=True)
class AllocationView:
    installment_number: int
    component: str
    amount: Decimal


@dataclass(frozen=True)
class PaymentResult:
    id: uuid.UUID
    amount: Decimal
    channel: str
    external_ref: str
    paid_at: datetime
    allocations: list[AllocationView]
    loan_status: str
    outstanding_principal: Decimal


class PaymentService:
    def __init__(
        self, db: Session, clock: Clock, payments: PaymentGateway, sms: SmsGateway,
        ip: str | None,
    ) -> None:
        self._db = db
        self._clock = clock
        self._payments = payments
        self._notifications = NotificationService(db, clock, sms)
        self._audit = AuditService(db, clock)
        self._ip = ip

    def schedule(self, user: CurrentUser, loan_id: uuid.UUID) -> ScheduleView:
        loan = self._load(user, loan_id)
        installments = self._installments(loan.id)
        view = self._schedule_view(loan, installments)
        self._db.rollback()  # chỉ đọc: nhả khóa dòng
        return view

    def schedule_pdf(self, user: CurrentUser, loan_id: uuid.UUID) -> bytes:
        loan = self._load(user, loan_id)
        installments = self._installments(loan.id)
        customer = self._db.get_one(Customer, loan.customer_id)
        pdf = render_schedule(
            ScheduleTerms(
                loan_code=str(loan.id),
                customer_name=customer.full_name,
                principal=loan.principal,
                annual_rate=loan.annual_rate,
                term_months=loan.term_months,
                outstanding_principal=loan.outstanding_principal,
                generated_on=self._clock.now().date(),
                rows=[
                    ScheduleRow(
                        i.number, i.due_date, i.principal_due, i.interest_due, i.penalty,
                        i.paid_amount, i.status,
                    )
                    for i in installments
                ],
            )
        )
        self._db.rollback()
        return pdf

    def pay(
        self,
        user: CurrentUser,
        loan_id: uuid.UUID,
        amount: Decimal,
        *,
        receipt_no: str | None = None,
        idempotency_key: str | None = None,
    ) -> PaymentResult:
        """UC28 bước 1–5: xác định kênh theo loại người dùng, thu tiền rồi phân bổ vào các kỳ.

        `idempotency_key` do màn hình M04 sinh một lần cho mỗi lượt thanh toán: gửi lại (bấm hai
        lần, mạng chập chờn) thì cổng thanh toán trả lại đúng mã giao dịch cũ và khoản thanh toán
        chỉ được ghi nhận một lần (UC28 3b).
        """
        loan = self._load(user, loan_id, lock=True)
        if loan.status not in _PAYABLE_LOAN_STATUSES:
            raise LoanNotPayable
        installments = self._installments(loan.id, lock=True)
        balances = [
            remaining_balance(
                i.id, penalty=i.penalty, interest_due=i.interest_due,
                principal_due=i.principal_due, penalty_paid=i.penalty_paid,
                paid_amount=i.paid_amount,
            )
            for i in installments
            if i.status in UNPAID_INSTALLMENT
        ]
        total_remaining = sum((b.total_due for b in balances), Decimal(0))
        if amount > total_remaining:
            raise AmountExceedsDue

        if user.kind == "CUSTOMER":
            channel = PaymentChannel.ONLINE
            external_ref = self._charge(loan, user, amount, idempotency_key or uuid.uuid4().hex)
        else:
            if not receipt_no:
                raise ReceiptRequired
            channel = PaymentChannel.COUNTER
            external_ref = receipt_no

        existing = self._by_ref(external_ref)
        if existing is not None:
            self._db.rollback()
            return self._duplicate(existing, loan.id, amount)

        allocations = allocate_payment(balances, amount)
        now = self._clock.now()
        payment = Payment(
            id=uuid.uuid4(), loan_id=loan.id, amount=amount, channel=channel,
            external_ref=external_ref, paid_at=now, recorded_by=user.user_id,
        )
        self._db.add(payment)
        self._apply(loan, installments, allocations)
        self._db.add_all(
            PaymentAllocation(
                payment_id=payment.id, installment_id=a.installment_id, component=a.component,
                amount=a.amount,
            )
            for a in allocations
        )
        self._audit.log(
            "PAYMENT", actor_id=user.user_id, target_type="LOAN", target_id=loan.id,
            ip_address=self._ip, detail=external_ref,
        )
        self._send_receipt(loan, amount)
        try:
            self._db.commit()
        except IntegrityError:
            # Yêu cầu trùng gửi đồng thời: bên kia đã ghi trước (UC28 3b).
            self._db.rollback()
            existing = self._by_ref(external_ref)
            assert existing is not None
            return self._duplicate(existing, loan.id, amount)
        self._notifications.deliver()
        return PaymentResult(
            id=payment.id, amount=amount, channel=channel, external_ref=external_ref, paid_at=now,
            allocations=[
                AllocationView(self._number_of(installments, a.installment_id), a.component, a.amount)
                for a in allocations
            ],
            loan_status=loan.status, outstanding_principal=loan.outstanding_principal,
        )

    # --- Nội bộ -------------------------------------------------------------------------------

    def _load(self, user: CurrentUser, loan_id: uuid.UUID, *, lock: bool = False) -> Loan:
        query = select(Loan).where(Loan.id == loan_id)
        if user.customer_id is not None:
            query = query.where(Loan.customer_id == user.customer_id)
        if lock:
            query = query.with_hint(Loan, "WITH (UPDLOCK, ROWLOCK)", "mssql")
        loan = self._db.scalars(query.execution_options(populate_existing=True)).one_or_none()
        if loan is None:
            self._db.rollback()
            raise LoanNotFound
        return loan

    def _installments(
        self, loan_id: uuid.UUID, *, lock: bool = False
    ) -> list[Installment]:
        """Mọi kỳ của khoản vay, kể cả Đã hủy (hiển thị đầy đủ ở M04; loại trừ khi phân bổ)."""
        query = select(Installment).where(Installment.loan_id == loan_id).order_by(Installment.number)
        if lock:
            query = query.with_hint(Installment, "WITH (UPDLOCK, ROWLOCK)", "mssql")
        return list(self._db.scalars(query.execution_options(populate_existing=True)).all())

    def _by_ref(self, external_ref: str) -> Payment | None:
        return self._db.scalars(
            select(Payment).where(Payment.external_ref == external_ref)
        ).one_or_none()

    def _duplicate(self, existing: Payment, loan_id: uuid.UUID, amount: Decimal) -> PaymentResult:
        """UC28 3b: xác nhận trùng của cùng một khoản thanh toán thì bỏ qua, trả lại kết quả cũ."""
        if existing.loan_id != loan_id or existing.amount != amount:
            raise ReferenceReused
        return self._result_of(existing)

    def _charge(
        self, loan: Loan, user: CurrentUser, amount: Decimal, idempotency_key: str
    ) -> str:
        try:
            result = self._payments.charge(amount, idempotency_key)
        except PaymentUnavailable:
            self._db.rollback()
            raise ChargeUnavailable from None
        if not result.succeeded:
            # UC28 3a: không ghi nhận thanh toán, nhưng lưu vết lượt thu tiền bị từ chối.
            self._audit.log(
                "PAYMENT_FAILED", actor_id=user.user_id, target_type="LOAN", target_id=loan.id,
                ip_address=self._ip, level="WARNING", detail=result.reason,
            )
            self._db.commit()
            raise ChargeFailed
        assert result.transaction_ref is not None
        return result.transaction_ref

    def _apply(
        self, loan: Loan, installments: list[Installment], allocations: list[Allocation]
    ) -> None:
        by_id = {i.id: i for i in installments}
        principal_paid = Decimal(0)
        for allocation in allocations:
            installment = by_id[allocation.installment_id]
            installment.paid_amount += allocation.amount
            if allocation.component == "PENALTY":
                installment.penalty_paid += allocation.amount
            elif allocation.component == "PRINCIPAL":
                principal_paid += allocation.amount
            if installment.amount_remaining() <= 0:
                installment.status = InstallmentStatus.PAID
            elif installment.status == InstallmentStatus.DUE:
                # 3.4c T05. Kỳ Chưa đến hạn được trả trước một phần vẫn Chưa đến hạn; kỳ Quá hạn
                # chỉ rời Quá hạn khi trả đủ (T08).
                installment.status = InstallmentStatus.PARTIAL
        loan.outstanding_principal -= principal_paid
        if loan.status == LoanStatus.OVERDUE and not any(
            i.status == InstallmentStatus.OVERDUE for i in installments
        ):
            # 3.4b T03: đã trả hết các kỳ quá hạn thì về Đang hoạt động, nhóm nợ 1.
            self._audit.log(
                "LOAN_STATUS_CHANGE", target_type="LOAN", target_id=loan.id,
                detail=f"{loan.status}->{LoanStatus.ACTIVE} debt_group {loan.debt_group}->1",
            )
            loan.status = LoanStatus.ACTIVE
            loan.debt_group = 1
        if loan.outstanding_principal <= 0:
            loan.outstanding_principal = Decimal(0)
            loan.status = LoanStatus.SETTLED
            loan.settled_at = self._clock.now()

    def _send_receipt(self, loan: Loan, amount: Decimal) -> None:
        customer = self._db.get_one(Customer, loan.customer_id)
        self._notifications.notify_customer(
            customer.id, "PAYMENT_RECEIVED",
            f"Đã ghi nhận thanh toán {vnd(amount)} đồng cho khoản vay. Dư nợ gốc còn lại: "
            f"{vnd(loan.outstanding_principal)} đồng.",
            phone=customer.phone,
        )
        if loan.status == LoanStatus.SETTLED:
            # 3.4b T05: phát hành xác nhận tất toán.
            self._notifications.notify_customer(
                customer.id, "LOAN_SETTLED",
                "Khoản vay của Quý khách đã được tất toán. Cảm ơn Quý khách đã sử dụng dịch vụ.",
                phone=customer.phone,
            )

    def _schedule_view(self, loan: Loan, installments: list[Installment]) -> ScheduleView:
        due_now = [
            i for i in installments
            if i.status in UNPAID_INSTALLMENT and i.due_date <= self._clock.now().date()
        ]
        amount_due = sum((i.amount_remaining() for i in due_now), Decimal(0))
        upcoming = [i for i in installments if i.status in UNPAID_INSTALLMENT]
        return ScheduleView(
            loan_id=loan.id, status=loan.status, debt_group=loan.debt_group,
            principal=loan.principal,
            annual_rate=loan.annual_rate, term_months=loan.term_months,
            outstanding_principal=loan.outstanding_principal, amount_due=amount_due,
            next_due_date=upcoming[0].due_date if upcoming else None,
            installments=[
                InstallmentView(
                    i.number, i.due_date, i.principal_due, i.interest_due, i.penalty,
                    i.paid_amount, i.status,
                )
                for i in installments
            ],
        )

    @staticmethod
    def _number_of(installments: list[Installment], installment_id: uuid.UUID) -> int:
        return next(i.number for i in installments if i.id == installment_id)

    def _result_of(self, payment: Payment) -> PaymentResult:
        loan = self._db.get_one(Loan, payment.loan_id)
        allocations = self._db.scalars(
            select(PaymentAllocation).where(PaymentAllocation.payment_id == payment.id)
        ).all()
        installments = {i.id: i for i in self._installments(loan.id)}
        return PaymentResult(
            id=payment.id, amount=payment.amount, channel=payment.channel,
            external_ref=payment.external_ref, paid_at=payment.paid_at,
            allocations=[
                AllocationView(installments[a.installment_id].number, a.component, a.amount)
                for a in allocations
            ],
            loan_status=loan.status, outstanding_principal=loan.outstanding_principal,
        )
