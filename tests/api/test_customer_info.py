"""Seam 1: ticket #17 Thông tin khách hàng — hồ sơ cá nhân, đổi liên hệ qua OTP, tra cứu của NV."""

from fastapi.testclient import TestClient

from loan_system.adapters.email import FakeEmailGateway
from loan_system.adapters.sms import FakeSmsGateway
from tests.api.staff import new_client
from tests.api.test_customer_registration import PASSWORD, PHONE, otp_sent_to, register_and_verify
from tests.api.workflow import Team, customer_browser, submitted_application
from tests.conftest import FakeClock


def test_new_customer_profile_starts_empty_and_unlocked(
    client: TestClient, sms: FakeSmsGateway
) -> None:
    browser = customer_browser(client, sms)

    profile = browser.get("/customers/me")
    assert profile.status_code == 200
    body = profile.json()
    assert body["phone"] == PHONE
    assert body["national_id"] is None
    assert body["income_locked"] is False


def test_customer_updates_their_own_profile(client: TestClient, sms: FakeSmsGateway) -> None:
    browser = customer_browser(client, sms)

    updated = browser.patch(
        "/customers/me",
        json={
            "occupation": "Kỹ sư", "employer": "Cty ABC", "employment_years": 3,
            "monthly_income": 20_000_000, "housing_type": "RENT", "address": "1 Lê Lợi",
        },
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["occupation"] == "Kỹ sư"
    assert body["monthly_income"] == "20000000"
    assert body["address"] == "1 Lê Lợi"


def test_income_is_locked_while_an_application_is_in_progress(
    client: TestClient, sms: FakeSmsGateway
) -> None:
    browser = customer_browser(client, sms)
    submitted_application(browser)

    locked = browser.get("/customers/me").json()
    assert locked["income_locked"] is True

    rejected = browser.patch("/customers/me", json={"monthly_income": 30_000_000})
    assert rejected.status_code == 409
    # Các trường khác không bị khóa theo.
    ok = browser.patch("/customers/me", json={"address": "Địa chỉ mới"})
    assert ok.status_code == 200
    assert ok.json()["address"] == "Địa chỉ mới"


def test_income_unlocks_after_the_application_is_cancelled(
    client: TestClient, sms: FakeSmsGateway
) -> None:
    browser = customer_browser(client, sms)
    app_id = submitted_application(browser)
    browser.post(f"/applications/{app_id}/cancel", json={}).raise_for_status()

    unlocked = browser.get("/customers/me").json()
    assert unlocked["income_locked"] is False
    assert browser.patch("/customers/me", json={"monthly_income": 30_000_000}).status_code == 200


def test_changing_phone_requires_otp_and_updates_login_username(
    client: TestClient, sms: FakeSmsGateway
) -> None:
    browser = customer_browser(client, sms)
    new_phone = "0909999999"

    started = browser.post("/customers/me/phone", json={"new_phone": new_phone})
    assert started.status_code == 202
    challenge_id = started.json()["challenge_id"]

    wrong = browser.post(
        "/customers/me/phone/confirm", json={"challenge_id": challenge_id, "otp": "000000"}
    )
    assert wrong.status_code == 400

    confirmed = browser.post(
        "/customers/me/phone/confirm",
        json={"challenge_id": challenge_id, "otp": otp_sent_to(sms, PHONE)},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["phone"] == new_phone

    assert new_client(client).post(
        "/auth/login", json={"username": new_phone, "password": PASSWORD}
    ).status_code == 200
    assert new_client(client).post(
        "/auth/login", json={"username": PHONE, "password": PASSWORD}
    ).status_code == 401


def test_changing_email_requires_otp(client: TestClient, sms: FakeSmsGateway) -> None:
    browser = customer_browser(client, sms)

    started = browser.post("/customers/me/email", json={"new_email": "moi@example.com"})
    assert started.status_code == 202
    challenge_id = started.json()["challenge_id"]

    confirmed = browser.post(
        "/customers/me/email/confirm",
        json={"challenge_id": challenge_id, "otp": otp_sent_to(sms, PHONE)},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["email"] == "moi@example.com"


def test_new_phone_already_belonging_to_another_customer_is_rejected(
    client: TestClient, sms: FakeSmsGateway
) -> None:
    register_and_verify(client, sms, phone="0911111111", email="a@example.com")
    browser = customer_browser(client, sms, phone="0922222222", email="b@example.com")

    started = browser.post("/customers/me/phone", json={"new_phone": "0911111111"})
    assert started.status_code == 409


def test_staff_lookup_returns_masked_data_by_default(
    client: TestClient, clock: FakeClock, email: FakeEmailGateway, sms: FakeSmsGateway
) -> None:
    team = Team(client, clock, email)
    browser = customer_browser(client, sms)
    submitted_application(browser)

    found = team.officer.client.post("/customers/lookup", json={"national_id": "079095001234"})
    assert found.status_code == 200
    body = found.json()
    assert body["national_id"] is not None and "*" in body["national_id"]
    assert body["monthly_income"] is None


def test_unknown_national_id_lookup_is_404(
    client: TestClient, clock: FakeClock, email: FakeEmailGateway
) -> None:
    team = Team(client, clock, email)
    response = team.officer.client.post(
        "/customers/lookup", json={"national_id": "000000000000"}
    )
    assert response.status_code == 404


def test_only_credit_officer_and_appraiser_can_lookup_customers(
    client: TestClient, clock: FakeClock, email: FakeEmailGateway
) -> None:
    team = Team(client, clock, email)
    denied = team.approver.client.post("/customers/lookup", json={"national_id": "079095001234"})
    assert denied.status_code == 403


def test_reveal_pii_requires_the_pii_permission_and_logs_view_pii(
    client: TestClient, clock: FakeClock, email: FakeEmailGateway, sms: FakeSmsGateway
) -> None:
    team = Team(client, clock, email)
    browser = customer_browser(client, sms)
    submitted_application(browser)
    customer_id = browser.get("/customers/me").json()["id"]

    denied = team.officer.client.post(f"/customers/{customer_id}/reveal-pii")
    assert denied.status_code == 403

    revealed = team.appraiser.client.post(f"/customers/{customer_id}/reveal-pii")
    assert revealed.status_code == 200
    body = revealed.json()
    assert body["national_id"] == "079095001234"
    assert body["monthly_income"] is not None

    views = team.auditor.client.get(
        "/audit/logs", params={"action": "VIEW_PII", "target_id": customer_id}
    ).json()
    assert len(views) == 1


def test_a_customer_cannot_reveal_another_customers_pii(
    client: TestClient, sms: FakeSmsGateway
) -> None:
    """CUSTOMER_VIEW_PII cũng được cấp cho vai trò CUSTOMER (tự xem hồ sơ mình); "Hiện đầy đủ"
    chỉ dành cho nhân viên sau một lượt tra cứu, không phải lối tắt để soi hồ sơ người khác."""
    victim = customer_browser(client, sms)
    submitted_application(victim)
    victim_id = victim.get("/customers/me").json()["id"]

    attacker = customer_browser(client, sms, phone="0933333333", email="attacker@example.com")

    assert attacker.post(f"/customers/{victim_id}/reveal-pii").status_code == 403
