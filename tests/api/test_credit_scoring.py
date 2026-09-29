"""Seam 1: UC18 Chấm điểm tín dụng tự động, UC19 Tra cứu CIC, UC20 Giải thích điểm (ticket #6)."""

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from loan_system.adapters.cic import CicReport, FakeCicGateway
from loan_system.adapters.email import FakeEmailGateway
from loan_system.adapters.sms import FakeSmsGateway
from tests.api.staff import new_client
from tests.api.test_customer_registration import PASSWORD
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
NATIONAL_ID = FINANCES["national_id"]


def cic_report(**overrides: Any) -> CicReport:
    values: dict[str, Any] = {
        "highest_debt_group": 1,
        "total_outstanding": Decimal(20_000_000),
        "lender_count": 1,
        "monthly_obligation": Decimal(1_500_000),
        "utility_late_payments": 0,
    }
    values.update(overrides)
    return CicReport(**values)


@pytest.fixture
def team(client: TestClient, clock: FakeClock, email: FakeEmailGateway) -> Team:
    return Team(client, clock, email)


@pytest.fixture
def customer(client: TestClient, sms: FakeSmsGateway) -> TestClient:
    return customer_browser(client, sms, phone=PHONE)


def verified(team: Team, customer: TestClient, **finances: Any) -> str:
    """Hồ sơ vay được NV tín dụng xác nhận hợp lệ, việc chấm điểm chạy ngay sau đó."""
    app_id = submitted_application(customer, **finances)
    response = verify_as(team.officer.client, app_id)
    assert response.status_code == 200, response.text
    return app_id


def score_of(team: Team, app_id: str) -> dict[str, Any]:
    response = team.appraiser.client.get(f"/applications/{app_id}/score")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def status_of(customer: TestClient, app_id: str) -> str:
    status: str = customer.get(f"/applications/{app_id}").json()["status"]
    return status


def test_tc03_debt_group_3_on_cic_is_rejected_automatically_with_reason(
    team: Team, customer: TestClient, cic: FakeCicGateway, sms: FakeSmsGateway
) -> None:
    cic.respond(NATIONAL_ID, cic_report(highest_debt_group=3))

    app_id = verified(team, customer)

    detail = customer.get(f"/applications/{app_id}").json()
    assert detail["status"] == "REJECTED"
    assert [h["status"] for h in detail["history"]][-2:] == ["VERIFIED", "REJECTED"]
    score = score_of(team, app_id)
    assert score["knock_out_reason"] == "Nợ nhóm 3 trở lên"
    assert (score["score"], score["grade"]) == (None, None)
    assert "Nợ nhóm 3 trở lên" in sms.last_to(PHONE).message


def test_grade_a_moves_to_appraisal_with_the_grade_rate_and_an_explanation(
    team: Team, customer: TestClient, cic: FakeCicGateway
) -> None:
    cic.respond(NATIONAL_ID, cic_report())
    appraiser = team.appraiser.client

    app_id = verified(team, customer)

    assert status_of(customer, app_id) == "APPRAISING"
    assert any(n["type"] == "APPLICATION_SCORED" for n in notifications_of(appraiser))
    score = score_of(team, app_id)
    # 25 triệu (180), DTI (2 triệu + 2.895.180) / 25 triệu ≈ 19,6% (200), CIC nhóm 1 (200),
    # 4 năm (120), hóa đơn đúng hạn (120), 31 tuổi (80), thuê nhà (30)
    assert (score["score"], score["grade"], score["knock_out_reason"]) == (930, "A", None)
    assert Decimal(score["dti"]) == Decimal("0.1958")
    assert Decimal(score["annual_rate"]) == Decimal("0.20")  # chính sách mặc định, hạng A
    assert score["model_version"] == "SC-2026.1"
    assert {f["code"]: (f["points"], f["max_points"]) for f in score["factors"]} == {
        "monthly_income": (180, 220),
        "dti": (200, 200),
        "cic_debt_group": (200, 200),
        "employment_years": (120, 120),
        "utility_late_payments": (120, 120),
        "age": (80, 80),
        "housing_type": (30, 60),
    }
    assert score["top_factors"] == ["monthly_income", "housing_type"]  # chỉ yếu tố bị mất điểm
    assert score["cic"]["highest_debt_group"] == 1
    assert (score["cic_missing"], score["fraud_suspected"]) == (False, False)
    # CIC nhận mã hồ sơ vay làm tham chiếu (UC19 bước 2).
    assert [q.reference for q in cic.queries] == [customer.get(f"/applications/{app_id}").json()["code"]]


