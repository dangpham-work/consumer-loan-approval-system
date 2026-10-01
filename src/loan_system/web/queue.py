"""Màn hình nhân viên M05 Hàng đợi hồ sơ vay và M06 Chi tiết, thẩm định hồ sơ vay.

UC14 Kiểm tra hồ sơ vay, UC15 Yêu cầu bổ sung, UC11 xem thông tin khách hàng (đã che, "Hiện" ghi
VIEW_PII), UC20 Giải thích điểm, UC22 Thẩm định. Cùng tầng nghiệp vụ và cùng thông điệp với
`api/applications.py`.

Trang chỉ hiện thao tác người xem được làm; thao tác vi phạm phân tách nhiệm vụ (BR06) bị ẩn kèm lời
giải thích, và nếu vẫn gửi thẳng yêu cầu thì tầng nghiệp vụ chặn (403, ghi SOD_VIOLATION, ST03).
"""

import base64
import uuid
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from loan_system.api.applications import (
    AppraisalRequest,
    Applications,
    Appraisals,
    InfoRequestBody,
    Reviews,
    Scoring,
)
from loan_system.domain.applications import INFO_ITEMS, ApplicationStatus, DocumentVerdict
from loan_system.domain.appraisal import InvalidProposal, Proposal, Recommendation
from loan_system.services.application_service import (
    ApplicationService,
    ApplicationSummary,
    ApplicationView,
)
from loan_system.services.appraisal_service import (
    AppraisalService,
    DtiPreview,
    DtiTooHigh,
    PII_PERMISSION,
)
from loan_system.services.auth_service import CurrentUser
from loan_system.services.review_service import (
    DocumentsNotAccepted,
    InfoRequest,
    ReviewService,
)
from loan_system.services.scoring_service import ScoreNotFound, ScoreView, ScoringService
from loan_system.web.pages import (
    PREFIX,
    Csrf,
    Entry,
    PageError,
    code_of,
    message_of,
    redirect,
    render,
    require_page,
    validate,
)

router = APIRouter(prefix=f"{PREFIX}/queue", include_in_schema=False)

QueuePage = Annotated[CurrentUser, Depends(require_page("APPLICATION_VIEW", "EMPLOYEE"))]
VerifierPage = Annotated[CurrentUser, Depends(require_page("APPLICATION_VERIFY", "EMPLOYEE"))]
InfoRequesterPage = Annotated[
    CurrentUser, Depends(require_page("APPLICATION_REQUEST_INFO", "EMPLOYEE"))
]
AppraiserPage = Annotated[CurrentUser, Depends(require_page("APPRAISAL_SUBMIT", "EMPLOYEE"))]

# Hàng đợi công việc mặc định: trạng thái mà từng quyền phải xử lý tiếp.
WORK = (
    ("APPLICATION_VERIFY", ApplicationStatus.SUBMITTED),
    ("APPRAISAL_SUBMIT", ApplicationStatus.APPRAISING),
    ("LOAN_APPROVE", ApplicationStatus.PENDING_APPROVAL),
    ("DISBURSE", ApplicationStatus.APPROVED),
)
ALL = "ALL"

FIELD_ERRORS = {
    "message": "Lời nhắn từ 10 đến 500 ký tự.",
    "items": "Chọn ít nhất một mục cần bổ sung.",
    "recommendation": "Vui lòng chọn đề xuất.",
    "proposed_amount": "Hạn mức đề xuất từ 5.000.000 đến 100.000.000 đồng.",
    "proposed_term": "Kỳ hạn đề xuất từ 6 đến 36 tháng.",
    "comment": "Nhận xét tối đa 1.000 ký tự.",
}


@dataclass(frozen=True)
class Desk:
    """Các dịch vụ mà màn hình M06 dùng."""

    applications: ApplicationService
    reviews: ReviewService
    scoring: ScoringService
    appraisals: AppraisalService


def _desk(
    applications: Applications, reviews: Reviews, scoring: Scoring, appraisals: Appraisals
) -> Desk:
    return Desk(applications, reviews, scoring, appraisals)


Services = Annotated[Desk, Depends(_desk)]


@dataclass(frozen=True)
class Actions:
    """Thao tác người xem được làm trên hồ sơ vay, suy ra từ trạng thái, quyền và vai trò đã tham
    gia (SUC01). Tầng nghiệp vụ vẫn kiểm tra lại từng thao tác."""

    claim: bool
    review: bool  # Người tiếp nhận: kiểm tra giấy tờ, xác nhận hợp lệ
    request_info: bool
    open_appraisal: bool
    appraise: bool  # người thẩm định của hồ sơ vay
    held_by_other: bool
    sod_blocked: bool


