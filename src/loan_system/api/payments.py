"""UC27 Xem lịch trả nợ, UC28 Thanh toán kỳ (màn hình M04).

Lỗi nghiệp vụ được đổi sang mã HTTP ở `api/errors.py`.
"""

import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, Field

from loan_system.api.access import require
from loan_system.api.deps import ClientIp, Ctx, Db
from loan_system.services.auth_service import CurrentUser
from loan_system.services.payment_service import PaymentService

router = APIRouter(prefix="/loans", tags=["Thu nợ"])

# UC27, UC28: Khách hàng và NV tín dụng (quyền PAYMENT_RECORD theo ma trận RBAC).
Payer = Annotated[CurrentUser, Depends(require("PAYMENT_RECORD"))]


def _payments(db: Db, ctx: Ctx, ip: ClientIp) -> PaymentService:
    return PaymentService(db, ctx.clock, ctx.payments, ctx.sms, ip)


Payments = Annotated[PaymentService, Depends(_payments)]


class InstallmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    number: int
    due_date: date
    principal_due: Decimal
    interest_due: Decimal
    penalty: Decimal
    paid_amount: Decimal
    status: str


class ScheduleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    loan_id: uuid.UUID
    status: str
    principal: Decimal
    annual_rate: Decimal
    term_months: int
    outstanding_principal: Decimal
    amount_due: Decimal
    next_due_date: date | None
    installments: list[InstallmentResponse]


class PayRequest(BaseModel):
    amount: Annotated[Decimal, Field(gt=0, le=Decimal("1e12"), decimal_places=0)]
    # UC28 bước 3 (tại quầy): mã phiếu thu; bỏ qua nếu người gọi là khách hàng (kênh luôn ONLINE).
    receipt_no: str | None = Field(default=None, max_length=50)
    # Trực tuyến: M04 sinh một lần cho mỗi lượt thanh toán, gửi lại thì không bị thu hai lần.
    idempotency_key: str | None = Field(default=None, min_length=16, max_length=64)


class AllocationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    installment_number: int
    component: str
    amount: Decimal


class PaymentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    amount: Decimal
    channel: str
    external_ref: str
    allocations: list[AllocationResponse]
    loan_status: str
    outstanding_principal: Decimal


@router.get("/{loan_id}/schedule", response_model=ScheduleResponse)
def get_schedule(loan_id: uuid.UUID, user: Payer, payments: Payments) -> ScheduleResponse:
    return ScheduleResponse.model_validate(payments.schedule(user, loan_id))


@router.get("/{loan_id}/schedule/pdf")
def get_schedule_pdf(loan_id: uuid.UUID, user: Payer, payments: Payments) -> Response:
    pdf = payments.schedule_pdf(user, loan_id)
    return Response(
        content=pdf, media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=lich_tra_no_{loan_id}.pdf"},
    )


@router.post("/{loan_id}/payments", response_model=PaymentResponse)
def pay(loan_id: uuid.UUID, body: PayRequest, user: Payer, payments: Payments) -> PaymentResponse:
    return PaymentResponse.model_validate(
        payments.pay(
            user, loan_id, body.amount, receipt_no=body.receipt_no,
            idempotency_key=body.idempotency_key,
        )
    )
