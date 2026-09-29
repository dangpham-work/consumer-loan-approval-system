"""Seam 1: UC23 Phê duyệt, UC24 Từ chối / Trả về, SUC01, snapshot HMAC, màn hình M07 (ticket #8)."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from loan_system.adapters.email import FakeEmailGateway
from loan_system.adapters.sms import FakeSmsGateway
from tests.api.test_appraisal import PHONE, appraising, open_appraisal, report, status_of
from tests.api.workflow import (
    Team,
    customer_browser,
    notifications_of,
    submitted_application,
    verify_as,
)
from tests.conftest import FakeClock


@pytest.fixture
def team(client: TestClient, clock: FakeClock, email: FakeEmailGateway) -> Team:
    return Team(client, clock, email)


@pytest.fixture
def customer(client: TestClient, sms: FakeSmsGateway) -> TestClient:
    return customer_browser(client, sms, phone=PHONE)


def pending_approval(
    team: Team, customer: TestClient, loan: dict[str, Any] | None = None, **proposal: Any
) -> str:
    """Hồ sơ vay đã có tờ trình thẩm định, đang chờ phê duyệt."""
    app_id = appraising(team, customer, loan)
    appraiser = team.appraiser.client
    open_appraisal(appraiser, app_id)
    appraiser.post(f"/applications/{app_id}/appraisal", json=report(**proposal)).raise_for_status()
    return app_id


def approval_screen(approver: TestClient, app_id: str) -> dict[str, Any]:
    response = approver.get(f"/applications/{app_id}/approval")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def test_approver_approves_and_the_approved_snapshot_is_signed(
    team: Team, customer: TestClient, sms: FakeSmsGateway
) -> None:
    disburser = team.disburser.client
    approver = team.approver.client
    app_id = pending_approval(team, customer)

    screen = approval_screen(approver, app_id)
    assert screen["can_decide"] is True
    assert (screen["required_approvals"], screen["approvals"]) == (1, 0)
    assert screen["report"]["proposed_amount"] == "25000000"
    assert screen["score"]["grade"] == "A"
    assert screen["application"]["applicant"]["national_id"] == "079******234"  # dữ liệu đã che

    approved = approver.post(
        f"/applications/{app_id}/approve", json={"comment": "Đồng ý theo tờ trình."}
    )

    assert approved.status_code == 200, approved.text
    body = approved.json()
    assert body["application"]["status"] == "APPROVED"
    assert (body["approved_amount"], body["approved_term"]) == ("25000000", 12)
    assert body["can_decide"] is False
    [decision] = body["decisions"]
    assert (decision["decision"], decision["approver"], decision["comment"]) == (
        "APPROVE", "Nhân viên pheduyet1", "Đồng ý theo tờ trình."
    )
    # SR08: HMAC-SHA256 của snapshot, kèm phiên bản khóa đã dùng (4.2.5).
    assert decision["key_version"] == 1
    assert len(decision["snapshot_hash"]) == 64
    assert status_of(customer, app_id) == "APPROVED"
    assert "đã được phê duyệt: 25.000.000 đồng, 12 tháng." in sms.last_to(PHONE).message
    assert any(n["type"] == "APPLICATION_APPROVED" for n in notifications_of(disburser))


def test_st02_credit_officer_calling_the_approval_api_is_forbidden(
    team: Team, customer: TestClient
) -> None:
    app_id = pending_approval(team, customer)
    officer = team.officer.client

    approve = officer.post(f"/applications/{app_id}/approve", json={})
    reject = officer.post(
        f"/applications/{app_id}/reject",
        json={"reason_group": "OTHER", "description": "Tự ý từ chối hồ sơ vay này."},
    )

    assert approve.status_code == reject.status_code == 403  # thiếu LOAN_APPROVE, LOAN_REJECT
    assert status_of(customer, app_id) == "PENDING_APPROVAL"
    denied = team.auditor.client.get("/audit/logs", params={"action": "ACCESS_DENIED"}).json()
    assert len(denied) >= 2


def test_st03_manager_cannot_approve_an_application_they_received(
    team: Team, customer: TestClient
) -> None:
    auditor = team.auditor.client
    both = team.hire("tindung_pheduyet", "CREDIT_OFFICER", "APPROVER")
    app_id = submitted_application(customer)
    assert verify_as(both.client, app_id).status_code == 200
    open_appraisal(team.appraiser.client, app_id)
    team.appraiser.client.post(f"/applications/{app_id}/appraisal", json=report()).raise_for_status()

    assert approval_screen(both.client, app_id)["can_decide"] is False
    response = both.client.post(f"/applications/{app_id}/approve", json={})

    assert response.status_code == 403  # SUC01, BR06
    assert status_of(customer, app_id) == "PENDING_APPROVAL"
    violations = auditor.get("/audit/logs", params={"action": "SOD_VIOLATION"}).json()
    assert [(v["level"], v["target_id"]) for v in violations] == [("WARNING", app_id)]
    assert any(n["type"] == "SOD_VIOLATION" for n in notifications_of(auditor))
    # Quản lý khác vẫn phê duyệt được.
    team.approver.client.post(f"/applications/{app_id}/approve", json={}).raise_for_status()


def test_the_appraiser_cannot_also_approve(team: Team, customer: TestClient) -> None:
    both = team.hire("thamdinh_pheduyet", "APPRAISER", "APPROVER")
    app_id = appraising(team, customer)
    open_appraisal(both.client, app_id)
    both.client.post(f"/applications/{app_id}/appraisal", json=report()).raise_for_status()

    assert both.client.post(f"/applications/{app_id}/approve", json={}).status_code == 403


def test_rejection_tells_the_customer_only_the_reason_group(
    team: Team, customer: TestClient, sms: FakeSmsGateway
) -> None:
    app_id = pending_approval(team, customer)
    description = "Thu nhập thực tế thấp hơn khai báo theo xác minh nội bộ."

    rejected = team.approver.client.post(
        f"/applications/{app_id}/reject",
        json={"reason_group": "FINANCIAL_CAPACITY", "description": description},
    )

    assert rejected.status_code == 200, rejected.text
    [decision] = rejected.json()["decisions"]
    assert (decision["decision"], decision["reason_group"], decision["comment"]) == (
        "REJECT", "FINANCIAL_CAPACITY", description
    )
    assert decision["snapshot_hash"] is None
    assert status_of(customer, app_id) == "REJECTED"
    message = sms.last_to(PHONE).message
    assert "Lý do: năng lực tài chính" in message
    assert description not in message
    assert any(n["type"] == "APPLICATION_REJECTED" for n in notifications_of(customer))


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("reject", {"reason_group": "OTHER", "description": "   "}),
        ("reject", {"description": "Không đủ điều kiện vay vốn."}),
        ("return", {"clarification": "Làm rõ"}),
    ],
)
def test_rejection_and_return_need_a_reason(
    team: Team, customer: TestClient, path: str, body: dict[str, Any]
) -> None:
    app_id = pending_approval(team, customer)

    response = team.approver.client.post(f"/applications/{app_id}/{path}", json=body)

    assert response.status_code == 400  # UC24 2a
    assert status_of(customer, app_id) == "PENDING_APPROVAL"


def test_returned_application_is_appraised_again_and_old_decisions_no_longer_count(
    team: Team, customer: TestClient
) -> None:
    approver, appraiser = team.approver.client, team.appraiser.client
    app_id = pending_approval(team, customer)
    clarification = "Cần làm rõ nguồn thu nhập thêm ngoài lương."

    returned = approver.post(f"/applications/{app_id}/return", json={"clarification": clarification})

    assert returned.status_code == 200, returned.text
    assert status_of(customer, app_id) == "APPRAISING"
    [notice] = [n for n in notifications_of(appraiser) if n["type"] == "APPLICATION_RETURNED"]
    assert clarification in notice["content"]
    # Người thẩm định lập tờ trình mới với hạn mức thấp hơn; cùng Quản lý được quyết định lại.
    open_appraisal(appraiser, app_id)
    appraiser.post(
        f"/applications/{app_id}/appraisal", json=report(proposed_amount=20_000_000)
    ).raise_for_status()
    screen = approval_screen(approver, app_id)
    assert (screen["can_decide"], screen["approvals"]) == (True, 0)
    assert screen["report"]["proposed_amount"] == "20000000"
    assert [d["superseded"] for d in screen["decisions"]] == [True]

    approved = approver.post(f"/applications/{app_id}/approve", json={})

    assert approved.status_code == 200, approved.text
    assert approved.json()["approved_amount"] == "20000000"
    assert [(d["decision"], d["superseded"]) for d in approved.json()["decisions"]] == [
        ("RETURN", True), ("APPROVE", False)
    ]


def test_a_rejection_proposal_cannot_be_approved(team: Team, customer: TestClient) -> None:
    app_id = pending_approval(
        team, customer, recommendation="REJECT", proposed_amount=None, proposed_term=None
    )
    approver = team.approver.client

    refused = approver.post(f"/applications/{app_id}/approve", json={})

    assert refused.status_code == 409
    assert status_of(customer, app_id) == "PENDING_APPROVAL"
    approver.post(
        f"/applications/{app_id}/reject",
        json={"reason_group": "FRAUD_SUSPECTED", "description": "Đồng ý với đề xuất từ chối."},
    ).raise_for_status()


def test_decisions_only_while_pending_approval(team: Team, customer: TestClient) -> None:
    approver = team.approver.client
    app_id = appraising(team, customer)

    assert approver.post(f"/applications/{app_id}/approve", json={}).status_code == 409
    assert approver.get(f"/applications/{app_id}/approval").status_code == 409

    open_appraisal(team.appraiser.client, app_id)
    team.appraiser.client.post(f"/applications/{app_id}/appraisal", json=report()).raise_for_status()
    approver.post(f"/applications/{app_id}/approve", json={}).raise_for_status()
    again = approver.post(
        f"/applications/{app_id}/return", json={"clarification": "Muốn xem lại tờ trình."}
    )
    assert again.status_code == 409
