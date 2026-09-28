"""Hồ sơ vay: UC12–UC17 (màn hình M02, M03, M05).

Lỗi nghiệp vụ được đổi sang mã HTTP ở `api/errors.py`.
"""

import uuid
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from loan_system.api.access import FORBIDDEN_MESSAGE, Auth, enforce_rate_limit, require
from loan_system.api.deps import ClientIp, Ctx, Db
from loan_system.domain.applications import (
    MAX_AMOUNT,
    MAX_TERM_MONTHS,
    MIN_AMOUNT,
    MIN_TERM_MONTHS,
    ApplicationStatus,
    INFO_ITEMS,
    DocumentType,
    DocumentVerdict,
    Purpose,
)
from loan_system.domain.documents import MAX_DOCUMENT_BYTES
from loan_system.services.application_service import (
    ApplicationService,
    ApplicationView,
    DraftChanges,
    LoanTerms,
)
from loan_system.services.auth_service import CurrentUser
from loan_system.services.counter_service import CounterService
from loan_system.services.review_service import InfoRequest, ReviewService

router = APIRouter(prefix="/applications", tags=["Hồ sơ vay"])

Amount = Annotated[Decimal, Field(ge=MIN_AMOUNT, le=MAX_AMOUNT, decimal_places=0)]  # BR02
Term = Annotated[int, Field(ge=MIN_TERM_MONTHS, le=MAX_TERM_MONTHS)]
NonNegativeMoney = Annotated[Decimal, Field(ge=0, le=Decimal("1e12"), decimal_places=0)]
Otp = Annotated[str, Field(pattern=r"^\d{6}$")]
OTP_SENT_TO_CUSTOMER = "Mã OTP đã được gửi tới số điện thoại của khách hàng."


def restricted_to(
    kind: Literal["CUSTOMER", "EMPLOYEE"], permission: str
) -> Callable[..., CurrentUser]:
    """Quyền theo ma trận RBAC, giới hạn thêm theo loại người dùng.

    Ví dụ APPLICATION_CREATE: khách hàng tự lập hồ sơ vay ở /applications, còn NV tín dụng lập hộ
    ở /counter (UC12 1a).
    """
    has_permission = require(permission)

    def check(user: Annotated[CurrentUser, Depends(has_permission)], auth: Auth) -> CurrentUser:
        if user.kind != kind:
            auth.record_access_denied(user, "PERMISSION", permission)
            raise HTTPException(status.HTTP_403_FORBIDDEN, FORBIDDEN_MESSAGE)
        return user

    return check


CustomerUser = Annotated[CurrentUser, Depends(restricted_to("CUSTOMER", "APPLICATION_CREATE"))]
Officer = Annotated[CurrentUser, Depends(restricted_to("EMPLOYEE", "APPLICATION_CREATE"))]
# Chủ hồ sơ vay hoặc NV tín dụng đã nộp hộ (UC13); phạm vi kiểm tra ở tầng nghiệp vụ.
Editor = Annotated[CurrentUser, Depends(require("APPLICATION_CREATE"))]
Viewer = Annotated[CurrentUser, Depends(require("APPLICATION_VIEW"))]
Verifier = Annotated[CurrentUser, Depends(require("APPLICATION_VERIFY"))]
InfoRequester = Annotated[CurrentUser, Depends(require("APPLICATION_REQUEST_INFO"))]


def _applications(db: Db, ctx: Ctx, ip: ClientIp) -> ApplicationService:
    return ApplicationService(db, ctx.clock, ctx.settings, ctx.sms, ip)


def _reviews(db: Db, ctx: Ctx, ip: ClientIp) -> ReviewService:
    return ReviewService(db, ctx.clock, ctx.settings, ctx.sms, ip)


def _counter(db: Db, ctx: Ctx, ip: ClientIp) -> CounterService:
    return CounterService(db, ctx.clock, ctx.settings, ctx.sms, ip)


Applications = Annotated[ApplicationService, Depends(_applications)]
Reviews = Annotated[ReviewService, Depends(_reviews)]
Counter = Annotated[CounterService, Depends(_counter)]


# Mọi schema đầu vào chỉ nhận trường khai báo; trường thừa như status, customer_id, code bị bỏ
# qua (SR10, ST05).
class CreateApplicationRequest(BaseModel):
    requested_amount: Amount
    term_months: Term
    purpose: Purpose


