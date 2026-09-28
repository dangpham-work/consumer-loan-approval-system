"""UC?? Kiểm soát viên tra cứu, lọc, xuất và kiểm tra toàn vẹn nhật ký kiểm toán (SR09, ticket #15).

Lỗi nghiệp vụ được đổi sang mã HTTP ở `api/errors.py`.
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, ConfigDict

from loan_system.api.access import require
from loan_system.api.deps import Db
from loan_system.services.audit_query_service import (
    LIST_MAX,
    AuditLogFilter,
    AuditQueryService,
)
from loan_system.services.auth_service import CurrentUser

router = APIRouter(prefix="/audit", tags=["Kiểm toán"])

Viewer = Annotated[CurrentUser, Depends(require("AUDIT_VIEW"))]
Verifier = Annotated[CurrentUser, Depends(require("AUDIT_VERIFY"))]


def _service(db: Db) -> AuditQueryService:
    return AuditQueryService(db)


Service = Annotated[AuditQueryService, Depends(_service)]


def _filters(
    actor_id: uuid.UUID | None = None,
    action: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    level: str | None = None,
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: datetime | None = None,
) -> AuditLogFilter:
    return AuditLogFilter(actor_id, action, target_type, target_id, level, from_, to)


Filters = Annotated[AuditLogFilter, Depends(_filters)]


class AuditLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    seq: int
    actor_id: uuid.UUID | None
    action: str
    target_type: str | None
    target_id: str | None
    ip_address: str | None
    level: str
    detail: str | None
    created_at: datetime


class VerifyResponse(BaseModel):
    intact: bool
    broken_at_seq: int | None


@router.get("/logs", response_model=list[AuditLogResponse])
def list_logs(
    user: Viewer,
    service: Service,
    filters: Filters,
    limit: Annotated[int, Query(ge=1, le=LIST_MAX)] = LIST_MAX,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AuditLogResponse]:
    entries = service.search(filters, limit=limit, offset=offset)
    return [AuditLogResponse.model_validate(entry) for entry in entries]


@router.get("/logs/export")
def export_logs(user: Viewer, service: Service, filters: Filters) -> Response:
    csv_text = service.export_csv(filters)
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=audit_logs.csv"},
        status_code=status.HTTP_200_OK,
    )


@router.get("/verify", response_model=VerifyResponse)
def verify_chain_integrity(user: Verifier, service: Service) -> VerifyResponse:
    broken_at = service.verify_integrity()
    return VerifyResponse(intact=broken_at is None, broken_at_seq=broken_at)
