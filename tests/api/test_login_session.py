"""Seam 1: UC01 Đăng nhập (khách hàng), phiên làm việc (SR11) và đăng xuất."""

from typing import Any

from fastapi.testclient import TestClient

from loan_system.adapters.sms import FakeSmsGateway
from tests.api.test_customer_registration import PASSWORD, PHONE, register_and_verify


def login(client: TestClient, username: str = PHONE, password: str = PASSWORD) -> Any:
    return client.post("/auth/login", json={"username": username, "password": password})


def test_wrong_password_and_unknown_user_get_the_same_generic_answer(
    client: TestClient, sms: FakeSmsGateway
) -> None:
    register_and_verify(client, sms)

    wrong_password = login(client, password="khong-dung-mat-khau")
    unknown_user = login(client, username="0999999999")

    assert wrong_password.status_code == unknown_user.status_code == 401
    assert wrong_password.json() == unknown_user.json()
    assert "session" not in client.cookies


def test_session_cookie_is_httponly_secure_and_samesite(
    client: TestClient, sms: FakeSmsGateway
) -> None:
    register_and_verify(client, sms)

    set_cookie = login(client).headers["set-cookie"].lower()

    assert "httponly" in set_cookie
    assert "secure" in set_cookie
    assert "samesite=strict" in set_cookie


def test_session_expires_after_15_minutes_of_inactivity(
    client: TestClient, sms: FakeSmsGateway, clock: Any
) -> None:
    register_and_verify(client, sms)
    login(client)

    clock.advance(minutes=14)
    assert client.get("/auth/session").status_code == 200  # hoạt động -> gia hạn

    clock.advance(minutes=14)
    assert client.get("/auth/session").status_code == 200

    clock.advance(minutes=15, seconds=1)
    assert client.get("/auth/session").status_code == 401


def test_logout_ends_the_session(client: TestClient, sms: FakeSmsGateway) -> None:
    register_and_verify(client, sms)
    login(client)
    token = client.cookies["session"]

    assert client.post("/auth/logout").status_code == 204

    # Token cũ không dùng lại được, kể cả khi bị đánh cắp trước lúc đăng xuất.
    client.cookies.set("session", token)
    assert client.get("/auth/session").status_code == 401
