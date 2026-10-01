"""Seam 1: Phê duyệt kép (BR05, UC23 6a, 6b), quy tắc gộp AD04 và khóa lạc quan (ticket #9)."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from loan_system.adapters.email import FakeEmailGateway
from loan_system.adapters.sms import FakeSmsGateway
from tests.api.test_appraisal import PHONE, open_appraisal, report, status_of
from tests.api.test_approval import approval_screen, decide, pending_approval
from tests.api.workflow import Team, customer_browser, notifications_of
from tests.conftest import FakeClock

BIG_LOAN = {"requested_amount": 80_000_000, "term_months": 24, "purpose": "CONSUMER_GOODS"}


@pytest.fixture
def team(client: TestClient, clock: FakeClock, email: FakeEmailGateway) -> Team:
    return Team(client, clock, email)


@pytest.fixture
def customer(client: TestClient, sms: FakeSmsGateway) -> TestClient:
    return customer_browser(client, sms, phone=PHONE)


def big_loan(team: Team, customer: TestClient) -> str:
    """Hồ sơ vay 80 triệu chờ phê duyệt: trên 50 triệu nên cần hai Quản lý phê duyệt (BR05)."""
    return pending_approval(
        team, customer, BIG_LOAN, proposed_amount=80_000_000, proposed_term=24
    )


def test_tc02_a_loan_over_50_million_waits_for_a_second_approver(
    team: Team, customer: TestClient, sms: FakeSmsGateway, clock: FakeClock
) -> None:
    first, second = team.approver.client, team.approver2.client
    app_id = big_loan(team, customer)

    screen = approval_screen(first, app_id)
    assert (screen["required_approvals"], screen["approvals"]) == (2, 0)
    once = first.post(
        f"/applications/{app_id}/approve", json={"version": screen["version"]}
    )

    assert once.status_code == 200, once.text
    assert once.json()["application"]["status"] == "PENDING_APPROVAL"
    assert (once.json()["approvals"], once.json()["can_decide"]) == (1, False)
    assert status_of(customer, app_id) == "PENDING_APPROVAL"
    # UC23 6a: Quản lý thứ hai được báo, người vừa duyệt thì không; chưa có snapshot vì hồ sơ
    # vay chưa được duyệt.
    assert any(n["type"] == "APPROVAL_NEEDED" for n in notifications_of(second))
    assert not any(n["type"] == "APPROVAL_NEEDED" for n in notifications_of(first))
    [decision] = once.json()["decisions"]
    assert decision["snapshot_hash"] is None

    clock.advance(minutes=5)  # Quản lý thứ hai xem hồ sơ vay sau
    screen = approval_screen(second, app_id)
    assert (screen["approvals"], screen["can_decide"]) == (1, True)
    twice = second.post(
        f"/applications/{app_id}/approve", json={"version": screen["version"]}
    )

    assert twice.status_code == 200, twice.text
    body = twice.json()
    assert body["application"]["status"] == "APPROVED"
    assert (body["approved_amount"], body["approved_term"]) == ("80000000", 24)
    # SR08: snapshot được ký trên quyết định làm hồ sơ vay được duyệt.
    assert [(d["approver"], d["snapshot_hash"] is not None) for d in body["decisions"]] == [
        ("Nhân viên pheduyet1", False), ("Nhân viên pheduyet2", True)
    ]
    assert "80.000.000 đồng, 24 tháng" in sms.last_to(PHONE).message


REASONS: dict[str, dict[str, Any]] = {
    "approve": {},
    "reject": {"reason_group": "CREDIT_HISTORY", "description": "Lịch sử tín dụng chưa đủ tốt."},
    "return": {"clarification": "Cần làm rõ nguồn thu nhập thêm ngoài lương."},
}


def decide_as(approver: TestClient, app_id: str, action: str) -> Any:
    """Quyết định kèm lý do hợp lệ cho Từ chối, Trả về."""
    return decide(approver, app_id, action, **REASONS[action])


@pytest.mark.parametrize("action", ["approve", "reject", "return"])
def test_uc23_6b_a_decision_made_on_a_stale_screen_is_refused(
    team: Team, customer: TestClient, action: str
) -> None:
    first, second = team.approver.client, team.approver2.client
    app_id = big_loan(team, customer)
    # Cả hai Quản lý cùng mở M07 khi chưa có phê duyệt nào.
    seen = approval_screen(second, app_id)["version"]
    assert decide_as(first, app_id, "approve").status_code == 200

    stale = second.post(
        f"/applications/{app_id}/{action}", json={"version": seen, **REASONS[action]}
    )

    assert stale.status_code == 409  # hồ sơ vay vừa được cập nhật, phải tải lại
    assert "vui lòng tải lại" in stale.json()["detail"]
    screen = approval_screen(second, app_id)
    assert (screen["approvals"], len(screen["decisions"])) == (1, 1)  # không ghi thêm gì
    assert decide_as(second, app_id, "approve").json()["application"]["status"] == "APPROVED"


@pytest.mark.parametrize(
    ("first_action", "second_action", "status"),
    [
        ("approve", "approve", "APPROVED"),
        ("approve", "reject", "REJECTED"),
        ("approve", "return", "APPRAISING"),
    ],
)
def test_the_second_decision_is_merged_with_the_first(
    team: Team, customer: TestClient, first_action: str, second_action: str, status: str
) -> None:
    # AD04: một Từ chối là từ chối, một Trả về đưa về thẩm định, đủ hai Phê duyệt thì duyệt.
    app_id = big_loan(team, customer)
    assert decide_as(team.approver.client, app_id, first_action).status_code == 200

    response = decide_as(team.approver2.client, app_id, second_action)

    assert response.status_code == 200, response.text
    assert status_of(customer, app_id) == status


@pytest.mark.parametrize(("action", "status"), [("reject", "REJECTED"), ("return", "APPRAISING")])
def test_a_first_rejection_or_return_needs_no_second_decision(
    team: Team, customer: TestClient, action: str, status: str
) -> None:
    app_id = big_loan(team, customer)

    assert decide_as(team.approver.client, app_id, action).status_code == 200

    assert status_of(customer, app_id) == status
    # Hồ sơ vay không còn chờ phê duyệt nên Quản lý thứ hai không quyết định được nữa.
    assert decide_as(team.approver2.client, app_id, "approve").status_code == 409


def test_one_manager_cannot_approve_twice(team: Team, customer: TestClient) -> None:
    approver, auditor = team.approver.client, team.auditor.client
    app_id = big_loan(team, customer)
    seen = approval_screen(approver, app_id)["version"]
    assert decide_as(approver, app_id, "approve").status_code == 200

    assert approval_screen(approver, app_id)["can_decide"] is False
    again = decide_as(approver, app_id, "approve")
    # Gửi lại đúng yêu cầu cũ: vẫn là vi phạm SoD, không chỉ là màn hình cũ.
    replayed = approver.post(f"/applications/{app_id}/approve", json={"version": seen})

    assert again.status_code == replayed.status_code == 403  # SUC01: hai người khác nhau
    assert status_of(customer, app_id) == "PENDING_APPROVAL"
    violations = auditor.get("/audit/logs", params={"action": "SOD_VIOLATION"}).json()
    assert len(violations) == 2


def test_a_return_voids_the_first_approval(team: Team, customer: TestClient) -> None:
    # CONTEXT.md: một Trả về làm vô hiệu mọi Quyết định phê duyệt trước đó; tờ trình mới lại cần
    # đủ hai Phê duyệt, và người đã quyết định trên tờ trình cũ được quyết định lại.
    first, second = team.approver.client, team.approver2.client
    appraiser = team.appraiser.client
    app_id = big_loan(team, customer)
    decide_as(first, app_id, "approve").raise_for_status()
    decide_as(second, app_id, "return").raise_for_status()
    open_appraisal(appraiser, app_id)
    appraiser.post(
        f"/applications/{app_id}/appraisal",
        json=report(proposed_amount=70_000_000, proposed_term=24),
    ).raise_for_status()

    after_first = decide_as(first, app_id, "approve").json()

    assert after_first["application"]["status"] == "PENDING_APPROVAL"
    assert (after_first["required_approvals"], after_first["approvals"]) == (2, 1)
    assert decide_as(second, app_id, "approve").json()["approved_amount"] == "70000000"


def test_a_decision_must_say_which_version_it_was_made_on(
    team: Team, customer: TestClient
) -> None:
    app_id = big_loan(team, customer)

    response = team.approver.client.post(f"/applications/{app_id}/approve", json={})

    assert response.status_code == 400
    assert approval_screen(team.approver.client, app_id)["approvals"] == 0
