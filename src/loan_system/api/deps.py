from collections.abc import Iterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session, sessionmaker

from loan_system.adapters.sms import SmsGateway
from loan_system.clock import Clock
from loan_system.config import Settings
from loan_system.db import session_scope


@dataclass
class AppContext:
    settings: Settings
    clock: Clock
    sms: SmsGateway
    session_factory: sessionmaker[Session]


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
