"""Tiện ích dựng quy trình cho vay qua REST API: đội ngũ nhân viên, khách hàng, hồ sơ vay đã nộp."""

from dataclasses import dataclass, field
from functools import cached_property
from typing import Any

from fastapi.testclient import TestClient

from loan_system.adapters.email import FakeEmailGateway
from loan_system.adapters.sms import FakeSmsGateway
from tests.api.staff import Staff, bootstrap_admin, create_staff, login_with_otp, new_client
from tests.api.test_customer_registration import PASSWORD, register_and_verify
from tests.conftest import FakeClock

JPEG = b"\xff\xd8\xff\xe0" + b"\x01" * 2048
PNG = b"\x89PNG\r\n\x1a\n" + b"\x02" * 2048
PDF = b"%PDF-1.7\n" + b"\x03" * 2048

LOAN: dict[str, Any] = {"requested_amount": 30_000_000, "term_months": 12, "purpose": "CONSUMER_GOODS"}
FINANCES: dict[str, Any] = {
    "national_id": "079095001234",
    "occupation": "Kỹ sư phần mềm",
    "employer": "Công ty ABC",
    "employment_years": 4,
    "monthly_income": 25_000_000,
    "existing_monthly_debt": 2_000_000,
    "housing_type": "RENT",
    "address": "12 Lê Lợi, Quận 1, TP.HCM",
    "receiving_account": "0123456789",
}
DOCUMENTS: dict[str, tuple[str, bytes]] = {
    "ID_FRONT": ("cccd-truoc.jpg", JPEG),
    "ID_BACK": ("cccd-sau.png", PNG),
    "INCOME_PROOF": ("sao-ke-luong.pdf", PDF),
    "UTILITY_BILL": ("hoa-don-dien.pdf", PDF + b"\x04"),
}


@dataclass
class Team:
    """Nhân viên được tạo khi cần lần đầu, mỗi người một trình duyệt riêng."""

    client: TestClient
    clock: FakeClock
    email: FakeEmailGateway
    _count: dict[str, int] = field(default_factory=dict)

    @cached_property
    def admin(self) -> Staff:
        return bootstrap_admin(self.client, self.clock)

    def hire(self, username: str, *roles: str) -> Staff:
        return create_staff(self.admin, self.clock, self.email, username, list(roles))

    @cached_property
    def officer(self) -> Staff:
        return self.hire("tindung1", "CREDIT_OFFICER")

    @cached_property
    def officer2(self) -> Staff:
        return self.hire("tindung2", "CREDIT_OFFICER")

    @cached_property
    def appraiser(self) -> Staff:
        return self.hire("thamdinh1", "APPRAISER")

    @cached_property
    def approver(self) -> Staff:
        return self.hire("pheduyet1", "APPROVER")

    @cached_property
    def approver2(self) -> Staff:
        return self.hire("pheduyet2", "APPROVER")

    @cached_property
    def disburser(self) -> Staff:
        return self.hire("giaingan1", "DISBURSER")

    @cached_property
    def auditor(self) -> Staff:
        return self.hire("kiemsoat1", "AUDITOR")

    def relogin(self, staff: Staff) -> TestClient:
        """Phiên hết hạn sau 15 phút không hoạt động; test dài thì đăng nhập lại."""
        browser = new_client(self.client)
        login_with_otp(browser, self.clock, staff)
        staff.client = browser
        return browser


def customer_browser(
    client: TestClient, sms: FakeSmsGateway, phone: str = "0901234567", email: str = "an@example.com",
    **overrides: Any,
) -> TestClient:
    register_and_verify(client, sms, phone=phone, email=email, **overrides)
    browser = new_client(client)
    browser.post("/auth/login", json={"username": phone, "password": PASSWORD}).raise_for_status()
    return browser


def upload(browser: TestClient, app_id: str, doc_type: str, filename: str, content: bytes) -> Any:
    return browser.post(
        f"/applications/{app_id}/documents",
        data={"doc_type": doc_type},
        files={"file": (filename, content, "application/octet-stream")},
    )


def fill_draft(browser: TestClient, app_id: str, **finances: Any) -> None:
    browser.patch(f"/applications/{app_id}", json={**FINANCES, **finances}).raise_for_status()
    for doc_type, (filename, content) in DOCUMENTS.items():
        upload(browser, app_id, doc_type, filename, content).raise_for_status()


def submitted_application(browser: TestClient, loan: dict[str, Any] | None = None, **finances: Any) -> str:
    created = browser.post("/applications", json={**LOAN, **(loan or {})})
    assert created.status_code == 201, created.text
    app_id: str = created.json()["id"]
    fill_draft(browser, app_id, **finances)
    submitted = browser.post(
        f"/applications/{app_id}/submit", json={"accept_data_processing": True}
    )
    assert submitted.status_code == 200, submitted.text
    return app_id


def verify_as(officer: TestClient, app_id: str) -> Any:
    """NV tín dụng nhận hồ sơ vay, đánh dấu mọi giấy tờ Đạt rồi xác nhận hợp lệ (UC14)."""
    officer.post(f"/applications/{app_id}/claim").raise_for_status()
    for document in officer.get(f"/applications/{app_id}").json()["documents"]:
        officer.put(
            f"/applications/{app_id}/documents/{document['id']}/review", json={"verdict": "PASS"}
        ).raise_for_status()
    return officer.post(f"/applications/{app_id}/verify")


def notifications_of(browser: TestClient) -> list[dict[str, Any]]:
    response = browser.get("/notifications")
    assert response.status_code == 200, response.text
    items: list[dict[str, Any]] = response.json()
    return items
