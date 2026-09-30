"""Màn hình M04 Lịch trả nợ và thanh toán: khách hàng mở từ trang chủ, Nhân viên tín dụng mở từ chi
tiết hồ sơ vay đã giải ngân (M06).

UC27 Xem lịch trả nợ (bảng kỳ, dư nợ, tải PDF), UC28 Thanh toán kỳ, UC31 Tất toán trước hạn. Cùng tầng
nghiệp vụ và cùng thông điệp với `api/payments.py`. Khoản vay của người khác được báo như không tồn
tại (SR04, trang lỗi 404).

Khách hàng thanh toán trực tuyến: mỗi lượt thanh toán có một `idempotency_key` sinh sẵn trong biểu
mẫu, gửi lại (bấm hai lần, tải lại trang sau khi gửi) thì chỉ bị thu một lần (UC28 3b). Cổng thanh toán
từ chối thì lượt đó đã kết thúc, trang cấp khóa mới cho lượt sau; các lỗi khác (cổng không phản hồi,
nhập sai) giữ nguyên khóa vì tiền có thể đã được thu. Nhân viên tín dụng ghi nhận tiền mặt tại quầy
kèm mã phiếu thu.
"""

import secrets
import uuid
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from loan_system.api.payments import Payments, PayRequest, SettleRequest
from loan_system.domain.loans import LoanStatus
from loan_system.services.auth_service import CurrentUser
from loan_system.services.payment_service import (
    AmountExceedsDue,
    AmountExceedsPayoff,
    ChargeFailed,
    ChargeUnavailable,
    LoanNotPayable,
    PaymentService,
    QuoteExpired,
    ReceiptRequired,
    ReferenceReused,
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

router = APIRouter(prefix=PREFIX, include_in_schema=False)

PayerPage = Annotated[CurrentUser, Depends(require_page("PAYMENT_RECORD"))]
CustomerPayerPage = Annotated[CurrentUser, Depends(require_page("PAYMENT_RECORD", "CUSTOMER"))]
SettlerPage = Annotated[CurrentUser, Depends(require_page("LOAN_SETTLE"))]

STALE = "Trang đã cũ. Vui lòng tải lại trang rồi thử lại."
FIELD_ERRORS = {
    "amount": "Số tiền thanh toán phải là số nguyên đồng lớn hơn 0.",
    "receipt_no": "Mã phiếu thu tối đa 50 ký tự.",
    "idempotency_key": STALE,
    "quoted_on": STALE,
}
_PAYABLE = (LoanStatus.ACTIVE, LoanStatus.OVERDUE)
_KEY_LENGTH = (16, 64)  # như `PayRequest.idempotency_key`
# Lỗi nghiệp vụ hiện lại M04 cùng thông điệp; lỗi khác (không tìm thấy khoản vay) ra trang lỗi.
_PAYMENT_ERRORS = (
    AmountExceedsDue, AmountExceedsPayoff, ChargeFailed, ChargeUnavailable, LoanNotPayable,
    QuoteExpired, ReceiptRequired, ReferenceReused,
)


def _new_key() -> str:
    return secrets.token_hex(16)


def _loan_path(loan_id: uuid.UUID) -> str:
    return f"{PREFIX}/loans/{loan_id}"


def loan_page(
    request: Request, user: CurrentUser, payments: PaymentService, loan_id: uuid.UUID,
    status_code: int = status.HTTP_200_OK, **context: Any,
) -> HTMLResponse:
    schedule = payments.schedule(user, loan_id)
    payable = schedule.status in _PAYABLE
    quote = None
    if payable and "LOAN_SETTLE" in user.permissions:
        try:
            quote = payments.payoff_quote(user, loan_id)
        except LoanNotPayable:
            pass
    online = user.customer_id is not None
    return render(
        request, "loan.html",
        {
            "loan": schedule,
            "quote": quote,
            "can_pay": payable,
            "online": online,
            "pay_key": context.pop("pay_key", None) or (_new_key() if online else None),
            "settle_key": context.pop("settle_key", None) or (_new_key() if online else None),
            "form": context.pop("form", {}),
            **context,
        },
        user=user, status_code=status_code,
    )


@router.get("/loans", response_class=HTMLResponse)
def loans(request: Request, user: CustomerPayerPage, payments: Payments) -> HTMLResponse:
    return render(request, "loans.html", {"loans": payments.own_loans(user)}, user=user)


@router.get("/loans/{loan_id}", response_class=HTMLResponse)
def loan(
    request: Request, loan_id: uuid.UUID, user: PayerPage, payments: Payments
) -> HTMLResponse:
    return loan_page(request, user, payments, loan_id)


@router.get("/loans/{loan_id}/schedule.pdf")
def schedule_pdf(loan_id: uuid.UUID, user: PayerPage, payments: Payments) -> Response:
    return Response(
        content=payments.schedule_pdf(user, loan_id), media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=lich_tra_no_{loan_id}.pdf",
            "Cache-Control": "no-store",
        },
    )


