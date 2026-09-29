"""Seam 1: UC05 Quản lý vai trò – quyền, UC06 Cấu hình chính sách phê duyệt (ticket #16)."""

from decimal import Decimal
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import delete, select, update

from loan_system.adapters.email import FakeEmailGateway
from loan_system.repositories.models import ApprovalPolicy, ApprovalPolicyTier
from tests.api.staff import bootstrap_admin, create_staff, ctx_of, otp
from tests.conftest import FakeClock

DEFAULT_TIERS = [
    {"min_amount": 5_000_000, "max_amount": 50_000_000, "required_approvals": 1},
    {"min_amount": 50_000_001, "max_amount": 100_000_000, "required_approvals": 2},
]


def new_role(admin: Any, clock: FakeClock, code: str, **overrides: Any) -> dict[str, Any]:
    # roles/permissions/role_permissions không bị xóa giữa các test (dữ liệu gốc RBAC, xem
    # tests/conftest.py); mỗi test dùng một mã vai trò riêng để không đụng vai trò của test khác.
    body: dict[str, Any] = {
        "code": code,
        "name": "Người xem báo cáo",
        "permissions": ["REPORT_VIEW"],
        "otp": otp(clock, admin.totp_secret),
    }
    body.update(overrides)
    return body


# --- UC05: vai trò – quyền -------------------------------------------------------------------


def test_admin_lists_roles_with_their_permissions_and_the_full_catalog(
    client: TestClient, clock: FakeClock
) -> None:
    admin = bootstrap_admin(client, clock)

    roles = admin.client.get("/admin/roles")
    assert roles.status_code == 200, roles.text
    by_code = {role["code"]: role["permissions"] for role in roles.json()}
    assert set(by_code["CREDIT_OFFICER"]) >= {"APPLICATION_CREATE", "APPLICATION_VERIFY"}
    assert set(by_code["AUDITOR"]) == {"AUDIT_VIEW", "AUDIT_VERIFY", "APPLICATION_LOCK_RESOLVE"}

    permissions = admin.client.get("/admin/permissions")
    assert permissions.status_code == 200, permissions.text
    codes = {p["code"] for p in permissions.json()}
    assert {"ROLE_MANAGE", "POLICY_CONFIGURE", "LOAN_APPROVE", "DISBURSE"} <= codes


def test_non_role_manager_cannot_read_or_write_roles(
    client: TestClient, clock: FakeClock, email: FakeEmailGateway
) -> None:
    admin = bootstrap_admin(client, clock)
    officer = create_staff(admin, clock, email, "tindung1", ["CREDIT_OFFICER"])

    assert officer.client.get("/admin/roles").status_code == 403
    assert officer.client.post(
        "/admin/roles", json=new_role(officer, clock, "NON_MANAGER_TEST")
    ).status_code == 403


def test_admin_creates_a_role_and_can_edit_its_permissions_later(
    client: TestClient, clock: FakeClock
) -> None:
    admin = bootstrap_admin(client, clock)

    created = admin.client.post("/admin/roles", json=new_role(admin, clock, "REPORT_VIEWER"))
    assert created.status_code == 201, created.text

    roles = admin.client.get("/admin/roles").json()
    assert {"code": "REPORT_VIEWER", "name": "Người xem báo cáo", "permissions": ["REPORT_VIEW"]} in roles

    updated = admin.client.put(
        "/admin/roles/REPORT_VIEWER/permissions",
        json={"permissions": ["REPORT_VIEW", "AUDIT_VIEW"], "otp": otp(clock, admin.totp_secret)},
    )
    assert updated.status_code == 200, updated.text
    roles_after = {r["code"]: r["permissions"] for r in admin.client.get("/admin/roles").json()}
    assert sorted(roles_after["REPORT_VIEWER"]) == ["AUDIT_VIEW", "REPORT_VIEW"]


def test_creating_a_role_requires_a_fresh_totp_code(client: TestClient, clock: FakeClock) -> None:
    admin = bootstrap_admin(client, clock)

    response = admin.client.post(
        "/admin/roles", json=new_role(admin, clock, "FRESH_OTP_TEST", otp="000000")
    )
    assert response.status_code == 403


