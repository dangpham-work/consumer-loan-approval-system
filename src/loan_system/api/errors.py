"""Ánh xạ lỗi nghiệp vụ sang mã HTTP theo quy ước mục 4.2.4.

Thông điệp là câu tiếng Việt cố định, không chứa chi tiết kỹ thuật. Lỗi có thông điệp an toàn do
tầng nghiệp vụ soạn (ví dụ lý do file không hợp lệ) thì dùng chính thông điệp đó.
"""

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from loan_system.domain.applications import InvalidTransition
from loan_system.domain.appraisal import InvalidProposal, NoApprovalTier
from loan_system.domain.documents import InvalidDocument
from loan_system.domain.report import DateRangeTooLong, InvalidDateRange
from loan_system.services.application_service import (
    ApplicationInProgress,
    ApplicationNotFound,
    ConcurrentModification,
    CustomerNotFound,
    IncompleteApplication,
    NationalIdConflict,
    NeedInfoExpired,
    NotEditable,
    NotLocked,
    NotRequested,
    TooManyDocuments,
)
from loan_system.services.appraisal_service import (
    AlreadyAppraised,
    DocumentNotViewable,
    DtiTooHigh,
    NotAppraisable,
    NotTheAppraiser,
)
from loan_system.services.approval_service import (
    NotAppraised,
    NotAwaitingApproval,
    ReportNotApprovable,
)
from loan_system.services.audit_query_service import ExportTooLarge
from loan_system.services.auth_service import InvalidOtp
from loan_system.services.disbursement_service import (
    IntegrityFailure,
    NoFailedDisbursement,
    NotApproved,
    PaymentPending,
    PreviouslyFailed,
    TransferRejected,
)
from loan_system.services.integrity_service import IntegrityKeyMissing
from loan_system.services.counter_service import DuplicateCustomer
from loan_system.services.customer_service import ContactTaken, IncomeLocked
from loan_system.services.otp_challenge_service import ChallengeFailed
from loan_system.services.payment_service import (
    AmountExceedsDue,
    AmountExceedsPayoff,
    ChargeFailed,
    ChargeUnavailable,
    LoanNotFound,
    LoanNotPayable,
    QuoteExpired,
    ReceiptRequired,
    ReferenceReused,
)
from loan_system.services.scoring_service import ScoreNotFound
from loan_system.services.review_service import (
    AlreadyReceived,
    DocumentNotFound,
    DocumentsNotAccepted,
    NotReviewable,
    NotTheReceiver,
)
from loan_system.services.segregation import SodViolation

