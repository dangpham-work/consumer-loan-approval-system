"""Cổng gửi SMS. Hệ thống thật nằm ngoài phạm vi; bản giả lập lưu tin nhắn vào hộp thư ra."""

from dataclasses import dataclass, field
from typing import Protocol


class SmsGateway(Protocol):
    def send(self, phone: str, message: str) -> None: ...


@dataclass
class SentSms:
    phone: str
    message: str


@dataclass
class FakeSmsGateway:
    outbox: list[SentSms] = field(default_factory=list)

    def send(self, phone: str, message: str) -> None:
        self.outbox.append(SentSms(phone, message))

    def last_to(self, phone: str) -> SentSms:
        return next(sms for sms in reversed(self.outbox) if sms.phone == phone)
