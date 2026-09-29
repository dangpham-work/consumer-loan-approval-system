"""Cổng thanh toán (UC25, UC28). Hệ thống thật nằm ngoài phạm vi; bản giả lập theo kịch bản.

Cổng thanh toán nhận idempotency key: gửi lại cùng một lệnh (cùng khóa) thì nhận lại đúng kết quả
lần trước và tiền không bị chuyển hai lần (UC25 7a). `charge` (UC28: khách hàng thanh toán trực
tuyến) dùng cùng cơ chế cho chiều tiền vào; `external_ref` trả về được lưu trên Payment để chống
ghi nhận trùng (UC28 3b, UNIQUE trên `payments.external_ref`).
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


@dataclass(frozen=True)
class ChargeResult:
    succeeded: bool
    transaction_ref: str | None  # mã giao dịch, dùng làm external_ref (UC28 bước 7)
    reason: str | None = None  # lý do giao dịch thất bại


class PaymentGateway(Protocol):
    def transfer(self, account: str, amount: Decimal, idempotency_key: str) -> TransferResult: ...

    def charge(self, amount: Decimal, idempotency_key: str) -> ChargeResult: ...


@dataclass(frozen=True)
class Transfer:
    account: str
    amount: Decimal
    idempotency_key: str
    transaction_ref: str


@dataclass(frozen=True)
class Charge:
    amount: Decimal
    idempotency_key: str
    transaction_ref: str


@dataclass
class FakePaymentGateway:
    transfers: list[Transfer] = field(default_factory=list)  # tiền đã thực sự chuyển
    requests: list[str] = field(default_factory=list)  # idempotency key của mọi lệnh nhận được
    charges: list[Charge] = field(default_factory=list)  # tiền đã thực sự thu
    charge_requests: list[str] = field(default_factory=list)
    _results: dict[str, TransferResult] = field(default_factory=dict)
    _charge_results: dict[str, ChargeResult] = field(default_factory=dict)
    _unavailable: int = 0
    _rejected_accounts: set[str] = field(default_factory=set)
    _charge_unavailable: int = 0
    _reject_next_charge: str | None = None

    def unavailable_for(self, requests: int) -> None:
        """`requests` lệnh tiếp theo gặp lỗi tạm thời."""
        self._unavailable = requests

    def reject_account(self, account: str) -> None:
        self._rejected_accounts.add(account)

    def charge_unavailable_for(self, requests: int) -> None:
        self._charge_unavailable = requests

    def reject_next_charge(self, reason: str) -> None:
        self._reject_next_charge = reason

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

    def charge(self, amount: Decimal, idempotency_key: str) -> ChargeResult:
        self.charge_requests.append(idempotency_key)
        if idempotency_key in self._charge_results:
            return self._charge_results[idempotency_key]
        if self._charge_unavailable > 0:
            self._charge_unavailable -= 1
            raise PaymentUnavailable
        if self._reject_next_charge is not None:
            result = ChargeResult(False, None, self._reject_next_charge)
            self._reject_next_charge = None
        else:
            ref = f"TT{len(self.charges) + 1:010d}"
            self.charges.append(Charge(amount, idempotency_key, ref))
            result = ChargeResult(True, ref)
        self._charge_results[idempotency_key] = result
        return result
