"""UC12 Tạo và nộp hồ sơ vay, UC13 Tải lên giấy tờ, UC16 Theo dõi trạng thái, UC17 Hủy hồ sơ vay.

Mọi truy cập đi qua `load` (SUC03): khách hàng chỉ thấy Hồ sơ vay của chính mình (SR04); nhân viên
chỉ thấy hồ sơ vay đã nộp, cùng bản nháp do chính mình nộp hộ; chỉ Người tạo mới sửa được hồ sơ vay
nộp hộ. Hồ sơ vay ngoài phạm vi được báo như không tồn tại, để không xác nhận được sự tồn tại của
nó (4.2.4, ST01).
"""

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import ColumnElement, func, or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from loan_system.adapters.sms import SmsGateway
from loan_system.clock import Clock
from loan_system.config import Settings
from loan_system.domain.applications import (
    CEILING_RATE,
    CUSTOMER_CANCELLABLE,
    EDITABLE,
    IN_PROGRESS,
    MAX_DOCUMENTS_PER_APPLICATION,
    ApplicationStatus,
    application_code,
    ensure_transition,
    mask,
    missing_for_submission,
    outside_request,
)
from loan_system.domain.calculations import annuity_payment
from loan_system.domain.documents import check_document
from loan_system.domain.loans import UNSETTLED
from loan_system.repositories.models import (
    ApplicationDocument,
    ApplicationStatusHistory,
    Customer,
    Loan,
    LoanApplication,
)
from loan_system.security.crypto import FieldCipher, blind_index
from loan_system.services.audit_service import AuditService
from loan_system.services.auth_service import CurrentUser
from loan_system.services.customer_pii import income_context, national_id_context
from loan_system.services.notification_service import NotificationService

_EXTENSIONS = {"image/jpeg": ".jpg", "image/png": ".png", "application/pdf": ".pdf"}
STAFF_LIST_LIMIT = 200


class ApplicationNotFound(Exception):
    """Không tồn tại hoặc nằm ngoài phạm vi truy cập của người gọi."""


class CustomerNotFound(Exception):
    pass


class ApplicationInProgress(Exception):
    """Khách hàng đã có một Hồ sơ vay đang xử lý (BR02)."""


class NotEditable(Exception):
    """Hồ sơ vay không ở trạng thái cho phép thao tác này."""


class NotLocked(Exception):
    """Hồ sơ vay không ở trạng thái Bị khóa."""


class NeedInfoExpired(Exception):
    """Đã quá hạn bổ sung (BR11)."""


class NotRequested(Exception):
    """Khi bổ sung chỉ được sửa đúng những mục NV tín dụng đã yêu cầu (UC15)."""


class ConcurrentModification(Exception):
    """Hồ sơ vay vừa bị thay đổi bởi một yêu cầu khác (khóa lạc quan)."""


class TooManyDocuments(Exception):
    """Hồ sơ vay đã có quá nhiều file tải lên."""


class NationalIdConflict(Exception):
    """CCCD đã thuộc về khách hàng khác, hoặc không được đổi nữa."""


class IncompleteApplication(Exception):
    def __init__(self, missing: list[str]) -> None:
        super().__init__(missing)
        self.missing = missing


@dataclass(frozen=True)
class LoanTerms:
    requested_amount: Decimal
    term_months: int
    purpose: str


@dataclass(frozen=True)
class DraftChanges:
    """Các trường người dùng được sửa ở bước 1 và 2; None là không đổi."""

    requested_amount: Decimal | None = None
    term_months: int | None = None
    purpose: str | None = None
    national_id: str | None = None
    occupation: str | None = None
    employer: str | None = None
    employment_years: int | None = None
    monthly_income: Decimal | None = None
    existing_monthly_debt: Decimal | None = None
    housing_type: str | None = None
    address: str | None = None
    receiving_account: str | None = None


@dataclass(frozen=True)
class DocumentReview:
    verdict: str
    note: str | None


