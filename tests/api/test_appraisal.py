"""Seam 1: UC22 Thẩm định hồ sơ vay, SUC01 Phân tách nhiệm vụ, màn hình M06 (ticket #7)."""

from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from loan_system.adapters.email import FakeEmailGateway
from loan_system.adapters.sms import FakeSmsGateway
from tests.api.workflow import (
    FINANCES,
    Team,
    customer_browser,
    notifications_of,
    submitted_application,
    verify_as,
)
from tests.conftest import FakeClock

PHONE = "0901234567"
COMMENT = "Thu nhập ổn định, lịch sử tín dụng tốt, đề xuất duyệt."


@pytest.fixture
def team(client: TestClient, clock: FakeClock, email: FakeEmailGateway) -> Team:
    return Team(client, clock, email)


@pytest.fixture
def customer(client: TestClient, sms: FakeSmsGateway) -> TestClient:
    return customer_browser(client, sms, phone=PHONE)


def appraising(
    team: Team, customer: TestClient, loan: dict[str, Any] | None = None, **finances: Any
) -> str:
    """Hồ sơ vay đã chấm điểm, đang chờ thẩm định (CIC giả lập mặc định: nhóm 1, hạng A)."""
    app_id = submitted_application(customer, loan, **finances)
    assert verify_as(team.officer.client, app_id).status_code == 200
    assert status_of(customer, app_id) == "APPRAISING"
    return app_id


def status_of(customer: TestClient, app_id: str) -> str:
    status: str = customer.get(f"/applications/{app_id}").json()["status"]
    return status


def open_appraisal(appraiser: TestClient, app_id: str) -> dict[str, Any]:
    response = appraiser.post(f"/applications/{app_id}/appraisal/open")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def report(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "recommendation": "APPROVE",
        "proposed_amount": 25_000_000,
        "proposed_term": 12,
        "fraud_suspected": False,
        "comment": COMMENT,
    }
    body.update(overrides)
    return body


def test_appraiser_reviews_the_file_and_submits_a_report_for_approval(
    team: Team, customer: TestClient
) -> None:
    approver = team.approver.client
    app_id = appraising(team, customer)
    appraiser = team.appraiser.client

    view = open_appraisal(appraiser, app_id)

    # M06: CCCD và thu nhập hiển thị đầy đủ cho chuyên viên thẩm định.
    assert view["applicant"]["national_id"] == FINANCES["national_id"]
    assert Decimal(view["applicant"]["monthly_income"]) == Decimal(25_000_000)
    assert (view["score"]["score"], view["score"]["grade"]) == (930, "A")
    assert Decimal(view["annual_rate"]) == Decimal("0.20")

    submitted = appraiser.post(f"/applications/{app_id}/appraisal", json=report())
    assert submitted.status_code == 200, submitted.text

    assert status_of(customer, app_id) == "PENDING_APPROVAL"
    assert any(n["type"] == "APPLICATION_APPRAISED" for n in notifications_of(approver))
    latest = submitted.json()["report"]
    assert (latest["recommendation"], latest["proposed_amount"], latest["proposed_term"]) == (
        "APPROVE", "25000000", 12
    )
    # DTI tính lại theo lãi suất hạng A (20%): (2 triệu + 2.315.863) / 25 triệu ≈ 17,26%.
    assert Decimal(latest["dti"]) == Decimal("0.1726")
    assert submitted.json()["required_approvals"] == 1


def customer_id_of(customer: TestClient) -> str:
    customer_id: str = customer.get("/customers/me").json()["id"]
    return customer_id


def test_every_opening_of_the_appraisal_screen_logs_view_pii(
    team: Team, customer: TestClient
) -> None:
    app_id = appraising(team, customer)

    open_appraisal(team.appraiser.client, app_id)
    open_appraisal(team.appraiser.client, app_id)

    views = team.auditor.client.get(
        "/audit/logs", params={"action": "VIEW_PII", "target_id": customer_id_of(customer)}
    ).json()
    assert len(views) == 2


def test_proposal_above_50_percent_dti_is_refused_until_the_term_is_longer(
    team: Team, customer: TestClient
) -> None:
    # Thu nhập 10 triệu, đang trả 2 triệu, vay 30 triệu 36 kỳ: DTI ≈ 32% lúc chấm điểm. Rút kỳ hạn
    # xuống 6 tháng thì trả ≈ 5,3 triệu/kỳ, DTI ≈ 73% > 50% (UC22 5a).
    app_id = appraising(
        team, customer, {"term_months": 36}, monthly_income=10_000_000,
        existing_monthly_debt=2_000_000,
    )
    appraiser = team.appraiser.client
    open_appraisal(appraiser, app_id)

    preview = appraiser.get(
        f"/applications/{app_id}/appraisal/dti", params={"amount": 30_000_000, "term": 6}
    ).json()
    assert preview["within_limit"] is False

    refused = appraiser.post(
        f"/applications/{app_id}/appraisal",
        json=report(proposed_amount=30_000_000, proposed_term=6),
    )
    assert refused.status_code == 400
    assert "giảm hạn mức hoặc tăng kỳ hạn" in refused.json()["detail"]
    assert status_of(customer, app_id) == "APPRAISING"

    accepted = appraiser.post(
        f"/applications/{app_id}/appraisal",
        json=report(proposed_amount=30_000_000, proposed_term=24),
    )
    assert accepted.status_code == 200, accepted.text


