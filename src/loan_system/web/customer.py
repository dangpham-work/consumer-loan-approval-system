"""Màn hình khách hàng M02 Trang chủ và M03 Biểu mẫu nộp hồ sơ vay 4 bước.

UC10 Cập nhật thông tin cá nhân, UC12 Tạo và nộp hồ sơ vay, UC13 Tải lên giấy tờ, UC15 bổ sung hồ sơ
vay (phía khách hàng), UC16 Theo dõi trạng thái, UC17 Hủy hồ sơ vay.

Cùng tầng nghiệp vụ, cùng schema kiểm tra dữ liệu và cùng thông điệp với `api/applications.py`,
`api/customers.py`. Phạm vi truy cập (SR04, ST01) kiểm tra ở tầng nghiệp vụ: hồ sơ vay của người
khác được báo như không tồn tại (trang lỗi 404).
"""

import uuid
from collections.abc import Mapping
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from loan_system.api.access import Auth
from loan_system.api.applications import (
    Applications,
    ConsentConfirmation,
    CreateApplicationRequest,
    UpdateDraftRequest,
)
from loan_system.api.customers import (
    Customers,
    EmailChangeRequest,
    PhoneChangeRequest,
    UpdateProfileRequest,
)
from loan_system.api.deps import Ctx
from loan_system.api.payments import Payments
from loan_system.domain.applications import (
    CEILING_RATE,
    CUSTOMER_CANCELLABLE,
    DOCUMENT_TYPES,
    EDITABLE,
    IN_PROGRESS,
    MAX_AMOUNT,
    MAX_TERM_MONTHS,
    MIN_AMOUNT,
    MIN_TERM_MONTHS,
    ApplicationStatus,
    DocumentType,
    Purpose,
)
from loan_system.domain.documents import MAX_DOCUMENT_BYTES, InvalidDocument
from loan_system.domain.text import vnd
from loan_system.services.application_service import (
    ApplicationInProgress,
    ApplicationView,
    DraftChanges,
    IncompleteApplication,
    LoanTerms,
    NationalIdConflict,
    TooManyDocuments,
)
from loan_system.services.auth_service import CurrentUser
from loan_system.services.customer_service import ContactTaken, IncomeLocked, ProfileChanges
from loan_system.services.otp_challenge_service import ChallengeFailed
from loan_system.web.labels import ITEMS
from loan_system.web.pages import (
    ERROR_MESSAGES,
    PREFIX,
    Csrf,
    Entry,
    PageError,
    PageUser,
    code_of,
    message_of,
    redirect,
    render,
    require_page,
    validate,
)
from loan_system.web.queue import queue_page

router = APIRouter(prefix=PREFIX, include_in_schema=False)

CustomerPage = Annotated[CurrentUser, Depends(require_page("APPLICATION_CREATE", "CUSTOMER"))]
# Bước 1–3 và trang xác nhận của M03 dùng chung cho NV tín dụng nộp hộ (UC12 1a, `web/counter.py`);
# phạm vi (chủ hồ sơ vay hoặc Người tạo) kiểm tra ở tầng nghiệp vụ.
EditorPage = Annotated[CurrentUser, Depends(require_page("APPLICATION_CREATE"))]


def customer_only(user: PageUser, auth: Auth) -> CurrentUser:
    """UC10: mọi khách hàng sửa hồ sơ cá nhân của chính mình, không cần quyền nghiệp vụ riêng
    (như `api.customers.customer_only`)."""
    if user.customer_id is None:
        auth.record_access_denied(user, "CUSTOMER_PROFILE", "self")
        raise PageError(status.HTTP_403_FORBIDDEN)
    return user


ProfilePage = Annotated[CurrentUser, Depends(customer_only)]

TOO_MANY = ERROR_MESSAGES[status.HTTP_429_TOO_MANY_REQUESTS]
CONSENT_REQUIRED = "Bạn cần đồng ý cho phép xử lý dữ liệu cá nhân để nộp hồ sơ vay."

