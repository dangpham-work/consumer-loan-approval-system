from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from loan_system.adapters.cic import CicGateway, FakeCicGateway
from loan_system.adapters.email import EmailGateway, FakeEmailGateway
from loan_system.adapters.sms import FakeSmsGateway, SmsGateway
from loan_system.api import (
    admin,
    applications,
    audit,
    auth,
    counter,
    customers,
    errors,
    notifications,
)
from loan_system.api.deps import AppContext
from loan_system.clock import Clock, SystemClock
from loan_system.config import Settings
from loan_system.db import make_engine, make_session_factory
from loan_system.security.rate_limit import RateLimits


def create_app(
    settings: Settings | None = None,
    clock: Clock | None = None,
    sms: SmsGateway | None = None,
    email: EmailGateway | None = None,
    cic: CicGateway | None = None,
) -> FastAPI:
    settings = settings or Settings()
    clock = clock or SystemClock()
    app = FastAPI(title="Hệ thống quản lý và xét duyệt vay tín dụng tiêu dùng")
    app.state.ctx = AppContext(
        settings=settings,
        clock=clock,
        # CIC, SMS, email, cổng thanh toán đều là giả lập
        sms=sms or FakeSmsGateway(),
        email=email or FakeEmailGateway(),
        cic=cic or FakeCicGateway(),
        session_factory=make_session_factory(make_engine(settings.sqlalchemy_url())),
        limits=RateLimits.from_settings(settings, clock),
    )

    @app.exception_handler(RequestValidationError)
    async def invalid_input(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Quy ước lỗi mục 4.2.4: 400, chỉ nêu trường và lý do, không lộ chi tiết kỹ thuật.
        errors = [
            {"field": ".".join(str(p) for p in err["loc"][1:]), "message": err["msg"]}
            for err in exc.errors()
        ]
        return JSONResponse(status_code=400, content={"detail": "Dữ liệu không hợp lệ", "errors": errors})

    app.include_router(customers.router)
    app.include_router(auth.router)
    app.include_router(admin.router)
    app.include_router(applications.router)
    app.include_router(counter.router)
    app.include_router(notifications.router)
    app.include_router(audit.router)
    errors.register(app)
    return app
