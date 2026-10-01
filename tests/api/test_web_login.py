"""Seam 1 (trang HTML qua TestClient): khung giao diện Jinja2 và màn hình M01.

UC01 Đăng nhập, UC02 Xác thực OTP, đổi mật khẩu tạm khi đăng nhập lần đầu, UC09 Đăng ký tài khoản
khách hàng.
"""

import re
from typing import Any

from fastapi.testclient import TestClient

from loan_system.adapters.sms import FakeSmsGateway
from loan_system.services.staff_service import create_first_admin
from tests.api.staff import NEW_PASSWORD, bootstrap_admin, ctx_of, new_client, otp
from tests.api.test_customer_registration import (
    PASSWORD,
    PHONE,
    otp_sent_to,
    register_and_verify,
)
from tests.conftest import FakeClock


def submit(client: TestClient, path: str, data: dict[str, str]) -> Any:
    """Gửi biểu mẫu như trình duyệt: mở trang trước để nhận cookie CSRF rồi gửi kèm mã."""
    client.get("/app/login")
    return client.post(path, data={**data, "csrf": client.cookies["csrf"]})


def assert_forms_carry_csrf(client: TestClient, page_text: str) -> None:
    """Mọi biểu mẫu POST trên trang mang đúng mã CSRF của cookie. `submit` tự lấy mã từ cookie nên
    không phát hiện được ô ẩn trống (macro `csrf_field` phải được import `with context`)."""
    tokens = re.findall(r'name="csrf" value="([^"]*)"', page_text)
    assert tokens, "trang không có biểu mẫu mang mã CSRF"
    assert set(tokens) == {client.cookies["csrf"]}


def web_login(client: TestClient, username: str = PHONE, password: str = PASSWORD) -> Any:
    return submit(client, "/app/login", {"username": username, "password": password})


def test_customer_logs_in_through_the_login_page_and_lands_on_the_home_page(
    client: TestClient, sms: FakeSmsGateway
) -> None:
    register_and_verify(client, sms)

    page = client.get("/app/login")
    assert page.status_code == 200
    assert 'name="csrf"' in page.text
    assert client.get("/app/static/app.css").status_code == 200

    home = web_login(client)

    assert home.status_code == 200
    assert home.url.path == "/app"
    assert "Đăng xuất" in home.text


def test_wrong_password_shows_the_generic_message_and_starts_no_session(
    client: TestClient, sms: FakeSmsGateway
) -> None:
    register_and_verify(client, sms)

    page = web_login(client, password="khong-dung-mat-khau")

    assert page.status_code == 401
    assert "Thông tin đăng nhập không đúng" in page.text
    assert "session" not in client.cookies


def test_form_without_the_csrf_token_is_rejected(client: TestClient, sms: FakeSmsGateway) -> None:
    register_and_verify(client, sms)
    client.get("/app/login")

    forged = client.post("/app/login", data={"username": PHONE, "password": PASSWORD})
    wrong = client.post(
        "/app/login", data={"username": PHONE, "password": PASSWORD, "csrf": "gia-mao"}
    )

    assert forged.status_code == wrong.status_code == 403
    assert "Biểu mẫu đã hết hạn" in forged.text
    assert "session" not in client.cookies


def test_pages_require_login_and_say_when_the_session_expired(
    client: TestClient, sms: FakeSmsGateway, clock: FakeClock
) -> None:
    anonymous = client.get("/app")
    assert anonymous.url.path == "/app/login"
    assert "Vui lòng đăng nhập để tiếp tục" in anonymous.text

    register_and_verify(client, sms)
    home = web_login(client)
    assert 'data-idle-seconds="900"' in home.text  # đếm ngược hết phiên 15 phút (SR11)

    clock.advance(minutes=16)
    expired = client.get("/app")
    assert expired.url.path == "/app/login"
    assert "Phiên làm việc đã hết hạn" in expired.text


def test_logout_ends_the_session(client: TestClient, sms: FakeSmsGateway) -> None:
    register_and_verify(client, sms)
    web_login(client)

    page = submit(client, "/app/logout", {})

    assert page.url.path == "/app/login"
    assert "Bạn đã đăng xuất" in page.text
    assert client.get("/app").url.path == "/app/login"


def test_menu_only_shows_screens_of_the_users_role(
    client: TestClient, sms: FakeSmsGateway, clock: FakeClock
) -> None:
    register_and_verify(client, sms)
    customer_home = web_login(client).text
    admin = bootstrap_admin(client, clock)
    admin_browser = new_client(client)
    web_login(admin_browser, admin.username, admin.password)
    admin_home = submit(admin_browser, "/app/login/otp", {"code": otp(clock, admin.totp_secret)})

    assert "Khoản vay của tôi" in customer_home
    assert "Quản trị" not in customer_home
    assert "Quản trị" in admin_home.text
    assert "Nộp hồ sơ vay" not in admin_home.text


def test_unknown_page_gets_the_html_error_page_but_the_api_keeps_json(client: TestClient) -> None:
    page = client.get("/app/khong-co-trang-nay")
    api = client.get("/khong-co-api-nay")

    assert page.status_code == api.status_code == 404
    assert "Không tìm thấy trang" in page.text
    assert page.headers["content-type"].startswith("text/html")
    assert api.headers["content-type"].startswith("application/json")