# Lỗi kiểm tra của pydantic là tiếng Anh: thông điệp riêng cho từng trường của biểu mẫu.
FIELD_ERRORS = {
    "requested_amount": f"Số tiền vay từ {vnd(MIN_AMOUNT)} đến {vnd(MAX_AMOUNT)} đồng.",
    "term_months": f"Kỳ hạn từ {MIN_TERM_MONTHS} đến {MAX_TERM_MONTHS} tháng.",
    "purpose": "Vui lòng chọn mục đích vay.",
    "national_id": "Số CCCD gồm 12 chữ số.",
    "occupation": "Nghề nghiệp từ 2 đến 50 ký tự.",
    "employer": "Nơi làm việc từ 2 đến 100 ký tự.",
    "employment_years": "Số năm làm việc từ 0 đến 50.",
    "monthly_income": "Thu nhập hằng tháng là số tiền không âm, tính bằng đồng.",
    "existing_monthly_debt": "Tiền trả nợ hằng tháng là số tiền không âm, tính bằng đồng.",
    "housing_type": "Vui lòng chọn hình thức nhà ở.",
    "address": "Địa chỉ từ 5 đến 255 ký tự.",
    "receiving_account": "Số tài khoản gồm 6 đến 20 chữ số.",
}

STEPS = (
    ("loan", "Thông tin khoản vay"),
    ("finance", "Thông tin tài chính"),
    ("documents", "Tải giấy tờ"),
    ("confirm", "Xác nhận và đồng ý"),
)


def _requested(view: ApplicationView) -> set[str] | None:
    """Mục được sửa khi bổ sung (UC15); None khi là bản nháp (sửa được mọi mục)."""
    return set(view.need_info.items) if view.need_info else None


def wizard(
    request: Request, user: CurrentUser, step: str, view: ApplicationView | None,
    status_code: int = status.HTTP_200_OK, **context: Any,
) -> HTMLResponse:
    return render(
        request, f"apply_{step}.html",
        {
            "steps": STEPS, "step": step, "application": view,
            "requested": _requested(view) if view else None, **context,
        },
        user=user, status_code=status_code,
    )


def detail_path(user: CurrentUser, application_id: uuid.UUID) -> str:
    """Trang chi tiết hồ sơ vay: M02 của khách hàng, M06 của nhân viên."""
    if user.kind == "CUSTOMER":
        return f"{PREFIX}/applications/{application_id}"
    return f"{PREFIX}/queue/{application_id}"


def _editable_by(user: CurrentUser, view: ApplicationView) -> bool:
    """Trang sửa chỉ mở cho chủ hồ sơ vay hoặc Người tạo (nhân viên nộp hộ), như `load(edit=True)`:
    nhân viên khác xem được hồ sơ vay nhưng không được mở các bước sửa."""
    if view.status not in EDITABLE:
        return False
    return user.kind == "CUSTOMER" or (
        user.employee_id is not None and view.created_by == user.employee_id
    )


def _editable_or_detail(
    request: Request, user: CurrentUser, step: str, view: ApplicationView
) -> HTMLResponse | RedirectResponse:
    if not _editable_by(user, view):
        return redirect(detail_path(user, view.id))
    return wizard(request, user, step, view)


# --- M02 --------------------------------------------------------------------------------------


@router.get("", response_class=HTMLResponse)
def home(
    request: Request, user: PageUser, applications: Applications, payments: Payments
) -> HTMLResponse:
    if user.kind != "CUSTOMER":
        # Nhân viên nghiệp vụ vào thẳng hàng đợi (M05); Quản trị viên, Kiểm soát viên thì không.
        if "APPLICATION_VIEW" in user.permissions:
            return queue_page(request, user, applications)
        return render(request, "home.html", user=user)
    summaries = applications.list_visible(user, None)
    loans = payments.own_loans(user)
    busy = any(a.status in IN_PROGRESS for a in summaries) or bool(loans)
    return render(
        request, "customer_home.html",
        {
            "applications": summaries,
            "loans": loans,
            "can_apply": not busy,
            "cancellable": CUSTOMER_CANCELLABLE,
        },
        user=user,
    )