@dataclass(frozen=True)
class DocumentView:
    id: uuid.UUID
    doc_type: str
    content_type: str
    size_bytes: int
    sha256: str
    uploaded_at: datetime
    review: DocumentReview | None


@dataclass(frozen=True)
class ApplicantView:
    full_name: str
    national_id: str | None  # đã che
    occupation: str | None
    employer: str | None
    employment_years: int | None
    monthly_income: Decimal | None
    housing_type: str | None
    address: str | None


@dataclass(frozen=True)
class StatusChange:
    status: str
    at: datetime


@dataclass(frozen=True)
class NeedInfoView:
    message: str
    items: list[str]
    deadline: datetime


@dataclass(frozen=True)
class ApplicationView:
    id: uuid.UUID
    code: str | None
    customer_id: uuid.UUID
    status: str
    requested_amount: Decimal
    term_months: int
    purpose: str
    estimated_monthly_payment: Decimal
    existing_monthly_debt: Decimal | None
    receiving_account: str | None  # đã che
    applicant: ApplicantView
    documents: list[DocumentView]
    history: list[StatusChange]
    need_info: NeedInfoView | None
    created_by: uuid.UUID | None
    received_by: uuid.UUID | None
    appraised_by: uuid.UUID | None
    created_at: datetime
    submitted_at: datetime | None


@dataclass(frozen=True)
class ApplicationSummary:
    id: uuid.UUID
    code: str | None
    customer_id: uuid.UUID
    customer_name: str
    status: str
    requested_amount: Decimal
    term_months: int
    created_at: datetime
    submitted_at: datetime | None


def has_unfinished_business(db: Session, customer_id: uuid.UUID) -> bool:
    """BR02: Khách hàng đang có Hồ sơ vay đang xử lý hoặc Khoản vay chưa tất toán."""
    application = db.scalars(
        select(LoanApplication.id)
        .where(LoanApplication.customer_id == customer_id)
        .where(LoanApplication.status.in_(IN_PROGRESS))
    ).first()
    loan = db.scalars(
        select(Loan.id).where(Loan.customer_id == customer_id).where(Loan.status.in_(UNSETTLED))
    ).first()
    return application is not None or loan is not None


def _account_context(application_id: uuid.UUID) -> str:
    return f"loan_applications.receiving_account:{application_id}"