def test_duplicate_role_code_is_rejected(client: TestClient, clock: FakeClock) -> None:
    admin = bootstrap_admin(client, clock)
    admin.client.post(
        "/admin/roles", json=new_role(admin, clock, "DUPLICATE_ROLE_TEST")
    ).raise_for_status()

    again = admin.client.post("/admin/roles", json=new_role(admin, clock, "DUPLICATE_ROLE_TEST"))
    assert again.status_code == 409


def test_unknown_permission_code_is_rejected(client: TestClient, clock: FakeClock) -> None:
    admin = bootstrap_admin(client, clock)

    response = admin.client.post(
        "/admin/roles",
        json=new_role(
            admin, clock, "UNKNOWN_PERMISSION_TEST", permissions=["NOT_A_REAL_PERMISSION"]
        ),
    )
    assert response.status_code == 400


def test_a_role_cannot_combine_two_permissions_of_the_sod_chain(
    client: TestClient, clock: FakeClock
) -> None:
    # UC05 4a: thẩm định và phê duyệt không được cùng một vai trò (BR06).
    admin = bootstrap_admin(client, clock)

    response = admin.client.post(
        "/admin/roles",
        json=new_role(
            admin, clock, "SOD_CREATE_TEST", permissions=["APPRAISAL_SUBMIT", "LOAN_APPROVE"]
        ),
    )
    assert response.status_code == 400
    assert "APPRAISAL_SUBMIT" in response.text and "LOAN_APPROVE" in response.text

    admin.client.post(
        "/admin/roles", json=new_role(admin, clock, "SOD_UPDATE_TEST")
    ).raise_for_status()
    conflict_on_update = admin.client.put(
        "/admin/roles/SOD_UPDATE_TEST/permissions",
        json={
            "permissions": ["LOAN_APPROVE", "DISBURSE"], "otp": otp(clock, admin.totp_secret),
        },
    )
    assert conflict_on_update.status_code == 400


def test_editing_permissions_of_an_unknown_role_is_404(client: TestClient, clock: FakeClock) -> None:
    admin = bootstrap_admin(client, clock)

    response = admin.client.put(
        "/admin/roles/NOT_A_ROLE/permissions",
        json={"permissions": ["REPORT_VIEW"], "otp": otp(clock, admin.totp_secret)},
    )
    assert response.status_code == 404


def test_the_admin_role_cannot_be_given_a_lending_permission_directly(
    client: TestClient, clock: FakeClock
) -> None:
    # UC05: sửa thẳng quyền của vai trò ADMIN không được lách quy tắc "ADMIN không có quyền
    # nghiệp vụ cho vay" mà mixes_admin_and_lending vốn chặn ở bước gán vai trò (ticket #3).
    admin = bootstrap_admin(client, clock)

    response = admin.client.put(
        "/admin/roles/ADMIN/permissions",
        json={
            "permissions": ["USER_MANAGE", "ROLE_MANAGE", "POLICY_CONFIGURE", "LOAN_APPROVE"],
            "otp": otp(clock, admin.totp_secret),
        },
    )
    assert response.status_code == 400
    assert "LOAN_APPROVE" in response.text
    # Không có gì bị đổi: ADMIN vẫn giữ đúng quyền quản trị ban đầu.
    admin_permissions = next(
        r["permissions"] for r in admin.client.get("/admin/roles").json() if r["code"] == "ADMIN"
    )
    assert "LOAN_APPROVE" not in admin_permissions


# --- UC06: chính sách phê duyệt ---------------------------------------------------------------


def new_policy(admin: Any, clock: FakeClock, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "rate_grade_a": "0.19",
        "rate_grade_b": "0.23",
        "rate_grade_c": "0.27",
        "prepayment_fee_rate": "0.02",
        "tiers": DEFAULT_TIERS,
        "otp": otp(clock, admin.totp_secret),
    }
    body.update(overrides)
    return body


