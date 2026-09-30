"""Màn hình M10 Nhật ký kiểm toán (Kiểm soát viên).

UC07 Tra cứu nhật ký: lọc theo khoảng ngày (giờ Việt Nam, tính trọn ngày ở hai đầu), người thực hiện
(tên đăng nhập), hành động và mức độ; xuất CSV đúng bộ lọc đang xem. UC08 Kiểm tra toàn vẹn chuỗi
băm: nút "Kiểm tra toàn vẹn chuỗi" chỉ ra bản ghi đầu tiên bị phá vỡ (ST08). Cùng tầng nghiệp vụ với
`api/audit.py`; trang chỉ đọc, không có thao tác sửa nhật ký.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Annotated, Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import HTMLResponse

from loan_system.api.audit import Service
from loan_system.services.audit_query_service import (
    AuditLogEntry,
    AuditLogFilter,
    AuditQueryService,
)
from loan_system.services.auth_service import CurrentUser
from loan_system.web.labels import VIETNAM_TIME
from loan_system.web.pages import PREFIX, Csrf, render, require_page

router = APIRouter(prefix=f"{PREFIX}/audit", include_in_schema=False)

ViewerPage = Annotated[CurrentUser, Depends(require_page("AUDIT_VIEW"))]
VerifierPage = Annotated[CurrentUser, Depends(require_page("AUDIT_VERIFY"))]

PAGE_SIZE = 50
LEVELS = ("INFO", "WARNING", "CRITICAL")
INVALID_FILTER = ("Bộ lọc không hợp lệ: ngày theo lịch chọn (năm-tháng-ngày), ngày kết thúc không "
                  "trước ngày bắt đầu, mức độ là INFO, WARNING hoặc CRITICAL.")
# Không có người dùng nào mang mã này: lọc theo tên đăng nhập không tồn tại thì không ra bản ghi nào.
_NOBODY = uuid.UUID(int=0)


@dataclass(frozen=True)
class Criteria:
    """Bộ lọc M10 đúng như người dùng nhập (chuỗi), để hiện lại trên biểu mẫu và dựng liên kết."""

    from_: str = ""
    to: str = ""
    actor: str = ""
    action: str = ""
    level: str = ""

    def query(self) -> str:
        """Chuỗi truy vấn của các ô đã nhập, dùng cho liên kết xuất CSV và trang sau."""
        pairs = {"from": self.from_, "to": self.to, "actor": self.actor, "action": self.action,
                 "level": self.level}
        return urlencode({k: v for k, v in pairs.items() if v})


def criteria(
    from_: Annotated[str, Query(alias="from", max_length=10)] = "",
    to: Annotated[str, Query(max_length=10)] = "",
    actor: Annotated[str, Query(max_length=50)] = "",
    action: Annotated[str, Query(max_length=50)] = "",
    level: Annotated[str, Query(max_length=10)] = "",
) -> Criteria:
    return Criteria(from_.strip(), to.strip(), actor.strip(), action.strip().upper(),
                    level.strip().upper())


Criterion = Annotated[Criteria, Depends(criteria)]


def _day(text: str) -> date | None:
    return date.fromisoformat(text) if text else None


def to_filter(service: AuditQueryService, c: Criteria) -> AuditLogFilter | None:
    """Bộ lọc của tầng nghiệp vụ; None nếu người dùng nhập sai (ngày, mức độ)."""
    try:
        first, last = _day(c.from_), _day(c.to)
    except ValueError:
        return None
    if (c.level and c.level not in LEVELS) or (first and last and last < first):
        return None
    actor_id = (service.actor_id(c.actor) or _NOBODY) if c.actor else None
    return AuditLogFilter(
        actor_id=actor_id,
        action=c.action or None,
        level=c.level or None,
        from_=datetime.combine(first, time.min, VIETNAM_TIME) if first else None,
        to=datetime.combine(last, time.max, VIETNAM_TIME) if last else None,
    )


def audit_page(
    request: Request, user: CurrentUser, service: AuditQueryService, c: Criteria, page: int = 1,
    status_code: int = status.HTTP_200_OK, **context: Any,
) -> HTMLResponse:
    filters = to_filter(service, c)
    entries: list[AuditLogEntry] = []
    if filters is None:
        status_code, context["error"] = status.HTTP_400_BAD_REQUEST, INVALID_FILTER
    else:
        entries = service.search(filters, limit=PAGE_SIZE + 1, offset=(page - 1) * PAGE_SIZE)
    has_next = len(entries) > PAGE_SIZE
    entries = entries[:PAGE_SIZE]
    return render(
        request, "audit.html",
        {"entries": entries, "usernames": service.usernames(entries), "criteria": c,
         "query": c.query(), "page": page, "has_next": has_next, "levels": LEVELS,
         "can_verify": "AUDIT_VERIFY" in user.permissions, **context},
        user=user, status_code=status_code,
    )


@router.get("", response_class=HTMLResponse)
def audit_log(
    request: Request, user: ViewerPage, service: Service, c: Criterion,
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
) -> HTMLResponse:
    return audit_page(request, user, service, c, page)


@router.get("/export", response_model=None)
def export(
    request: Request, user: ViewerPage, service: Service, c: Criterion
) -> Response:
    filters = to_filter(service, c)
    if filters is None:
        return audit_page(request, user, service, c)
    return Response(
        content=service.export_csv(filters), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=audit_logs.csv",
                 "Cache-Control": "no-store"},
    )


@router.post("/verify", dependencies=[Csrf], response_class=HTMLResponse)
def verify(request: Request, user: VerifierPage, service: Service) -> HTMLResponse:
    """UC08: duyệt lại toàn bộ chuỗi băm; kết quả hiện ngay trên M10 (bộ lọc để trống)."""
    return audit_page(request, user, service, Criteria(),
                      verified=True, broken_at=service.verify_integrity())