def test_invalid_proposals_are_rejected_with_a_reason(team: Team, customer: TestClient) -> None:
    app_id = appraising(team, customer)
    appraiser = team.appraiser.client
    open_appraisal(appraiser, app_id)

    too_much = appraiser.post(
        f"/applications/{app_id}/appraisal", json=report(proposed_amount=31_000_000)
    )
    short = appraiser.post(f"/applications/{app_id}/appraisal", json=report(comment="Ổn."))

    assert too_much.status_code == short.status_code == 400
    assert too_much.json()["detail"] == "Hạn mức đề xuất vượt số tiền yêu cầu"
    assert short.json()["detail"] == "Nhận xét phải có ít nhất 20 ký tự"


def test_a_rejection_proposal_still_goes_to_the_approvers(
    team: Team, customer: TestClient
) -> None:
    app_id = appraising(team, customer)
    appraiser = team.appraiser.client
    open_appraisal(appraiser, app_id)

    submitted = appraiser.post(
        f"/applications/{app_id}/appraisal",
        json={
            "recommendation": "REJECT",
            "fraud_suspected": True,
            "comment": "Sao kê lương không khớp nơi làm việc khai báo, nghi khai man.",
        },
    )

    assert submitted.status_code == 200, submitted.text
    assert status_of(customer, app_id) == "PENDING_APPROVAL"  # UC22 4b
    latest = submitted.json()["report"]
    assert (latest["recommendation"], latest["proposed_amount"], latest["fraud_suspected"]) == (
        "REJECT", None, True
    )


@pytest.mark.parametrize(("proposed", "approvals"), [(50_000_000, 1), (60_000_000, 2)])
def test_required_approvals_follow_the_proposed_amount(
    team: Team, customer: TestClient, proposed: int, approvals: int
) -> None:
    # BR05: ≤ 50 triệu cần 1 Quản lý phê duyệt, > 50 triệu cần 2; theo hạn mức đề xuất.
    app_id = appraising(team, customer, {"requested_amount": 60_000_000, "term_months": 24})
    appraiser = team.appraiser.client
    open_appraisal(appraiser, app_id)

    submitted = appraiser.post(
        f"/applications/{app_id}/appraisal",
        json=report(proposed_amount=proposed, proposed_term=24),
    )

    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["required_approvals"] == approvals


def test_the_officer_who_received_the_file_cannot_appraise_it(
    team: Team, customer: TestClient
) -> None:
    auditor = team.auditor.client
    both = team.hire("tindung_thamdinh", "CREDIT_OFFICER", "APPRAISER")
    app_id = submitted_application(customer)
    assert verify_as(both.client, app_id).status_code == 200

    response = both.client.post(f"/applications/{app_id}/appraisal/open")

    assert response.status_code == 403  # SUC01, BR06
    assert any(n["type"] == "SOD_VIOLATION" for n in notifications_of(auditor))
    assert open_appraisal(team.appraiser.client, app_id)["status"] == "APPRAISING"


def test_one_appraiser_per_application(team: Team, customer: TestClient) -> None:
    app_id = appraising(team, customer)
    other = team.hire("thamdinh2", "APPRAISER").client

    not_opened = other.post(f"/applications/{app_id}/appraisal", json=report())
    open_appraisal(team.appraiser.client, app_id)
    taken = other.post(f"/applications/{app_id}/appraisal/open")

    assert not_opened.status_code == 403
    assert taken.status_code == 409


def test_only_appraisers_can_appraise_and_only_while_appraising(
    team: Team, customer: TestClient
) -> None:
    app_id = appraising(team, customer)

    assert team.officer.client.post(f"/applications/{app_id}/appraisal/open").status_code == 403
    assert team.approver.client.post(f"/applications/{app_id}/appraisal/open").status_code == 403

    appraiser = team.appraiser.client
    open_appraisal(appraiser, app_id)
    appraiser.post(f"/applications/{app_id}/appraisal", json=report()).raise_for_status()
    assert appraiser.post(f"/applications/{app_id}/appraisal/open").status_code == 409


def test_dti_preview_refuses_an_amount_above_the_request(team: Team, customer: TestClient) -> None:
    app_id = appraising(team, customer)
    appraiser = team.appraiser.client
    open_appraisal(appraiser, app_id)

    preview = appraiser.get(
        f"/applications/{app_id}/appraisal/dti", params={"amount": 31_000_000, "term": 12}
    )

    assert preview.status_code == 400
    assert preview.json()["detail"] == "Hạn mức đề xuất vượt số tiền yêu cầu"
