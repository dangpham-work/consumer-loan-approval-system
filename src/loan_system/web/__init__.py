"""Tầng giao diện người dùng Jinja2 (mục 4.3 đề cương), dưới đường dẫn `/app`."""

from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from loan_system.web import auth, customer, pages


def register(app: FastAPI) -> None:
    pages.register(app)
    app.include_router(auth.router)
    app.include_router(customer.router)

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return pages.redirect(pages.PREFIX)
