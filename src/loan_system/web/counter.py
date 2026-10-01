"""UC12 1a: NV tín dụng nộp hộ hồ sơ vay tại quầy (mở từ M05).

Tìm khách hàng đã có tài khoản theo CCCD, hoặc lập khách hàng vãng lai (khách đọc mã OTP gửi tới
điện thoại của họ để đồng ý). Sau đó NV đi qua đúng các bước 1–3 của M03 như khách hàng; ở bước 4 sự
đồng ý nộp hồ sơ vay của khách hàng được xác nhận bằng OTP thay cho ô đánh dấu.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from loan_system.api.applications import Applications, Counter, CreateApplicationRequest
from loan_system.api.counter import WalkInRequest
from loan_system.api.customers import Customers, LookupRequest
from loan_system.api.deps import Ctx
from loan_system.services.application_service import (
    ApplicationInProgress,
    CustomerNotFound,
    IncompleteApplication,
    LoanTerms,
)
from loan_system.services.auth_service import CurrentUser
from loan_system.services.counter_service import DuplicateCustomer, WalkInCustomer
from loan_system.services.otp_challenge_service import ChallengeFailed
from loan_system.web.customer import FIELD_ERRORS as APPLICATION_FIELD_ERRORS
from loan_system.web.customer import TOO_MANY, loan_step, wizard
from loan_system.web.labels import ITEMS
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

router = APIRouter(prefix=PREFIX, include_in_schema=False)

OfficerPage = Annotated[CurrentUser, Depends(require_page("APPLICATION_CREATE", "EMPLOYEE"))]
LookupPage = Annotated[CurrentUser, Depends(require_page("CUSTOMER_VIEW", "EMPLOYEE"))]

FIELD_ERRORS = {
    "full_name": "Họ tên từ 2 đến 100 ký tự.",
    "date_of_birth": "Ngày sinh không hợp lệ.",
    "phone": "Số điện thoại gồm 10 chữ số, bắt đầu bằng 0.",
    "email": "Email không hợp lệ.",
    "national_id": "Số CCCD gồm 12 chữ số.",
}
INVALID_OTP = "Mã OTP gồm 6 chữ số."


def _counter_page(
    request: Request, user: CurrentUser, status_code: int = status.HTTP_200_OK, **context: Any
) -> HTMLResponse:
    context.setdefault("walk_in", {"full_name": "", "date_of_birth": "", "phone": "", "email": ""})
    return render(request, "counter.html", context, user=user, status_code=status_code)


@router.get("/counter", response_class=HTMLResponse)
def counter_page(request: Request, user: OfficerPage) -> HTMLResponse:
    return _counter_page(request, user)


@router.post("/counter/lookup", dependencies=[Csrf], response_class=HTMLResponse)
def lookup(
    request: Request, user: LookupPage, customers: Customers, national_id: Entry = ""
) -> HTMLResponse:
    body, field_errors = validate(LookupRequest, {"national_id": national_id}, FIELD_ERRORS)
    if body is None:
        return _counter_page(request, user, status.HTTP_400_BAD_REQUEST,
                             lookup_errors=field_errors)
    try:
        found = customers.lookup(body.national_id)
    except CustomerNotFound as exc:
        return _counter_page(request, user, code_of(exc), lookup_errors=[message_of(exc)])
    return _counter_page(request, user, found=found)


# --- Khách hàng vãng lai -----------------------------------------------------------------------


def _otp_page(
    request: Request, user: CurrentUser, action: str, challenge_id: str,
    status_code: int = status.HTTP_200_OK, error: str | None = None,
) -> HTMLResponse:
    return render(
        request, "counter_otp.html",
        {"action": action, "challenge_id": challenge_id, "error": error},
        user=user, status_code=status_code,
    )


@router.post("/counter/walk-in", dependencies=[Csrf], response_class=HTMLResponse)
def start_walk_in(
    request: Request, user: OfficerPage, counter: Counter, ctx: Ctx,
    full_name: Entry = "", date_of_birth: Entry = "", phone: Entry = "", email: Entry = "",
) -> HTMLResponse:
    form = {"full_name": full_name, "date_of_birth": date_of_birth, "phone": phone,
            "email": email}
    body, field_errors = validate(WalkInRequest, form, FIELD_ERRORS)
    if body is None:
        return _counter_page(request, user, status.HTTP_400_BAD_REQUEST, walk_in=form,
                             walk_in_errors=field_errors)
    if not ctx.limits.application_write.hit(str(user.user_id)):
        return _counter_page(request, user, status.HTTP_429_TOO_MANY_REQUESTS, walk_in=form,
                             walk_in_errors=[TOO_MANY])
    try:
        challenge_id = counter.start_walk_in(
            user, WalkInCustomer(body.full_name, body.date_of_birth, body.phone, str(body.email))
        )
    except DuplicateCustomer as exc:
        return _counter_page(request, user, code_of(exc), walk_in=form,
                             walk_in_errors=[message_of(exc)])
    return _otp_page(request, user, f"{PREFIX}/counter/walk-in/confirm", str(challenge_id))


@router.post("/counter/walk-in/confirm", dependencies=[Csrf], response_model=None)
def confirm_walk_in(
    request: Request, user: OfficerPage, counter: Counter, ctx: Ctx,
    challenge_id: Annotated[uuid.UUID, Form()], otp: Entry = "",
) -> HTMLResponse | RedirectResponse:
    action = f"{PREFIX}/counter/walk-in/confirm"
    if not (len(otp) == 6 and otp.isdigit()):
        return _otp_page(request, user, action, str(challenge_id),
                         status.HTTP_400_BAD_REQUEST, INVALID_OTP)
    if not ctx.limits.otp.hit(str(user.user_id)):
        return _otp_page(request, user, action, str(challenge_id),
                         status.HTTP_429_TOO_MANY_REQUESTS, TOO_MANY)
    try:
        customer_id = counter.confirm_walk_in(user, challenge_id, otp)
    except ChallengeFailed as exc:
        return _otp_page(request, user, action, str(challenge_id), code_of(exc),
                         message_of(exc))
    except DuplicateCustomer as exc:
        return _counter_page(request, user, code_of(exc), walk_in_errors=[message_of(exc)])
    return redirect(f"{PREFIX}/counter/customers/{customer_id}/applications/new")


# --- M03 bước 1 cho khách hàng đã chọn ---------------------------------------------------------


def _new_path(customer_id: uuid.UUID) -> str:
    return f"{PREFIX}/counter/customers/{customer_id}/applications/new"


@router.get("/counter/customers/{customer_id}/applications/new", response_class=HTMLResponse)
def new_counter_application(
    request: Request, customer_id: uuid.UUID, user: OfficerPage
) -> HTMLResponse:
    empty = {"requested_amount": "", "term_months": "", "purpose": ""}
    return loan_step(request, user, None, empty, form_action=_new_path(customer_id))


@router.post(
    "/counter/customers/{customer_id}/applications/new", dependencies=[Csrf], response_model=None
)
def create_counter_application(
    request: Request, customer_id: uuid.UUID, user: OfficerPage, applications: Applications,
    requested_amount: Entry = "", term_months: Entry = "", purpose: Entry = "",
) -> HTMLResponse | RedirectResponse:
    form = {"requested_amount": requested_amount, "term_months": term_months, "purpose": purpose}
    body, field_errors = validate(CreateApplicationRequest, form, APPLICATION_FIELD_ERRORS)
    if body is None:
        return loan_step(request, user, None, form, status.HTTP_400_BAD_REQUEST,
                         field_errors=field_errors, form_action=_new_path(customer_id))
    try:
        view = applications.create_for(
            user, customer_id, LoanTerms(body.requested_amount, body.term_months, body.purpose)
        )
    except (ApplicationInProgress, CustomerNotFound) as exc:
        return loan_step(request, user, None, form, code_of(exc), error=message_of(exc),
                         form_action=_new_path(customer_id))
    return redirect(f"{PREFIX}/applications/{view.id}/finance")


# --- M03 bước 4: khách hàng đồng ý bằng OTP ----------------------------------------------------


@router.post("/applications/{application_id}/consent", dependencies=[Csrf], response_model=None)
def start_consent(
    request: Request, application_id: uuid.UUID, user: OfficerPage, counter: Counter,
    applications: Applications, ctx: Ctx,
) -> HTMLResponse:
    def step(code: int = status.HTTP_200_OK, **context: Any) -> HTMLResponse:
        view = applications.get(user, application_id)
        return wizard(request, user, "confirm", view, code, **context)

    if not ctx.limits.application_write.hit(str(user.user_id)):
        return step(status.HTTP_429_TOO_MANY_REQUESTS, error=TOO_MANY)
    try:
        challenge_id = counter.start_submission(user, application_id)
    except IncompleteApplication as exc:
        return step(
            status.HTTP_400_BAD_REQUEST,
            error="Hồ sơ vay chưa đủ thông tin hoặc giấy tờ. Còn thiếu:",
            field_errors=[ITEMS.get(item, item) for item in exc.missing],
        )
    return step(challenge_id=str(challenge_id))


@router.post(
    "/applications/{application_id}/consent/confirm", dependencies=[Csrf], response_model=None
)
def confirm_consent(
    request: Request, application_id: uuid.UUID, user: OfficerPage, counter: Counter,
    applications: Applications, ctx: Ctx,
    challenge_id: Annotated[uuid.UUID, Form()], otp: Entry = "",
) -> HTMLResponse | RedirectResponse:
    def failed(code: int, error: str) -> HTMLResponse:
        view = applications.get(user, application_id)
        return wizard(request, user, "confirm", view, code, error=error,
                      challenge_id=str(challenge_id))

    if not (len(otp) == 6 and otp.isdigit()):
        return failed(status.HTTP_400_BAD_REQUEST, INVALID_OTP)
    if not ctx.limits.otp.hit(str(user.user_id)):
        return failed(status.HTTP_429_TOO_MANY_REQUESTS, TOO_MANY)
    try:
        counter.confirm_submission(user, application_id, challenge_id, otp)
    except ChallengeFailed as exc:
        return failed(code_of(exc), message_of(exc))
    except IncompleteApplication:
        return failed(status.HTTP_400_BAD_REQUEST,
                      "Hồ sơ vay chưa đủ thông tin hoặc giấy tờ. Vui lòng kiểm tra lại.")
    return redirect(f"{PREFIX}/queue/{application_id}?notice=submitted")
