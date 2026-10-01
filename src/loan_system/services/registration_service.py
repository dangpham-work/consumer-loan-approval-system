"""UC09 Đăng ký tài khoản khách hàng: gửi OTP xác minh số điện thoại rồi tạo tài khoản."""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import delete, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from loan_system.adapters.sms import SmsGateway
from loan_system.clock import Clock
from loan_system.config import Settings
from loan_system.domain.access import CUSTOMER
from loan_system.domain.eligibility import is_age_eligible
from loan_system.repositories.atomic import increment
from loan_system.repositories.models import Customer, RegistrationRequest, Role, User, UserRole
from loan_system.security.secrets import hash_password, keyed_hash, matches, new_otp
from loan_system.services.audit_service import AuditService


class DuplicateIdentity(Exception):
    """Số điện thoại hoặc email đã thuộc về một khách hàng khác."""


class RegistrationFailed(Exception):
    """Không xác minh được yêu cầu đăng ký; thông điệp an toàn để hiển thị cho người dùng."""


@dataclass(frozen=True)
class NewRegistration:
    full_name: str
    date_of_birth: date
    phone: str
    email: str
    password: str


@dataclass(frozen=True)
class RegistrationStarted:
    registration_id: uuid.UUID
    eligible_for_loan: bool


class RegistrationService:
    def __init__(
        self, db: Session, clock: Clock, sms: SmsGateway, settings: Settings, ip: str | None
    ) -> None:
        self._db = db
        self._clock = clock
        self._sms = sms
        self._settings = settings
        self._audit = AuditService(db, clock)
        self._ip = ip

    def start(self, data: NewRegistration) -> RegistrationStarted:
        if self._identity_taken(data.phone, data.email):
            raise DuplicateIdentity
        now = self._clock.now()
        # Yêu cầu mới thay thế yêu cầu cũ chưa xác minh của cùng số điện thoại.
        self._db.execute(delete(RegistrationRequest).where(RegistrationRequest.phone == data.phone))
        otp = new_otp()
        request = RegistrationRequest(
            full_name=data.full_name,
            dob=data.date_of_birth,
            phone=data.phone,
            email=data.email,
            password_hash=hash_password(data.password),
            otp_hash=keyed_hash(self._settings.session_secret, otp),
            otp_expires_at=now + timedelta(minutes=self._settings.otp_ttl_minutes),
            failed_attempts=0,
            consent_version=self._settings.terms_version,
            created_at=now,
        )
        self._db.add(request)
        self._db.commit()
        self._sms.send(data.phone, f"Ma xac minh dang ky cua ban la {otp}. Khong chia se ma nay.")
        # UC09 2a: vẫn cho đăng ký, chỉ báo sớm là chưa đủ tuổi vay (BR01)
        return RegistrationStarted(request.id, is_age_eligible(data.date_of_birth, now.date()))

    def verify(self, registration_id: uuid.UUID, otp: str) -> None:
        request = self._db.get(RegistrationRequest, registration_id)
        if request is None:
            raise RegistrationFailed("Yêu cầu đăng ký không tồn tại hoặc đã bị hủy.")
        now = self._clock.now()
        if now > request.otp_expires_at:
            self._cancel(request)
            raise RegistrationFailed("Mã OTP đã hết hạn. Vui lòng đăng ký lại.")
        if not matches(self._settings.session_secret, otp, request.otp_hash):
            # Tăng bộ đếm bằng một câu UPDATE nguyên tử: gửi song song nhiều mã cũng không
            # vượt được giới hạn số lần thử.
            attempts = increment(
                self._db, RegistrationRequest.failed_attempts,
                RegistrationRequest.id == request.id,
            )
            if attempts >= self._settings.otp_max_attempts:
                self._cancel(request)
                raise RegistrationFailed("Nhập sai OTP quá số lần cho phép. Yêu cầu đã bị hủy.")
            self._db.commit()
            raise RegistrationFailed("Mã OTP không đúng.")
        if self._identity_taken(request.phone, request.email):
            self._cancel(request)
            raise DuplicateIdentity
        try:
            self._create_account(request, now)
        except IntegrityError as exc:
            # Hai yêu cầu cùng số điện thoại/email được xác minh cùng lúc: chỉ một cái thắng.
            self._db.rollback()
            raise DuplicateIdentity from exc

    def _create_account(self, request: RegistrationRequest, now: datetime) -> None:
        customer = Customer(
            full_name=request.full_name,
            dob=request.dob,
            phone=request.phone,
            email=request.email,
            consent_at=request.created_at,
            consent_version=request.consent_version,
            created_at=now,
        )
        self._db.add(customer)
        self._db.flush()
        user = User(
            username=request.phone,
            password_hash=request.password_hash,
            status="ACTIVE",
            failed_attempts=0,
            customer_id=customer.id,
            created_at=now,
        )
        self._db.add(user)
        self._db.flush()
        customer_role = self._db.scalars(select(Role.id).where(Role.code == CUSTOMER)).one()
        self._db.add(UserRole(user_id=user.id, role_id=customer_role))
        self._db.execute(delete(RegistrationRequest).where(RegistrationRequest.id == request.id))
        self._db.flush()
        self._audit.log(
            "CUSTOMER_REGISTER", actor_id=user.id, target_type="CUSTOMER", target_id=customer.id,
            ip_address=self._ip,
        )
        self._db.commit()

    def _identity_taken(self, phone: str, email: str) -> bool:
        existing = self._db.scalars(
            select(Customer.id).where(or_(Customer.phone == phone, Customer.email == email))
        ).first()
        return existing is not None

    def _cancel(self, request: RegistrationRequest) -> None:
        self._db.delete(request)
        self._audit.log(
            "REGISTRATION_CANCELLED", target_type="REGISTRATION", target_id=request.id,
            ip_address=self._ip, level="WARNING",
        )
        self._db.commit()
