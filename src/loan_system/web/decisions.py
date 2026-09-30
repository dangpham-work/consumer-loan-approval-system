"""Màn hình nhân viên M07 Phê duyệt hồ sơ vay và M08 Giải ngân, mở từ chi tiết hồ sơ vay (M06).

UC23 Phê duyệt, UC24 Từ chối / Trả về, UC25 Giải ngân, UC26 tải hợp đồng PDF. Cùng tầng nghiệp vụ và
cùng thông điệp với `api/approvals.py`, `api/disbursements.py`.

M07 ẩn nút quyết định khi `can_decide` sai; máy chủ vẫn chặn (403, ghi SOD_VIOLATION, ST03). Quyết định
gửi kèm phiên bản hồ sơ vay đang xem: đã cũ thì báo tải lại trang (409, UC23 6b). M08 kiểm tra phân
tách nhiệm vụ và toàn vẹn ngay khi mở trang (SD06); snapshot không khớp thì hồ sơ vay bị khóa và trang
hiện trạng thái đỏ (ST04).
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from loan_system.api.applications import Applications
from loan_system.api.approvals import (
    ApproveRequest,
    Approvals,
    RejectRequest,
    ReturnRequest,
)
from loan_system.api.disbursements import Disbursements
from loan_system.domain.applications import ApplicationStatus
from loan_system.domain.approval import RejectionReason
from loan_system.services.application_service import ApplicationService, ConcurrentModification
from loan_system.services.approval_service import (
    ApprovalService,
    NotAwaitingApproval,
    ReportNotApprovable,
)
from loan_system.services.auth_service import CurrentUser, InvalidOtp
from loan_system.services.disbursement_service import (
    DisbursementResult,
    DisbursementScreen,
    DisbursementService,
    IntegrityFailure,
    NotApproved,
    PaymentPending,
    PreviouslyFailed,
    TransferRejected,
)
from loan_system.web.pages import (
    PREFIX,
    Csrf,
    Entry,
    code_of,
    message_of,
    redirect,
    render,
    require_page,
    validate,
)

router = APIRouter(prefix=f"{PREFIX}/queue", include_in_schema=False)

ApproverPage = Annotated[CurrentUser, Depends(require_page("LOAN_APPROVE", "EMPLOYEE"))]
RejecterPage = Annotated[CurrentUser, Depends(require_page("LOAN_REJECT", "EMPLOYEE"))]
DisburserPage = Annotated[CurrentUser, Depends(require_page("DISBURSE", "EMPLOYEE"))]

FIELD_ERRORS = {
    "version": "Trang đã cũ. Vui lòng tải lại trang rồi thử lại.",
    "comment": "Ý kiến tối đa 1.000 ký tự.",
    "reason_group": "Vui lòng chọn nhóm lý do từ chối.",
    "description": "Mô tả lý do từ chối cần ít nhất 10 ký tự.",
    "clarification": "Nội dung cần làm rõ cần ít nhất 10 ký tự.",
}
INVALID_OTP = "Mã OTP gồm 6 chữ số."


# --- M07 --------------------------------------------------------------------------------------


def approval_page(
    request: Request, user: CurrentUser, approvals: ApprovalService, application_id: uuid.UUID,
    status_code: int = status.HTTP_200_OK, **context: Any,
) -> HTMLResponse:
    view = approvals.view(user, application_id)
    return render(
        request, "approval.html",
        {
            "approval": view,
            "application": view.application,
            "score": view.score,
            "report": view.report,
            "reasons": list(RejectionReason),
            "form": context.pop("form", {}),
            **context,
        },
        user=user, status_code=status_code,
    )


def _approval_path(application_id: uuid.UUID) -> str:
    return f"{PREFIX}/queue/{application_id}/approval"


@router.get("/{application_id}/approval", response_class=HTMLResponse)
def approval(
    request: Request, application_id: uuid.UUID, user: ApproverPage, approvals: Approvals
) -> HTMLResponse:
    return approval_page(request, user, approvals, application_id)


def _decide[M: BaseModel](
    request: Request, user: CurrentUser, approvals: ApprovalService, application_id: uuid.UUID,
    model: type[M], form: dict[str, str], decide: Callable[[M], object],
) -> HTMLResponse | RedirectResponse:
    """Kiểm tra biểu mẫu bằng schema của REST API rồi quyết định; lỗi thì hiện lại M07."""
    body, field_errors = validate(model, form, FIELD_ERRORS)
    if body is None:
        return approval_page(request, user, approvals, application_id,
                             status.HTTP_400_BAD_REQUEST, field_errors=field_errors, form=form)
    try:
        decide(body)
    except ConcurrentModification as exc:
        # UC23 6b: không hiện lại nút quyết định trên dữ liệu vừa đổi; Quản lý tải lại trang để
        # xem lịch sử quyết định mới rồi mới quyết định.
        return approval_page(request, user, approvals, application_id, code_of(exc),
                             error=message_of(exc), stale=True)
    except (NotAwaitingApproval, ReportNotApprovable) as exc:
        return approval_page(request, user, approvals, application_id, code_of(exc),
                             error=message_of(exc), form=form)
    return redirect(_approval_path(application_id))


@router.post("/{application_id}/approve", dependencies=[Csrf], response_model=None)
def approve(
    request: Request, application_id: uuid.UUID, user: ApproverPage, approvals: Approvals,
    version: Entry = "", comment: Entry = "",
) -> HTMLResponse | RedirectResponse:
    return _decide(
        request, user, approvals, application_id, ApproveRequest,
        {"version": version, "comment": comment},
        lambda body: approvals.approve(user, application_id, body.version, body.comment),
    )


@router.post("/{application_id}/reject", dependencies=[Csrf], response_model=None)
def reject(
    request: Request, application_id: uuid.UUID, user: RejecterPage, approvals: Approvals,
    version: Entry = "", reason_group: Entry = "", description: Entry = "",
) -> HTMLResponse | RedirectResponse:
    return _decide(
        request, user, approvals, application_id, RejectRequest,
        {"version": version, "reason_group": reason_group, "description": description},
        lambda body: approvals.reject(
            user, application_id, body.version, body.reason_group, body.description
        ),
    )


@router.post("/{application_id}/return", dependencies=[Csrf], response_model=None)
def return_to_appraisal(
    request: Request, application_id: uuid.UUID, user: RejecterPage, approvals: Approvals,
    version: Entry = "", clarification: Entry = "",
) -> HTMLResponse | RedirectResponse:
    return _decide(
        request, user, approvals, application_id, ReturnRequest,
        {"version": version, "clarification": clarification},
        lambda body: approvals.return_to_appraisal(
            user, application_id, body.version, body.clarification
        ),
    )


# --- M08 --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Desk:
    applications: ApplicationService
    disbursements: DisbursementService


def _desk(applications: Applications, disbursements: Disbursements) -> Desk:
    return Desk(applications, disbursements)


Services = Annotated[Desk, Depends(_desk)]


def disbursement_page(
    request: Request, user: CurrentUser, desk: Desk, application_id: uuid.UUID,
    status_code: int = status.HTTP_200_OK, **context: Any,
) -> HTMLResponse:
    """M08 theo trạng thái hồ sơ vay: Đã phê duyệt (kiểm tra toàn vẹn, thông tin chuyển tiền, nhập
    TOTP), Bị khóa (toàn vẹn đỏ), Đã giải ngân (khoản vay, hợp đồng)."""
    view = desk.applications.get(user, application_id)
    screen: DisbursementScreen | None = None
    result: DisbursementResult | None = None
    if view.status == ApplicationStatus.APPROVED:
        try:
            screen = desk.disbursements.screen(user, application_id)
        except IntegrityFailure as exc:
            # SUC02 4a: hồ sơ vay vừa bị khóa; hiện trạng thái mới.
            view = desk.applications.get(user, application_id)
            status_code, context["error"] = code_of(exc), message_of(exc)
    elif view.status == ApplicationStatus.DISBURSED:
        result = desk.disbursements.completed(user, application_id)
    elif view.status != ApplicationStatus.LOCKED:
        raise NotApproved
    return render(
        request, "disbursement.html",
        {"application": view, "screen": screen, "result": result, **context},
        user=user, status_code=status_code,
    )


def _disbursement_path(application_id: uuid.UUID) -> str:
    return f"{PREFIX}/queue/{application_id}/disbursement"


@router.get("/{application_id}/disbursement", response_class=HTMLResponse)
def disbursement(
    request: Request, application_id: uuid.UUID, user: DisburserPage, desk: Services
) -> HTMLResponse:
    return disbursement_page(request, user, desk, application_id)


@router.post("/{application_id}/disburse", dependencies=[Csrf], response_model=None)
def disburse(
    request: Request, application_id: uuid.UUID, user: DisburserPage, desk: Services,
    otp: Entry = "",
) -> HTMLResponse | RedirectResponse:
    if not (len(otp) == 6 and otp.isdigit()):
        return disbursement_page(request, user, desk, application_id,
                                 status.HTTP_400_BAD_REQUEST, error=INVALID_OTP)
    try:
        desk.disbursements.disburse(user, application_id, otp)
    except (
        InvalidOtp, IntegrityFailure, PaymentPending, PreviouslyFailed, TransferRejected
    ) as exc:
        return disbursement_page(request, user, desk, application_id, code_of(exc),
                                 error=message_of(exc))
    except NotApproved:
        # Gửi biểu mẫu hai lần: yêu cầu trước đã giải ngân xong trong lúc yêu cầu này chờ khóa
        # dòng. M08 hiện đúng trạng thái hiện tại (Đã giải ngân) thay vì báo lỗi.
        pass
    return redirect(_disbursement_path(application_id))


@router.post("/{application_id}/disbursement/cancel", dependencies=[Csrf])
def cancel_disbursement(
    application_id: uuid.UUID, user: DisburserPage, disbursements: Disbursements
) -> RedirectResponse:
    """UC25 7b: hủy hồ sơ vay để khách hàng lập lại sau khi lệnh giải ngân bị từ chối."""
    disbursements.cancel_failed(user, application_id)
    return redirect(f"{PREFIX}/queue/{application_id}")


@router.get("/{application_id}/contract")
def contract(
    application_id: uuid.UUID, user: DisburserPage, disbursements: Disbursements
) -> Response:
    return Response(
        content=disbursements.contract(user, application_id), media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=hop_dong_{application_id}.pdf",
            "Cache-Control": "no-store",
        },
    )
