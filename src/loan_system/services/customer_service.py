"""UC11 Tra cứu thông tin khách hàng; Khách hàng tự xem và cập nhật thông tin của mình.

Thông tin khách hàng tồn tại độc lập với Hồ sơ vay (CONTEXT.md): đây là màn hình hồ sơ cá nhân,
khác với `ApplicantView` trong application_service.py (thông tin khách hàng theo góc nhìn của một
Hồ sơ vay cụ thể). Đổi số điện thoại hoặc email cần xác nhận bằng OTP vì đó cũng là định danh đăng
nhập/liên lạc (UC09 tương tự). Nhân viên tra cứu qua blind index luôn thấy dữ liệu đã che; chỉ hành
động "Hiện đầy đủ" (`reveal`) mới trả về PII đầy đủ và luôn ghi nhật ký VIEW_PII (ma trận RBAC).
"""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from loan_system.adapters.sms import SmsGateway
from loan_system.clock import Clock
from loan_system.config import Settings
from loan_system.domain.applications import mask
from loan_system.repositories.models import Customer, User
from loan_system.security.crypto import FieldCipher, blind_index
from loan_system.security.rate_limit import SlidingWindowLimiter
from loan_system.services.application_service import CustomerNotFound, has_unfinished_business
from loan_system.services.audit_service import AuditService
from loan_system.services.auth_service import CurrentUser
from loan_system.services.customer_pii import income_context, national_id_context
from loan_system.services.notification_service import NotificationService
from loan_system.services.otp_challenge_service import OtpChallenges

CONTACT_CHANGE = "CONTACT_CHANGE"
ContactField = Literal["phone", "email"]


class IncomeLocked(Exception):
    """Không đổi thu nhập khi Khách hàng đang có Hồ sơ vay đang xử lý (số liệu đã dùng để chấm
    điểm/thẩm định hồ sơ đó không được lặng lẽ đổi khác)."""


class ContactTaken(Exception):
    """Số điện thoại hoặc email mới đã thuộc về một khách hàng khác."""


@dataclass(frozen=True)
class ProfileChanges:
    """Các trường Khách hàng tự sửa được; None là không đổi. Không gồm số điện thoại/email (cần
    OTP, xem `start_contact_change`) hay CCCD/họ tên (định danh, không đổi ở màn hình này)."""

    occupation: str | None = None
    employer: str | None = None
    employment_years: int | None = None
    monthly_income: Decimal | None = None
    housing_type: str | None = None
    address: str | None = None


@dataclass(frozen=True)
class CustomerProfileView:
    id: uuid.UUID
    full_name: str
    dob: date
    phone: str
    email: str
    national_id: str | None  # đã che nếu reveal_pii=False
    occupation: str | None
    employer: str | None
    employment_years: int | None
    monthly_income: Decimal | None  # None nếu bị che
    housing_type: str | None
    address: str | None
    income_locked: bool