class UpdateDraftRequest(BaseModel):
    requested_amount: Amount | None = None
    term_months: Term | None = None
    purpose: Purpose | None = None
    national_id: str | None = Field(default=None, pattern=r"^\d{12}$")  # CCCD 12 số
    occupation: str | None = Field(default=None, min_length=2, max_length=50)
    employer: str | None = Field(default=None, min_length=2, max_length=100)
    employment_years: int | None = Field(default=None, ge=0, le=50)
    monthly_income: NonNegativeMoney | None = None
    existing_monthly_debt: NonNegativeMoney | None = None
    housing_type: Literal["OWN", "FAMILY", "RENT"] | None = None
    address: str | None = Field(default=None, min_length=5, max_length=255)
    receiving_account: str | None = Field(default=None, pattern=r"^\d{6,20}$")


class SubmitRequest(BaseModel):
    accept_data_processing: Literal[True]  # SR14: phải tự tích, không tích sẵn


class CancelRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=200)


class ReviewRequest(BaseModel):
    verdict: DocumentVerdict
    note: str | None = Field(default=None, max_length=200)


class InfoRequestBody(BaseModel):
    message: str = Field(min_length=10, max_length=500)
    # Chỉ nhận mã mục cố định (trường thông tin hoặc loại giấy tờ), để lưu và đối chiếu an toàn.
    items: list[str] = Field(min_length=1, max_length=len(INFO_ITEMS))

    @field_validator("items")
    @classmethod
    def known_items(cls, items: list[str]) -> list[str]:
        unknown = set(items) - set(INFO_ITEMS)
        if unknown:
            raise ValueError(f"Mục không hợp lệ: {', '.join(sorted(unknown))}")
        return items


class ConsentConfirmation(BaseModel):
    challenge_id: uuid.UUID
    otp: Otp


class ChallengeResponse(BaseModel):
    challenge_id: uuid.UUID
    message: str


class DocumentReviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    verdict: str
    note: str | None


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    doc_type: str
    content_type: str
    size_bytes: int
    sha256: str
    uploaded_at: datetime
    review: DocumentReviewResponse | None = None


class ApplicantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    full_name: str
    national_id: str | None
    occupation: str | None
    employer: str | None
    employment_years: int | None
    monthly_income: Decimal | None
    housing_type: str | None
    address: str | None


class StatusChangeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: str
    at: datetime


class NeedInfoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    message: str
    items: list[str]
    deadline: datetime


class ApplicationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str | None
    customer_id: uuid.UUID
    status: str
    requested_amount: Decimal
    term_months: int
    purpose: str
    estimated_monthly_payment: Decimal
    existing_monthly_debt: Decimal | None
    receiving_account: str | None
    applicant: ApplicantResponse
    documents: list[DocumentResponse]
    history: list[StatusChangeResponse]
    need_info: NeedInfoResponse | None
    created_by: uuid.UUID | None
    received_by: uuid.UUID | None
    created_at: datetime
    submitted_at: datetime | None


class ApplicationSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str | None
    customer_id: uuid.UUID
    status: str
    requested_amount: Decimal
    term_months: int
    created_at: datetime
    submitted_at: datetime | None


def respond(view: ApplicationView) -> ApplicationResponse:
    return ApplicationResponse.model_validate(view)


# --- UC12, UC13: lập, sửa, nộp hồ sơ vay ------------------------------------------------------


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ApplicationResponse)
def create_application(
    body: CreateApplicationRequest, user: CustomerUser, applications: Applications
) -> ApplicationResponse:
    terms = LoanTerms(body.requested_amount, body.term_months, body.purpose)
    return respond(applications.create(user, terms))


@router.patch("/{application_id}", response_model=ApplicationResponse)
def update_draft(
    application_id: uuid.UUID, body: UpdateDraftRequest, user: Editor, applications: Applications
) -> ApplicationResponse:
    changes = DraftChanges(**body.model_dump(exclude_none=True))
    return respond(applications.update_draft(user, application_id, changes))


