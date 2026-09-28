"""Seam 1: UC09 Đăng ký tài khoản khách hàng và UC01 Đăng nhập (khách hàng)."""

import re
from typing import Any

from fastapi.testclient import TestClient

from loan_system.adapters.sms import FakeSmsGateway

PHONE = "0901234567"
PASSWORD = "mat-khau-du-dai"


def registration(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "full_name": "Nguyễn Văn An",
        "date_of_birth": "1995-04-12",
        "phone": PHONE,
        "email": "an.nguyen@example.com",
        "password": PASSWORD,
        "accept_terms": True,
    }
    body.update(overrides)
    return body


def otp_sent_to(sms: FakeSmsGateway, phone: str) -> str:
    match = re.search(r"\b(\d{6})\b", sms.last_to(phone).message)
    assert match, "SMS phải chứa mã OTP 6 chữ số"
    return match.group(1)


def test_customer_registers_verifies_phone_and_logs_in(
    client: TestClient, sms: FakeSmsGateway
) -> None:
    started = client.post("/customers/register", json=registration())
    assert started.status_code == 202

    verified = client.post(
        "/customers/register/verify",
        json={"registration_id": started.json()["registration_id"], "otp": otp_sent_to(sms, PHONE)},
    )
    assert verified.status_code == 201

    login = client.post("/auth/login", json={"username": PHONE, "password": PASSWORD})
    assert login.status_code == 200
    me = client.get("/auth/session")
    assert me.status_code == 200
    assert me.json()["role"] == "CUSTOMER"


def test_registration_requires_a_password_of_at_least_10_characters(client: TestClient) -> None:
    response = client.post("/customers/register", json=registration(password="ngan-qua"))
    assert response.status_code == 400


def test_registration_requires_accepting_the_terms(client: TestClient) -> None:
    response = client.post("/customers/register", json=registration(accept_terms=False))
    assert response.status_code == 400


def test_applicant_outside_20_to_60_can_register_but_is_told_they_cannot_borrow_yet(
    client: TestClient,
) -> None:
    # Hôm nay (đồng hồ test) là 28/09/2026: sinh 01/10/2006 thì mới 19 tuổi
    too_young = client.post("/customers/register", json=registration(date_of_birth="2006-10-01"))
    assert too_young.status_code == 202
    assert too_young.json()["eligible_for_loan"] is False

    turned_20 = client.post(
        "/customers/register",
        json=registration(date_of_birth="2006-09-28", phone="0907654321", email="b@example.com"),
    )
    assert turned_20.json()["eligible_for_loan"] is True


def register_and_verify(client: TestClient, sms: FakeSmsGateway, **overrides: Any) -> None:
    body = registration(**overrides)
    started = client.post("/customers/register", json=body)
    client.post(
        "/customers/register/verify",
        json={
            "registration_id": started.json()["registration_id"],
            "otp": otp_sent_to(sms, body["phone"]),
        },
    ).raise_for_status()


def test_duplicate_phone_or_email_gets_the_same_generic_message(
    client: TestClient, sms: FakeSmsGateway
) -> None:
    register_and_verify(client, sms)

    same_phone = client.post("/customers/register", json=registration(email="khac@example.com"))
    same_email = client.post("/customers/register", json=registration(phone="0911111111"))

    assert same_phone.status_code == same_email.status_code == 409
    # Không tiết lộ trường nào bị trùng (UC09 2b)
    assert same_phone.json() == same_email.json()


def test_three_wrong_otps_cancel_the_registration(client: TestClient, sms: FakeSmsGateway) -> None:
    started = client.post("/customers/register", json=registration()).json()
    correct = otp_sent_to(sms, PHONE)
    wrong = "000000" if correct != "000000" else "111111"

    for _ in range(3):
        attempt = client.post(
            "/customers/register/verify",
            json={"registration_id": started["registration_id"], "otp": wrong},
        )
        assert attempt.status_code == 400

    too_late = client.post(
        "/customers/register/verify",
        json={"registration_id": started["registration_id"], "otp": correct},
    )
    assert too_late.status_code == 400
    assert client.post("/auth/login", json={"username": PHONE, "password": PASSWORD}).status_code == 401


def test_expired_otp_is_rejected(client: TestClient, sms: FakeSmsGateway, clock: Any) -> None:
    started = client.post("/customers/register", json=registration()).json()
    clock.advance(minutes=6)

    response = client.post(
        "/customers/register/verify",
        json={"registration_id": started["registration_id"], "otp": otp_sent_to(sms, PHONE)},
    )
    assert response.status_code == 400


def test_extra_fields_in_registration_are_ignored(client: TestClient, sms: FakeSmsGateway) -> None:
    # SR10 / ST05: kẻ gian gửi thêm trạng thái hoặc vai trò mong muốn
    register_and_verify(client, sms, status="DISABLED", role="ADMIN", customer_id="x")

    assert client.post("/auth/login", json={"username": PHONE, "password": PASSWORD}).status_code == 200
    assert client.get("/auth/session").json()["role"] == "CUSTOMER"