# --- M03 bước 1: thông tin khoản vay ------------------------------------------------------------


def _loan_form(view: ApplicationView | None) -> dict[str, str]:
    if view is None:
        return {"requested_amount": "", "term_months": "", "purpose": ""}
    return {
        "requested_amount": str(view.requested_amount),
        "term_months": str(view.term_months),
        "purpose": view.purpose,
    }


def loan_step(
    request: Request, user: CurrentUser, view: ApplicationView | None, form: Mapping[str, str],
    status_code: int = status.HTTP_200_OK, **context: Any,
) -> HTMLResponse:
    return wizard(
        request, user, "loan", view, status_code,
        form=form, purposes=list(Purpose), ceiling_rate=CEILING_RATE,
        min_amount=MIN_AMOUNT, max_amount=MAX_AMOUNT,
        min_term=MIN_TERM_MONTHS, max_term=MAX_TERM_MONTHS, **context,
    )


@router.get("/applications/new", response_class=HTMLResponse)
def new_application_page(request: Request, user: CustomerPage) -> HTMLResponse:
    return loan_step(request, user, None, _loan_form(None))


@router.post("/applications/new", dependencies=[Csrf], response_model=None)
def create_application(
    request: Request, user: CustomerPage, applications: Applications,
    requested_amount: Entry = "", term_months: Entry = "", purpose: Entry = "",
) -> HTMLResponse | RedirectResponse:
    form = {"requested_amount": requested_amount, "term_months": term_months, "purpose": purpose}
    body, field_errors = validate(CreateApplicationRequest, form, FIELD_ERRORS)
    if body is None:
        return loan_step(request, user, None, form, status.HTTP_400_BAD_REQUEST,
                          field_errors=field_errors)
    try:
        view = applications.create(
            user, LoanTerms(body.requested_amount, body.term_months, body.purpose)
        )
    except ApplicationInProgress as exc:
        return loan_step(request, user, None, form, status.HTTP_409_CONFLICT,
                          error=message_of(exc))
    return redirect(f"{PREFIX}/applications/{view.id}/finance")


# Sau /applications/new: "new" không phải mã hồ sơ vay.
@router.get("/applications/{application_id}", response_class=HTMLResponse)
def application_detail(
    request: Request, application_id: uuid.UUID, user: CustomerPage, applications: Applications
) -> HTMLResponse:
    view = applications.get(user, application_id)
    return render(
        request, "application_detail.html",
        {
            "application": view,
            "editable": view.status in EDITABLE,
            "cancellable": view.status in CUSTOMER_CANCELLABLE,
        },
        user=user,
    )


@router.post("/applications/{application_id}/cancel", dependencies=[Csrf])
def cancel_application(
    application_id: uuid.UUID, user: CustomerPage, applications: Applications,
    reason: Entry = "",
) -> RedirectResponse:
    applications.cancel(user, application_id, reason.strip()[:200] or None)
    return redirect(f"{PREFIX}?notice=cancelled")


@router.get("/applications/{application_id}/loan", response_model=None)
def loan_page(
    request: Request, application_id: uuid.UUID, user: EditorPage, applications: Applications
) -> HTMLResponse | RedirectResponse:
    view = applications.get(user, application_id)
    if view.status != ApplicationStatus.DRAFT or not _editable_by(user, view):
        # Khi bổ sung không được đổi số tiền, kỳ hạn, mục đích (UC15): đi thẳng bước 2.
        if _editable_by(user, view):
            return redirect(f"{PREFIX}/applications/{view.id}/finance")
        return redirect(detail_path(user, view.id))
    return loan_step(request, user, view, _loan_form(view))


