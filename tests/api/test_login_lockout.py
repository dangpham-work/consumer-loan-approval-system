"""Seam 1: ST06 dò mật khẩu — khóa tạm sau 5 lần sai liên tiếp (SR01) và giới hạn tần suất (SR12)."""

from typing import Any

from fastapi.testclient import TestClient

from loan_system.adapters.sms import FakeSmsGateway
from tests.api.test_customer_registration import PASSWORD, PHONE, register_and_verify
from tests.conftest import FakeClock

WRONG = "khong-phai-mat-khau"


def login(client: TestClient, password: str, username: str = PHONE) -> Any:
    return client.post("/auth/login", json={"username": username, "password": password})


def test_st06_account_is_locked_for_15_minutes_after_5_wrong_passwords(
    client: TestClient, sms: FakeSmsGateway, clock: FakeClock
) -> None:
    register_and_verify(client, sms)

    for _ in range(4):
        assert login(client, WRONG).status_code == 401
    fifth = login(client, WRONG)
    assert fifth.status_code == 401
    assert "khóa" in fifth.json()["detail"]

    # Đang khóa: mật khẩu đúng cũng bị từ chối
    clock.advance(minutes=14)
    assert login(client, PASSWORD).status_code == 401

    clock.advance(minutes=1, seconds=1)
    assert login(client, PASSWORD).status_code == 200


def test_a_successful_login_resets_the_failure_counter(
    client: TestClient, sms: FakeSmsGateway
) -> None:
    register_and_verify(client, sms)

    for _ in range(4):
        login(client, WRONG)
    assert login(client, PASSWORD).status_code == 200
    for _ in range(4):
        login(client, WRONG)

    assert login(client, PASSWORD).status_code == 200


def test_st06_too_many_login_attempts_from_one_address_get_429(
    client: TestClient, sms: FakeSmsGateway, clock: FakeClock
) -> None:
    register_and_verify(client, sms)

    # Dò nhiều tài khoản khác nhau để né cơ chế khóa theo tài khoản
    statuses = [login(client, WRONG, username=f"09000000{i:02d}").status_code for i in range(11)]
    assert statuses[:10] == [401] * 10
    assert statuses[10] == 429
    assert login(client, PASSWORD).status_code == 429

    clock.advance(minutes=1, seconds=1)
    assert login(client, PASSWORD).status_code == 200