class CustomerService:
    def __init__(
        self,
        db: Session,
        clock: Clock,
        settings: Settings,
        sms: SmsGateway,
        ip: str | None,
        pii_view_limiter: SlidingWindowLimiter | None = None,
    ) -> None:
        self._db = db
        self._clock = clock
        self._settings = settings
        self._cipher = FieldCipher(settings.data_enc_key)
        self._challenges = OtpChallenges(db, clock, sms, settings, ip)
        self._audit = AuditService(db, clock, pii_view_limiter)
        self._notifications = NotificationService(db, clock, sms)
        self._ip = ip

    # --- Khách hàng tự xem/sửa -----------------------------------------------------------------

    def view_self(self, user: CurrentUser) -> CustomerProfileView:
        return self._view(self._own_customer(user), reveal_pii=True)

    def update_self(self, user: CurrentUser, changes: ProfileChanges) -> CustomerProfileView:
        customer = self._own_customer(user)
        if changes.monthly_income is not None and self._income_locked(customer.id):
            raise IncomeLocked
        for field in ("occupation", "employer", "employment_years", "housing_type", "address"):
            value = getattr(changes, field)
            if value is not None:
                setattr(customer, field, value)
        if changes.monthly_income is not None:
            customer.monthly_income_enc = self._cipher.encrypt(
                str(changes.monthly_income), context=income_context(customer.id)
            )
        self._audit.log(
            "CUSTOMER_PROFILE_UPDATE", actor_id=user.user_id, target_type="CUSTOMER",
            target_id=customer.id, ip_address=self._ip,
        )
        self._db.commit()
        return self._view(customer, reveal_pii=True)

    def start_contact_change(
        self, user: CurrentUser, field: ContactField, new_value: str
    ) -> uuid.UUID:
        """Gửi OTP tới số điện thoại hiện tại để xác nhận đổi số điện thoại hoặc email."""
        customer = self._own_customer(user)
        if self._contact_taken(field, new_value, exclude_customer_id=customer.id):
            raise ContactTaken
        label = "số điện thoại" if field == "phone" else "email"
        issued = self._challenges.start(
            CONTACT_CHANGE,
            customer.phone,
            f"Ma xac nhan doi {label}: {{otp}}. Bo qua neu khong phai ban yeu cau.",
            created_by=user.user_id,
            subject_id=str(customer.id),
            payload={"field": field, "new_value": new_value},
        )
        self._db.commit()
        self._challenges.deliver(issued)
        return issued.id

    def confirm_contact_change(
        self, user: CurrentUser, challenge_id: uuid.UUID, otp: str
    ) -> CustomerProfileView:
        customer = self._own_customer(user)
        payload = self._challenges.confirm(
            challenge_id, CONTACT_CHANGE, otp, confirmed_by=user.user_id,
            subject_id=str(customer.id),
        )
        field: ContactField = payload["field"]
        new_value: str = payload["new_value"]
        if self._contact_taken(field, new_value, exclude_customer_id=customer.id):
            self._db.commit()  # mã đã bị tiêu thụ, không dùng lại được
            raise ContactTaken
        old_value = customer.phone if field == "phone" else customer.email
        if field == "phone":
            customer.phone = new_value
            # username của khách hàng chính là số điện thoại (de-cuong-thay-doi.md).
            account = self._db.scalars(
                select(User).where(User.customer_id == customer.id)
            ).one_or_none()
            if account is not None:
                account.username = new_value
        else:
            customer.email = new_value
        self._audit.log(
            "CUSTOMER_CONTACT_CHANGE", actor_id=user.user_id, target_type="CUSTOMER",
            target_id=customer.id, ip_address=self._ip,
            detail=f"{field}: {mask(old_value)} -> {mask(new_value)}",
        )
        try:
            self._db.commit()
        except IntegrityError as exc:
            self._db.rollback()
            raise ContactTaken from exc
        self._notifications.notify_customer(
            customer.id, "CONTACT_CHANGE",
            "Thong tin lien he cua ban vua duoc thay doi. Neu khong phai ban, lien he tong dai.",
            phone=customer.phone,
        )
        self._notifications.deliver()
        return self._view(customer, reveal_pii=True)

    # --- Nhân viên tra cứu (UC11) ---------------------------------------------------------------

    def lookup(self, national_id: str) -> CustomerProfileView:
        """Tra cứu theo CCCD qua blind index; luôn trả về dữ liệu đã che (xem `reveal`)."""
        digest = blind_index(self._settings.blind_index_key, national_id)
        customer = self._db.scalars(
            select(Customer).where(Customer.national_id_hash == digest)
        ).one_or_none()
        if customer is None:
            raise CustomerNotFound
        return self._view(customer, reveal_pii=False)

    def reveal(self, actor: CurrentUser, customer_id: uuid.UUID) -> CustomerProfileView:
        """"Hiện đầy đủ": luôn ghi VIEW_PII, kể cả khi gọi lặp lại (ma trận RBAC)."""
        customer = self._db.get(Customer, customer_id)
        if customer is None:
            raise CustomerNotFound
        self._audit.log_pii_view(
            actor.user_id, target_type="CUSTOMER", target_id=customer.id, ip_address=self._ip,
        )
        self._db.commit()
        return self._view(customer, reveal_pii=True)

    # --- Nội bộ -----------------------------------------------------------------------------

    def _own_customer(self, user: CurrentUser) -> Customer:
        if user.customer_id is None:
            raise CustomerNotFound
        customer = self._db.get(Customer, user.customer_id)
        if customer is None:
            raise CustomerNotFound
        return customer

    def _income_locked(self, customer_id: uuid.UUID) -> bool:
        return has_unfinished_business(self._db, customer_id)

    def _contact_taken(
        self, field: ContactField, value: str, *, exclude_customer_id: uuid.UUID
    ) -> bool:
        column = Customer.phone if field == "phone" else Customer.email
        return self._db.scalars(
            select(Customer.id).where(column == value).where(Customer.id != exclude_customer_id)
        ).first() is not None

    def _view(self, customer: Customer, *, reveal_pii: bool) -> CustomerProfileView:
        national_id = self._decrypt(customer.national_id_enc, national_id_context(customer.id))
        income = self._decrypt(customer.monthly_income_enc, income_context(customer.id))
        return CustomerProfileView(
            id=customer.id,
            full_name=customer.full_name,
            dob=customer.dob,
            phone=customer.phone,
            email=customer.email,
            national_id=(
                (national_id if reveal_pii else mask(national_id)) if national_id else None
            ),
            occupation=customer.occupation,
            employer=customer.employer,
            employment_years=customer.employment_years,
            monthly_income=Decimal(income) if income and reveal_pii else None,
            housing_type=customer.housing_type,
            address=customer.address,
            income_locked=self._income_locked(customer.id),
        )

    def _decrypt(self, sealed: bytes | None, context: str) -> str | None:
        return self._cipher.decrypt(sealed, context=context) if sealed else None
