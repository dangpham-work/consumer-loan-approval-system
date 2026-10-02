"""Thông báo trong ứng dụng, kèm SMS (giả lập) khi cần báo ngay tới điện thoại khách hàng.

Nội dung thông báo không chứa CCCD, số tài khoản, thu nhập (SR07) và không chứa liên kết đăng
nhập, để không bị lợi dụng giả mạo lừa đảo (UC30).
"""

import uuid
from collections.abc import Collection

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from loan_system.adapters.sms import SmsGateway
from loan_system.clock import Clock
from loan_system.domain.access import CREDIT_OFFICER, AccountStatus
from loan_system.repositories.atomic import update_matched
from loan_system.repositories.models import Notification, Role, User, UserRole

MAX_LISTED = 50
SMS_ATTEMPTS = 3  # UC30 3a: gửi thất bại thì thử lại 2 lần


class NotificationService:
    """Chỉ thêm bản ghi vào phiên CSDL; người gọi commit cùng giao dịch nghiệp vụ rồi gọi
    `deliver()` để gửi SMS, để giao dịch thất bại thì khách hàng không nhận tin sai."""

    def __init__(self, db: Session, clock: Clock, sms: SmsGateway) -> None:
        self._db = db
        self._clock = clock
        self._sms = sms
        self._outbox: list[tuple[str, str]] = []

    def notify(
        self, user_id: uuid.UUID, type_: str, content: str, *, sms_phone: str | None = None
    ) -> None:
        self._db.add(
            Notification(
                recipient_user_id=user_id,
                type=type_,
                content=content,
                channel="IN_APP",
                is_read=False,
                created_at=self._clock.now(),
            )
        )
        if sms_phone:
            self._outbox.append((sms_phone, content))

    def notify_role(
        self, role_code: str, type_: str, content: str,
        *, except_employees: Collection[uuid.UUID | None] = (),
    ) -> None:
        recipients = self._db.execute(
            select(User.id, User.employee_id)
            .join(UserRole, UserRole.user_id == User.id)
            .join(Role, Role.id == UserRole.role_id)
            .where(Role.code == role_code)
            .where(User.status == AccountStatus.ACTIVE)
        ).all()
        for user_id, employee_id in recipients:
            if employee_id is None or employee_id not in except_employees:
                self.notify(user_id, type_, content)

    def notify_employee(self, employee_id: uuid.UUID, type_: str, content: str) -> None:
        user_id = self._db.scalars(select(User.id).where(User.employee_id == employee_id)).first()
        if user_id is not None:
            self.notify(user_id, type_, content)

    def notify_credit_officer(
        self, received_by: uuid.UUID | None, *, employee_type: str, role_type: str, content: str
    ) -> None:
        """Báo đúng NV tín dụng đã tiếp nhận hồ sơ vay, hoặc mọi NV tín dụng nếu chưa ai tiếp nhận
        (UC15 bước 5, ticket #11)."""
        if received_by is not None:
            self.notify_employee(received_by, employee_type, content)
        else:
            self.notify_role(CREDIT_OFFICER, role_type, content)

    def notify_customer(self, customer_id: uuid.UUID, type_: str, content: str, phone: str) -> None:
        """Khách vãng lai chưa có tài khoản đăng nhập được vẫn nhận SMS."""
        user_id = self._db.scalars(select(User.id).where(User.customer_id == customer_id)).first()
        if user_id is not None:
            self.notify(user_id, type_, content)
        self._outbox.append((phone, content))

    def deliver(self) -> int:
        """Gửi các SMS đã xếp hàng; gọi sau khi giao dịch đã commit. Mỗi tin thử lại 2 lần (UC30
        3a); tin vẫn lỗi thì bỏ qua để các tin sau vẫn được gửi. Trả về số tin gửi thất bại để
        người gọi ghi nhận (thông báo trong ứng dụng đã được lưu cùng giao dịch)."""
        failed = 0
        for phone, content in self._outbox:
            for attempt in range(SMS_ATTEMPTS):
                try:
                    self._sms.send(phone, content)
                    break
                except Exception:
                    if attempt == SMS_ATTEMPTS - 1:
                        failed += 1
        self._outbox.clear()
        return failed

    def list_for(self, user_id: uuid.UUID) -> list[Notification]:
        return list(
            self._db.scalars(
                select(Notification)
                .where(Notification.recipient_user_id == user_id)
                .order_by(Notification.created_at.desc())
                .limit(MAX_LISTED)
            )
        )

    def unread_count(self, user_id: uuid.UUID) -> int:
        return self._db.scalar(
            select(func.count())
            .select_from(Notification)
            .where(Notification.recipient_user_id == user_id)
            .where(Notification.is_read == False)
        ) or 0

    def mark_all_read(self, user_id: uuid.UUID) -> None:
        self._db.execute(
            update(Notification)
            .where(Notification.recipient_user_id == user_id)
            .where(Notification.is_read == False)
            .values(is_read=True)
        )
        self._db.commit()

    def mark_read(self, user_id: uuid.UUID, notification_id: uuid.UUID) -> bool:
        """Chỉ đánh dấu thông báo của chính người gọi (SR04)."""
        updated = update_matched(
            self._db,
            update(Notification)
            .where(Notification.id == notification_id)
            .where(Notification.recipient_user_id == user_id)
            .values(is_read=True),
        )
        self._db.commit()
        return updated
