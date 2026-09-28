"""Cổng gửi email công việc. Hệ thống thật nằm ngoài phạm vi; bản giả lập lưu thư vào hộp thư ra."""

from dataclasses import dataclass, field
from typing import Protocol


class EmailGateway(Protocol):
    def send(self, to: str, subject: str, body: str) -> None: ...


@dataclass
class SentEmail:
    to: str
    subject: str
    body: str


@dataclass
class FakeEmailGateway:
    outbox: list[SentEmail] = field(default_factory=list)

    def send(self, to: str, subject: str, body: str) -> None:
        self.outbox.append(SentEmail(to, subject, body))

    def last_to(self, to: str) -> SentEmail:
        return next(mail for mail in reversed(self.outbox) if mail.to == to)