# --- UC02: nhân viên nhập mã TOTP -------------------------------------------------------------


def test_staff_enters_the_totp_code_after_the_password(
    client: TestClient, clock: FakeClock
) -> None:
    admin = bootstrap_admin(client, clock)
    browser = new_client(client)

    otp_page = web_login(browser, admin.username, admin.password)
    assert otp_page.url.path == "/app/login/otp"
    # Chưa qua OTP thì chưa vào được: quay lại bước nhập mã, không báo hết phiên.
    assert browser.get("/app").url.path == "/app/login/otp"

    wrong = submit(browser, "/app/login/otp", {"code": "000000"})
    assert wrong.status_code == 400
    assert "Mã OTP không đúng" in wrong.text

    home = submit(browser, "/app/login/otp", {"code": otp(clock, admin.totp_secret)})
    assert home.url.path == "/app"
    assert "Đăng xuất" in home.text


def test_three_wrong_totp_codes_send_the_staff_back_to_the_login_page(
    client: TestClient, clock: FakeClock
) -> None:
    admin = bootstrap_admin(client, clock)
    browser = new_client(client)
    web_login(browser, admin.username, admin.password)

    for _ in range(2):
        assert submit(browser, "/app/login/otp", {"code": "000000"}).status_code == 400
    page = submit(browser, "/app/login/otp", {"code": "000000"})

    assert page.url.path == "/app/login"
    assert "Nhập sai mã OTP quá số lần cho phép" in page.text


def test_otp_page_left_open_too_long_says_the_session_expired(
    client: TestClient, clock: FakeClock
) -> None:
    admin = bootstrap_admin(client, clock)
    browser = new_client(client)
    web_login(browser, admin.username, admin.password)

    clock.advance(minutes=16)
    page = submit(browser, "/app/login/otp", {"code": otp(clock, admin.totp_secret)})

    assert page.url.path == "/app/login"
    assert "Phiên làm việc đã hết hạn" in page.text


# --- UC01 3b: nhân viên đăng nhập lần đầu -----------------------------------------------------


def test_new_staff_changes_the_temporary_password_and_enrolls_totp(
    client: TestClient, clock: FakeClock
) -> None:
    ctx = ctx_of(client)
    with ctx.session_factory() as db:
        temp_password = create_first_admin(
            db, ctx.clock, username="quantri", full_name="Quản Trị Viên", email="quantri@cty.vn"
        )

    setup = web_login(client, "quantri", temp_password)
    assert setup.url.path == "/app/setup/password"

    mismatch = submit(client, "/app/setup/password", {
        "current_password": temp_password, "new_password": NEW_PASSWORD,
        "confirm_password": "go-nham-mat-khau",
    })
    assert mismatch.status_code == 400
    assert "không khớp" in mismatch.text

    totp_page = submit(client, "/app/setup/password", {
        "current_password": temp_password, "new_password": NEW_PASSWORD,
        "confirm_password": NEW_PASSWORD,
    })
    assert totp_page.url.path == "/app/setup/totp"

    enrollment = submit(client, "/app/setup/totp", {})
    match = re.search(r'<code class="secret">([A-Z2-7]+)</code>', enrollment.text)
    assert match, "Trang phải hiển thị khóa TOTP"

    home = submit(client, "/app/setup/totp/confirm", {"code": otp(clock, match.group(1))})
    assert home.url.path == "/app"
    assert "Đã kích hoạt tài khoản" in home.text


# --- UC09 -------------------------------------------------------------------------------------


def registration_form(**overrides: str) -> dict[str, str]:
    form = {
        "full_name": "Nguyễn Văn An",
        "date_of_birth": "1995-04-12",
        "phone": PHONE,
        "email": "an.nguyen@example.com",
        "password": PASSWORD,
        "accept_terms": "true",
    }
    form.update(overrides)
    return form


def test_customer_registers_through_the_web_form_and_logs_in(
    client: TestClient, sms: FakeSmsGateway
) -> None:
    verify_page = submit(client, "/app/register", registration_form())
    assert verify_page.status_code == 200
    match = re.search(r'name="registration_id" value="([^"]+)"', verify_page.text)
    assert match

    login_page = submit(client, "/app/register/verify", {
        "registration_id": match.group(1), "otp": otp_sent_to(sms, PHONE),
    })
    assert login_page.url.path == "/app/login"
    assert "Đăng ký thành công" in login_page.text

    assert web_login(client).url.path == "/app"


def test_registration_form_lists_the_invalid_fields(client: TestClient) -> None:
    form = registration_form(phone="12345", password="ngan")
    del form["accept_terms"]

    page = submit(client, "/app/register", form)

    assert page.status_code == 400
    assert "Số điện thoại gồm 10 chữ số" in page.text
    assert "Mật khẩu từ 10 đến 128 ký tự" in page.text
    assert "Bạn cần đồng ý điều khoản sử dụng" in page.text
    assert 'value="Nguyễn Văn An"' in page.text  # giữ lại dữ liệu đã nhập


def test_duplicate_registration_gets_the_generic_message(
    client: TestClient, sms: FakeSmsGateway
) -> None:
    register_and_verify(client, sms)

    page = submit(client, "/app/register", registration_form(email="khac@example.com"))

    assert page.status_code == 409
    assert "Không thể đăng ký với thông tin này" in page.text
