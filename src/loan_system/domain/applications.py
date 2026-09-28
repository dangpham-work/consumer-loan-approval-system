"""Quy tắc của Hồ sơ vay ở bước lập và nộp (UC12, BR02, biểu đồ trạng thái 3.4a)."""

from collections.abc import Iterable
from decimal import Decimal
from enum import StrEnum


class ApplicationStatus(StrEnum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    NEED_INFO = "NEED_INFO"
    VERIFIED = "VERIFIED"
    APPRAISING = "APPRAISING"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    DISBURSED = "DISBURSED"
    LOCKED = "LOCKED"


# Hồ sơ vay đang xử lý (BR02, CONTEXT.md): mọi trạng thái chưa kết thúc, kể cả nháp và bị khóa.
# Khoản vay chưa tất toán cũng chặn tạo mới; kiểm tra đó thêm vào khi có bảng loans.
IN_PROGRESS = frozenset(
    {
        ApplicationStatus.DRAFT,
        ApplicationStatus.SUBMITTED,
        ApplicationStatus.NEED_INFO,
        ApplicationStatus.VERIFIED,
        ApplicationStatus.APPRAISING,
        ApplicationStatus.PENDING_APPROVAL,
        ApplicationStatus.APPROVED,
        ApplicationStatus.LOCKED,
    }
)

S = ApplicationStatus
# Bảng chuyển trạng thái (3.4a, cùng các bổ sung trong docs/de-cuong-thay-doi.md). Mọi chuyển
# trạng thái không có ở đây đều bị từ chối: đây là một cơ chế bảo mật (MUC02).
TRANSITIONS: dict[ApplicationStatus, frozenset[ApplicationStatus]] = {
    S.DRAFT: frozenset({S.SUBMITTED, S.CANCELLED}),
    S.SUBMITTED: frozenset({S.VERIFIED, S.NEED_INFO, S.CANCELLED}),
    S.NEED_INFO: frozenset({S.SUBMITTED, S.CANCELLED}),
    S.VERIFIED: frozenset({S.APPRAISING, S.REJECTED}),
    S.APPRAISING: frozenset({S.PENDING_APPROVAL, S.NEED_INFO}),
    S.PENDING_APPROVAL: frozenset({S.APPROVED, S.REJECTED, S.APPRAISING}),
    S.APPROVED: frozenset({S.DISBURSED, S.LOCKED, S.CANCELLED}),
    S.LOCKED: frozenset({S.CANCELLED}),
}
del S

# Khách hàng chỉ tự hủy được Hồ sơ vay chưa tới bước thẩm định (UC17 1b).
CUSTOMER_CANCELLABLE = frozenset(
    {ApplicationStatus.DRAFT, ApplicationStatus.SUBMITTED, ApplicationStatus.NEED_INFO}
)
# Người lập Hồ sơ vay còn sửa được: bản nháp, hoặc khi được yêu cầu bổ sung (UC13, UC15).
EDITABLE = frozenset({ApplicationStatus.DRAFT, ApplicationStatus.NEED_INFO})

NEED_INFO_DAYS = 15  # BR11


class InvalidTransition(Exception):
    def __init__(self, source: str, target: str) -> None:
        super().__init__(f"{source} -> {target}")
        self.source = source
        self.target = target


def ensure_transition(source: str, target: str) -> None:
    if ApplicationStatus(target) not in TRANSITIONS.get(ApplicationStatus(source), frozenset()):
        raise InvalidTransition(source, target)


MIN_AMOUNT = Decimal(5_000_000)  # BR02
MAX_AMOUNT = Decimal(100_000_000)
MIN_TERM_MONTHS = 6
MAX_TERM_MONTHS = 36


class Purpose(StrEnum):
    CONSUMER_GOODS = "CONSUMER_GOODS"
    EDUCATION = "EDUCATION"
    HEALTHCARE = "HEALTHCARE"
    HOME_IMPROVEMENT = "HOME_IMPROVEMENT"
    TRAVEL = "TRAVEL"
    VEHICLE = "VEHICLE"
    OTHER = "OTHER"


class DocumentType(StrEnum):  # M03 bước 3
    ID_FRONT = "ID_FRONT"
    ID_BACK = "ID_BACK"
    INCOME_PROOF = "INCOME_PROOF"
    UTILITY_BILL = "UTILITY_BILL"


DOCUMENT_TYPES = tuple(DocumentType)

# Lãi suất trần (CONTEXT.md): lãi suất của hạng C, dùng khi Hồ sơ vay chưa có Hạng, ví dụ số tiền
# trả hằng tháng ước tính ở M03 bước 1 (ADR 0001).
CEILING_RATE = Decimal("0.28")

# Tổng số file (kể cả file đã bị thay thế) của một Hồ sơ vay, chặn việc tải lên vô hạn.
MAX_DOCUMENTS_PER_APPLICATION = 20

# Thông tin bắt buộc khi nộp (M03 bước 2); nơi làm việc không bắt buộc.
REQUIRED_FIELDS = (
    "national_id",
    "occupation",
    "employment_years",
    "monthly_income",
    "existing_monthly_debt",
    "housing_type",
    "address",
    "receiving_account",
)


class DocumentVerdict(StrEnum):  # UC14 bước 4
    PASS = "PASS"
    FAIL = "FAIL"


# Những mục NV tín dụng được yêu cầu bổ sung (UC15 bước 2). Số tiền, kỳ hạn, mục đích không nằm
# trong đó: khách hàng muốn đổi khoản vay thì hủy và lập hồ sơ vay mới.
INFO_ITEMS = (*REQUIRED_FIELDS, "employer", *DOCUMENT_TYPES)


def outside_request(changed: set[str], requested: set[str]) -> set[str]:
    """Các mục bị sửa nhưng không nằm trong yêu cầu bổ sung (UC15: chỉ bổ sung đúng mục thiếu)."""
    return changed - requested


def missing_for_submission(filled_fields: Iterable[str], documents: Iterable[str]) -> list[str]:
    """Danh sách trường và loại giấy tờ còn thiếu, theo thứ tự trên biểu mẫu."""
    filled, uploaded = set(filled_fields), set(documents)
    return [f for f in REQUIRED_FIELDS if f not in filled] + [
        d for d in DOCUMENT_TYPES if d not in uploaded
    ]


def application_code(year: int, sequence: int) -> str:
    """Mã hồ sơ vay dạng HS2026000123 (4.1.2d)."""
    return f"HS{year}{sequence:06d}"


def mask(value: str, keep_start: int = 3, keep_end: int = 3) -> str:
    """Che dữ liệu nhạy cảm theo mẫu SR07 (079*****123); chuỗi quá ngắn thì che toàn bộ."""
    if len(value) <= keep_start + keep_end:
        return "*" * len(value)
    return value[:keep_start] + "*" * (len(value) - keep_start - keep_end) + value[-keep_end:]
