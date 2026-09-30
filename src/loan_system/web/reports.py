"""Màn hình M11 Báo cáo thống kê (UC32), quyền `REPORT_VIEW` (Quản lý phê duyệt).

Chọn khoảng ngày (tối đa 12 tháng, mặc định từ đầu tháng đến hôm nay theo giờ Việt Nam); biểu đồ vẽ
bằng thanh CSS, không cần thư viện JavaScript. Xuất CSV/PDF ghi `REPORT_EXPORT` như REST API. Cùng
tầng nghiệp vụ và cùng thông điệp với `api/reports.py`.
"""

from dataclasses import dataclass
from datetime import date
from typing import Annotated, Any, Literal
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import HTMLResponse

from loan_system.api.deps import Ctx
from loan_system.api.reports import _CONTENT_TYPE, _EXTENSION, Service
from loan_system.domain.report import DateRangeTooLong, InvalidDateRange, StatisticsReport
from loan_system.services.auth_service import CurrentUser
from loan_system.web.labels import VIETNAM_TIME
from loan_system.web.pages import PREFIX, message_of, render, require_page

router = APIRouter(prefix=f"{PREFIX}/reports", include_in_schema=False)

ViewerPage = Annotated[CurrentUser, Depends(require_page("REPORT_VIEW"))]
Format = Annotated[Literal["CSV", "PDF"], Query(alias="format")]

INVALID_DATE = "Ngày không hợp lệ: chọn ngày theo lịch (năm-tháng-ngày)."


@dataclass(frozen=True)
class Period:
    """Khoảng ngày đúng như người dùng nhập, để hiện lại trên biểu mẫu và dựng liên kết xuất."""

    from_: str
    to: str

    def query(self, fmt: str) -> str:
        return urlencode({"from": self.from_, "to": self.to, "format": fmt})


def period(
    ctx: Ctx,
    from_: Annotated[str, Query(alias="from", max_length=50)] = "",
    to: Annotated[str, Query(max_length=50)] = "",
) -> Period:
    # Giới hạn rộng hơn 10 ký tự của một ngày để giá trị sai định dạng vẫn tới `_statistics` và hiện
    # thông điệp ngay trên trang, thay vì trang lỗi 400 chung của lỗi kiểm tra tham số.
    today = ctx.clock.now().astimezone(VIETNAM_TIME).date()
    return Period(from_.strip() or today.replace(day=1).isoformat(),
                  to.strip() or today.isoformat())


Chosen = Annotated[Period, Depends(period)]


def _statistics(service: Service, p: Period) -> StatisticsReport | str:
    """Báo cáo của khoảng đã chọn, hoặc thông điệp lỗi hiện trên biểu mẫu (UC32 2a)."""
    try:
        first, last = date.fromisoformat(p.from_), date.fromisoformat(p.to)
    except ValueError:
        return INVALID_DATE
    try:
        return service.statistics(first, last)
    except (InvalidDateRange, DateRangeTooLong) as exc:
        return message_of(exc)


def _bars(counts: dict[Any, int]) -> list[tuple[Any, int, int]]:
    """(khóa, số lượng, độ dài thanh theo % so với giá trị lớn nhất) cho biểu đồ thanh ngang."""
    peak = max(counts.values(), default=0)
    return [(key, n, round(n * 100 / peak) if peak else 0) for key, n in counts.items()]


def _page(request: Request, user: CurrentUser, p: Period,
          outcome: StatisticsReport | str) -> HTMLResponse:
    if isinstance(outcome, str):
        return render(request, "reports.html", {"period": p, "report": None, "error": outcome},
                      user=user, status_code=status.HTTP_400_BAD_REQUEST)
    return render(
        request, "reports.html",
        {"period": p, "report": outcome,
         "status_bars": _bars(outcome.applications_by_status),
         "group_bars": _bars(outcome.loans_by_debt_group),
         "grade_bars": _bars(outcome.credit_grade_distribution)},
        user=user,
    )


@router.get("", response_class=HTMLResponse)
def statistics(request: Request, user: ViewerPage, service: Service, p: Chosen) -> HTMLResponse:
    return _page(request, user, p, _statistics(service, p))


@router.get("/export", response_model=None)
def export(
    request: Request, user: ViewerPage, service: Service, p: Chosen, fmt: Format = "CSV"
) -> Response:
    """UC32 3a: tải báo cáo của đúng khoảng đang xem; khoảng sai thì hiện lại trang kèm lỗi."""
    outcome = _statistics(service, p)
    if isinstance(outcome, str):
        return _page(request, user, p, outcome)
    return Response(
        content=service.export(user, outcome, fmt), media_type=_CONTENT_TYPE[fmt],
        headers={"Content-Disposition": f"attachment; filename=bao_cao_thong_ke.{_EXTENSION[fmt]}",
                 "Cache-Control": "no-store"},
    )