def actions_for(user: CurrentUser, view: ApplicationView) -> Actions:
    me = user.employee_id
    submitted = view.status == ApplicationStatus.SUBMITTED
    appraising = view.status == ApplicationStatus.APPRAISING
    can_verify = submitted and "APPLICATION_VERIFY" in user.permissions
    can_appraise = appraising and "APPRAISAL_SUBMIT" in user.permissions
    receiver = me is not None and submitted and view.received_by == me
    claim_blocked = (
        can_verify and view.received_by is None and me is not None and me == view.created_by
    )
    appraise_blocked = (
        can_appraise and view.appraised_by is None and me is not None
        and me in (view.created_by, view.received_by)
    )
    return Actions(
        claim=can_verify and view.received_by is None and not claim_blocked,
        review=receiver and "APPLICATION_VERIFY" in user.permissions,
        request_info=receiver and "APPLICATION_REQUEST_INFO" in user.permissions,
        open_appraisal=can_appraise and view.appraised_by is None and not appraise_blocked,
        appraise=me is not None and appraising and view.appraised_by == me,
        held_by_other=(can_verify and view.received_by not in (None, me))
        or (can_appraise and view.appraised_by not in (None, me)),
        sod_blocked=claim_blocked or appraise_blocked,
    )


# --- M05 --------------------------------------------------------------------------------------


def _work_statuses(user: CurrentUser) -> list[ApplicationStatus]:
    return [s for permission, s in WORK if permission in user.permissions]


def queue_page(
    request: Request, user: CurrentUser, applications: ApplicationService,
    selected: str = "", q: str = "",
) -> HTMLResponse:
    if selected == ALL:
        statuses: list[ApplicationStatus | None] = [None]
    elif selected:
        try:
            statuses = [ApplicationStatus(selected)]
        except ValueError as exc:
            raise PageError(status.HTTP_400_BAD_REQUEST) from exc
    else:
        statuses = [*_work_statuses(user)] or [None]
    summaries: list[ApplicationSummary] = []
    for s in statuses:
        summaries += applications.list_visible(user, s, q.strip()[:100] or None)
    summaries.sort(key=lambda a: a.submitted_at or a.created_at)
    return render(
        request, "queue.html",
        {
            "applications": summaries, "selected": selected, "q": q,
            "statuses": list(ApplicationStatus), "all": ALL,
        },
        user=user,
    )


@router.get("", response_class=HTMLResponse)
def queue(
    request: Request, user: QueuePage, applications: Applications,
    status_filter: Annotated[str, Query(alias="status")] = "", q: str = "",
) -> HTMLResponse:
    return queue_page(request, user, applications, status_filter, q)


# --- M06 --------------------------------------------------------------------------------------


def _score(desk: Desk, user: CurrentUser, view: ApplicationView) -> ScoreView | None:
    if "CREDIT_SCORE_VIEW" not in user.permissions:
        return None
    try:
        return desk.scoring.explain(user, view.id)
    except ScoreNotFound:
        return None


def _proposal_form(view: ApplicationView) -> dict[str, str]:
    return {
        "recommendation": Recommendation.APPROVE,
        "proposed_amount": str(view.requested_amount),
        "proposed_term": str(view.term_months),
        "fraud_suspected": "",
        "comment": "",
    }


def detail_page(
    request: Request, user: CurrentUser, desk: Desk, application_id: uuid.UUID,
    status_code: int = status.HTTP_200_OK, **context: Any,
) -> HTMLResponse:
    view = desk.applications.get(user, application_id)
    actions = actions_for(user, view)
    return render(
        request, "queue_detail.html",
        {
            "application": view,
            "actions": actions,
            "score": _score(desk, user, view),
            "report": (
                desk.appraisals.report(user, view.id)
                if "CREDIT_SCORE_VIEW" in user.permissions else None
            ),
            "can_reveal": PII_PERMISSION in user.permissions,
            "info_items": INFO_ITEMS,
            "verdicts": list(DocumentVerdict),
            "proposal": context.pop("proposal", None) or _proposal_form(view),
            **context,
        },
        user=user, status_code=status_code,
    )


def _back(application_id: uuid.UUID) -> RedirectResponse:
    return redirect(f"{PREFIX}/queue/{application_id}")


@router.get("/{application_id}", response_class=HTMLResponse)
def application_detail(
    request: Request, application_id: uuid.UUID, user: QueuePage, desk: Services
) -> HTMLResponse:
    return detail_page(request, user, desk, application_id)


# --- UC14, UC15 -------------------------------------------------------------------------------


@router.post("/{application_id}/claim", dependencies=[Csrf])
def claim(application_id: uuid.UUID, user: VerifierPage, reviews: Reviews) -> RedirectResponse:
    reviews.claim(user, application_id)
    return _back(application_id)


@router.post("/{application_id}/documents/{document_id}/review", dependencies=[Csrf])
def review_document(
    application_id: uuid.UUID, document_id: uuid.UUID, user: VerifierPage, reviews: Reviews,
    verdict: Annotated[DocumentVerdict, Form()], note: Entry = "",
) -> RedirectResponse:
    reviews.review_document(user, application_id, document_id, verdict,
                            note.strip()[:200] or None)
    return _back(application_id)


