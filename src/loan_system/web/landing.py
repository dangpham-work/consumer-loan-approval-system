"""Trang giới thiệu công khai ở `/`: điều kiện vay, ước tính số tiền trả hằng tháng, lối vào đăng ký
và đăng nhập. Người đã đăng nhập được đưa thẳng vào `/app`."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from loan_system.api.access import Auth, SessionToken
from loan_system.domain.applications import (
    CEILING_RATE,
    DOCUMENT_TYPES,
    MAX_AMOUNT,
    MAX_TERM_MONTHS,
    MIN_AMOUNT,
    MIN_TERM_MONTHS,
)
from loan_system.domain.eligibility import MAX_AGE, MIN_AGE
from loan_system.services.auth_service import NotAuthenticated
from loan_system.web.pages import PREFIX, redirect, render

router = APIRouter(include_in_schema=False)


@router.get("/", response_model=None)
def landing(
    request: Request, auth: Auth, session: SessionToken = None
) -> HTMLResponse | RedirectResponse:
    if session:
        try:
            auth.authenticate(session)
        except NotAuthenticated:
            pass
        else:
            return redirect(PREFIX)
    return render(request, "landing.html", {
        "ceiling_rate": CEILING_RATE,
        "min_amount": MIN_AMOUNT, "max_amount": MAX_AMOUNT,
        "min_term": MIN_TERM_MONTHS, "max_term": MAX_TERM_MONTHS,
        "min_age": MIN_AGE, "max_age": MAX_AGE,
        "document_types": list(DOCUMENT_TYPES),
    })
