"""Cổng tra cứu CIC (UC19). Hệ thống CIC thật nằm ngoài phạm vi; bản giả lập trả kết quả theo kịch bản.

Kịch bản mặc định theo chữ số cuối của số CCCD, để demo được mọi nhánh của UC18 mà không cần cấu
hình: 9 - không phản hồi; 8 - nợ nhóm 3; 7 - nợ nhóm 2; 6 - chưa có lịch sử tín dụng; còn lại -
nợ nhóm 1. Test đặt kịch bản riêng cho từng số CCCD bằng `respond` và `never_respond`.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True)
class CicReport:
    highest_debt_group: int  # nhóm nợ cao nhất 24 tháng; 0 = chưa có lịch sử tín dụng
    total_outstanding: Decimal
    lender_count: int
    monthly_obligation: Decimal
    # Dữ liệu thay thế (giả lập): số lần trễ hạn hóa đơn điện/nước 12 tháng; None = không có.
    utility_late_payments: int | None


class CicTimeout(Exception):
    """CIC không phản hồi trong thời gian chờ."""


class CicGateway(Protocol):
    def query(self, national_id: str, reference: str, timeout_seconds: float) -> CicReport: ...


@dataclass(frozen=True)
class CicQuery:
    reference: str
    timeout_seconds: float


@dataclass(frozen=True)
class _Scenario:
    report: CicReport | None  # None = không bao giờ phản hồi
    timeouts: int  # số lần hết thời gian chờ trước khi phản hồi


_NO_HISTORY = CicReport(0, Decimal(0), 0, Decimal(0), 0)
_DEFAULTS: dict[str, CicReport | None] = {
    "9": None,
    "8": CicReport(3, Decimal(45_000_000), 2, Decimal(4_000_000), 3),
    "7": CicReport(2, Decimal(30_000_000), 2, Decimal(2_500_000), 1),
    "6": _NO_HISTORY,
}
_GROUP_1 = CicReport(1, Decimal(20_000_000), 1, Decimal(1_500_000), 0)


@dataclass
class FakeCicGateway:
    queries: list[CicQuery] = field(default_factory=list)
    _scenarios: dict[str, _Scenario] = field(default_factory=dict)
    _attempts: dict[str, int] = field(default_factory=dict)

    def respond(self, national_id: str, report: CicReport, *, after_timeouts: int = 0) -> None:
        self._scenarios[national_id] = _Scenario(report, after_timeouts)

    def never_respond(self, national_id: str) -> None:
        self._scenarios[national_id] = _Scenario(None, 0)

    def query(self, national_id: str, reference: str, timeout_seconds: float) -> CicReport:
        self.queries.append(CicQuery(reference, timeout_seconds))
        scenario = self._scenarios.get(national_id) or _Scenario(
            _DEFAULTS.get(national_id[-1:], _GROUP_1), 0
        )
        attempt = self._attempts.get(national_id, 0) + 1
        self._attempts[national_id] = attempt
        if scenario.report is None or attempt <= scenario.timeouts:
            raise CicTimeout
        return scenario.report
