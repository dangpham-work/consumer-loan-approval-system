"""UC23 Phê duyệt, UC24 Từ chối / Trả về hồ sơ vay (màn hình M07).

Lỗi nghiệp vụ được đổi sang mã HTTP ở `api/errors.py`.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from loan_system.api.access import require
from loan_system.api.applications import ApplicationResponse, ReportResponse, ScoreResponse, respond
from loan_system.api.deps import ClientIp, Ctx, Db
from loan_system.domain.approval import MIN_REASON_LENGTH, RejectionReason
from loan_system.services.approval_service import ApprovalService, ApprovalView
from loan_system.services.auth_service import CurrentUser

router = APIRouter(prefix="/applications", tags=["Phê duyệt"])

Approver = Annotated[CurrentUser, Depends(require("LOAN_APPROVE"))]
Rejecter = Annotated[CurrentUser, Depends(require("LOAN_REJECT"))]
# UC24 2a: Từ chối, Trả về không có lý do thì không cho xác nhận.
Reason = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=MIN_REASON_LENGTH, max_length=1000)
]


def _approvals(db: Db, ctx: Ctx, ip: ClientIp) -> ApprovalService:
    return ApprovalService(db, ctx.clock, ctx.settings, ctx.sms, ip)


Approvals = Annotated[ApprovalService, Depends(_approvals)]


class DecisionRequest(BaseModel):
    # UC23 6b: phiên bản hồ sơ vay mà Quản lý đã xem trên M07 (khóa lạc quan).
    version: int


class ApproveRequest(DecisionRequest):
    comment: str | None = Field(default=None, max_length=1000)


class RejectRequest(DecisionRequest):
    reason_group: RejectionReason
    description: Reason


class ReturnRequest(DecisionRequest):
    clarification: Reason


class DecisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    decision: str
    approver: str
    reason_group: str | None
    comment: str | None
    snapshot_hash: str | None
    key_version: int | None
    decided_at: datetime
    superseded: bool


class ApprovalResponse(BaseModel):
    application: ApplicationResponse
    score: ScoreResponse
    report: ReportResponse
    annual_rate: Decimal | None
    required_approvals: int | None
    approvals: int
    approved_amount: Decimal | None
    approved_term: int | None
    decisions: list[DecisionResponse]
    can_decide: bool
    version: int


def respond_approval(view: ApprovalView) -> ApprovalResponse:
    return ApprovalResponse(
        application=respond(view.application),
        score=ScoreResponse.model_validate(view.score),
        report=ReportResponse.model_validate(view.report),
        annual_rate=view.annual_rate,
        required_approvals=view.required_approvals,
        approvals=view.approvals,
        approved_amount=view.approved_amount,
        approved_term=view.approved_term,
        decisions=[DecisionResponse.model_validate(d) for d in view.decisions],
        can_decide=view.can_decide,
        version=view.version,
    )


@router.get("/{application_id}/approval", response_model=ApprovalResponse)
def get_approval(
    application_id: uuid.UUID, user: Approver, approvals: Approvals
) -> ApprovalResponse:
    return respond_approval(approvals.view(user, application_id))


@router.post("/{application_id}/approve", response_model=ApprovalResponse)
def approve(
    application_id: uuid.UUID, body: ApproveRequest, user: Approver, approvals: Approvals
) -> ApprovalResponse:
    return respond_approval(approvals.approve(user, application_id, body.version, body.comment))


@router.post("/{application_id}/reject", response_model=ApprovalResponse)
def reject(
    application_id: uuid.UUID, body: RejectRequest, user: Rejecter, approvals: Approvals
) -> ApprovalResponse:
    return respond_approval(
        approvals.reject(
            user, application_id, body.version, body.reason_group, body.description
        )
    )


@router.post("/{application_id}/return", response_model=ApprovalResponse)
def return_to_appraisal(
    application_id: uuid.UUID, body: ReturnRequest, user: Rejecter, approvals: Approvals
) -> ApprovalResponse:
    return respond_approval(
        approvals.return_to_appraisal(user, application_id, body.version, body.clarification)
    )
