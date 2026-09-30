"""UC32 Xem báo cáo thống kê (màn hình M11), quyền `REPORT_VIEW` (Quản lý phê duyệt).

Lỗi nghiệp vụ được đổi sang mã HTTP ở `api/errors.py`.
"""

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, ConfigDict

from loan_system.api.access import require
from loan_system.api.deps import ClientIp, Ctx, Db
from loan_system.services.auth_service import CurrentUser
from loan_system.services.report_service import ReportService

router = APIRouter(prefix="/reports", tags=["Báo cáo thống kê"])

Viewer = Annotated[CurrentUser, Depends(require("REPORT_VIEW"))]
FromDate = Annotated[date, Query(alias="from")]
ToDate = Annotated[date, Query(alias="to")]
Format = Annotated[Literal["CSV", "PDF"], Query(alias="format")]

_CONTENT_TYPE: dict[str, str] = {"CSV": "text/csv; charset=utf-8", "PDF": "application/pdf"}
_EXTENSION: dict[str, str] = {"CSV": "csv", "PDF": "pdf"}


def _service(db: Db, ctx: Ctx, ip: ClientIp) -> ReportService:
    return ReportService(db, ctx.clock, ip)


Service = Annotated[ReportService, Depends(_service)]


class StatisticsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    from_date: date
    to_date: date
    total_applications: int
    applications_by_status: dict[str, int]
    approved_count: int
    rejected_count: int
    approval_rate: Decimal | None
    avg_processing_days: Decimal | None
    total_disbursed: Decimal
    total_loans: int
    outstanding_principal: Decimal
    loans_by_debt_group: dict[int, int]
    overdue_loan_count: int
    overdue_loan_rate: Decimal | None
    credit_grade_distribution: dict[str, int]


@router.get("/statistics", response_model=StatisticsResponse)
def statistics(user: Viewer, service: Service, from_: FromDate, to: ToDate) -> StatisticsResponse:
    report = service.statistics(from_, to)
    return StatisticsResponse.model_validate(report)


@router.get("/statistics/export")
def export_statistics(
    user: Viewer, service: Service, from_: FromDate, to: ToDate, fmt: Format = "CSV"
) -> Response:
    report = service.statistics(from_, to)
    content = service.export(user, report, fmt)
    return Response(
        content=content,
        media_type=_CONTENT_TYPE[fmt],
        headers={"Content-Disposition": f"attachment; filename=bao_cao_thong_ke.{_EXTENSION[fmt]}"},
    )
