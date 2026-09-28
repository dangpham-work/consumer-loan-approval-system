"""UC12 Tạo và nộp hồ sơ vay, UC13 Tải lên giấy tờ, UC16 Theo dõi trạng thái (phía khách hàng).

Mọi truy cập đi qua `_owned`: khách hàng chỉ thấy Hồ sơ vay của chính mình (SR04). Hồ sơ vay của
người khác được báo như không tồn tại, để không xác nhận được sự tồn tại của nó (4.2.4, ST01).
"""

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from loan_system.clock import Clock
from loan_system.config import Settings
from loan_system.domain.applications import (
    CEILING_RATE,
    IN_PROGRESS,
    MAX_DOCUMENTS_PER_APPLICATION,
    ApplicationStatus,
    application_code,
    mask,
    missing_for_submission,
)
from loan_system.domain.calculations import annuity_payment
from loan_system.domain.documents import check_document
from loan_system.repositories.models import ApplicationDocument, Customer, LoanApplication
from loan_system.security.crypto import FieldCipher, blind_index
from loan_system.services.audit_service import AuditService
from loan_system.services.auth_service import CurrentUser

_EXTENSIONS = {"image/jpeg": ".jpg", "image/png": ".png", "application/pdf": ".pdf"}


class ApplicationNotFound(Exception):
    """Không tồn tại hoặc không thuộc về người gọi."""


class ApplicationInProgress(Exception):
    """Khách hàng đã có một Hồ sơ vay đang xử lý (BR02)."""


class NotEditable(Exception):
    """Hồ sơ vay không còn ở trạng thái Nháp."""


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
class DocumentView:
    id: uuid.UUID
    doc_type: str
    content_type: str
    size_bytes: int
    sha256: str
    uploaded_at: datetime


@dataclass(frozen=True)
class ApplicantView:
    national_id: str | None  # đã che
    occupation: str | None
    employer: str | None
    employment_years: int | None
    monthly_income: Decimal | None
    housing_type: str | None
    address: str | None


@dataclass(frozen=True)
class ApplicationView:
    id: uuid.UUID
    code: str | None
    status: str
    requested_amount: Decimal
    term_months: int
    purpose: str
    estimated_monthly_payment: Decimal
    existing_monthly_debt: Decimal | None
    receiving_account: str | None  # đã che
    applicant: ApplicantView
    documents: list[DocumentView]
    created_at: datetime
    submitted_at: datetime | None


@dataclass(frozen=True)
class ApplicationSummary:
    id: uuid.UUID
    code: str | None
    status: str
    requested_amount: Decimal
    term_months: int
    created_at: datetime
    submitted_at: datetime | None


def _national_id_context(customer_id: uuid.UUID) -> str:
    return f"customers.national_id:{customer_id}"


def _income_context(customer_id: uuid.UUID) -> str:
    return f"customers.monthly_income:{customer_id}"


def _account_context(application_id: uuid.UUID) -> str:
    return f"loan_applications.receiving_account:{application_id}"


