"""Màn hình của Kiểm soát viên: hồ sơ vay bị khóa (ST04) và hủy sau khi điều tra xong.

Ngoại lệ có chủ đích duy nhất của Kiểm soát viên (CONTEXT.md, ticket #11). Cùng tầng nghiệp vụ và
cùng schema với `POST /applications/{id}/resolve-lock`.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from loan_system.api.applications import Applications, LockResolveRequest
from loan_system.domain.applications import ApplicationStatus
from loan_system.services.application_service import ApplicationService
from loan_system.services.auth_service import CurrentUser
from loan_system.web.pages import PREFIX, Csrf, Entry, redirect, render, require_page, validate

router = APIRouter(prefix=f"{PREFIX}/locked", include_in_schema=False)

ResolverPage = Annotated[
    CurrentUser, Depends(require_page("APPLICATION_LOCK_RESOLVE", "EMPLOYEE"))
]

FIELD_ERRORS = {"reason": "Lý do từ 10 đến 200 ký tự."}


def _page(
    request: Request, user: CurrentUser, applications: ApplicationService,
    status_code: int = status.HTTP_200_OK, **context: Any,
) -> HTMLResponse:
    return render(
        request, "locked.html",
        {"applications": applications.list_visible(user, ApplicationStatus.LOCKED), **context},
        user=user, status_code=status_code,
    )


@router.get("", response_class=HTMLResponse)
def locked_page(request: Request, user: ResolverPage, applications: Applications) -> HTMLResponse:
    return _page(request, user, applications)


@router.post("/{application_id}/resolve", dependencies=[Csrf], response_model=None)
def resolve(
    request: Request, application_id: uuid.UUID, user: ResolverPage, applications: Applications,
    reason: Entry = "",
) -> HTMLResponse | RedirectResponse:
    body, field_errors = validate(LockResolveRequest, {"reason": reason.strip()}, FIELD_ERRORS)
    if body is None:
        return _page(request, user, applications, status.HTTP_400_BAD_REQUEST,
                     field_errors=field_errors, failed_id=application_id, reason=reason)
    applications.resolve_lock(user, application_id, body.reason)
    return redirect(f"{PREFIX}/locked?notice=lock_resolved")