def test_dti_knock_out_uses_the_ceiling_rate(
    team: Team, customer: TestClient, cic: FakeCicGateway
) -> None:
    # (2,2 triệu + 2.895.180 theo lãi suất trần 28%) / 10 triệu ≈ 50,95% > 50%, dù theo lãi suất
    # hạng A (20%) chỉ ≈ 49,8% (ADR 0001).
    cic.respond(NATIONAL_ID, cic_report(monthly_obligation=Decimal(2_000_000)))

    app_id = verified(team, customer, monthly_income=10_000_000, existing_monthly_debt=2_200_000)

    assert status_of(customer, app_id) == "REJECTED"
    assert score_of(team, app_id)["knock_out_reason"] == "DTI vượt 50%"


def test_cic_obligation_above_declared_debt_is_used_and_flags_suspected_fraud(
    team: Team, customer: TestClient, cic: FakeCicGateway
) -> None:
    cic.respond(NATIONAL_ID, cic_report(monthly_obligation=Decimal(2_500_000)))

    app_id = verified(team, customer, existing_monthly_debt=1_000_000)

    score = score_of(team, app_id)
    # (2,5 triệu theo CIC + 2.895.180) / 25 triệu ≈ 21,6%: điểm DTI 140 thay vì 200 (ADR 0002)
    assert Decimal(score["dti"]) == Decimal("0.2158")
    assert score["fraud_suspected"] is True
    assert status_of(customer, app_id) == "APPRAISING"  # cờ chỉ để thẩm định xem xét


@pytest.mark.parametrize(
    ("employment_years", "score", "grade", "rate"),
    [
        (4, 670, "B", "0.24"),  # 930 - nợ nhóm 2 (140) - trễ hóa đơn 3 lần (120)
        (0, 580, "C", "0.28"),  # thêm dưới 1 năm làm việc (90)
    ],
)
def test_grades_b_and_c_get_the_rate_of_their_grade(
    team: Team, customer: TestClient, cic: FakeCicGateway,
    employment_years: int, score: int, grade: str, rate: str,
) -> None:
    cic.respond(NATIONAL_ID, cic_report(highest_debt_group=2, utility_late_payments=3))

    app_id = verified(team, customer, employment_years=employment_years)

    result = score_of(team, app_id)
    assert (result["score"], result["grade"]) == (score, grade)
    assert Decimal(result["annual_rate"]) == Decimal(rate)
    assert status_of(customer, app_id) == "APPRAISING"


def test_grade_d_is_rejected_automatically(
    team: Team, customer: TestClient, cic: FakeCicGateway, sms: FakeSmsGateway
) -> None:
    cic.respond(
        NATIONAL_ID,
        cic_report(highest_debt_group=2, monthly_obligation=Decimal(0), utility_late_payments=3),
    )

    # 8 triệu (120), DTI 36,2% (60), nhóm 2 (60), dưới 1 năm (30), trễ 3 lần (0), 31 tuổi (80),
    # thuê nhà (30) = 380
    app_id = verified(
        team, customer, monthly_income=8_000_000, existing_monthly_debt=0, employment_years=0
    )

    result = score_of(team, app_id)
    assert (result["score"], result["grade"], result["annual_rate"]) == (380, "D", None)
    assert status_of(customer, app_id) == "REJECTED"
    assert "Điểm tín dụng chưa đạt yêu cầu" in sms.last_to(PHONE).message


