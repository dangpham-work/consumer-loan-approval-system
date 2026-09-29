"""Thử thách OTP qua SMS: khách hàng xác nhận một thao tác do nhân viên khởi tạo (UC12 1a).

Mã hết hạn sau 5 phút, sai 3 lần thì hủy (giống UC09), chỉ dùng được một lần và chỉ người đã
khởi tạo mới xác nhận được. Dữ liệu chờ xác nhận được mã hóa (SR06) và bị xóa khi thử thách kết
thúc. `fingerprint` gắn sự đồng ý với đúng nội dung khách hàng đã thấy trong SMS: nội dung đổi sau
khi gửi mã thì mã không còn dùng được.
"""

import json
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import update
from sqlalchemy.orm import Session

from loan_system.adapters.sms import SmsGateway
from loan_system.clock import Clock
from loan_system.config import Settings
from loan_system.repositories.models import OtpChallenge
from loan_system.security.crypto import FieldCipher
from loan_system.security.secrets import keyed_hash, matches, new_otp
from loan_system.services.audit_service import AuditService


class ChallengeFailed(Exception):
    """Mã sai, hết hạn hoặc không tồn tại; thông điệp an toàn để hiển thị."""


@dataclass(frozen=True)
class IssuedChallenge:
    id: uuid.UUID
    phone: str
    message: str  # đã chứa mã OTP; chỉ gửi qua SMS, không lưu, không trả về API


def _payload_context(challenge_id: uuid.UUID) -> str:
    return f"otp_challenges.payload:{challenge_id}"


class OtpChallenges:
    def __init__(
        self, db: Session, clock: Clock, sms: SmsGateway, settings: Settings, ip: str | None
    ) -> None:
        self._db = db
        self._clock = clock
        self._sms = sms
        self._settings = settings
        self._cipher = FieldCipher(settings.data_enc_key)
        self._audit = AuditService(db, clock)
        self._ip = ip

    def start(
        self,
        purpose: str,
        phone: str,
        message: str,
        *,
        created_by: uuid.UUID,
        subject_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> IssuedChallenge:
        """Tạo thử thách; `message` chứa `{otp}` ở vị trí mã. Người gọi commit rồi `deliver`."""
        otp = new_otp()
        now = self._clock.now()
        challenge = OtpChallenge(
            id=uuid.uuid4(),
            purpose=purpose,
            phone=phone,
            subject_id=subject_id,
            otp_hash=keyed_hash(self._settings.session_secret, otp),
            expires_at=now + timedelta(minutes=self._settings.otp_ttl_minutes),
            failed_attempts=0,
            created_by=created_by,
            created_at=now,
        )
        if payload is not None:
            challenge.payload_enc = self._cipher.encrypt(
                json.dumps(payload, ensure_ascii=False), context=_payload_context(challenge.id)
            )
        self._db.add(challenge)
        self._db.flush()
        self._audit.log(
            "OTP_CHALLENGE_SENT", actor_id=created_by, target_type="OTP_CHALLENGE",
            target_id=challenge.id, ip_address=self._ip, detail=purpose,
        )
        return IssuedChallenge(challenge.id, phone, message.format(otp=otp))

    def deliver(self, issued: IssuedChallenge) -> None:
        """Gửi SMS sau khi giao dịch đã commit, để không báo mã cho một thử thách không tồn tại."""
        self._sms.send(issued.phone, issued.message)

    def confirm(
        self,
        challenge_id: uuid.UUID,
        purpose: str,
        otp: str,
        *,
        confirmed_by: uuid.UUID,
        subject_id: str | None = None,
    ) -> dict[str, Any]:
        """Trả về payload khi mã đúng; đánh dấu đã dùng (người gọi commit)."""
        challenge = self._db.get(OtpChallenge, challenge_id)
        if (
            challenge is None
            or challenge.purpose != purpose
            or challenge.created_by != confirmed_by
            or challenge.subject_id != subject_id
            or challenge.consumed_at is not None
        ):
            raise ChallengeFailed("Yêu cầu xác nhận không tồn tại hoặc đã được dùng.")
        now = self._clock.now()
        if now > challenge.expires_at:
            self._close(challenge)
            self._db.commit()
            raise ChallengeFailed("Mã OTP đã hết hạn.")
        if not matches(self._settings.session_secret, otp, challenge.otp_hash):
            attempts = self._db.execute(
                update(OtpChallenge)
                .where(OtpChallenge.id == challenge.id)
                .values(failed_attempts=OtpChallenge.failed_attempts + 1)
                .returning(OtpChallenge.failed_attempts)
            ).scalar_one()
            self._audit.log(
                "OTP_FAIL", actor_id=confirmed_by, target_type="OTP_CHALLENGE",
                target_id=challenge.id, ip_address=self._ip, level="WARNING", detail=purpose,
            )
            if attempts >= self._settings.otp_max_attempts:
                self._close(challenge)
                self._db.commit()
                raise ChallengeFailed("Nhập sai OTP quá số lần cho phép. Yêu cầu đã bị hủy.")
            self._db.commit()
            raise ChallengeFailed("Mã OTP không đúng.")
        sealed = challenge.payload_enc  # đọc trước khi câu UPDATE dưới đây xóa nó
        # Cập nhật có điều kiện: hai yêu cầu xác nhận song song thì chỉ một yêu cầu thắng.
        consumed = self._db.execute(
            update(OtpChallenge)
            .where(OtpChallenge.id == challenge.id)
            .where(OtpChallenge.consumed_at.is_(None))
            .values(consumed_at=now, payload_enc=None)
            .returning(OtpChallenge.id)
        ).first()
        if consumed is None:
            raise ChallengeFailed("Yêu cầu xác nhận không tồn tại hoặc đã được dùng.")
        if sealed is None:
            return {}
        payload: dict[str, Any] = json.loads(
            self._cipher.decrypt(sealed, context=_payload_context(challenge.id))
        )
        return payload

    def _close(self, challenge: OtpChallenge) -> None:
        challenge.consumed_at = self._clock.now()
        challenge.payload_enc = None
