"""Snapshot hồ sơ vay khi được duyệt (SR08): ký lúc phê duyệt (UC23 bước 6), đối chiếu trước giải
ngân (SUC02). Cả hai đều dựng snapshot từ chính các cột của hồ sơ vay, nên mọi thay đổi trên các
cột đó sau khi duyệt, kể cả sửa thẳng trong CSDL, đều làm snapshot không khớp (ST04)."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from loan_system.config import Settings
from loan_system.domain.approval import ApprovalSnapshot
from loan_system.repositories.models import ApprovalDecision, LoanApplication
from loan_system.security.crypto import DecryptionFailed
from loan_system.security.integrity import IntegrityKeyring, Signature, UnknownKeyVersion
from loan_system.services.application_service import ApplicationService


class IntegrityKeyMissing(Exception):
    """Snapshot được ký bằng phiên bản khóa không còn trong cấu hình: không kiểm tra được."""


def keyring_from(settings: Settings) -> IntegrityKeyring:
    """Khóa HMAC_INTEGRITY_KEY hiện hành cùng các khóa cũ còn giữ để kiểm tra (4.2.5)."""
    keys = {**settings.hmac_integrity_old_keys}
    keys[settings.hmac_integrity_key_version] = settings.hmac_integrity_key
    return IntegrityKeyring(keys, current=settings.hmac_integrity_key_version)


class IntegrityService:
    def __init__(self, db: Session, settings: Settings, applications: ApplicationService) -> None:
        self._db = db
        self._keyring = keyring_from(settings)
        self._applications = applications

    def sign(self, application: LoanApplication) -> Signature:
        """Ký snapshot; hạn mức, kỳ hạn được duyệt phải đã chốt vào hồ sơ vay."""
        snapshot = self._snapshot(application)
        assert snapshot is not None
        return self._keyring.sign(snapshot.canonical())

    def verify(self, application: LoanApplication) -> bool:
        """SUC02: tính lại HMAC với cùng phiên bản khóa, so sánh thời gian hằng với mã băm lưu trên
        quyết định làm hồ sơ vay được duyệt. Thiếu mã băm hay thiếu trường cũng là không khớp."""
        decision = self.approving_decision(application)
        snapshot = self._snapshot(application)
        if decision is None or snapshot is None:
            return False
        assert decision.snapshot_hash is not None and decision.key_version is not None
        try:
            return self._keyring.verify(
                snapshot.canonical(), Signature(decision.key_version, decision.snapshot_hash)
            )
        except UnknownKeyVersion as exc:
            raise IntegrityKeyMissing from exc

    def approving_decision(self, application: LoanApplication) -> ApprovalDecision | None:
        """Quyết định làm hồ sơ vay được duyệt: quyết định mang mã băm snapshot."""
        return self._db.scalars(
            select(ApprovalDecision)
            .where(ApprovalDecision.application_id == application.id)
            .where(ApprovalDecision.snapshot_hash.is_not(None))
            .order_by(ApprovalDecision.decided_at.desc())
        ).first()

    def _snapshot(self, application: LoanApplication) -> ApprovalSnapshot | None:
        try:
            account = self._applications.receiving_account_of(application)
        except DecryptionFailed:  # bản mã bị sửa hoặc chép từ hồ sơ vay khác
            return None
        if (
            application.code is None
            or application.approved_amount is None
            or application.approved_term is None
            or application.annual_rate is None
            or not account
        ):
            return None
        return ApprovalSnapshot(
            application_id=application.id,
            code=application.code,
            requested_amount=application.requested_amount,
            approved_amount=application.approved_amount,
            approved_term=application.approved_term,
            annual_rate=application.annual_rate,
            receiving_account=account,
        )