def test_admin_lists_the_default_policy_version(client: TestClient, clock: FakeClock) -> None:
    admin = bootstrap_admin(client, clock)

    policies = admin.client.get("/admin/policies")
    assert policies.status_code == 200, policies.text
    versions = policies.json()
    assert len(versions) == 1
    assert versions[0]["version"] == 1
    assert versions[0]["is_active"] is True
    assert Decimal(versions[0]["rate_grade_a"]) == Decimal("0.2")


def test_non_policy_manager_cannot_configure_policies(
    client: TestClient, clock: FakeClock, email: FakeEmailGateway
) -> None:
    admin = bootstrap_admin(client, clock)
    officer = create_staff(admin, clock, email, "tindung1", ["CREDIT_OFFICER"])

    assert officer.client.get("/admin/policies").status_code == 403
    assert officer.client.post("/admin/policies", json=new_policy(officer, clock)).status_code == 403


def test_configuring_a_policy_requires_a_fresh_totp_code(client: TestClient, clock: FakeClock) -> None:
    admin = bootstrap_admin(client, clock)

    response = admin.client.post("/admin/policies", json=new_policy(admin, clock, otp="000000"))
    assert response.status_code == 403


def test_overlapping_tiers_are_rejected_without_saving(client: TestClient, clock: FakeClock) -> None:
    admin = bootstrap_admin(client, clock)
    overlapping = [
        {"min_amount": 5_000_000, "max_amount": 60_000_000, "required_approvals": 1},
        {"min_amount": 50_000_000, "max_amount": 100_000_000, "required_approvals": 2},
    ]

    response = admin.client.post("/admin/policies", json=new_policy(admin, clock, tiers=overlapping))
    assert response.status_code == 400
    # Không có gì được lưu: vẫn chỉ một phiên bản, hiệu lực từ trước.
    assert len(admin.client.get("/admin/policies").json()) == 1


def test_gapped_tiers_are_rejected_without_saving(client: TestClient, clock: FakeClock) -> None:
    admin = bootstrap_admin(client, clock)
    gapped = [
        {"min_amount": 5_000_000, "max_amount": 40_000_000, "required_approvals": 1},
        {"min_amount": 50_000_000, "max_amount": 100_000_000, "required_approvals": 2},
    ]

    response = admin.client.post("/admin/policies", json=new_policy(admin, clock, tiers=gapped))
    assert response.status_code == 400
    assert len(admin.client.get("/admin/policies").json()) == 1


def test_admin_saves_a_new_policy_version_that_becomes_active(
    client: TestClient, clock: FakeClock
) -> None:
    # approval_policies không được xóa giữa các test (dữ liệu gốc theo migration); khôi phục lại
    # bản đang hiệu lực sau khi test xong để không ảnh hưởng đến các test khác trong cùng phiên.
    admin = bootstrap_admin(client, clock)
    ctx = ctx_of(client)

    try:
        created = admin.client.post("/admin/policies", json=new_policy(admin, clock))
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["version"] == 2
        assert body["is_active"] is True
        assert Decimal(body["rate_grade_a"]) == Decimal("0.19")
        assert [
            (Decimal(t["min_amount"]), Decimal(t["max_amount"]), t["required_approvals"])
            for t in body["tiers"]
        ] == [
            (Decimal(5_000_000), Decimal(50_000_000), 1),
            (Decimal(50_000_001), Decimal(100_000_000), 2),
        ]

        versions = admin.client.get("/admin/policies").json()
        assert {v["version"]: v["is_active"] for v in versions} == {1: False, 2: True}
    finally:
        with ctx.session_factory() as db:
            new_policy_id = db.scalars(
                select(ApprovalPolicy.id).where(ApprovalPolicy.version == 2)
            ).one_or_none()
            if new_policy_id is not None:
                db.execute(
                    delete(ApprovalPolicyTier).where(ApprovalPolicyTier.policy_id == new_policy_id)
                )
                db.execute(delete(ApprovalPolicy).where(ApprovalPolicy.id == new_policy_id))
            db.execute(update(ApprovalPolicy).where(ApprovalPolicy.version == 1).values(is_active=True))
            db.commit()