@router.post("/{application_id}/verify", dependencies=[Csrf], response_model=None)
def verify(
    request: Request, application_id: uuid.UUID, user: VerifierPage, desk: Services
) -> HTMLResponse | RedirectResponse:
    try:
        desk.reviews.verify(user, application_id)
    except DocumentsNotAccepted as exc:
        return detail_page(request, user, desk, application_id, code_of(exc),
                           error=message_of(exc))
    return _back(application_id)


@router.post("/{application_id}/request-info", dependencies=[Csrf], response_model=None)
def request_info(
    request: Request, application_id: uuid.UUID, user: InfoRequesterPage, desk: Services,
    message: Entry = "", items: Annotated[list[str], Form()] = [],  # noqa: B006
) -> HTMLResponse | RedirectResponse:
    body, field_errors = validate(
        InfoRequestBody, {"message": message.strip(), "items": items}, FIELD_ERRORS
    )
    if body is None:
        return detail_page(request, user, desk, application_id, status.HTTP_400_BAD_REQUEST,
                           field_errors=field_errors, info_form={"message": message,
                                                                 "items": items})
    desk.reviews.request_info(user, application_id, InfoRequest(body.message, body.items))
    return _back(application_id)


# --- UC22 -------------------------------------------------------------------------------------


@router.post("/{application_id}/appraisal/open", dependencies=[Csrf])
def open_appraisal(
    application_id: uuid.UUID, user: AppraiserPage, appraisals: Appraisals
) -> RedirectResponse:
    # Dữ liệu che sẵn: CCCD, thu nhập chỉ hiện (và ghi VIEW_PII) khi bấm "Hiện".
    appraisals.open(user, application_id, reveal=False)
    return _back(application_id)


@router.post("/{application_id}/appraisal", dependencies=[Csrf], response_model=None)
def submit_appraisal(
    request: Request, application_id: uuid.UUID, user: AppraiserPage, desk: Services,
    recommendation: Entry = "", proposed_amount: Entry = "", proposed_term: Entry = "",
    fraud_suspected: Annotated[bool, Form()] = False, comment: Entry = "",
    action: Entry = "submit",
) -> HTMLResponse | RedirectResponse:
    form = {
        "recommendation": recommendation, "proposed_amount": proposed_amount,
        "proposed_term": proposed_term, "fraud_suspected": "true" if fraud_suspected else "",
        "comment": comment,
    }

    def failed(code: int, **context: Any) -> HTMLResponse:
        return detail_page(request, user, desk, application_id, code, proposal=form, **context)

    # Nhận xét để trống vẫn hợp lệ ở schema; tầng miền báo "ít nhất 20 ký tự" khi nộp.
    body, field_errors = validate(
        AppraisalRequest, {**form, "fraud_suspected": fraud_suspected}, FIELD_ERRORS,
        keep={"comment"},
    )
    if body is None:
        return failed(status.HTTP_400_BAD_REQUEST, field_errors=field_errors)
    try:
        if action == "preview":
            if body.proposed_amount is None or body.proposed_term is None:
                raise InvalidProposal("Nhập hạn mức và kỳ hạn đề xuất để tính DTI")
            preview: DtiPreview = desk.appraisals.preview_dti(
                user, application_id, body.proposed_amount, body.proposed_term
            )
            return failed(status.HTTP_200_OK, preview=preview)
        proposal = Proposal(
            body.recommendation, body.proposed_amount, body.proposed_term, body.comment
        )
        desk.appraisals.submit(user, application_id, proposal, body.fraud_suspected)
    except (InvalidProposal, DtiTooHigh) as exc:
        return failed(code_of(exc), error=message_of(exc))
    return _back(application_id)


@router.get("/{application_id}/documents/{document_id}", response_class=HTMLResponse)
def view_document(
    request: Request, application_id: uuid.UUID, document_id: uuid.UUID, user: AppraiserPage,
    desk: Services,
) -> HTMLResponse:
    """Trình xem giấy tờ của M06: nội dung nhúng thẳng vào trang (một lượt xem, một dòng VIEW_PII),
    ảnh đã in watermark; PDF được phủ watermark lên trên."""
    shown = desk.appraisals.document(user, application_id, document_id)
    view = desk.applications.get(user, application_id)
    doc_type = next((d.doc_type for d in view.documents if d.id == document_id), "")
    response = render(
        request, "document_viewer.html",
        {
            "application": view,
            "doc_type": doc_type,
            "watermark": shown.watermark,
            "content_type": shown.content_type,
            "data": base64.b64encode(shown.content).decode(),
            "is_pdf": shown.content_type == "application/pdf",
        },
        user=user,
    )
    response.headers["Cache-Control"] = "no-store"
    return response
