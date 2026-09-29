"""Seam 1: UC04 Quản lý tài khoản nhân viên, đăng nhập lần đầu, UC02 Xác thực OTP và ma trận RBAC."""

from typing import Any

from fastapi.testclient import TestClient

from loan_system.adapters.email import FakeEmailGateway
from loan_system.security.totp import totp_code
from tests.api.staff import (
    NEW_PASSWORD,
    bootstrap_admin,
    create_staff,
    login_with_otp,
    new_client,
    otp,
    temp_password_emailed_to,
)
from tests.conftest import FakeClock


def session_of(client: TestClient) -> dict[str, Any]:
    response = client.get("/auth/session")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def test_first_admin_must_change_password_and_enroll_totp_before_working(
    client: TestClient, clock: FakeClock
) -> None:
    admin = bootstrap_admin(client, clock)

    me = session_of(admin.client)
    assert me["kind"] == "EMPLOYEE"
    assert me["roles"] == ["ADMIN"]


def test_pending_account_cannot_use_the_system_before_finishing_setup(
    client: TestClient, clock: FakeClock, email: FakeEmailGateway
) -> None:
    admin = bootstrap_admin(client, clock)
    admin.client.post(
        "/admin/users",
        json={"username": "tindung1", "full_name": "Trần Thị Bình", "email": "binh@cty.vn",
              "branch": "Hà Nội", "roles": ["CREDIT_OFFICER"],
              "otp": otp(clock, admin.totp_secret)},
    ).raise_for_status()
    temp_password = temp_password_emailed_to(email, "binh@cty.vn")

    browser = new_client(client)
    assert browser.post(
        "/auth/login", json={"username": "tindung1", "password": temp_password}
    ).json()["next"] == "SETUP"

    # Chưa đổi mật khẩu và đăng ký TOTP thì chưa có phiên làm việc đầy đủ.
    assert browser.get("/auth/session").status_code == 401
    # Không được đăng ký TOTP trước khi đổi mật khẩu tạm.
    assert browser.post("/auth/setup/totp").status_code == 409
    # Mật khẩu mới phải khác mật khẩu tạm và đủ 10 ký tự (SR01).
    same = browser.post(
        "/auth/setup/password",
        json={"current_password": temp_password, "new_password": temp_password},
    )
    assert same.status_code == 400
    short = browser.post(
        "/auth/setup/password", json={"current_password": temp_password, "new_password": "ngan"}
    )
    assert short.status_code == 400


def test_staff_login_requires_a_totp_code_after_the_password(
    client: TestClient, clock: FakeClock, email: FakeEmailGateway
) -> None:
    admin = bootstrap_admin(client, clock)
    officer = create_staff(admin, clock, email, "tindung1", ["CREDIT_OFFICER"])
    officer.client.post("/auth/logout").raise_for_status()

    browser = new_client(client)
    login = browser.post("/auth/login", json={"username": "tindung1", "password": NEW_PASSWORD})
    assert login.json()["next"] == "OTP"
    assert browser.get("/auth/session").status_code == 401  # mới qua một yếu tố

    verified = browser.post("/auth/otp/verify", json={"code": otp(clock, officer.totp_secret)})
    assert verified.status_code == 200
    assert session_of(browser)["roles"] == ["CREDIT_OFFICER"]


def test_three_wrong_totp_codes_end_the_pending_login(
    client: TestClient, clock: FakeClock, email: FakeEmailGateway
) -> None:
    admin = bootstrap_admin(client, clock)
    officer = create_staff(admin, clock, email, "tindung1", ["CREDIT_OFFICER"])

    browser = new_client(client)
    browser.post("/auth/login", json={"username": "tindung1", "password": NEW_PASSWORD})
    clock.advance(seconds=30)
    right = totp_code(officer.totp_secret, clock.now())
    wrong = "000000" if right != "000000" else "111111"
    for _ in range(3):
        assert browser.post("/auth/otp/verify", json={"code": wrong}).status_code == 400

    # UC02 3b: phiên chờ 2FA bị hủy, mã đúng cũng không cứu được
    assert browser.post("/auth/otp/verify", json={"code": right}).status_code == 401


