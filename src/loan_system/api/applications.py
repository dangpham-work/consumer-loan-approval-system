"""UC12 Tạo và nộp hồ sơ vay, UC13 Tải lên giấy tờ, UC16 Theo dõi trạng thái (màn hình M02, M03)."""

import uuid
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from loan_system.api.access import FORBIDDEN_MESSAGE, Auth, enforce_rate_limit, require
from loan_system.api.deps import ClientIp, Ctx, Db
from loan_system.domain.applications import (
    MAX_AMOUNT,
    MAX_TERM_MONTHS,
    MIN_AMOUNT,
    MIN_TERM_MONTHS,
    DocumentType,
    Purpose,
)
from loan_system.domain.documents import MAX_DOCUMENT_BYTES, InvalidDocument
from loan_system.services.application_service import (
    ApplicationInProgress,
    ApplicationNotFound,
    ApplicationService,
    ApplicationSummary,
    ApplicationView,
    ConcurrentModification,
    DocumentView,
    DraftChanges,
    IncompleteApplication,
    LoanTerms,
    NationalIdConflict,
    NotEditable,
    TooManyDocuments,
)
from loan_system.services.auth_service import CurrentUser

router = APIRouter(prefix="/applications", tags=["Hồ sơ vay"])

NOT_FOUND = "Không tìm thấy hồ sơ vay"

Amount = Annotated[Decimal, Field(ge=MIN_AMOUNT, le=MAX_AMOUNT, decimal_places=0)]  # BR02
Term = Annotated[int, Field(ge=MIN_TERM_MONTHS, le=MAX_TERM_MONTHS)]
NonNegativeMoney = Annotated[Decimal, Field(ge=0, le=Decimal("1e12"), decimal_places=0)]


def customer_with(permission: str) -> Callable[..., CurrentUser]:
    """Quyền theo ma trận RBAC, trong phạm vi "O": chỉ khách hàng, trên hồ sơ vay của chính mình.

    Nhân viên tín dụng nộp hộ tại quầy đi theo luồng riêng (UC12 1a).
    """
    has_permission = require(permission)

    def check(user: Annotated[CurrentUser, Depends(has_permission)], auth: Auth) -> CurrentUser:
        if user.customer_id is None:
            auth.record_access_denied(user, "PERMISSION", permission)
            raise HTTPException(status.HTTP_403_FORBIDDEN, FORBIDDEN_MESSAGE)
        return user

    return check


Creator = Annotated[CurrentUser, Depends(customer_with("APPLICATION_CREATE"))]
Viewer = Annotated[CurrentUser, Depends(customer_with("APPLICATION_VIEW"))]


def _service(db: Db, ctx: Ctx, ip: ClientIp) -> ApplicationService:
    return ApplicationService(db, ctx.clock, ctx.settings, ip)


Applications = Annotated[ApplicationService, Depends(_service)]


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


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    doc_type: str
    content_type: str
    size_bytes: int
    sha256: str
    uploaded_at: datetime


class ApplicantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    national_id: str | None
    occupation: str | None
    employer: str | None
    employment_years: int | None
    monthly_income: Decimal | None
    housing_type: str | None
    address: str | None


class ApplicationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str | None
    status: str
    requested_amount: Decimal
    term_months: int
    purpose: str
    estimated_monthly_payment: Decimal
    existing_monthly_debt: Decimal | None
    receiving_account: str | None
    applicant: ApplicantResponse
    documents: list[DocumentResponse]
    created_at: datetime
    submitted_at: datetime | None


class ApplicationSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str | None
    status: str
    requested_amount: Decimal
    term_months: int
    created_at: datetime
    submitted_at: datetime | None


def _respond(view: ApplicationView) -> ApplicationResponse:
    return ApplicationResponse.model_validate(view)


def _not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND)


def _not_editable() -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, "Hồ sơ vay đã nộp, không thể thay đổi")