@router.post(
    "/{application_id}/documents",
    status_code=status.HTTP_201_CREATED,
    response_model=DocumentResponse,
)
def upload_document(
    application_id: uuid.UUID,
    doc_type: Annotated[DocumentType, Form()],
    file: Annotated[UploadFile, File()],
    user: Editor,
    applications: Applications,
    ctx: Ctx,
) -> DocumentResponse:
    enforce_rate_limit(ctx.limits.application_write, str(user.user_id))
    # Đọc tối đa 5MB + 1 byte: đủ để biết file quá lớn mà không nạp cả file vào bộ nhớ.
    content = file.file.read(MAX_DOCUMENT_BYTES + 1)
    document = applications.upload_document(
        user, application_id, doc_type, file.filename or "", content
    )
    return DocumentResponse.model_validate(document)


@router.post("/{application_id}/submit", response_model=ApplicationResponse)
def submit_application(
    application_id: uuid.UUID,
    body: SubmitRequest,
    user: CustomerUser,
    applications: Applications,
    ctx: Ctx,
) -> ApplicationResponse:
    enforce_rate_limit(ctx.limits.application_write, str(user.user_id))
    return respond(applications.submit(user, application_id))


@router.post(
    "/{application_id}/submit-on-behalf",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ChallengeResponse,
)
def start_submission_on_behalf(
    application_id: uuid.UUID, user: Officer, counter: Counter, ctx: Ctx
) -> ChallengeResponse:
    """UC12 1a: NV nộp hộ; khách hàng xác nhận đồng ý bằng OTP gửi tới điện thoại của họ."""
    enforce_rate_limit(ctx.limits.application_write, str(user.user_id))
    challenge_id = counter.start_submission(user, application_id)
    return ChallengeResponse(
        challenge_id=challenge_id, message=OTP_SENT_TO_CUSTOMER
    )


@router.post("/{application_id}/submit-on-behalf/confirm", response_model=ApplicationResponse)
def confirm_submission_on_behalf(
    application_id: uuid.UUID,
    body: ConsentConfirmation,
    user: Officer,
    counter: Counter,
    ctx: Ctx,
) -> ApplicationResponse:
    enforce_rate_limit(ctx.limits.otp, str(user.user_id))
    return respond(counter.confirm_submission(user, application_id, body.challenge_id, body.otp))


@router.post("/{application_id}/cancel", response_model=ApplicationResponse)
def cancel_application(
    application_id: uuid.UUID, body: CancelRequest, user: CustomerUser, applications: Applications
) -> ApplicationResponse:
    return respond(applications.cancel(user, application_id, body.reason))


# --- UC16 và hàng đợi công việc (M05) ------------------------------------------------------------


@router.get("", response_model=list[ApplicationSummaryResponse])
def list_applications(
    user: Viewer,
    applications: Applications,
    status_filter: Annotated[ApplicationStatus | None, Query(alias="status")] = None,
) -> list[ApplicationSummaryResponse]:
    summaries = applications.list_visible(user, status_filter)
    return [ApplicationSummaryResponse.model_validate(s) for s in summaries]


@router.get("/{application_id}", response_model=ApplicationResponse)
def get_application(
    application_id: uuid.UUID, user: Viewer, applications: Applications
) -> ApplicationResponse:
    return respond(applications.get(user, application_id))


# --- UC14, UC15: kiểm tra và yêu cầu bổ sung -----------------------------------------------------


@router.post("/{application_id}/claim", response_model=ApplicationResponse)
def claim_application(
    application_id: uuid.UUID, user: Verifier, reviews: Reviews
) -> ApplicationResponse:
    return respond(reviews.claim(user, application_id))


@router.put(
    "/{application_id}/documents/{document_id}/review", response_model=ApplicationResponse
)
def review_document(
    application_id: uuid.UUID,
    document_id: uuid.UUID,
    body: ReviewRequest,
    user: Verifier,
    reviews: Reviews,
) -> ApplicationResponse:
    return respond(reviews.review_document(user, application_id, document_id, body.verdict, body.note))


@router.post("/{application_id}/verify", response_model=ApplicationResponse)
def verify_application(
    application_id: uuid.UUID, user: Verifier, reviews: Reviews
) -> ApplicationResponse:
    return respond(reviews.verify(user, application_id))


@router.post("/{application_id}/request-info", response_model=ApplicationResponse)
def request_info(
    application_id: uuid.UUID, body: InfoRequestBody, user: InfoRequester, reviews: Reviews
) -> ApplicationResponse:
    return respond(reviews.request_info(user, application_id, InfoRequest(body.message, body.items)))