def test_a_totp_code_cannot_be_replayed(
    client: TestClient, clock: FakeClock, email: FakeEmailGateway
) -> None:
    admin = bootstrap_admin(client, clock)
    officer = create_staff(admin, clock, email, "tindung1", ["CREDIT_OFFICER"])

    first = new_client(client)
    first.post("/auth/login", json={"username": "tindung1", "password": NEW_PASSWORD})
    code = otp(clock, officer.totp_secret)
    assert first.post("/auth/otp/verify", json={"code": code}).status_code == 200

    # Kẻ gian nhìn trộm mật khẩu và mã vừa dùng
    second = new_client(client)
    second.post("/auth/login", json={"username": "tindung1", "password": NEW_PASSWORD})
    assert second.post("/auth/otp/verify", json={"code": code}).status_code == 400


def test_roles_carry_the_permissions_of_the_rbac_matrix(
    client: TestClient, clock: FakeClock, email: FakeEmailGateway
) -> None:
    admin = bootstrap_admin(client, clock)
    officer = create_staff(admin, clock, email, "tindung1", ["CREDIT_OFFICER"])
    auditor = create_staff(admin, clock, email, "kiemsoat1", ["AUDITOR"])

    officer_perms = session_of(officer.client)["permissions"]
    assert {"APPLICATION_CREATE", "APPLICATION_VERIFY", "PAYMENT_RECORD"} <= set(officer_perms)
    assert "LOAN_APPROVE" not in officer_perms

    assert set(session_of(auditor.client)["permissions"]) == {
        "AUDIT_VIEW", "AUDIT_VERIFY", "APPLICATION_LOCK_RESOLVE",
    }
    # Quản trị viên không có quyền nghiệp vụ cho vay
    admin_perms = set(session_of(admin.client)["permissions"])
    assert "USER_MANAGE" in admin_perms
    assert not admin_perms & {"APPLICATION_VIEW", "LOAN_APPROVE", "DISBURSE"}


def test_only_user_managers_can_create_staff_accounts(
    client: TestClient, clock: FakeClock, email: FakeEmailGateway
) -> None:
    admin = bootstrap_admin(client, clock)
    officer = create_staff(admin, clock, email, "tindung1", ["CREDIT_OFFICER"])

    response = officer.client.post(
        "/admin/users",
        json={"username": "tindung2", "full_name": "Ai Đó", "email": "x@cty.vn",
              "branch": "HN", "roles": ["APPROVER"], "otp": otp(clock, officer.totp_secret)},
    )
    assert response.status_code == 403
    assert new_client(client).post("/admin/users", json={}).status_code == 401


def test_duplicate_username_or_email_is_rejected(
    client: TestClient, clock: FakeClock, email: FakeEmailGateway
) -> None:
    admin = bootstrap_admin(client, clock)
    create_staff(admin, clock, email, "tindung1", ["CREDIT_OFFICER"])

    def create(username: str, address: str) -> int:
        response = admin.client.post(
            "/admin/users",
            json={"username": username, "full_name": "Ai Đó", "email": address,
                  "branch": "HN", "roles": ["APPRAISER"], "otp": otp(clock, admin.totp_secret)},
        )
        code: int = response.status_code
        return code

    assert create("tindung1", "moi@cty.vn") == 409
    assert create("thamdinh1", "tindung1@cty.vn") == 409


def test_unknown_or_customer_role_cannot_be_given_to_staff(
    client: TestClient, clock: FakeClock
) -> None:
    admin = bootstrap_admin(client, clock)

    for roles in (["SUPERUSER"], ["CUSTOMER"], [], ["ADMIN", "APPROVER"]):
        response = admin.client.post(
            "/admin/users",
            json={"username": "nv1", "full_name": "Ai Đó", "email": "nv1@cty.vn",
                  "branch": "HN", "roles": roles, "otp": otp(clock, admin.totp_secret)},
        )
        assert response.status_code == 400, roles


def test_extra_fields_cannot_make_a_new_account_active(
    client: TestClient, clock: FakeClock, email: FakeEmailGateway
) -> None:
    admin = bootstrap_admin(client, clock)
    admin.client.post(
        "/admin/users",
        json={"username": "tindung1", "full_name": "Ai Đó", "email": "a@cty.vn", "branch": "HN",
              "roles": ["CREDIT_OFFICER"], "status": "ACTIVE", "password": "tu-dat-mat-khau-1",
              "otp": otp(clock, admin.totp_secret)},
    ).raise_for_status()

    browser = new_client(client)
    ignored = browser.post(
        "/auth/login", json={"username": "tindung1", "password": "tu-dat-mat-khau-1"}
    )
    assert ignored.status_code == 401
    temp = temp_password_emailed_to(email, "a@cty.vn")
    assert browser.post(
        "/auth/login", json={"username": "tindung1", "password": temp}
    ).json()["next"] == "SETUP"


