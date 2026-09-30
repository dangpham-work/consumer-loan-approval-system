"""Seam 1 (trang HTML qua TestClient): M09 Quản trị người dùng và chính sách.

UC04 Quản lý tài khoản nhân viên, UC05 Quản lý vai trò – quyền, UC06 Cấu hình chính sách phê duyệt;
dùng lại tầng nghiệp vụ của ticket #3 và #16. Mọi thao tác ghi yêu cầu nhập lại mã TOTP (SR02).
"""

import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, update

from loan_system.adapters.email import FakeEmailGateway
from loan_system.repositories.models import ApprovalPolicy, ApprovalPolicyTier
from tests.api.staff import Staff, ctx_of, otp
from tests.api.test_web_login import assert_forms_carry_csrf, submit
from tests.api.workflow import Team
from tests.conftest import FakeClock


@pytest.fixture
def team(client: TestClient, clock: FakeClock, email: FakeEmailGateway) -> Team:
    return Team(client, clock, email)


def user_path(page_text: str, username: str) -> str:
    """Đường dẫn trang đổi vai trò của nhân viên `username` trong danh sách tài khoản."""
    row = re.search(rf"<tr>(?:(?!</tr>).)*{re.escape(username)}(?:(?!</tr>).)*</tr>", page_text,
                    re.S)
    assert row, f"danh sách không có {username}"
    found = re.search(r'href="(/app/admin/users/[0-9a-f-]+)"', row.group(0))
    assert found, f"hàng {username} không có liên kết đổi vai trò"
    return found.group(1)


def new_staff_form(admin: Staff, clock: FakeClock, **overrides: str) -> dict[str, str]:
    form = {
        "username": "tindung9", "full_name": "Nhân viên mới", "email": "tindung9@cty.vn",
        "branch": "Hà Nội", "roles": "CREDIT_OFFICER", "otp": otp(clock, admin.totp_secret),
    }
    form.update(overrides)
    return form


def test_admin_lists_staff_and_creates_an_account_with_a_step_up_code(
    team: Team, clock: FakeClock, email: FakeEmailGateway,
) -> None:
    admin = team.admin
    team.officer  # noqa: B018 — tạo sẵn một nhân viên

    page = admin.client.get("/app/admin")
    assert page.status_code == 200
    assert "quantri" in page.text and "tindung1" in page.text
    assert "Đang hoạt động" in page.text
    assert 'name="otp"' in page.text
    assert_forms_carry_csrf(admin.client, page.text)

    created = submit(admin.client, "/app/admin/users", new_staff_form(admin, clock))

    assert created.status_code == 200
    assert "Đã tạo tài khoản nhân viên" in created.text
    assert "tindung9" in created.text
    assert "Chờ kích hoạt" in created.text
    assert "Mật khẩu tạm" in email.last_to("tindung9@cty.vn").body


def test_a_wrong_step_up_code_or_a_taken_username_creates_nothing(
    team: Team, clock: FakeClock,
) -> None:
    admin = team.admin

    wrong = submit(admin.client, "/app/admin/users", new_staff_form(admin, clock, otp="000000"))
    assert wrong.status_code == 403
    assert "Mã OTP không đúng" in wrong.text
    assert 'value="tindung9"' in wrong.text  # giữ lại các ô đã nhập
    assert "tindung9" not in admin.client.get("/app/admin").text

    invalid = submit(admin.client, "/app/admin/users",
                     new_staff_form(admin, clock, username="9x", roles=""))
    assert invalid.status_code == 400
    assert "Tên đăng nhập" in invalid.text
    assert "Chọn ít nhất một vai trò" in invalid.text

    taken = submit(admin.client, "/app/admin/users", new_staff_form(admin, clock, username="quantri"))
    assert taken.status_code == 409
    assert "Tên đăng nhập hoặc email đã được dùng" in taken.text


def test_admin_changes_the_roles_of_a_staff_member(team: Team, clock: FakeClock) -> None:
    admin, officer = team.admin, team.officer
    path = user_path(admin.client.get("/app/admin").text, "tindung1")

    page = admin.client.get(path)
    assert page.status_code == 200
    assert 'value="CREDIT_OFFICER" checked' in page.text

    changed = submit(admin.client, f"{path}/roles",
                     {"roles": "APPRAISER", "otp": otp(clock, admin.totp_secret)})

    assert changed.status_code == 200
    assert "Đã cập nhật vai trò" in changed.text
    assert officer.client.get("/auth/session").json()["roles"] == ["APPRAISER"]


def test_admin_cannot_grant_a_lending_role_to_themself(team: Team, clock: FakeClock) -> None:
    admin = team.admin
    path = user_path(admin.client.get("/app/admin").text, "quantri")

    denied = admin.client.post(f"{path}/roles", data={
        "roles": "APPROVER", "otp": otp(clock, admin.totp_secret),
        "csrf": admin.client.cookies["csrf"],
    })

    assert denied.status_code == 403
    assert "Bạn không có quyền thực hiện thao tác này" in denied.text


