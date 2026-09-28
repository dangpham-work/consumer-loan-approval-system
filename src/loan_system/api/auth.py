from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from pydantic import BaseModel

from loan_system.api.deps import ClientIp, Ctx, Db
from loan_system.services.auth_service import (
    AuthService,
    CurrentUser,
    InvalidCredentials,
    NotAuthenticated,
)

router = APIRouter(prefix="/auth", tags=["Xác thực"])

SESSION_COOKIE = "session"


class LoginRequest(BaseModel):
    username: str
    password: str


def _service(db: Db, ctx: Ctx, ip: ClientIp) -> AuthService:
    return AuthService(db, ctx.clock, ctx.settings, ip)


Auth = Annotated[AuthService, Depends(_service)]


def current_user(auth: Auth, session: Annotated[str | None, Cookie()] = None) -> CurrentUser:
    try:
        return auth.authenticate(session)
    except NotAuthenticated as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Chưa đăng nhập") from exc


@router.post("/login")
def login(body: LoginRequest, auth: Auth, response: Response) -> dict[str, str]:
    try:
        token = auth.login(body.username, body.password)
    except InvalidCredentials as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Thông tin đăng nhập không đúng") from exc
    response.set_cookie(
        SESSION_COOKIE, token, httponly=True, secure=True, samesite="strict", path="/"
    )
    return {"message": "Đăng nhập thành công"}


@router.get("/session")
def whoami(user: Annotated[CurrentUser, Depends(current_user)]) -> dict[str, str]:
    return {"user_id": str(user.user_id), "username": user.username, "role": user.role}


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(auth: Auth, response: Response, session: Annotated[str | None, Cookie()] = None) -> None:
    try:
        auth.logout(session)
    except NotAuthenticated as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Chưa đăng nhập") from exc
    response.delete_cookie(SESSION_COOKIE, httponly=True, secure=True, samesite="strict", path="/")