def _conflict() -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, "Hồ sơ vay vừa được cập nhật, vui lòng tải lại")


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ApplicationResponse)
def create_application(
    body: CreateApplicationRequest, user: Creator, applications: Applications
) -> ApplicationResponse:
    try:
        view = applications.create(
            user, LoanTerms(body.requested_amount, body.term_months, body.purpose)
        )
    except ApplicationInProgress as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Bạn đang có một hồ sơ vay hoặc khoản vay chưa kết thúc"
        ) from exc
    return _respond(view)


@router.patch("/{application_id}", response_model=ApplicationResponse)
def update_draft(
    application_id: uuid.UUID, body: UpdateDraftRequest, user: Creator, applications: Applications
) -> ApplicationResponse:
    try:
        view = applications.update_draft(
            user, application_id, DraftChanges(**body.model_dump(exclude_none=True))
        )
    except ApplicationNotFound as exc:
        raise _not_found() from exc
    except NotEditable as exc:
        raise _not_editable() from exc
    except ConcurrentModification as exc:
        raise _conflict() from exc
    except NationalIdConflict as exc:
        # Không nói CCCD đang thuộc về ai (giống thông điệp trùng khi đăng ký, UC09 2b).
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Không thể dùng số CCCD này. Vui lòng liên hệ nhân viên tín dụng.",
        ) from exc
    return _respond(view)


@router.post(
    "/{application_id}/documents",
    status_code=status.HTTP_201_CREATED,
    response_model=DocumentResponse,
)
def upload_document(
    application_id: uuid.UUID,
    doc_type: Annotated[DocumentType, Form()],
    file: Annotated[UploadFile, File()],
    user: Creator,
    applications: Applications,
    ctx: Ctx,
) -> DocumentResponse:
    enforce_rate_limit(ctx.limits.application_write, str(user.user_id))
    # Đọc tối đa 5MB + 1 byte: đủ để biết file quá lớn mà không nạp cả file vào bộ nhớ.
    content = file.file.read(MAX_DOCUMENT_BYTES + 1)
    try:
        document: DocumentView = applications.upload_document(
            user, application_id, doc_type, file.filename or "", content
        )
    except ApplicationNotFound as exc:
        raise _not_found() from exc
    except NotEditable as exc:
        raise _not_editable() from exc
    except ConcurrentModification as exc:
        raise _conflict() from exc
    except InvalidDocument as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except TooManyDocuments as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "Hồ sơ vay đã có quá nhiều file") from exc
    return DocumentResponse.model_validate(document)


@router.post("/{application_id}/submit", response_model=ApplicationResponse)
def submit_application(
    application_id: uuid.UUID,
    body: SubmitRequest,
    user: Creator,
    applications: Applications,
    ctx: Ctx,
) -> ApplicationResponse | JSONResponse:
    enforce_rate_limit(ctx.limits.application_write, str(user.user_id))
    try:
        view = applications.submit(user, application_id)
    except ApplicationNotFound as exc:
        raise _not_found() from exc
    except NotEditable as exc:
        raise _not_editable() from exc
    except ConcurrentModification as exc:
        raise _conflict() from exc
    except IncompleteApplication as exc:
        # Cùng định dạng với lỗi kiểm tra dữ liệu (mục 4.2.4): trường nào thiếu.
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "detail": "Hồ sơ vay chưa đủ thông tin hoặc giấy tờ",
                "errors": [{"field": item, "message": "Còn thiếu"} for item in exc.missing],
            },
        )
    return _respond(view)


@router.get("", response_model=list[ApplicationSummaryResponse])
def list_applications(user: Viewer, applications: Applications) -> list[ApplicationSummaryResponse]:
    summaries: list[ApplicationSummary] = applications.list_mine(user)
    return [ApplicationSummaryResponse.model_validate(s) for s in summaries]


@router.get("/{application_id}", response_model=ApplicationResponse)
def get_application(
    application_id: uuid.UUID, user: Viewer, applications: Applications
) -> ApplicationResponse:
    try:
        return _respond(applications.get(user, application_id))
    except ApplicationNotFound as exc:
        raise _not_found() from exc
