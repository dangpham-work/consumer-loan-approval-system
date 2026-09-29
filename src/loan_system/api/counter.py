"""UC12 1a: NV tín dụng tiếp khách vãng lai và lập hồ sơ vay hộ tại quầy."""

import uuid
from datetime import date

from fastapi import APIRouter, status
from pydantic import BaseModel, EmailStr, Field

from loan_system.api.access import enforce_rate_limit
from loan_system.api.applications import (
    Amount,
    ApplicationResponse,
    Applications,
    ChallengeResponse,
    OTP_SENT_TO_CUSTOMER,
    ConsentConfirmation,
    Counter,
    Officer,
    Term,
    respond,
)
from loan_system.api.deps import Ctx
from loan_system.domain.applications import Purpose
from loan_system.services.application_service import LoanTerms
from loan_system.services.counter_service import WalkInCustomer

router = APIRouter(prefix="/counter", tags=["Tại quầy"])


class WalkInRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=100)
    date_of_birth: date
    phone: str = Field(pattern=r"^0\d{9}$")
    email: EmailStr


class CustomerCreated(BaseModel):
    customer_id: uuid.UUID


class CounterApplicationRequest(BaseModel):
    customer_id: uuid.UUID
    requested_amount: Amount
    term_months: Term
    purpose: Purpose


@router.post("/customers", status_code=status.HTTP_202_ACCEPTED, response_model=ChallengeResponse)
def start_walk_in(
    body: WalkInRequest, user: Officer, counter: Counter, ctx: Ctx
) -> ChallengeResponse:
    enforce_rate_limit(ctx.limits.application_write, str(user.user_id))
    challenge_id = counter.start_walk_in(
        user, WalkInCustomer(body.full_name, body.date_of_birth, body.phone, str(body.email))
    )
    return ChallengeResponse(
        challenge_id=challenge_id, message=OTP_SENT_TO_CUSTOMER
    )


@router.post(
    "/customers/confirm", status_code=status.HTTP_201_CREATED, response_model=CustomerCreated
)
def confirm_walk_in(
    body: ConsentConfirmation, user: Officer, counter: Counter, ctx: Ctx
) -> CustomerCreated:
    enforce_rate_limit(ctx.limits.otp, str(user.user_id))
    return CustomerCreated(customer_id=counter.confirm_walk_in(user, body.challenge_id, body.otp))


@router.post(
    "/applications", status_code=status.HTTP_201_CREATED, response_model=ApplicationResponse
)
def create_counter_application(
    body: CounterApplicationRequest, user: Officer, applications: Applications
) -> ApplicationResponse:
    terms = LoanTerms(body.requested_amount, body.term_months, body.purpose)
    return respond(applications.create_for(user, body.customer_id, terms))