class ApplicationService:
    def __init__(
        self, db: Session, clock: Clock, settings: Settings, sms: SmsGateway, ip: str | None
    ) -> None:
        self._db = db
        self._clock = clock
        self._settings = settings
        self._cipher = FieldCipher(settings.data_enc_key)
        self._audit = AuditService(db, clock)
        self._notifications = NotificationService(db, clock, sms)
        self._ip = ip

    # --- UC12 ---------------------------------------------------------------------------------

    def create(self, user: CurrentUser, terms: LoanTerms) -> ApplicationView:
        if user.customer_id is None:
            raise CustomerNotFound
        return self.create_for(user, user.customer_id, terms)

    def create_for(
        self, user: CurrentUser, customer_id: uuid.UUID, terms: LoanTerms
    ) -> ApplicationView:
        """Khách hàng tự lập, hoặc NV tín dụng lập hộ (UC12 1a: ghi nhận Người tạo)."""
        # Khóa dòng khách hàng đến hết giao dịch: hai yêu cầu tạo song song không cùng lọt BR02.
        # Dialect SQL Server bỏ qua with_for_update(), nên phải ghi rõ table hint.
        customer = self._db.scalars(
            select(Customer)
            .with_hint(Customer, "WITH (UPDLOCK, ROWLOCK)", "mssql")
            .where(Customer.id == customer_id)
            .execution_options(populate_existing=True)
        ).one_or_none()
        if customer is None:
            raise CustomerNotFound
        if has_unfinished_business(self._db, customer.id):
            raise ApplicationInProgress
        now = self._clock.now()
        application = LoanApplication(
            id=uuid.uuid4(),
            customer_id=customer.id,
            requested_amount=terms.requested_amount,
            term_months=terms.term_months,
            purpose=terms.purpose,
            status=ApplicationStatus.DRAFT,
            created_by=user.employee_id,
            created_at=now,
        )
        self._db.add(application)
        self._db.flush()  # không có relationship: phải ghi hồ sơ vay trước dòng lịch sử
        self._db.add(
            ApplicationStatusHistory(
                application_id=application.id,
                status=ApplicationStatus.DRAFT,
                actor_id=user.user_id,
                changed_at=now,
            )
        )
        self._db.flush()
        self.log("APPLICATION_CREATE", user, application.id)
        self.commit()
        return self.view(application, user)

    def update_draft(
        self, user: CurrentUser, application_id: uuid.UUID, changes: DraftChanges
    ) -> ApplicationView:
        application = self.editable(user, application_id)
        self._ensure_requested(
            application, {k for k, v in vars(changes).items() if v is not None}
        )
        customer = self._db.get_one(Customer, application.customer_id)
        if changes.requested_amount is not None:
            application.requested_amount = changes.requested_amount
        if changes.term_months is not None:
            application.term_months = changes.term_months
        if changes.purpose is not None:
            application.purpose = changes.purpose
        if changes.existing_monthly_debt is not None:
            application.existing_monthly_debt = changes.existing_monthly_debt
        if changes.receiving_account is not None:
            application.receiving_account_enc = self._cipher.encrypt(
                changes.receiving_account, context=_account_context(application.id)
            )
        if changes.national_id is not None:
            self._set_national_id(customer, changes.national_id)
        # Thông tin tài chính thuộc về Khách hàng, tồn tại độc lập với Hồ sơ vay (CONTEXT.md).
        for field in ("occupation", "employer", "employment_years", "housing_type", "address"):
            value = getattr(changes, field)
            if value is not None:
                setattr(customer, field, value)
        if changes.monthly_income is not None:
            customer.monthly_income_enc = self._cipher.encrypt(
                str(changes.monthly_income), context=income_context(customer.id)
            )
        self.log("APPLICATION_UPDATE", user, application.id)
        try:
            self.commit()
        except IntegrityError as exc:
            # Blind index trùng khi hai khách hàng khai cùng một CCCD cùng lúc.
            self._db.rollback()
            raise NationalIdConflict from exc
        return self.view(application, user)

    def _set_national_id(self, customer: Customer, national_id: str) -> None:
        digest = blind_index(self._settings.blind_index_key, national_id)
        if digest == customer.national_id_hash:
            return
        # CCCD đã nằm trong một Hồ sơ vay đã nộp thì không đổi được nữa.
        submitted = self._db.scalars(
            select(LoanApplication.id)
            .where(LoanApplication.customer_id == customer.id)
            .where(LoanApplication.submitted_at.is_not(None))
        ).first()
        owner = self._db.scalars(
            select(Customer.id).where(Customer.national_id_hash == digest)
        ).first()
        if submitted is not None or owner is not None:
            raise NationalIdConflict
        customer.national_id_hash = digest
        customer.national_id_enc = self._cipher.encrypt(
            national_id, context=national_id_context(customer.id)
        )

    def submit(self, user: CurrentUser, application_id: uuid.UUID) -> ApplicationView:
        """Khách hàng tự nộp (hoặc gửi lại sau khi bổ sung), đã tích đồng ý điều khoản."""
        application = self.editable(user, application_id)
        self.ensure_complete(application)
        return self.record_submission(user, application)

    def ensure_complete(self, application: LoanApplication) -> None:
        customer = self._db.get_one(Customer, application.customer_id)
        filled = {
            "national_id": customer.national_id_enc,
            "occupation": customer.occupation,
            "employment_years": customer.employment_years,
            "monthly_income": customer.monthly_income_enc,
            "existing_monthly_debt": application.existing_monthly_debt,
            "housing_type": customer.housing_type,
            "address": customer.address,
            "receiving_account": application.receiving_account_enc,
        }
        missing = missing_for_submission(
            [name for name, value in filled.items() if value is not None],
            [d.doc_type for d in self._documents(application.id)],
        )
        if missing:
            raise IncompleteApplication(missing)

    def record_submission(
        self, user: CurrentUser, application: LoanApplication
    ) -> ApplicationView:
        """Chuyển sang Đã nộp; người gọi đã kiểm tra đủ dữ liệu và sự đồng ý của khách hàng."""
        now = self._clock.now()
        first_time = application.code is None
        if first_time:
            sequence: int = self._db.execute(
                text("SELECT NEXT VALUE FOR loan_application_code_seq")
            ).scalar_one()
            application.code = application_code(now.year, sequence)
            application.submitted_at = now
        # SR14: ghi nhận sự đồng ý xử lý dữ liệu cá nhân gắn với chính Hồ sơ vay này.
        application.consent_at = now
        application.consent_version = self._settings.data_processing_terms_version
        if application.status == ApplicationStatus.NEED_INFO:
            # Dữ liệu khai báo vừa đổi: NV phải đối chiếu lại mọi giấy tờ (UC14 bước 3).
            self._db.execute(
                update(ApplicationDocument)
                .where(ApplicationDocument.application_id == application.id)
                .values(review_verdict=None, review_note=None, reviewed_by=None, reviewed_at=None)
            )
        application.need_info_message = None
        application.need_info_items = None
        application.need_info_deadline = None
        self.transition(application, ApplicationStatus.SUBMITTED, user.user_id)
        self.log("APPLICATION_SUBMIT", user, application.id)
        message = f"Hồ sơ vay {application.code} " + (
            "vừa được nộp, đang chờ tiếp nhận." if first_time else "đã được bổ sung, cần kiểm tra lại."
        )
        # Hồ sơ vay gửi lại sau khi bổ sung trở về đúng NV đã tiếp nhận (UC15 bước 5).
        self._notifications.notify_credit_officer(
            application.received_by,
            employee_type="APPLICATION_RESUBMITTED",
            role_type="APPLICATION_SUBMITTED",
            content=message,
        )
        self.commit()
        return self.view(application, user)

    # --- UC17 ---------------------------------------------------------------------------------

    def cancel(
        self, user: CurrentUser, application_id: uuid.UUID, reason: str | None
    ) -> ApplicationView:
        application = self.load(user, application_id, lock=True)
        if application.status not in CUSTOMER_CANCELLABLE:
            raise NotEditable  # 1b: đã qua bước kiểm tra, liên hệ NV tín dụng
        application.cancel_reason = reason
        self.transition(application, ApplicationStatus.CANCELLED, user.user_id, reason)
        self.log("APPLICATION_CANCEL", user, application.id)
        self.commit()
        return self.view(application, user)

    # --- Ticket #11: Kiểm soát viên hủy hồ sơ vay bị khóa sau điều tra -------------------------

    def resolve_lock(
        self, user: CurrentUser, application_id: uuid.UUID, reason: str
    ) -> ApplicationView:
        """CONTEXT.md (Kiểm soát viên): ngoại lệ có chủ đích duy nhất, sau khi điều tra xong.

        Hồ sơ vay bị khóa không bao giờ được giải ngân (CONTEXT.md); lối ra duy nhất là hủy, bắt
        buộc lý do (`APPLICATION_LOCK_RESOLVE`, docs/de-cuong-thay-doi.md 3.4a).
        """
        application = self.load(user, application_id, lock=True)
        if application.status != ApplicationStatus.LOCKED:
            raise NotLocked
        application.cancel_reason = reason
        self.transition(application, ApplicationStatus.CANCELLED, user.user_id, reason)
        self.log("APPLICATION_LOCK_RESOLVE", user, application.id)
        self.commit()
        return self.view(application, user)

    # --- UC13 ---------------------------------------------------------------------------------

    def upload_document(
        self,
        user: CurrentUser,
        application_id: uuid.UUID,
        doc_type: str,
        filename: str,
        content: bytes,
    ) -> DocumentView:
        application = self.editable(user, application_id)
        self._ensure_requested(application, {doc_type})
        content_type = check_document(filename, content)
        uploaded = self._db.scalar(
            select(func.count())
            .select_from(ApplicationDocument)
            .where(ApplicationDocument.application_id == application.id)
        )
        if (uploaded or 0) >= MAX_DOCUMENTS_PER_APPLICATION:
            raise TooManyDocuments
        now = self._clock.now()
        # Tên file ngẫu nhiên, lưu ngoài thư mục web; tên file người dùng gửi không được dùng.
        relative = f"{application.id}/{uuid.uuid4().hex}{_EXTENSIONS[content_type]}"
        # UC13 2a: file cũ cùng loại được đánh dấu thay thế, không xóa.
        self._db.execute(
            update(ApplicationDocument)
            .where(ApplicationDocument.application_id == application.id)
            .where(ApplicationDocument.doc_type == doc_type)
            .where(ApplicationDocument.replaced_at.is_(None))
            .values(replaced_at=now)
        )
        document = ApplicationDocument(
            application_id=application.id,
            doc_type=doc_type,
            storage_path=relative,
            content_type=content_type,
            size_bytes=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            uploaded_by=user.user_id,
            uploaded_at=now,
        )
        self._db.add(document)
        self._db.flush()
        self.log("DOCUMENT_UPLOAD", user, application.id)
        target = self._settings.document_storage_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        try:
            self.commit()
        except Exception:
            target.unlink(missing_ok=True)  # không để lại file mồ côi khi giao dịch thất bại
            raise
        return self._document_view(document)

    # --- UC16 và hàng đợi công việc -------------------------------------------------------------

    def get(self, user: CurrentUser, application_id: uuid.UUID) -> ApplicationView:
        return self.view(self.load(user, application_id), user)

    def list_visible(
        self, user: CurrentUser, status: str | None, search: str | None = None
    ) -> list[ApplicationSummary]:
        """`search`: một phần mã hồ sơ vay hoặc họ tên khách hàng (M05), lọc trước giới hạn số dòng."""
        query = select(LoanApplication, Customer.full_name).join(
            Customer, Customer.id == LoanApplication.customer_id
        )
        if user.customer_id is not None:
            query = query.where(LoanApplication.customer_id == user.customer_id).order_by(
                LoanApplication.created_at.desc()
            )
        else:
            # Hàng đợi công việc (M05): hồ sơ vay cũ nhất lên trước.
            query = (
                query.where(self._staff_scope(user))
                .order_by(LoanApplication.submitted_at, LoanApplication.created_at)
                .limit(STAFF_LIST_LIMIT)
            )
        if status is not None:
            query = query.where(LoanApplication.status == status)
        if search:
            query = query.where(or_(
                LoanApplication.code.contains(search, autoescape=True),
                Customer.full_name.contains(search, autoescape=True),
            ))
        return [
            ApplicationSummary(
                id=a.id,
                code=a.code,
                customer_id=a.customer_id,
                customer_name=full_name,
                status=a.status,
                requested_amount=a.requested_amount,
                term_months=a.term_months,
                created_at=a.created_at,
                submitted_at=a.submitted_at,
            )
            for a, full_name in self._db.execute(query).all()
        ]

    # --- Dùng chung cho các dịch vụ xử lý hồ sơ vay ---------------------------------------------

    def load(
        self,
        user: CurrentUser,
        application_id: uuid.UUID,
        *,
        edit: bool = False,
        lock: bool = False,
    ) -> LoanApplication:
        """Hồ sơ vay trong phạm vi của người gọi, hoặc ApplicationNotFound (ghi ACCESS_DENIED)."""
        query = select(LoanApplication).where(LoanApplication.id == application_id)
        if user.customer_id is not None:
            query = query.where(LoanApplication.customer_id == user.customer_id)
        elif edit:
            query = query.where(LoanApplication.created_by == user.employee_id)
        else:
            query = query.where(self._staff_scope(user))
        if lock:
            # Khóa dòng đến hết giao dịch: các thao tác trên cùng hồ sơ vay chạy tuần tự, ví dụ
            # không thể gắn thêm file vào hồ sơ vay vừa được nộp.
            query = query.with_hint(LoanApplication, "WITH (UPDLOCK, ROWLOCK)", "mssql")
        application = self._db.scalars(
            query.execution_options(populate_existing=True)
        ).one_or_none()
        if application is None:
            self._audit.log(
                "ACCESS_DENIED", actor_id=user.user_id, target_type="LOAN_APPLICATION",
                target_id=application_id, ip_address=self._ip, level="WARNING",
            )
            self._db.commit()
            raise ApplicationNotFound
        return application

    @staticmethod
    def _staff_scope(user: CurrentUser) -> ColumnElement[bool]:
        # Nhân viên không thấy bản nháp của khách hàng, chỉ thấy bản nháp mình nộp hộ.
        return or_(
            LoanApplication.status != ApplicationStatus.DRAFT,
            LoanApplication.created_by == user.employee_id,
        )

    def transition(
        self,
        application: LoanApplication,
        target: ApplicationStatus,
        actor_id: uuid.UUID | None,
        reason: str | None = None,
    ) -> None:
        """Đổi trạng thái theo bảng chuyển trạng thái (3.4a) và ghi dòng thời gian."""
        ensure_transition(application.status, target)
        application.status = target
        self._db.add(
            ApplicationStatusHistory(
                application_id=application.id,
                status=target,
                actor_id=actor_id,
                reason=reason,
                changed_at=self._clock.now(),
            )
        )

    def view(self, application: LoanApplication, viewer: CurrentUser) -> ApplicationView:
        """Thông tin hồ sơ vay theo góc nhìn của người xem (SR07).

        Khách hàng thấy thu nhập của chính mình nhưng không thấy mã nhân viên xử lý; nhân viên
        không có CUSTOMER_VIEW_PII chỉ thấy dữ liệu đã che (ô "M" trong ma trận RBAC), còn xem đầy
        đủ có ghi nhật ký VIEW_PII làm ở màn hình thẩm định.
        """
        is_customer = viewer.customer_id is not None
        customer = self._db.get_one(Customer, application.customer_id)
        account = self._decrypt(application.receiving_account_enc, _account_context(application.id))
        national_id = self._decrypt(customer.national_id_enc, national_id_context(customer.id))
        income = self._decrypt(customer.monthly_income_enc, income_context(customer.id))
        history = self._db.scalars(
            select(ApplicationStatusHistory)
            .where(ApplicationStatusHistory.application_id == application.id)
            .order_by(ApplicationStatusHistory.changed_at, ApplicationStatusHistory.id)
        ).all()
        need_info = (
            NeedInfoView(
                message=application.need_info_message or "",
                items=[i for i in (application.need_info_items or "").split(",") if i],
                deadline=application.need_info_deadline,
            )
            if application.status == ApplicationStatus.NEED_INFO
            and application.need_info_deadline is not None
            else None
        )
        return ApplicationView(
            id=application.id,
            code=application.code,
            customer_id=application.customer_id,
            status=application.status,
            requested_amount=application.requested_amount,
            term_months=application.term_months,
            purpose=application.purpose,
            estimated_monthly_payment=annuity_payment(
                application.requested_amount, CEILING_RATE, application.term_months
            ),
            existing_monthly_debt=application.existing_monthly_debt,
            receiving_account=mask(account) if account else None,
            applicant=ApplicantView(
                full_name=customer.full_name,
                national_id=mask(national_id) if national_id else None,
                occupation=customer.occupation,
                employer=customer.employer,
                employment_years=customer.employment_years,
                monthly_income=Decimal(income) if income and is_customer else None,
                housing_type=customer.housing_type,
                address=customer.address,
            ),
            documents=[self._document_view(d) for d in self._documents(application.id)],
            history=[StatusChange(h.status, h.changed_at) for h in history],
            need_info=need_info,
            created_by=None if is_customer else application.created_by,
            received_by=None if is_customer else application.received_by,
            appraised_by=None if is_customer else application.appraised_by,
            created_at=application.created_at,
            submitted_at=application.submitted_at,
        )

    def ensure_editable(self, application: LoanApplication) -> None:
        if application.status not in EDITABLE:
            raise NotEditable
        if (
            application.status == ApplicationStatus.NEED_INFO
            and application.need_info_deadline is not None
            and self._clock.now() > application.need_info_deadline
        ):
            raise NeedInfoExpired

    def editable(self, user: CurrentUser, application_id: uuid.UUID) -> LoanApplication:
        """Hồ sơ vay người gọi được sửa (chủ hồ sơ hoặc Người tạo), đã khóa dòng."""
        application = self.load(user, application_id, edit=True, lock=True)
        self.ensure_editable(application)
        return application

    def terms_fingerprint(self, application: LoanApplication) -> str:
        """Dấu vân tay của khoản vay khách hàng đồng ý: đổi số tiền, kỳ hạn, mục đích hay tài
        khoản nhận thì sự đồng ý cũ không còn giá trị (UC12 1a)."""
        account = self._decrypt(application.receiving_account_enc, _account_context(application.id))
        material = f"{application.requested_amount}|{application.term_months}|{application.purpose}|{account}"
        return hashlib.sha256(material.encode()).hexdigest()

    def national_id_of(self, customer: Customer) -> str:
        """Số CCCD dạng rõ, chỉ dùng trong bộ nhớ (UC19 bước 1)."""
        return self._decrypt(customer.national_id_enc, national_id_context(customer.id)) or ""

    def monthly_income_of(self, customer: Customer) -> Decimal:
        income = self._decrypt(customer.monthly_income_enc, income_context(customer.id))
        return Decimal(income or 0)

    def receiving_account_of(self, application: LoanApplication) -> str:
        """Số tài khoản nhận dạng rõ, chỉ dùng trong bộ nhớ (snapshot phê duyệt, SUC02 bước 1)."""
        return self._decrypt(
            application.receiving_account_enc, _account_context(application.id)
        ) or ""

    def receiving_account_masked(self, application: LoanApplication) -> str:
        account = self.receiving_account_of(application)
        return mask(account) if account else ""

    def active_documents(self, application_id: uuid.UUID) -> list[ApplicationDocument]:
        return self._documents(application_id)

    # --- Nội bộ -------------------------------------------------------------------------------

    @staticmethod
    def _ensure_requested(application: LoanApplication, changed: set[str]) -> None:
        if application.status != ApplicationStatus.NEED_INFO:
            return
        requested = set((application.need_info_items or "").split(","))
        if outside_request(changed, requested):
            raise NotRequested

    def _documents(self, application_id: uuid.UUID) -> list[ApplicationDocument]:
        return list(
            self._db.scalars(
                select(ApplicationDocument)
                .where(ApplicationDocument.application_id == application_id)
                .where(ApplicationDocument.replaced_at.is_(None))
                .order_by(ApplicationDocument.uploaded_at, ApplicationDocument.doc_type)
            )
        )

    def _decrypt(self, sealed: bytes | None, context: str) -> str | None:
        return self._cipher.decrypt(sealed, context=context) if sealed else None

    def commit(self) -> None:
        """Commit; khóa lạc quan phát hiện ghi đè thì báo ConcurrentModification (409)."""
        try:
            self._db.commit()
        except StaleDataError as exc:
            self._db.rollback()
            raise ConcurrentModification from exc

    def log(self, action: str, user: CurrentUser, application_id: uuid.UUID) -> None:
        self._audit.log(action, actor_id=user.user_id, target_type="LOAN_APPLICATION",
                        target_id=application_id, ip_address=self._ip)

    @staticmethod
    def _document_view(document: ApplicationDocument) -> DocumentView:
        return DocumentView(
            id=document.id,
            doc_type=document.doc_type,
            content_type=document.content_type,
            size_bytes=document.size_bytes,
            sha256=document.sha256,
            uploaded_at=document.uploaded_at,
            review=(
                DocumentReview(document.review_verdict, document.review_note)
                if document.review_verdict
                else None
            ),
        )