@router.get("/queue/{application_id}/loan")
def loan_of_application(
    application_id: uuid.UUID, user: PayerPage, payments: Payments
) -> RedirectResponse:
    return redirect(_loan_path(payments.loan_of_application(user, application_id)))


def _submit[M: PayRequest](
    request: Request, user: CurrentUser, payments: PaymentService, loan_id: uuid.UUID,
    model: type[M], form: dict[str, str], key_field: str, notice: str,
    call: Callable[[M], None],
) -> HTMLResponse | RedirectResponse:
    """Kiểm tra biểu mẫu bằng schema của REST API rồi thanh toán; lỗi thì hiện lại M04.

    `key_field` là tên khóa của biểu mẫu đang gửi trong context (`pay_key` hoặc `settle_key`).
    """
    # Khóa sai định dạng (trang bị sửa) thì cấp khóa mới, để lần gửi sau không lỗi mãi.
    sent = form.get("idempotency_key", "")
    key = sent if _KEY_LENGTH[0] <= len(sent) <= _KEY_LENGTH[1] else None
    # Biểu mẫu tất toán không giữ số tiền đã gửi: M04 luôn hiện báo giá mới nhất.
    shown = form if key_field == "pay_key" else {}
    body, field_errors = validate(model, form, FIELD_ERRORS)
    if body is None:
        return loan_page(request, user, payments, loan_id, status.HTTP_400_BAD_REQUEST,
                         field_errors=field_errors, form=shown, **{key_field: key})
    try:
        call(body)
    except _PAYMENT_ERRORS as exc:
        if (isinstance(exc, LoanNotPayable)
                and payments.schedule(user, loan_id).status == LoanStatus.SETTLED):
            # Bấm hai lần khi tất toán (hoặc trả hết): yêu cầu thứ hai chỉ thấy khoản vay đã tất
            # toán; trình duyệt hiện phản hồi này nên báo kết quả thật thay vì báo lỗi.
            return redirect(f"{_loan_path(loan_id)}?notice=settled")
        if isinstance(exc, (ChargeFailed, QuoteExpired)):
            # Lượt thanh toán đã kết thúc mà không thu tiền: lượt sau cần khóa mới (cổng thanh toán
            # nhớ kết quả theo khóa, gửi lại cùng khóa sẽ bị từ chối mãi).
            key = None
        return loan_page(request, user, payments, loan_id, code_of(exc),
                         error=message_of(exc), form=shown, **{key_field: key})
    return redirect(f"{_loan_path(loan_id)}?notice={notice}")


@router.post("/loans/{loan_id}/payments", dependencies=[Csrf], response_model=None)
def pay(
    request: Request, loan_id: uuid.UUID, user: PayerPage, payments: Payments,
    amount: Entry = "", receipt_no: Entry = "", idempotency_key: Entry = "",
) -> HTMLResponse | RedirectResponse:
    form = {"amount": amount, "receipt_no": receipt_no, "idempotency_key": idempotency_key}

    def call(body: PayRequest) -> None:
        payments.pay(user, loan_id, body.amount, receipt_no=body.receipt_no,
                     idempotency_key=body.idempotency_key)

    return _submit(request, user, payments, loan_id, PayRequest, form, "pay_key", "paid", call)


@router.post("/loans/{loan_id}/settlement", dependencies=[Csrf], response_model=None)
def settle(
    request: Request, loan_id: uuid.UUID, user: SettlerPage, payments: Payments,
    amount: Entry = "", quoted_on: Entry = "", receipt_no: Entry = "",
    idempotency_key: Entry = "",
) -> HTMLResponse | RedirectResponse:
    form = {"amount": amount, "quoted_on": quoted_on, "receipt_no": receipt_no,
            "idempotency_key": idempotency_key}

    def call(body: SettleRequest) -> None:
        payments.settle(user, loan_id, body.amount, body.quoted_on, receipt_no=body.receipt_no,
                        idempotency_key=body.idempotency_key)

    return _submit(request, user, payments, loan_id, SettleRequest, form, "settle_key",
                   "settled", call)