class ApplicationService:
    def __init__(self, db: Session, clock: Clock, settings: Settings, ip: str | None) -> None:
        self._db = db
        self._clock = clock
        self._settings = settings
        self._cipher = FieldCipher(settings.data_enc_key)
        self._audit = AuditService(db, clock)
        self._ip = ip

    # --- UC12 ---------------------------------------------------------------------------------

    def create(self, user: CurrentUser, terms: LoanTerms) -> ApplicationView:
        # Khóa dòng khách hàng đến hết giao dịch: hai yêu cầu tạo song song không cùng lọt BR02.
        # Dialect SQL Server bỏ qua with_for_update(), nên phải ghi rõ table hint.
        customer = self._db.scalars(
            select(Customer)
            .with_hint(Customer, "WITH (UPDLOCK, ROWLOCK)", "mssql")
            .where(Customer.id == user.customer_id)
            .execution_options(populate_existing=True)
        ).one()
        in_progress = self._db.scalars(
            select(LoanApplication.id)
            .where(LoanApplication.customer_id == customer.id)
            .where(LoanApplication.status.in_(IN_PROGRESS))
        ).first()
        if in_progress is not None:
            raise ApplicationInProgress
        application = LoanApplication(
            id=uuid.uuid4(),
            customer_id=customer.id,
            requested_amount=terms.requested_amount,
            term_months=terms.term_months,
            purpose=terms.purpose,
            status=ApplicationStatus.DRAFT,
            created_at=self._clock.now(),
        )
        self._db.add(application)
        self._db.flush()
        self._log("APPLICATION_CREATE", user, application.id)
        self._commit()
        return self._view(application, customer)

    def update_draft(
        self, user: CurrentUser, application_id: uuid.UUID, changes: DraftChanges
    ) -> ApplicationView:
        application = self._editable(user, application_id)
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
                str(changes.monthly_income), context=_income_context(customer.id)
            )
        self._log("APPLICATION_UPDATE", user, application.id)
        try:
            self._commit()
        except IntegrityError as exc:
            # Blind index trùng khi hai khách hàng khai cùng một CCCD cùng lúc.
            self._db.rollback()
            raise NationalIdConflict from exc
        return self._view(application, customer)

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
            national_id, context=_national_id_context(customer.id)
        )

    def submit(self, user: CurrentUser, application_id: uuid.UUID) -> ApplicationView:
        application = self._editable(user, application_id)
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
        now = self._clock.now()
        sequence: int = self._db.execute(
            text("SELECT NEXT VALUE FOR loan_application_code_seq")
        ).scalar_one()
        application.code = application_code(now.year, sequence)
        application.status = ApplicationStatus.SUBMITTED
        application.submitted_at = now
        # SR14: ghi nhận sự đồng ý xử lý dữ liệu cá nhân gắn với chính Hồ sơ vay này.
        application.consent_at = now
        application.consent_version = self._settings.data_processing_terms_version
        self._log("APPLICATION_SUBMIT", user, application.id)
        self._commit()
        return self._view(application, customer)

    # --- UC13 ---------------------------------------------------------------------------------

    def upload_document(
        self,
        user: CurrentUser,
        application_id: uuid.UUID,
        doc_type: str,
        filename: str,
        content: bytes,
    ) -> DocumentView:
        application = self._editable(user, application_id)
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
        self._log("DOCUMENT_UPLOAD", user, application.id)
        target = self._settings.document_storage_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        try:
            self._commit()
        except Exception:
            target.unlink(missing_ok=True)  # không để lại file mồ côi khi giao dịch thất bại
            raise
        return self._document_view(document)

    # --- UC16 ---------------------------------------------------------------------------------

    def get(self, user: CurrentUser, application_id: uuid.UUID) -> ApplicationView:
        application = self._owned(user, application_id)
        return self._view(application, self._db.get_one(Customer, application.customer_id))

    def list_mine(self, user: CurrentUser) -> list[ApplicationSummary]:
        applications = self._db.scalars(
            select(LoanApplication)
            .where(LoanApplication.customer_id == user.customer_id)
            .order_by(LoanApplication.created_at.desc())
        )
        return [
            ApplicationSummary(
                id=a.id,
                code=a.code,
                status=a.status,
                requested_amount=a.requested_amount,
                term_months=a.term_months,
                created_at=a.created_at,
                submitted_at=a.submitted_at,
            )
            for a in applications
        ]

    # --- Nội bộ -------------------------------------------------------------------------------

    def _owned(
        self, user: CurrentUser, application_id: uuid.UUID, *, lock: bool = False
    ) -> LoanApplication:
        query = select(LoanApplication)
        if lock:
            # Khóa dòng đến hết giao dịch: tải giấy tờ, sửa nháp và nộp hồ sơ vay chạy tuần tự,
            # không thể gắn thêm file vào hồ sơ vay vừa được nộp.
            query = query.with_hint(LoanApplication, "WITH (UPDLOCK, ROWLOCK)", "mssql")
        application = self._db.scalars(
            query.where(LoanApplication.id == application_id)
            .where(LoanApplication.customer_id == user.customer_id)
            .execution_options(populate_existing=True)
        ).one_or_none()
        if application is None:
            self._audit.log(
                "ACCESS_DENIED", actor_id=user.user_id, target_type="LOAN_APPLICATION",
                target_id=application_id, ip_address=self._ip, level="WARNING",
            )
            self._db.commit()
            raise ApplicationNotFound
        return application

    def _editable(self, user: CurrentUser, application_id: uuid.UUID) -> LoanApplication:
        application = self._owned(user, application_id, lock=True)
        if application.status != ApplicationStatus.DRAFT:
            raise NotEditable
        return application

    def _documents(self, application_id: uuid.UUID) -> list[ApplicationDocument]:
        return list(
            self._db.scalars(
                select(ApplicationDocument)
                .where(ApplicationDocument.application_id == application_id)
                .where(ApplicationDocument.replaced_at.is_(None))
                .order_by(ApplicationDocument.uploaded_at, ApplicationDocument.doc_type)
            )
        )

    def _commit(self) -> None:
        try:
            self._db.commit()
        except StaleDataError as exc:
            self._db.rollback()
            raise ConcurrentModification from exc

    def _log(self, action: str, user: CurrentUser, application_id: uuid.UUID) -> None:
        self._audit.log(action, actor_id=user.user_id, target_type="LOAN_APPLICATION",
                        target_id=application_id, ip_address=self._ip)

    def _view(self, application: LoanApplication, customer: Customer) -> ApplicationView:
        account = (
            self._cipher.decrypt(
                application.receiving_account_enc, context=_account_context(application.id)
            )
            if application.receiving_account_enc
            else None
        )
        national_id = (
            self._cipher.decrypt(customer.national_id_enc, context=_national_id_context(customer.id))
            if customer.national_id_enc
            else None
        )
        income = (
            Decimal(
                self._cipher.decrypt(
                    customer.monthly_income_enc, context=_income_context(customer.id)
                )
            )
            if customer.monthly_income_enc
            else None
        )
        return ApplicationView(
            id=application.id,
            code=application.code,
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
                national_id=mask(national_id) if national_id else None,
                occupation=customer.occupation,
                employer=customer.employer,
                employment_years=customer.employment_years,
                monthly_income=income,
                housing_type=customer.housing_type,
                address=customer.address,
            ),
            documents=[self._document_view(d) for d in self._documents(application.id)],
            created_at=application.created_at,
            submitted_at=application.submitted_at,
        )

    @staticmethod
    def _document_view(document: ApplicationDocument) -> DocumentView:
        return DocumentView(
            id=document.id,
            doc_type=document.doc_type,
            content_type=document.content_type,
            size_bytes=document.size_bytes,
            sha256=document.sha256,
            uploaded_at=document.uploaded_at,
        )
