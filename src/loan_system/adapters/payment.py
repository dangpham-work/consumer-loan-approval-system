"""Cổng thanh toán (UC25). Hệ thống thật nằm ngoài phạm vi; bản giả lập chuyển tiền theo kịch bản.

Cổng thanh toán nhận idempotency key: gửi lại cùng một lệnh (cùng khóa) thì nhận lại đúng kết quả
lần trước và tiền không bị chuyển hai lần (UC25 7a).
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol


class PaymentUnavailable(Exception):
    """Lỗi tạm thời (hết thời gian chờ, cổng bảo trì): lệnh chưa được thực hiện, thử lại được."""


@dataclass(frozen=True)
class TransferResult:
    succeeded: bool
    transaction_ref: str | None  # mã giao dịch khi thành công
    reason: str | None = None  # lý do bị từ chối, ví dụ tài khoản không tồn tại


class PaymentGateway(Protocol):
    def transfer(self, account: str, amount: Decimal, idempotency_key: str) -> TransferResult: ...


@dataclass(frozen=True)
class Transfer:
    account: str
    amount: Decimal
    idempotency_key: str
    transaction_ref: str


@dataclass
class FakePaymentGateway:
    transfers: list[Transfer] = field(default_factory=list)  # tiền đã thực sự chuyển
    requests: list[str] = field(default_factory=list)  # idempotency key của mọi lệnh nhận được
    _results: dict[str, TransferResult] = field(default_factory=dict)
    _unavailable: int = 0
    _rejected_accounts: set[str] = field(default_factory=set)

    def unavailable_for(self, requests: int) -> None:
        """`requests` lệnh tiếp theo gặp lỗi tạm thời."""
        self._unavailable = requests

    def reject_account(self, account: str) -> None:
        self._rejected_accounts.add(account)

    def transfer(self, account: str, amount: Decimal, idempotency_key: str) -> TransferResult:
        self.requests.append(idempotency_key)
        if idempotency_key in self._results:
            return self._results[idempotency_key]
        if self._unavailable > 0:
            self._unavailable -= 1
            raise PaymentUnavailable
        if account in self._rejected_accounts:
            result = TransferResult(False, None, "Tài khoản nhận không tồn tại")
        else:
            ref = f"GD{len(self.transfers) + 1:010d}"
            self.transfers.append(Transfer(account, amount, idempotency_key, ref))
            result = TransferResult(True, ref)
        self._results[idempotency_key] = result
        return result
