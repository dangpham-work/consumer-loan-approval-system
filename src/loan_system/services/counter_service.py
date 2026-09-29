"""UC12 1a: NV tín dụng nộp hộ hồ sơ vay tại quầy, kể cả cho khách vãng lai chưa có tài khoản.

Khách hàng không tự thao tác trên hệ thống nên mọi sự đồng ý của họ (lưu thông tin khách hàng,
nộp hồ sơ vay) được xác nhận bằng OTP gửi tới số điện thoại của chính họ (docs/de-cuong-thay-doi.md,
UC09).
"""

import secrets
import uuid
from dataclasses import asdict, dataclass
from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from loan_system.adapters.sms import SmsGateway
from loan_system.clock import Clock
from loan_system.config import Settings
from loan_system.domain.access import CUSTOMER, AccountStatus
from loan_system.repositories.models import Customer, Role, User, UserRole
from loan_system.security.secrets import hash_password
from loan_system.services.application_service import ApplicationService, ApplicationView
from loan_system.services.audit_service import AuditService
from loan_system.services.auth_service import CurrentUser
from loan_system.services.otp_challenge_service import ChallengeFailed, OtpChallenges

WALK_IN_CONSENT = "WALK_IN_CONSENT"
SUBMIT_CONSENT = "SUBMIT_CONSENT"


class DuplicateCustomer(Exception):
    """Số điện thoại hoặc email đã thuộc về một khách hàng."""


@dataclass(frozen=True)
class WalkInCustomer:
    full_name: str
    date_of_birth: date
    phone: str
    email: str


class CounterService:
    def __init__(
        self, db: Session, clock: Clock, settings: Settings, sms: SmsGateway, ip: str | None
    ) -> None:
        self._db = db
        self._clock = clock
        self._settings = settings
        self._challenges = OtpChallenges(db, clock, sms, settings, ip)
        self._applications = ApplicationService(db, clock, settings, sms, ip)
        self._audit = AuditService(db, clock)
        self._ip = ip

    def start_walk_in(self, user: CurrentUser, data: WalkInCustomer) -> uuid.UUID:
        if self._identity_taken(data.phone, data.email):
            raise DuplicateCustomer
        payload = asdict(data) | {"date_of_birth": data.date_of_birth.isoformat()}
        issued = self._challenges.start(
            WALK_IN_CONSENT,
            data.phone,
            "Ma xac nhan dong y luu thong tin khach hang va xu ly du lieu ca nhan: {otp}. "
            "Chi doc ma cho nhan vien tai quay.",
            created_by=user.user_id,
            payload=payload,
        )
        self._db.commit()
        self._challenges.deliver(issued)
        return issued.id

    def confirm_walk_in(self, user: CurrentUser, challenge_id: uuid.UUID, otp: str) -> uuid.UUID:
        payload = self._challenges.confirm(
            challenge_id, WALK_IN_CONSENT, otp, confirmed_by=user.user_id
        )
        data = WalkInCustomer(
            full_name=payload["full_name"],
            date_of_birth=date.fromisoformat(payload["date_of_birth"]),
            phone=payload["phone"],
            email=payload["email"],
        )
        if self._identity_taken(data.phone, data.email):
            self._db.commit()
            raise DuplicateCustomer
        now = self._clock.now()
        customer = Customer(
            full_name=data.full_name,
            dob=data.date_of_birth,
            phone=data.phone,
            email=data.email,
            consent_at=now,
            consent_version=self._settings.terms_version,
            created_at=now,
        )
        self._db.add(customer)
        self._db.flush()
        # Tài khoản PENDING: khách vãng lai chưa đăng nhập được cho tới khi tự kích hoạt.
        account = User(
            username=data.phone,
            password_hash=hash_password(secrets.token_urlsafe(32)),
            status=AccountStatus.PENDING,
            failed_attempts=0,
            customer_id=customer.id,
            created_at=now,
        )
        self._db.add(account)
        self._db.flush()
        role_id = self._db.scalars(select(Role.id).where(Role.code == CUSTOMER)).one()
        self._db.add(UserRole(user_id=account.id, role_id=role_id))
        self._audit.log(
            "CUSTOMER_CREATE_AT_COUNTER", actor_id=user.user_id, target_type="CUSTOMER",
            target_id=customer.id, ip_address=self._ip,
        )
        try:
            self._db.commit()
        except IntegrityError as exc:
            self._db.rollback()
            raise DuplicateCustomer from exc
        return customer.id

    def start_submission(self, user: CurrentUser, application_id: uuid.UUID) -> uuid.UUID:
        """Kiểm tra đủ dữ liệu rồi gửi OTP để khách hàng xác nhận đồng ý nộp hồ sơ vay."""
        application = self._applications.editable(user, application_id)
        self._applications.ensure_complete(application)
        customer = self._db.get_one(Customer, application.customer_id)
        # SMS nêu rõ khoản vay khách hàng đang đồng ý; mã gắn với đúng các điều khoản đó.
        issued = self._challenges.start(
            SUBMIT_CONSENT,
            customer.phone,
            f"Ban dong y nop ho so vay {application.requested_amount:,.0f} dong, "
            f"{application.term_months} thang, nhan tien vao tai khoan "
            f"{self._applications.receiving_account_masked(application)}. "
            "Ma xac nhan: {otp}. Chi doc ma cho nhan vien tai quay.",
            created_by=user.user_id,
            subject_id=str(application.id),
            payload={"terms": self._applications.terms_fingerprint(application)},
        )
        self._db.commit()
        self._challenges.deliver(issued)
        return issued.id

    def confirm_submission(
        self, user: CurrentUser, application_id: uuid.UUID, challenge_id: uuid.UUID, otp: str
    ) -> ApplicationView:
        application = self._applications.editable(user, application_id)
        consented = self._challenges.confirm(
            challenge_id, SUBMIT_CONSENT, otp, confirmed_by=user.user_id,
            subject_id=str(application.id),
        )
        if consented.get("terms") != self._applications.terms_fingerprint(application):
            self._db.commit()  # mã đã bị tiêu thụ, không dùng lại được
            raise ChallengeFailed(
                "Khoản vay đã thay đổi sau khi gửi mã. Vui lòng gửi lại mã cho khách hàng."
            )
        self._applications.ensure_complete(application)
        return self._applications.record_submission(user, application)

    def _identity_taken(self, phone: str, email: str) -> bool:
        return (
            self._db.scalars(
                select(Customer.id).where(or_(Customer.phone == phone, Customer.email == email))
            ).first()
            is not None
            or self._db.scalars(select(User.id).where(User.username == phone)).first() is not None
        )
