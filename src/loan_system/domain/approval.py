"""Quyết định phê duyệt (UC23, UC24), quy tắc gộp (AD04) và snapshot hồ sơ vay khi được duyệt (SR08).

Các Quyết định phê duyệt được tính trên một tờ trình thẩm định: bị Trả về thì chuyên viên lập tờ
trình mới, nên các quyết định trước đó tự hết hiệu lực mà không phải sửa bản ghi nào (bảng
approval_decisions chỉ ghi thêm, 4.1.2e).
"""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class Decision(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    RETURN = "RETURN"


class RejectionReason(StrEnum):
    """Nhóm lý do từ chối (UC24 bước 2); khách hàng chỉ được báo nhóm lý do, không kèm mô tả."""

    FINANCIAL_CAPACITY = "FINANCIAL_CAPACITY"
    CREDIT_HISTORY = "CREDIT_HISTORY"
    FRAUD_SUSPECTED = "FRAUD_SUSPECTED"
    OTHER = "OTHER"

    @property
    def label(self) -> str:
        return _REASON_LABELS[self]


_REASON_LABELS = {
    RejectionReason.FINANCIAL_CAPACITY: "năng lực tài chính",
    RejectionReason.CREDIT_HISTORY: "lịch sử tín dụng",
    RejectionReason.FRAUD_SUSPECTED: "nghi ngờ gian lận",
    RejectionReason.OTHER: "lý do khác",
}

MIN_REASON_LENGTH = 10  # UC24 2a: Từ chối, Trả về phải có mô tả


class Outcome(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    RETURNED = "RETURNED"


def outcome_of(decisions: Iterable[Decision], required_approvals: int) -> Outcome:
    """Quy tắc gộp (AD04): một Từ chối là từ chối, một Trả về đưa hồ sơ vay về thẩm định, đủ số
    lượt Phê duyệt theo chính sách đã chốt thì duyệt; thứ tự các quyết định không quan trọng."""
    made = list(decisions)
    if Decision.REJECT in made:
        return Outcome.REJECTED
    if Decision.RETURN in made:
        return Outcome.RETURNED
    if made.count(Decision.APPROVE) >= required_approvals:
        return Outcome.APPROVED
    return Outcome.PENDING


@dataclass(frozen=True)
class ApprovalSnapshot:
    """Các trường quan trọng của Hồ sơ vay tại thời điểm được duyệt (CONTEXT.md: Snapshot).

    Hạn mức và kỳ hạn là của tờ trình được duyệt, tức là số tiền sẽ giải ngân; số tiền yêu cầu
    cũng nằm trong snapshot để mọi sửa đổi hồ sơ vay sau khi duyệt đều bị phát hiện (ST04).
    """

    application_id: uuid.UUID
    code: str
    requested_amount: Decimal
    approved_amount: Decimal
    approved_term: int
    annual_rate: Decimal
    receiving_account: str

    def canonical(self) -> str:
        """Chuỗi ghép theo thứ tự cố định (SUC02 bước 2). Số được chuẩn hóa về một dạng duy nhất,
        để giá trị đọc lại từ CSDL với độ chính xác khác vẫn cho cùng chuỗi."""
        return "|".join(
            [
                str(self.application_id),
                self.code,
                f"{self.requested_amount:.0f}",
                f"{self.approved_amount:.0f}",
                str(self.approved_term),
                f"{self.annual_rate:.4f}",
                self.receiving_account,
            ]
        )
