"""UC25 Giải ngân, UC26 Sinh hợp đồng và lịch trả nợ (màn hình M08).

Lỗi nghiệp vụ được đổi sang mã HTTP ở `api/errors.py`.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, Field

from loan_system.api.access import require
from loan_system.api.applications import ApplicationResponse, respond
from loan_system.api.deps import ClientIp, Ctx, Db
from loan_system.services.auth_service import CurrentUser
from loan_system.services.disbursement_service import DisbursementService

router = APIRouter(prefix="/applications", tags=["Giải ngân"])

Disburser = Annotated[CurrentUser, Depends(require("DISBURSE"))]


def _disbursements(db: Db, ctx: Ctx, ip: ClientIp) -> DisbursementService:
    return DisbursementService(db, ctx.clock, ctx.settings, ctx.sms, ctx.payments, ip)


Disbursements = Annotated[DisbursementService, Depends(_disbursements)]


class DisburseRequest(BaseModel):
    otp: str = Field(pattern=r"^\d{6}$")  # UC25 bước 5: xác thực lại (include UC02)


class DisbursementScreenResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    integrity: str
    approved_at: datetime
    recipient: str
    receiving_account: str
    amount: Decimal
    annual_rate: Decimal
    term_months: int
    pending: bool
    failed: bool


class InstallmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    number: int
    due_date: date
    principal_due: Decimal
    interest_due: Decimal
    penalty: Decimal
    paid_amount: Decimal
    status: str


class LoanResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    principal: Decimal
    annual_rate: Decimal
    term_months: int
    monthly_payment: Decimal
    outstanding_principal: Decimal
    status: str
    disbursed_at: datetime
    contract_sha256: str
    installments: list[InstallmentResponse]


class DisbursementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: str
    transaction_ref: str | None
    loan: LoanResponse | None


@router.get("/{application_id}/disbursement", response_model=DisbursementScreenResponse)
def get_disbursement(
    application_id: uuid.UUID, user: Disburser, disbursements: Disbursements
) -> DisbursementScreenResponse:
    return DisbursementScreenResponse.model_validate(disbursements.screen(user, application_id))


@router.post("/{application_id}/disburse", response_model=DisbursementResponse)
def disburse(
    application_id: uuid.UUID,
    body: DisburseRequest,
    user: Disburser,
    disbursements: Disbursements,
) -> DisbursementResponse:
    return DisbursementResponse.model_validate(
        disbursements.disburse(user, application_id, body.otp)
    )


@router.post("/{application_id}/disbursement/cancel", response_model=ApplicationResponse)
def cancel_disbursement(
    application_id: uuid.UUID, user: Disburser, disbursements: Disbursements
) -> ApplicationResponse:
    """Ticket #11 (UC25 7b): hủy để lập lại sau khi lệnh giải ngân bị cổng thanh toán từ chối."""
    return respond(disbursements.cancel_failed(user, application_id))


@router.get("/{application_id}/contract")
def get_contract(
    application_id: uuid.UUID, user: Disburser, disbursements: Disbursements
) -> Response:
    """UC26 bước 5: hợp đồng tín dụng PDF đã sinh lúc giải ngân."""
    return Response(
        content=disbursements.contract(user, application_id), media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=hop_dong_{application_id}.pdf"},
    )