@router.post("/applications/{application_id}/loan", dependencies=[Csrf], response_model=None)
def update_loan(
    request: Request, application_id: uuid.UUID, user: EditorPage, applications: Applications,
    requested_amount: Entry = "", term_months: Entry = "", purpose: Entry = "",
) -> HTMLResponse | RedirectResponse:
    form = {"requested_amount": requested_amount, "term_months": term_months, "purpose": purpose}
    body, field_errors = validate(CreateApplicationRequest, form, FIELD_ERRORS)
    if body is None:
        view = applications.get(user, application_id)
        return loan_step(request, user, view, form, status.HTTP_400_BAD_REQUEST,
                          field_errors=field_errors)
    changes = DraftChanges(
        requested_amount=body.requested_amount, term_months=body.term_months, purpose=body.purpose
    )
    applications.update_draft(user, application_id, changes)
    return redirect(f"{PREFIX}/applications/{application_id}/finance")


# --- M03 bước 2: thông tin tài chính -----------------------------------------------------------


@router.get("/applications/{application_id}/finance", response_model=None)
def finance_page(
    request: Request, application_id: uuid.UUID, user: EditorPage, applications: Applications
) -> HTMLResponse | RedirectResponse:
    return _editable_or_detail(request, user, "finance", applications.get(user, application_id))


@router.post("/applications/{application_id}/finance", dependencies=[Csrf], response_model=None)
def update_finance(
    request: Request, application_id: uuid.UUID, user: EditorPage, applications: Applications,
    national_id: Entry = "", occupation: Entry = "", employer: Entry = "",
    employment_years: Entry = "", monthly_income: Entry = "",
    existing_monthly_debt: Entry = "", housing_type: Entry = "", address: Entry = "",
    receiving_account: Entry = "",
) -> HTMLResponse | RedirectResponse:
    form = {
        "national_id": national_id, "occupation": occupation, "employer": employer,
        "employment_years": employment_years, "monthly_income": monthly_income,
        "existing_monthly_debt": existing_monthly_debt, "housing_type": housing_type,
        "address": address, "receiving_account": receiving_account,
    }

    def failed(code: int, **context: Any) -> HTMLResponse:
        view = applications.get(user, application_id)
        return wizard(request, user, "finance", view, code, form=form, **context)

    body, field_errors = validate(UpdateDraftRequest, form, FIELD_ERRORS)
    if body is None:
        return failed(status.HTTP_400_BAD_REQUEST, field_errors=field_errors)
    changes = DraftChanges(**body.model_dump(exclude_none=True))
    if any(v is not None for v in vars(changes).values()):
        try:
            applications.update_draft(user, application_id, changes)
        except NationalIdConflict as exc:
            return failed(status.HTTP_409_CONFLICT, error=message_of(exc))
    return redirect(f"{PREFIX}/applications/{application_id}/documents")


# --- M03 bước 3: tải giấy tờ -------------------------------------------------------------------


def _documents_step(
    request: Request, user: CurrentUser, view: ApplicationView,
    status_code: int = status.HTTP_200_OK, **context: Any,
) -> HTMLResponse:
    uploaded = {d.doc_type: d for d in view.documents}
    return wizard(
        request, user, "documents", view, status_code,
        document_types=DOCUMENT_TYPES, uploaded=uploaded,
        max_mb=MAX_DOCUMENT_BYTES // (1024 * 1024), **context,
    )


@router.get("/applications/{application_id}/documents", response_model=None)
def documents_page(
    request: Request, application_id: uuid.UUID, user: EditorPage, applications: Applications
) -> HTMLResponse | RedirectResponse:
    view = applications.get(user, application_id)
    if not _editable_by(user, view):
        return redirect(detail_path(user, view.id))
    return _documents_step(request, user, view)


