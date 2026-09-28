from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from loan_system.adapters.sms import FakeSmsGateway, SmsGateway
from loan_system.api import auth, customers
from loan_system.api.deps import AppContext
from loan_system.clock import Clock, SystemClock
from loan_system.config import Settings
from loan_system.db import make_engine, make_session_factory


def create_app(
    settings: Settings | None = None,
    clock: Clock | None = None,
    sms: SmsGateway | None = None,
) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title="Hệ thống quản lý và xét duyệt vay tín dụng tiêu dùng")
    app.state.ctx = AppContext(
        settings=settings,
        clock=clock or SystemClock(),
        sms=sms or FakeSmsGateway(),  # CIC, SMS, cổng thanh toán đều là giả lập
        session_factory=make_session_factory(make_engine(settings.sqlalchemy_url())),
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
    return app