def test_cic_not_responding_after_3_tries_is_still_scored_as_no_history(
    team: Team, customer: TestClient, cic: FakeCicGateway
) -> None:
    cic.never_respond(NATIONAL_ID)

    app_id = verified(team, customer)

    assert [q.timeout_seconds for q in cic.queries] == [5, 10, 20]  # chờ tăng dần (UC19 2a)
    assert status_of(customer, app_id) == "APPRAISING"
    score = score_of(team, app_id)
    assert (score["cic_missing"], score["cic"]) == (True, None)
    factors = {f["code"]: f["points"] for f in score["factors"]}
    # CIC như "chưa có lịch sử" (100 thay vì 200), hóa đơn như trễ 1–2 lần (60 thay vì 120)
    assert (factors["cic_debt_group"], factors["utility_late_payments"]) == (100, 60)
    assert (score["score"], score["grade"]) == (770, "A")


def test_cic_answering_on_the_third_try_is_used(
    team: Team, customer: TestClient, cic: FakeCicGateway
) -> None:
    cic.respond(NATIONAL_ID, cic_report(highest_debt_group=2), after_timeouts=2)

    app_id = verified(team, customer)

    assert len(cic.queries) == 3
    score = score_of(team, app_id)
    assert (score["cic_missing"], score["cic"]["highest_debt_group"]) == (False, 2)


def test_cic_report_under_30_days_old_is_reused(
    team: Team, client: TestClient, customer: TestClient, cic: FakeCicGateway, clock: FakeClock
) -> None:
    cic.respond(NATIONAL_ID, cic_report(highest_debt_group=3))
    first = verified(team, customer)
    assert status_of(customer, first) == "REJECTED"

    def apply_again_after(days: int) -> str:
        clock.advance(days=days)
        browser = new_client(client)  # phiên cũ đã hết hạn
        browser.post("/auth/login", json={"username": PHONE, "password": PASSWORD}).raise_for_status()
        team.relogin(team.officer)
        app_id = verified(team, browser)
        assert status_of(browser, app_id) == "REJECTED"
        return app_id

    apply_again_after(days=29)
    assert len(cic.queries) == 1  # báo cáo của hồ sơ vay trước, tra cứu 29 ngày trước

    apply_again_after(days=2)
    assert len(cic.queries) == 2


def test_st09_replaced_model_file_stops_scoring_and_alerts_the_admin(
    team: Team, customer: TestClient, cic: FakeCicGateway, scoring_model_dir: Path
) -> None:
    cic.respond(NATIONAL_ID, cic_report())
    model_file = scoring_model_dir / "scorecard-2026.1.json"
    # Kẻ tấn công nâng điểm "thuê nhà" từ 30 lên 300.
    model_file.write_bytes(model_file.read_bytes().replace(b'"RENT": 30', b'"RENT": 300'))

    app_id = verified(team, customer)

    assert status_of(customer, app_id) == "VERIFIED"  # giữ nguyên để chấm lại (UC18 4a)
    assert any(n["type"] == "MODEL_INTEGRITY_FAIL" for n in notifications_of(team.admin.client))
    response = team.appraiser.client.get(f"/applications/{app_id}/score")
    assert response.status_code == 404


def test_only_appraisers_and_approvers_can_view_the_score(
    team: Team, customer: TestClient, cic: FakeCicGateway
) -> None:
    cic.respond(NATIONAL_ID, cic_report())
    app_id = verified(team, customer)

    assert team.officer.client.get(f"/applications/{app_id}/score").status_code == 403
    assert customer.get(f"/applications/{app_id}/score").status_code == 403
    assert team.approver.client.get(f"/applications/{app_id}/score").status_code == 200


def test_a_scoring_failure_does_not_undo_the_verification(
    team: Team, customer: TestClient, cic: FakeCicGateway
) -> None:
    # CIC trả dữ liệu ngoài miền giá trị (nhóm nợ chỉ từ 0 đến 5): lưu kết quả thất bại.
    cic.respond(NATIONAL_ID, cic_report(highest_debt_group=7))

    app_id = verified(team, customer)

    assert status_of(customer, app_id) == "VERIFIED"  # chờ chấm lại
    assert team.appraiser.client.get(f"/applications/{app_id}/score").status_code == 404