@router.post("/applications/{application_id}/documents", dependencies=[Csrf], response_model=None)
def upload_document(
    request: Request, application_id: uuid.UUID, user: EditorPage, applications: Applications,
    ctx: Ctx, doc_type: Annotated[DocumentType, Form()], file: Annotated[UploadFile, File()],
) -> HTMLResponse | RedirectResponse:
    def failed(code: int, error: str) -> HTMLResponse:
        return _documents_step(request, user, applications.get(user, application_id), code,
                               error=error)

    if not ctx.limits.application_write.hit(str(user.user_id)):
        return failed(status.HTTP_429_TOO_MANY_REQUESTS, TOO_MANY)
    # Như REST API: đọc tối đa 5MB + 1 byte, đủ biết file quá lớn mà không nạp cả file.
    content = file.file.read(MAX_DOCUMENT_BYTES + 1)
    try:
        applications.upload_document(user, application_id, doc_type, file.filename or "", content)
    except (InvalidDocument, TooManyDocuments) as exc:
        code = status.HTTP_400_BAD_REQUEST if isinstance(exc, InvalidDocument) else (
            status.HTTP_409_CONFLICT
        )
        return failed(code, message_of(exc))
    return redirect(f"{PREFIX}/applications/{application_id}/documents")


# --- M03 bước 4: xác nhận và đồng ý ------------------------------------------------------------


@router.get("/applications/{application_id}/confirm", response_model=None)
def confirm_page(
    request: Request, application_id: uuid.UUID, user: EditorPage, applications: Applications
) -> HTMLResponse | RedirectResponse:
    return _editable_or_detail(request, user, "confirm", applications.get(user, application_id))


@router.post("/applications/{application_id}/confirm", dependencies=[Csrf], response_model=None)
def submit_application(
    request: Request, application_id: uuid.UUID, user: CustomerPage, applications: Applications,
    ctx: Ctx, accept_data_processing: Annotated[bool, Form()] = False,
) -> HTMLResponse | RedirectResponse:
    def failed(code: int, **context: Any) -> HTMLResponse:
        view = applications.get(user, application_id)
        return wizard(request, user, "confirm", view, code, **context)

    # SR14: ô đồng ý không tích sẵn; máy chủ vẫn kiểm tra dù trình duyệt đã bắt buộc.
    if not accept_data_processing:
        return failed(status.HTTP_400_BAD_REQUEST, error=CONSENT_REQUIRED)
    if not ctx.limits.application_write.hit(str(user.user_id)):
        return failed(status.HTTP_429_TOO_MANY_REQUESTS, error=TOO_MANY)
    try:
        applications.submit(user, application_id)
    except IncompleteApplication as exc:
        return failed(
            status.HTTP_400_BAD_REQUEST,
            error="Hồ sơ vay chưa đủ thông tin hoặc giấy tờ. Còn thiếu:",
            field_errors=[ITEMS.get(item, item) for item in exc.missing],
        )
    return redirect(f"{PREFIX}/applications/{application_id}?notice=submitted")


# --- UC10: thông tin cá nhân -------------------------------------------------------------------

@router.get("/profile", response_class=HTMLResponse)
def profile_page(request: Request, user: ProfilePage, customers: Customers) -> HTMLResponse:
    return render(request, "profile.html", {"profile": customers.view_self(user)}, user=user)