FIXED: dict[type[Exception], tuple[int, str]] = {
    ApplicationNotFound: (status.HTTP_404_NOT_FOUND, "Không tìm thấy hồ sơ vay"),
    DocumentNotFound: (status.HTTP_404_NOT_FOUND, "Không tìm thấy giấy tờ"),
    CustomerNotFound: (status.HTTP_404_NOT_FOUND, "Không tìm thấy khách hàng"),
    ScoreNotFound: (status.HTTP_404_NOT_FOUND, "Hồ sơ vay chưa được chấm điểm"),
    ApplicationInProgress: (
        status.HTTP_409_CONFLICT,
        "Khách hàng đang có một hồ sơ vay hoặc khoản vay chưa kết thúc",
    ),
    NotEditable: (status.HTTP_409_CONFLICT, "Hồ sơ vay không ở trạng thái cho phép thao tác này"),
    NotLocked: (status.HTTP_409_CONFLICT, "Hồ sơ vay không ở trạng thái Bị khóa"),
    InvalidTransition: (
        status.HTTP_409_CONFLICT, "Hồ sơ vay không ở trạng thái cho phép thao tác này"
    ),
    NeedInfoExpired: (status.HTTP_409_CONFLICT, "Đã quá hạn bổ sung hồ sơ vay"),
    NotRequested: (
        status.HTTP_409_CONFLICT, "Chỉ được bổ sung những mục nhân viên tín dụng đã yêu cầu"
    ),
    ConcurrentModification: (
        status.HTTP_409_CONFLICT, "Hồ sơ vay vừa được cập nhật, vui lòng tải lại"
    ),
    TooManyDocuments: (status.HTTP_409_CONFLICT, "Hồ sơ vay đã có quá nhiều file"),
    # Không nói CCCD đang thuộc về ai (giống thông điệp trùng khi đăng ký, UC09 2b).
    NationalIdConflict: (
        status.HTTP_409_CONFLICT,
        "Không thể dùng số CCCD này. Vui lòng liên hệ nhân viên tín dụng.",
    ),
    DuplicateCustomer: (
        status.HTTP_409_CONFLICT, "Số điện thoại hoặc email đã thuộc về một khách hàng"
    ),
    NotReviewable: (status.HTTP_409_CONFLICT, "Hồ sơ vay không ở trạng thái Đã nộp"),
    AlreadyReceived: (status.HTTP_409_CONFLICT, "Hồ sơ vay đã được nhân viên khác tiếp nhận"),
    DocumentsNotAccepted: (
        status.HTTP_409_CONFLICT, "Còn giấy tờ thiếu, chưa kiểm tra hoặc không đạt"
    ),
    NotTheReceiver: (status.HTTP_403_FORBIDDEN, "Chỉ người tiếp nhận mới thực hiện được"),
    SodViolation: (
        status.HTTP_403_FORBIDDEN, "Thao tác vi phạm nguyên tắc phân tách nhiệm vụ"
    ),
    NotAppraisable: (status.HTTP_409_CONFLICT, "Hồ sơ vay không ở trạng thái Đang thẩm định"),
    AlreadyAppraised: (
        status.HTTP_409_CONFLICT, "Hồ sơ vay đã được chuyên viên khác thẩm định"
    ),
    NotTheAppraiser: (status.HTTP_403_FORBIDDEN, "Chỉ người thẩm định mới thực hiện được"),
    DtiTooHigh: (
        status.HTTP_400_BAD_REQUEST,
        "DTI với hạn mức, kỳ hạn đề xuất vượt 50%. Vui lòng giảm hạn mức hoặc tăng kỳ hạn.",
    ),
    DocumentNotViewable: (status.HTTP_409_CONFLICT, "Không hiển thị được giấy tờ này"),
    NoApprovalTier: (
        status.HTTP_409_CONFLICT,
        "Chính sách phê duyệt không áp dụng được cho hạn mức này. Vui lòng báo quản trị viên.",
    ),
    NotAwaitingApproval: (status.HTTP_409_CONFLICT, "Hồ sơ vay không ở trạng thái Chờ phê duyệt"),
    NotAppraised: (status.HTTP_409_CONFLICT, "Hồ sơ vay chưa có tờ trình thẩm định"),
    ReportNotApprovable: (
        status.HTTP_409_CONFLICT,
        "Tờ trình đề xuất từ chối nên không thể phê duyệt. Vui lòng từ chối hoặc trả về.",
    ),
    NotApproved: (status.HTTP_409_CONFLICT, "Hồ sơ vay không ở trạng thái Đã phê duyệt"),
    IntegrityFailure: (
        status.HTTP_409_CONFLICT,
        "Phát hiện thay đổi trên hồ sơ vay sau khi phê duyệt. Hồ sơ vay đã bị khóa.",
    ),
    IntegrityKeyMissing: (
        status.HTTP_409_CONFLICT,
        "Không kiểm tra được toàn vẹn hồ sơ vay. Vui lòng báo quản trị viên.",
    ),
    PreviouslyFailed: (
        status.HTTP_409_CONFLICT,
        "Lệnh giải ngân trước đã bị cổng thanh toán từ chối. Cần hủy hồ sơ vay để lập lại.",
    ),
    NoFailedDisbursement: (
        status.HTTP_409_CONFLICT,
        "Hồ sơ vay chưa có lệnh giải ngân bị từ chối. Không cần hủy để lập lại.",
    ),
    # Xác thực lại trước thao tác nhạy cảm (SR02): sai mã thì từ chối như thiếu quyền.
    InvalidOtp: (status.HTTP_403_FORBIDDEN, "Mã OTP không đúng"),
    TransferRejected: (
        status.HTTP_409_CONFLICT,
        "Cổng thanh toán từ chối lệnh giải ngân. Vui lòng kiểm tra tài khoản nhận với khách hàng.",
    ),
    PaymentPending: (
        status.HTTP_409_CONFLICT,
        "Cổng thanh toán tạm thời không phản hồi. Lệnh giải ngân đang chờ, vui lòng thử lại.",
    ),
    ExportTooLarge: (
        status.HTTP_409_CONFLICT,
        "Kết quả lọc có quá nhiều dòng để xuất CSV. Vui lòng thu hẹp bộ lọc.",
    ),
    IncomeLocked: (
        status.HTTP_409_CONFLICT,
        "Không thể đổi thu nhập khi đang có hồ sơ vay hoặc khoản vay chưa kết thúc",
    ),
    ContactTaken: (
        status.HTTP_409_CONFLICT, "Số điện thoại hoặc email này đã thuộc về một khách hàng khác"
    ),
    LoanNotFound: (status.HTTP_404_NOT_FOUND, "Không tìm thấy khoản vay"),
    LoanNotPayable: (
        status.HTTP_409_CONFLICT, "Khoản vay không ở trạng thái cho phép thanh toán"
    ),
    ReceiptRequired: (status.HTTP_400_BAD_REQUEST, "Cần nhập mã phiếu thu"),
    ReferenceReused: (
        status.HTTP_409_CONFLICT, "Mã phiếu thu đã được dùng cho một khoản thanh toán khác"
    ),
    AmountExceedsDue: (
        status.HTTP_400_BAD_REQUEST, "Số tiền vượt quá tổng số tiền còn phải trả"
    ),
    AmountExceedsPayoff: (status.HTTP_400_BAD_REQUEST, "Số tiền vượt quá số tiền tất toán"),
    QuoteExpired: (
        status.HTTP_409_CONFLICT,
        "Báo giá tất toán chỉ có hiệu lực trong ngày. Vui lòng xem lại số tiền tất toán.",
    ),
    ChargeFailed: (
        status.HTTP_409_CONFLICT, "Cổng thanh toán từ chối giao dịch. Vui lòng thử lại."
    ),
    ChargeUnavailable: (
        status.HTTP_409_CONFLICT, "Cổng thanh toán tạm thời không phản hồi. Vui lòng thử lại."
    ),
    InvalidDateRange: (
        status.HTTP_400_BAD_REQUEST, "Khoảng thời gian không hợp lệ: ngày kết thúc phải sau ngày bắt đầu."
    ),
    DateRangeTooLong: (
        status.HTTP_400_BAD_REQUEST,
        "Khoảng thời gian quá dài (tối đa 12 tháng). Vui lòng thu hẹp khoảng thời gian.",
    ),
}
# Thông điệp do tầng nghiệp vụ soạn, an toàn để hiển thị.
OWN_MESSAGE: dict[type[Exception], int] = {
    InvalidDocument: status.HTTP_400_BAD_REQUEST,
    ChallengeFailed: status.HTTP_400_BAD_REQUEST,
    InvalidProposal: status.HTTP_400_BAD_REQUEST,
}


def register(app: FastAPI) -> None:
    for exc_type, (code, message) in FIXED.items():
        app.add_exception_handler(exc_type, _fixed(code, message))
    for exc_type, code in OWN_MESSAGE.items():
        app.add_exception_handler(exc_type, _own_message(code))
    app.add_exception_handler(IncompleteApplication, _incomplete)


Handler = Callable[[Request, Exception], Awaitable[JSONResponse]]


def _fixed(code: int, message: str) -> Handler:
    async def handle(_: Request, __: Exception) -> JSONResponse:
        return JSONResponse(status_code=code, content={"detail": message})

    return handle


def _own_message(code: int) -> Handler:
    async def handle(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=code, content={"detail": str(exc)})

    return handle


async def _incomplete(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, IncompleteApplication)
    # Cùng định dạng với lỗi kiểm tra dữ liệu: chỉ ra trường hoặc giấy tờ nào còn thiếu.
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "detail": "Hồ sơ vay chưa đủ thông tin hoặc giấy tờ",
            "errors": [{"field": item, "message": "Còn thiếu"} for item in exc.missing],
        },
    )
