"""Khoản vay, Kỳ trả nợ và lệnh giải ngân (UC25, UC26, biểu đồ trạng thái 3.4b, 3.4c)."""

from enum import StrEnum


class LoanStatus(StrEnum):
    ACTIVE = "ACTIVE"
    OVERDUE = "OVERDUE"
    BAD_DEBT = "BAD_DEBT"
    SETTLED = "SETTLED"


# Khoản vay chưa tất toán chặn Khách hàng lập Hồ sơ vay mới (BR02).
UNSETTLED = frozenset({LoanStatus.ACTIVE, LoanStatus.OVERDUE, LoanStatus.BAD_DEBT})


class InstallmentStatus(StrEnum):
    UPCOMING = "UPCOMING"
    DUE = "DUE"
    PARTIAL = "PARTIAL"
    PAID = "PAID"
    OVERDUE = "OVERDUE"
    CANCELLED = "CANCELLED"


# Kỳ còn phải trả: chưa trả đủ và chưa bị hủy (nhận thanh toán ở UC28, được quét ở UC29).
UNPAID_INSTALLMENT = frozenset(
    {InstallmentStatus.UPCOMING, InstallmentStatus.DUE, InstallmentStatus.PARTIAL,
     InstallmentStatus.OVERDUE}
)


class DisbursementStatus(StrEnum):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class PaymentChannel(StrEnum):
    """UC28: khách hàng thanh toán trực tuyến, hoặc NV tín dụng ghi nhận tại quầy."""

    ONLINE = "ONLINE"
    COUNTER = "COUNTER"