@router.post("/profile", dependencies=[Csrf], response_model=None)
def update_profile(
    request: Request, user: ProfilePage, customers: Customers,
    occupation: Entry = "", employer: Entry = "", employment_years: Entry = "",
    monthly_income: Entry = "", housing_type: Entry = "", address: Entry = "",
) -> HTMLResponse | RedirectResponse:
    form = {
        "occupation": occupation, "employer": employer, "employment_years": employment_years,
        "monthly_income": monthly_income, "housing_type": housing_type, "address": address,
    }

    def failed(code: int, **context: Any) -> HTMLResponse:
        return render(request, "profile.html",
                      {"profile": customers.view_self(user), "form": form, **context},
                      user=user, status_code=code)

    body, field_errors = validate(UpdateProfileRequest, form, FIELD_ERRORS)
    if body is None:
        return failed(status.HTTP_400_BAD_REQUEST, field_errors=field_errors)
    try:
        customers.update_self(user, ProfileChanges(**body.model_dump(exclude_none=True)))
    except IncomeLocked as exc:
        return failed(status.HTTP_409_CONFLICT, error=message_of(exc))
    return redirect(f"{PREFIX}/profile?notice=profile_saved")

# --- Đổi số điện thoại, email (UC10): xác nhận bằng OTP gửi tới số điện thoại hiện tại ----------

CONTACT_FIELDS: dict[str, tuple[type[BaseModel], str, str]] = {
    "phone": (PhoneChangeRequest, "new_phone", "Số điện thoại gồm 10 chữ số, bắt đầu bằng 0."),
    "email": (EmailChangeRequest, "new_email", "Email không hợp lệ."),
}
OTP_ERRORS = {"otp": "Mã OTP gồm 6 chữ số.", "challenge_id": ERROR_MESSAGES[400]}


def _contact_otp_page(
    request: Request, user: CurrentUser, challenge_id: str,
    status_code: int = status.HTTP_200_OK, **context: Any,
) -> HTMLResponse:
    return render(request, "profile_otp.html", {"challenge_id": challenge_id, **context},
                  user=user, status_code=status_code)


@router.post("/profile/contact", dependencies=[Csrf], response_class=HTMLResponse)
def start_contact_change(
    request: Request, user: ProfilePage, customers: Customers,
    field: Entry = "", new_value: Entry = "",
) -> HTMLResponse:
    if field not in CONTACT_FIELDS:
        raise PageError(status.HTTP_400_BAD_REQUEST)
    model, key, message = CONTACT_FIELDS[field]

    def failed(code: int, **context: Any) -> HTMLResponse:
        return render(request, "profile.html",
                      {"profile": customers.view_self(user),
                       "contact": {field: new_value}, **context},
                      user=user, status_code=code)

    body, field_errors = validate(model, {key: new_value.strip()}, {key: message})
    if body is None:
        return failed(status.HTTP_400_BAD_REQUEST, contact_errors=field_errors)
    try:
        challenge_id = customers.start_contact_change(
            user, "phone" if field == "phone" else "email", str(getattr(body, key))
        )
    except ContactTaken as exc:
        return failed(status.HTTP_409_CONFLICT, contact_errors=[message_of(exc)])
    return _contact_otp_page(request, user, str(challenge_id))


@router.post("/profile/contact/confirm", dependencies=[Csrf], response_model=None)
def confirm_contact_change(
    request: Request, user: ProfilePage, customers: Customers, ctx: Ctx,
    challenge_id: Entry = "", otp: Entry = "",
) -> HTMLResponse | RedirectResponse:
    if not ctx.limits.otp.hit(str(user.user_id)):
        return _contact_otp_page(request, user, challenge_id,
                                 status.HTTP_429_TOO_MANY_REQUESTS, error=TOO_MANY)
    body, field_errors = validate(
        ConsentConfirmation, {"challenge_id": challenge_id, "otp": otp.strip()}, OTP_ERRORS
    )
    if body is None:
        return _contact_otp_page(request, user, challenge_id, status.HTTP_400_BAD_REQUEST,
                                 error=field_errors[0])
    try:
        customers.confirm_contact_change(user, body.challenge_id, body.otp)
    except (ChallengeFailed, ContactTaken) as exc:
        return _contact_otp_page(request, user, challenge_id, code_of(exc),
                                 error=message_of(exc))
    return redirect(f"{PREFIX}/profile?notice=contact_saved")
