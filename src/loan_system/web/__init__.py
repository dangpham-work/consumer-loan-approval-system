"""Tầng giao diện người dùng Jinja2 (mục 4.3 đề cương), dưới đường dẫn `/app`."""

from fastapi import FastAPI

from loan_system.web import (
    admin, audit, auth, counter, customer, decisions, landing, loans, locked, notifications,
    pages, queue, reports,
)


def register(app: FastAPI) -> None:
    pages.register(app)
    app.include_router(landing.router)
    app.include_router(auth.router)
    app.include_router(customer.router)
    app.include_router(notifications.router)
    app.include_router(queue.router)
    app.include_router(decisions.router)
    app.include_router(locked.router)
    app.include_router(counter.router)
    app.include_router(loans.router)
    app.include_router(admin.router)
    app.include_router(audit.router)
    app.include_router(reports.router)
