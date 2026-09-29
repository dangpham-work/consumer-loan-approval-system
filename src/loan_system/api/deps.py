from collections.abc import Iterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session, sessionmaker

from loan_system.adapters.cic import CicGateway
from loan_system.adapters.email import EmailGateway
from loan_system.adapters.payment import PaymentGateway
from loan_system.adapters.sms import SmsGateway
from loan_system.clock import Clock
from loan_system.config import Settings
from loan_system.db import session_scope
from loan_system.security.rate_limit import RateLimits


@dataclass
class AppContext:
    settings: Settings
    clock: Clock
    sms: SmsGateway
    email: EmailGateway
    cic: CicGateway
    payments: PaymentGateway
    session_factory: sessionmaker[Session]
    limits: RateLimits


def get_ctx(request: Request) -> AppContext:
    ctx: AppContext = request.app.state.ctx
    return ctx


def get_db(ctx: Annotated[AppContext, Depends(get_ctx)]) -> Iterator[Session]:
    yield from session_scope(ctx.session_factory)


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


Ctx = Annotated[AppContext, Depends(get_ctx)]
Db = Annotated[Session, Depends(get_db)]
ClientIp = Annotated[str | None, Depends(client_ip)]