def test_admin_changes_a_staff_role_with_step_up_otp(
    client: TestClient, clock: FakeClock, email: FakeEmailGateway
) -> None:
    admin = bootstrap_admin(client, clock)
    officer = create_staff(admin, clock, email, "tindung1", ["CREDIT_OFFICER"])
    officer_id = session_of(officer.client)["user_id"]

    without_otp = admin.client.put(
        f"/admin/users/{officer_id}/roles", json={"roles": ["APPRAISER"], "otp": "000000"}
    )
    assert without_otp.status_code == 403

    changed = admin.client.put(
        f"/admin/users/{officer_id}/roles",
        json={"roles": ["APPRAISER"], "otp": otp(clock, admin.totp_secret)},
    )
    assert changed.status_code == 200
    assert session_of(officer.client)["roles"] == ["APPRAISER"]


def test_admin_cannot_give_themselves_a_business_role(
    client: TestClient, clock: FakeClock
) -> None:
    admin = bootstrap_admin(client, clock)
    admin_id = session_of(admin.client)["user_id"]

    response = admin.client.put(
        f"/admin/users/{admin_id}/roles",
        json={"roles": ["ADMIN", "APPROVER"], "otp": otp(clock, admin.totp_secret)},
    )

    assert response.status_code == 403
    assert session_of(admin.client)["roles"] == ["ADMIN"]


def test_role_change_for_unknown_user_is_404(client: TestClient, clock: FakeClock) -> None:
    admin = bootstrap_admin(client, clock)
    response = admin.client.put(
        "/admin/users/00000000-0000-0000-0000-000000000001/roles",
        json={"roles": ["APPRAISER"], "otp": otp(clock, admin.totp_secret)},
    )
    assert response.status_code == 404


def test_staff_session_expires_after_15_minutes_of_inactivity(
    client: TestClient, clock: FakeClock, email: FakeEmailGateway
) -> None:
    admin = bootstrap_admin(client, clock)
    officer = create_staff(admin, clock, email, "tindung1", ["CREDIT_OFFICER"])
    browser = new_client(client)
    login_with_otp(browser, clock, officer)

    clock.advance(minutes=15, seconds=1)
    assert browser.get("/auth/session").status_code == 401


def test_creating_staff_requires_a_fresh_totp_code(client: TestClient, clock: FakeClock) -> None:
    admin = bootstrap_admin(client, clock)

    response = admin.client.post(
        "/admin/users",
        json={"username": "nv1", "full_name": "Ai Đó", "email": "nv1@cty.vn", "branch": "HN",
              "roles": ["APPRAISER"], "otp": "000000"},
    )
    assert response.status_code == 403


def test_no_account_may_hold_admin_together_with_a_lending_role(
    client: TestClient, clock: FakeClock, email: FakeEmailGateway
) -> None:
    admin = bootstrap_admin(client, clock)
    other_admin = create_staff(admin, clock, email, "quantri2", ["ADMIN"])
    other_id = session_of(other_admin.client)["user_id"]

    response = admin.client.put(
        f"/admin/users/{other_id}/roles",
        json={"roles": ["ADMIN", "APPROVER"], "otp": otp(clock, admin.totp_secret)},
    )
    assert response.status_code == 400
    assert session_of(other_admin.client)["roles"] == ["ADMIN"]


def test_guessing_totp_codes_over_several_logins_locks_the_account(
    client: TestClient, clock: FakeClock, email: FakeEmailGateway
) -> None:
    # Kẻ gian đã biết mật khẩu: mỗi lần đăng nhập được đoán vài mã, nhưng bộ đếm sai dồn lại.
    admin = bootstrap_admin(client, clock)
    officer = create_staff(admin, clock, email, "tindung1", ["CREDIT_OFFICER"])
    attacker = new_client(client)
    clock.advance(seconds=30)
    right = totp_code(officer.totp_secret, clock.now())
    wrong = "000000" if right != "000000" else "111111"

    for _ in range(2):
        attacker.post("/auth/login", json={"username": "tindung1", "password": NEW_PASSWORD})
        for _ in range(3):
            attacker.post("/auth/otp/verify", json={"code": wrong})
        clock.advance(minutes=1)

    locked = attacker.post("/auth/login", json={"username": "tindung1", "password": NEW_PASSWORD})
    assert locked.status_code == 401
    assert "khóa" in locked.json()["detail"]
