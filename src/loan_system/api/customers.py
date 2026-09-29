import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from loan_system.api.access import Auth, FORBIDDEN_MESSAGE, User, enforce_rate_limit, require
from loan_system.api.applications import (
    ChallengeResponse,
    ConsentConfirmation,
    NonNegativeMoney,
    restricted_to,
)
from loan_system.api.deps import ClientIp, Ctx, Db
from loan_system.domain.access import MIN_PASSWORD_LENGTH
from loan_system.services.auth_service import CurrentUser
from loan_system.services.customer_service import CustomerService, ProfileChanges
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


# --- UC11: thông tin khách hàng (M?? hồ sơ cá nhân, tra cứu của nhân viên) ---------------------

OTP_SENT_TO_CURRENT_PHONE = "Mã OTP đã được gửi tới số điện thoại hiện tại của bạn."


def customer_only(user: User, auth: Auth) -> CurrentUser:
    """Màn hình hồ sơ cá nhân không nằm trong ma trận RBAC (mọi Khách hàng xem/sửa của chính
    mình, SR04); chỉ cần loại tài khoản, không cần quyền nghiệp vụ riêng."""
    if user.customer_id is None:
        auth.record_access_denied(user, "CUSTOMER_PROFILE", "self")
        raise HTTPException(status.HTTP_403_FORBIDDEN, FORBIDDEN_MESSAGE)
    return user


CustomerSelf = Annotated[CurrentUser, Depends(customer_only)]
Lookup = Annotated[CurrentUser, Depends(require("CUSTOMER_VIEW"))]
# CUSTOMER_VIEW_PII cũng được cấp cho vai trò CUSTOMER (để tự xem đầy đủ hồ sơ của mình qua
# /customers/me): riêng "Hiện đầy đủ" là hành động của nhân viên theo sau một lượt tra cứu, nên
# phải chặn thêm loại tài khoản để một Khách hàng không tự soi CCCD/thu nhập của người khác.
Reveal = Annotated[CurrentUser, Depends(restricted_to("EMPLOYEE", "CUSTOMER_VIEW_PII"))]


def _customers(db: Db, ctx: Ctx, ip: ClientIp) -> CustomerService:
    return CustomerService(db, ctx.clock, ctx.settings, ctx.sms, ip, ctx.limits.pii_view)


Customers = Annotated[CustomerService, Depends(_customers)]


class ProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    full_name: str
    dob: date
    phone: str
    email: str
    national_id: str | None
    occupation: str | None
    employer: str | None
    employment_years: int | None
    monthly_income: Decimal | None
    housing_type: str | None
    address: str | None
    income_locked: bool


class UpdateProfileRequest(BaseModel):
    # Không gồm số điện thoại/email (cần OTP riêng) hay CCCD/họ tên (không đổi ở đây, SR10).
    occupation: str | None = Field(default=None, min_length=2, max_length=50)
    employer: str | None = Field(default=None, min_length=2, max_length=100)
    employment_years: int | None = Field(default=None, ge=0, le=50)
    monthly_income: NonNegativeMoney | None = None
    housing_type: Literal["OWN", "FAMILY", "RENT"] | None = None
    address: str | None = Field(default=None, min_length=5, max_length=255)


class PhoneChangeRequest(BaseModel):
    new_phone: str = Field(pattern=r"^0\d{9}$")


class EmailChangeRequest(BaseModel):
    new_email: EmailStr


class LookupRequest(BaseModel):
    national_id: str = Field(pattern=r"^\d{12}$")


def _respond(view: object) -> ProfileResponse:
    return ProfileResponse.model_validate(view)


@router.get("/me", response_model=ProfileResponse)
def get_my_profile(user: CustomerSelf, customers: Customers) -> ProfileResponse:
    return _respond(customers.view_self(user))


@router.patch("/me", response_model=ProfileResponse)
def update_my_profile(
    body: UpdateProfileRequest, user: CustomerSelf, customers: Customers
) -> ProfileResponse:
    changes = ProfileChanges(**body.model_dump(exclude_none=True))
    return _respond(customers.update_self(user, changes))


@router.post("/me/phone", status_code=status.HTTP_202_ACCEPTED, response_model=ChallengeResponse)
def start_phone_change(
    body: PhoneChangeRequest, user: CustomerSelf, customers: Customers
) -> ChallengeResponse:
    challenge_id = customers.start_contact_change(user, "phone", body.new_phone)
    return ChallengeResponse(challenge_id=challenge_id, message=OTP_SENT_TO_CURRENT_PHONE)


@router.post("/me/phone/confirm", response_model=ProfileResponse)
def confirm_phone_change(
    body: ConsentConfirmation, user: CustomerSelf, customers: Customers, ctx: Ctx
) -> ProfileResponse:
    enforce_rate_limit(ctx.limits.otp, str(user.user_id))
    return _respond(customers.confirm_contact_change(user, body.challenge_id, body.otp))


@router.post("/me/email", status_code=status.HTTP_202_ACCEPTED, response_model=ChallengeResponse)
def start_email_change(
    body: EmailChangeRequest, user: CustomerSelf, customers: Customers
) -> ChallengeResponse:
    challenge_id = customers.start_contact_change(user, "email", str(body.new_email))
    return ChallengeResponse(challenge_id=challenge_id, message=OTP_SENT_TO_CURRENT_PHONE)


@router.post("/me/email/confirm", response_model=ProfileResponse)
def confirm_email_change(
    body: ConsentConfirmation, user: CustomerSelf, customers: Customers, ctx: Ctx
) -> ProfileResponse:
    enforce_rate_limit(ctx.limits.otp, str(user.user_id))
    return _respond(customers.confirm_contact_change(user, body.challenge_id, body.otp))


@router.post("/lookup", response_model=ProfileResponse)
def lookup_customer(body: LookupRequest, user: Lookup, customers: Customers) -> ProfileResponse:
    return _respond(customers.lookup(body.national_id))


@router.post("/{customer_id}/reveal-pii", response_model=ProfileResponse)
def reveal_customer_pii(
    customer_id: uuid.UUID, user: Reveal, customers: Customers
) -> ProfileResponse:
    return _respond(customers.reveal(user, customer_id))
