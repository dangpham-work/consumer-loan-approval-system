"""Ánh xạ lỗi nghiệp vụ sang mã HTTP theo quy ước mục 4.2.4.

Thông điệp là câu tiếng Việt cố định, không chứa chi tiết kỹ thuật. Lỗi có thông điệp an toàn do
tầng nghiệp vụ soạn (ví dụ lý do file không hợp lệ) thì dùng chính thông điệp đó.
"""

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from loan_system.domain.applications import InvalidTransition
from loan_system.domain.documents import InvalidDocument
from loan_system.services.application_service import (
    ApplicationInProgress,
    ApplicationNotFound,
    ConcurrentModification,
    CustomerNotFound,
    IncompleteApplication,
    NationalIdConflict,
    NeedInfoExpired,
    NotEditable,
    NotRequested,
    TooManyDocuments,
)
from loan_system.services.counter_service import DuplicateCustomer
from loan_system.services.otp_challenge_service import ChallengeFailed
from loan_system.services.review_service import (
    AlreadyReceived,
    DocumentNotFound,
    DocumentsNotAccepted,
    NotReviewable,
    NotTheReceiver,
    SodViolation,
)

FIXED: dict[type[Exception], tuple[int, str]] = {
    ApplicationNotFound: (status.HTTP_404_NOT_FOUND, "Không tìm thấy hồ sơ vay"),
    DocumentNotFound: (status.HTTP_404_NOT_FOUND, "Không tìm thấy giấy tờ"),
    CustomerNotFound: (status.HTTP_404_NOT_FOUND, "Không tìm thấy khách hàng"),
    ApplicationInProgress: (
        status.HTTP_409_CONFLICT,
        "Khách hàng đang có một hồ sơ vay hoặc khoản vay chưa kết thúc",
    ),
    NotEditable: (status.HTTP_409_CONFLICT, "Hồ sơ vay không ở trạng thái cho phép thao tác này"),
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
}
# Thông điệp do tầng nghiệp vụ soạn, an toàn để hiển thị.
OWN_MESSAGE: dict[type[Exception], int] = {
    InvalidDocument: status.HTTP_400_BAD_REQUEST,
    ChallengeFailed: status.HTTP_400_BAD_REQUEST,
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