def test_admin_creates_a_role_and_changes_its_permissions(team: Team, clock: FakeClock) -> None:
    # Vai trò không bị xóa giữa các test (dữ liệu gốc RBAC): dùng mã riêng cho test này.
    admin = team.admin

    page = admin.client.get("/app/admin/roles")
    assert page.status_code == 200
    assert "AUDITOR" in page.text and "AUDIT_VERIFY" in page.text
    assert 'name="permissions" value="REPORT_VIEW"' in page.text

    created = admin.client.post("/app/admin/roles", data={
        "code": "WEB_REPORTER", "name": "Người xem báo cáo", "permissions": ["REPORT_VIEW"],
        "otp": otp(clock, admin.totp_secret), "csrf": admin.client.cookies["csrf"],
    })
    assert created.status_code == 200
    assert "Đã tạo vai trò" in created.text
    assert "WEB_REPORTER" in created.text

    conflict = admin.client.post("/app/admin/roles/WEB_REPORTER/permissions", data={
        "permissions": ["APPRAISAL_SUBMIT", "LOAN_APPROVE"],
        "otp": otp(clock, admin.totp_secret), "csrf": admin.client.cookies["csrf"],
    })
    assert conflict.status_code == 400
    assert "không được gán cho cùng một vai trò" in conflict.text

    edit = admin.client.get("/app/admin/roles/WEB_REPORTER")
    assert edit.status_code == 200
    assert 'value="REPORT_VIEW" checked' in edit.text
    changed = admin.client.post("/app/admin/roles/WEB_REPORTER/permissions", data={
        "permissions": ["REPORT_VIEW", "CREDIT_SCORE_VIEW"],
        "otp": otp(clock, admin.totp_secret), "csrf": admin.client.cookies["csrf"],
    })
    assert changed.status_code == 200
    assert "Đã cập nhật quyền" in changed.text
    roles = {r["code"]: r["permissions"] for r in admin.client.get("/admin/roles").json()}
    assert set(roles["WEB_REPORTER"]) == {"REPORT_VIEW", "CREDIT_SCORE_VIEW"}


POLICY_FORM = {
    "rate_grade_a": "19", "rate_grade_b": "23", "rate_grade_c": "28",
    "prepayment_fee_rate": "2",
    "tier_min": ["5000000", "50000001", ""], "tier_max": ["50000000", "100000000", ""],
    "tier_approvals": ["1", "2", ""],
}


def test_admin_saves_a_new_policy_version_from_the_policy_table(
    team: Team, clock: FakeClock, client: TestClient,
) -> None:
    admin = team.admin
    page = admin.client.get("/app/admin/policies")
    assert page.status_code == 200
    assert "Phiên bản 1" in page.text
    assert "Đang hiệu lực" in page.text
    assert 'name="tier_min"' in page.text
    assert_forms_carry_csrf(admin.client, page.text)

    try:
        saved = admin.client.post("/app/admin/policies", data={
            **POLICY_FORM, "otp": otp(clock, admin.totp_secret),
            "csrf": admin.client.cookies["csrf"],
        })
        assert saved.status_code == 200
        assert "Đã lưu phiên bản chính sách mới" in saved.text
        assert "Phiên bản 2" in saved.text
        versions = {v["version"]: v for v in admin.client.get("/admin/policies").json()}
        assert versions[2]["is_active"] is True
        assert versions[1]["is_active"] is False
        assert versions[2]["rate_grade_a"] == "0.1900"
        assert len(versions[2]["tiers"]) == 2
    finally:
        # approval_policies không bị xóa giữa các test: khôi phục phiên bản 1 như
        # test_role_policy_admin.py.
        with ctx_of(client).session_factory() as db:
            new_id = db.scalars(
                select(ApprovalPolicy.id).where(ApprovalPolicy.version == 2)
            ).one_or_none()
            if new_id is not None:
                db.execute(delete(ApprovalPolicyTier).where(ApprovalPolicyTier.policy_id == new_id))
                db.execute(delete(ApprovalPolicy).where(ApprovalPolicy.id == new_id))
            db.execute(update(ApprovalPolicy).where(ApprovalPolicy.version == 1)
                       .values(is_active=True))
            db.commit()


def test_gapped_policy_tiers_are_rejected_without_saving(team: Team, clock: FakeClock) -> None:
    admin = team.admin
    admin.client.get("/app/admin/policies")

    rejected = admin.client.post("/app/admin/policies", data={
        **POLICY_FORM, "tier_min": ["5000000", "60000000"], "tier_max": ["50000000", "100000000"],
        "tier_approvals": ["1", "2"], "otp": otp(clock, admin.totp_secret),
        "csrf": admin.client.cookies["csrf"],
    })

    assert rejected.status_code == 400
    assert 'value="60000000"' in rejected.text  # giữ lại bảng đã nhập
    assert len(admin.client.get("/admin/policies").json()) == 1


def test_only_the_administrator_opens_m09(team: Team) -> None:
    for staff in (team.officer, team.auditor):
        for path in ("/app/admin", "/app/admin/roles", "/app/admin/policies"):
            assert staff.client.get(path).status_code == 403, (staff.username, path)
    assert 'href="/app/admin"' in team.admin.client.get("/app").text
    assert 'href="/app/admin"' not in team.officer.client.get("/app").text


def test_a_policy_only_role_reaches_m09_from_the_menu(team: Team, clock: FakeClock) -> None:
    # Vai trò tùy biến chỉ có POLICY_CONFIGURE (UC05): mục "Quản trị" dẫn thẳng tới thẻ chính sách.
    admin = team.admin
    admin.client.get("/app/admin/roles")
    created = admin.client.post("/app/admin/roles", data={
        "code": "WEB_POLICY_ONLY", "name": "Quản lý rủi ro", "permissions": ["POLICY_CONFIGURE"],
        "otp": otp(clock, admin.totp_secret), "csrf": admin.client.cookies["csrf"],
    })
    assert created.status_code == 200
    risk = team.hire("ruiro1", "WEB_POLICY_ONLY")

    home = risk.client.get("/app")
    assert 'href="/app/admin/policies"' in home.text
    assert 'href="/app/admin"' not in home.text
    assert home.text.count(">Quản trị<") == 1
    assert risk.client.get("/app/admin/policies").status_code == 200
