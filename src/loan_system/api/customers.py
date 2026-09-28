import uuid
from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr, Field

from loan_system.api.deps import ClientIp, Ctx, Db
from loan_system.domain.access import MIN_PASSWORD_LENGTH
from loan_system.services.registration_service import (
    DuplicateIdentity,
    NewRegistration,
    RegistrationFailed,
    RegistrationService,
)

router = APIRouter(prefix="/customers", tags=["Khách hàng"])

# UC09 2b: cùng một thông điệp cho mọi trường hợp trùng, không nói trường nào bị trùng.
DUPLICATE_MESSAGE = (
    "Không thể đăng ký với thông tin này. Nếu bạn đã có tài khoản, "
    "hãy đăng nhập hoặc dùng chức năng quên mật khẩu."
)


class RegisterRequest(BaseModel):
    # Chỉ nhận các trường khai báo ở đây; trường thừa bị bỏ qua (SR10, chống mass assignment).
    full_name: str = Field(min_length=2, max_length=100)
    date_of_birth: date
    phone: str = Field(pattern=r"^0\d{9}$")
    email: EmailStr
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=128)  # SR01
    accept_terms: Literal[True]  # phải tự tích đồng ý điều khoản sử dụng


class RegisterResponse(BaseModel):
    registration_id: uuid.UUID
    eligible_for_loan: bool
    message: str


class VerifyRequest(BaseModel):
    registration_id: uuid.UUID
    otp: str = Field(pattern=r"^\d{6}$")


def _service(db: Db, ctx: Ctx, ip: ClientIp) -> RegistrationService:
    return RegistrationService(db, ctx.clock, ctx.sms, ctx.settings, ip)


@router.post("/register", status_code=status.HTTP_202_ACCEPTED, response_model=RegisterResponse)
def register(body: RegisterRequest, db: Db, ctx: Ctx, ip: ClientIp) -> RegisterResponse:
    try:
        started = _service(db, ctx, ip).start(
            NewRegistration(
                full_name=body.full_name,
                date_of_birth=body.date_of_birth,
                phone=body.phone,
                email=str(body.email),
                password=body.password,
            )
        )
    except DuplicateIdentity as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, DUPLICATE_MESSAGE) from exc
    return RegisterResponse(
        registration_id=started.registration_id,
        eligible_for_loan=started.eligible_for_loan,
        message="Mã OTP đã được gửi tới số điện thoại của bạn.",
    )


@router.post("/register/verify", status_code=status.HTTP_201_CREATED)
def verify(body: VerifyRequest, db: Db, ctx: Ctx, ip: ClientIp) -> dict[str, str]:
    try:
        _service(db, ctx, ip).verify(body.registration_id, body.otp)
    except RegistrationFailed as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except DuplicateIdentity as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, DUPLICATE_MESSAGE) from exc
    return {"message": "Đăng ký thành công. Bạn có thể đăng nhập."}
