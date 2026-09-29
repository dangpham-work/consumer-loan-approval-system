"""Tiện ích cho test liên quan đến nhân viên: dựng Quản trị viên đầu tiên, tạo nhân viên, đăng nhập 2FA."""

import re
from dataclasses import dataclass

from fastapi.testclient import TestClient

from loan_system.adapters.email import FakeEmailGateway
from loan_system.api.deps import AppContext
from loan_system.security.totp import totp_code
from loan_system.services.staff_service import create_first_admin
from tests.conftest import FakeClock

NEW_PASSWORD = "mat-khau-nhan-vien-moi"


@dataclass
class Staff:
    username: str
    password: str
    totp_secret: str
    client: TestClient


def new_client(client: TestClient) -> TestClient:
    """Một trình duyệt khác (cookie riêng) trên cùng ứng dụng."""
    return TestClient(client.app, base_url="https://testserver")


def ctx_of(client: TestClient) -> AppContext:
    ctx: AppContext = client.app.state.ctx  # type: ignore[attr-defined]
    return ctx


def otp(clock: FakeClock, secret: str) -> str:
    # Mỗi mã TOTP chỉ dùng được một lần; sang bước 30 giây mới để lấy mã mới.
    clock.advance(seconds=30)
    return totp_code(secret, clock.now())


def complete_first_login(
    client: TestClient, clock: FakeClock, username: str, temp_password: str
) -> str:
    """Đăng nhập lần đầu: đổi mật khẩu tạm, đăng ký TOTP. Trả về khóa TOTP."""
    login = client.post("/auth/login", json={"username": username, "password": temp_password})
    assert login.status_code == 200, login.text
    assert login.json()["next"] == "SETUP"
    client.post(
        "/auth/setup/password",
        json={"current_password": temp_password, "new_password": NEW_PASSWORD},
    ).raise_for_status()
    secret: str = client.post("/auth/setup/totp").json()["secret"]
    client.post(
        "/auth/setup/totp/confirm", json={"code": otp(clock, secret)}
    ).raise_for_status()
    return secret


def bootstrap_admin(client: TestClient, clock: FakeClock, username: str = "quantri") -> Staff:
    ctx = ctx_of(client)
    with ctx.session_factory() as db:
        temp_password = create_first_admin(
            db, ctx.clock, username=username, full_name="Quản Trị Viên", email=f"{username}@cty.vn"
        )
    browser = new_client(client)
    secret = complete_first_login(browser, clock, username, temp_password)
    return Staff(username, NEW_PASSWORD, secret, browser)


def temp_password_emailed_to(email: FakeEmailGateway, address: str) -> str:
    match = re.search(r"Mật khẩu tạm: (\S+)", email.last_to(address).body)
    assert match, "Email phải chứa mật khẩu tạm"
    return match.group(1)


def create_staff(
    admin: Staff,
    clock: FakeClock,
    email: FakeEmailGateway,
    username: str,
    roles: list[str],
) -> Staff:
    created = admin.client.post(
        "/admin/users",
        json={
            "username": username,
            "full_name": f"Nhân viên {username}",
            "email": f"{username}@cty.vn",
            "branch": "Hà Nội",
            "roles": roles,
            "otp": otp(clock, admin.totp_secret),
        },
    )
    assert created.status_code == 201, created.text
    browser = new_client(admin.client)
    temp_password = temp_password_emailed_to(email, f"{username}@cty.vn")
    secret = complete_first_login(browser, clock, username, temp_password)
    return Staff(username, NEW_PASSWORD, secret, browser)


def login_with_otp(client: TestClient, clock: FakeClock, staff: Staff) -> None:
    login = client.post("/auth/login", json={"username": staff.username, "password": staff.password})
    assert login.json()["next"] == "OTP"
    client.post("/auth/otp/verify", json={"code": otp(clock, staff.totp_secret)}).raise_for_status()
