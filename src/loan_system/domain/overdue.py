"""UC29 Quét và xử lý quá hạn: nhóm nợ (BR09) và phí phạt tính lại mỗi đêm (mục 1.2.8c).

Chỉ tính toán thuần; đọc/ghi CSDL nằm ở `services/nightly_job.py`.
"""

from decimal import Decimal
from enum import StrEnum

from loan_system.domain.calculations import calculate_penalty

BAD_DEBT_AFTER_DAYS = 90  # UC29 4a: quá hạn trên 90 ngày thì khoản vay là Nợ xấu

# BR09: (số ngày quá hạn tối thiểu, nhóm nợ), xét từ nhóm cao xuống. Quá hạn 1–9 ngày vẫn là
# nhóm 1 dù Kỳ trả nợ đã Quá hạn: nhóm nợ tách khỏi trạng thái (docs/de-cuong-thay-doi.md, Q4).
_DEBT_GROUP_BANDS = ((361, 5), (181, 4), (91, 3), (10, 2))


class ReminderKind(StrEnum):
    """Mốc nhắc nợ (UC30 bước 1): trước hạn 3 ngày, đúng ngày đến hạn, quá hạn 1/7/15/30 ngày."""

    BEFORE_DUE = "BEFORE_DUE"
    DUE = "DUE"
    OVERDUE_1 = "OVERDUE_1"
    OVERDUE_7 = "OVERDUE_7"
    OVERDUE_15 = "OVERDUE_15"
    OVERDUE_30 = "OVERDUE_30"


_OVERDUE_REMINDERS = (
    (30, ReminderKind.OVERDUE_30), (15, ReminderKind.OVERDUE_15), (7, ReminderKind.OVERDUE_7),
    (1, ReminderKind.OVERDUE_1),
)


def overdue_reminder(days_overdue: int) -> ReminderKind:
    """Mốc nhắc quá hạn gần nhất đã tới. Đêm nào bị lỡ thì lần chạy sau vẫn gửi mốc vừa qua
    (UC29 ngoại lệ); các mốc đã gửi được ghi lại nên mỗi mốc chỉ gửi một lần."""
    return next(kind for start, kind in _OVERDUE_REMINDERS if days_overdue >= start)


def debt_group(days_overdue: int) -> int:
    """Nhóm nợ theo số ngày quá hạn của Kỳ trả nợ quá hạn lâu nhất (BR09)."""
    return next((group for start, group in _DEBT_GROUP_BANDS if days_overdue >= start), 1)


def is_bad_debt(days_overdue: int) -> bool:
    return days_overdue > BAD_DEBT_AFTER_DAYS


def recalculated_penalty(
    *,
    interest_due: Decimal,
    principal_due: Decimal,
    penalty_paid: Decimal,
    paid_amount: Decimal,
    annual_rate: Decimal,
    days_overdue: int,
) -> Decimal:
    """Phí phạt của một kỳ, tính lại từ đầu trên phần gốc và lãi còn nợ (mục 1.2.8c).

    Tính lại chứ không cộng thêm mỗi đêm, nên tác vụ chạy hai lần trong một ngày cho cùng kết quả
    (UC29 ngoại lệ). Phần gốc và lãi đã trả được giảm khỏi cơ sở tính; phí phạt đã trả thì không
    bao giờ bị lấy lại, kể cả khi cơ sở tính giảm sau một lần trả một phần.
    """
    owed = interest_due + principal_due - (paid_amount - penalty_paid)
    return max(penalty_paid, calculate_penalty(owed, annual_rate, days_overdue))
