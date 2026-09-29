"""Seam 1: UC29 Quét và xử lý quá hạn, UC30 Gửi nhắc nợ, BR11, UC18 4a (ticket #13).

Bộ lập lịch (tác nhân Timer) kích hoạt tác vụ hằng đêm; test đóng vai bộ lập lịch bằng cách chạy
`NightlyJob` trên cùng ứng dụng rồi quan sát kết quả qua REST API.
"""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from loan_system.adapters.cic import FakeCicGateway
from loan_system.adapters.email import FakeEmailGateway
from loan_system.adapters.sms import FakeSmsGateway
from loan_system.services.nightly_job import NightlyJob
from tests.api.staff import ctx_of
from tests.api.test_application_review import request_front_id
from tests.api.test_appraisal import PHONE
from tests.api.test_credit_scoring import NATIONAL_ID, cic_report, status_of, verified
from tests.api.test_customer_registration import PASSWORD
from tests.api.test_payment import disbursed_loan
from tests.api.workflow import Team, customer_browser, notifications_of
from tests.conftest import FakeClock


@pytest.fixture
def team(client: TestClient, clock: FakeClock, email: FakeEmailGateway) -> Team:
    return Team(client, clock, email)


@pytest.fixture
def customer(client: TestClient, sms: FakeSmsGateway) -> TestClient:
    return customer_browser(client, sms, phone=PHONE)


def run_nightly(client: TestClient) -> None:
    ctx = ctx_of(client)
    NightlyJob(ctx.session_factory, ctx.clock, ctx.settings, ctx.sms, ctx.cic).run()


def relogin(customer: TestClient) -> TestClient:
    """Phiên hết hạn sau 15 phút; sau nhiều ngày khách hàng đăng nhập lại."""
    customer.post("/auth/login", json={"username": PHONE, "password": PASSWORD}).raise_for_status()
    return customer


def schedule_of(customer: TestClient, loan_id: str) -> dict[str, Any]:
    response = customer.get(f"/loans/{loan_id}/schedule")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def test_tc04_installment_15_days_overdue_has_a_penalty_and_debt_group_2(
    team: Team, customer: TestClient, clock: FakeClock, cic: FakeCicGateway, client: TestClient,
) -> None:
    loan_id = disbursed_loan(team, customer, clock, cic)
    clock.advance(days=45)  # kỳ 1 đến hạn 28/10/2026; nay 12/11/2026: quá hạn 15 ngày

    run_nightly(client)

    schedule = schedule_of(relogin(customer), loan_id)
    assert schedule["status"] == "OVERDUE"
    assert schedule["debt_group"] == 2
    ky1, ky2 = schedule["installments"][:2]
    assert ky1["status"] == "OVERDUE"
    assert ky1["penalty"] == "41969"  # 2.836.788 × 36% / 365 × 15 (mục 1.2.8c)
    assert ky2["status"] == "UPCOMING"


def test_running_the_job_twice_on_the_same_night_does_not_add_up(
    team: Team, customer: TestClient, clock: FakeClock, cic: FakeCicGateway, client: TestClient,
    sms: FakeSmsGateway,
) -> None:
    loan_id = disbursed_loan(team, customer, clock, cic)
    clock.advance(days=45)

    run_nightly(client)
    sent = len(sms.outbox)
    run_nightly(client)

    schedule = schedule_of(relogin(customer), loan_id)
    assert schedule["installments"][0]["penalty"] == "41969"  # không cộng dồn phí phạt
    reminders = [n for n in notifications_of(customer) if n["type"] == "PAYMENT_OVERDUE"]
    assert len(reminders) == 1  # nhắc quá hạn 15 ngày chỉ gửi một lần
    assert len(sms.outbox) == sent


def test_customer_is_reminded_three_days_before_and_on_the_due_date(
    team: Team, customer: TestClient, clock: FakeClock, cic: FakeCicGateway, client: TestClient,
    sms: FakeSmsGateway,
) -> None:
    loan_id = disbursed_loan(team, customer, clock, cic)

    clock.advance(days=27)  # 25/10/2026: kỳ 1 đến hạn sau 3 ngày
    run_nightly(client)
    before = sms.last_to(PHONE).message
    assert "Kỳ 1" in before and "28/10/2026" in before and "2.836.788" in before
    assert "HS2" in before and "http" not in before  # mã khoản vay đã che, không có liên kết

    clock.advance(days=3)  # 28/10/2026: đúng ngày đến hạn
    run_nightly(client)

    schedule = schedule_of(relogin(customer), loan_id)
    assert schedule["installments"][0]["status"] == "DUE"
    reminders = [n for n in notifications_of(customer) if n["type"] == "PAYMENT_REMINDER"]
    assert len(reminders) == 2

    clock.advance(days=1)  # 29/10/2026: quá hạn 1 ngày
    run_nightly(client)
    overdue = sms.last_to(PHONE).message
    assert "quá hạn 1 ngày" in overdue


def test_a_missed_night_still_sends_the_latest_overdue_reminder_once(
    team: Team, customer: TestClient, clock: FakeClock, cic: FakeCicGateway, client: TestClient,
    sms: FakeSmsGateway,
) -> None:
    disbursed_loan(team, customer, clock, cic)
    clock.advance(days=30 + 9)  # 06/11/2026: quá hạn 9 ngày, các đêm trước bị lỡ

    run_nightly(client)
    run_nightly(client)

    reminders = [n for n in notifications_of(relogin(customer)) if n["type"] == "PAYMENT_OVERDUE"]
    assert len(reminders) == 1  # mốc 7 ngày gửi bù đúng một lần
    assert "quá hạn 9 ngày" in sms.last_to(PHONE).message


def test_an_installment_paid_in_advance_is_neither_reminded_nor_marked_overdue(
    team: Team, customer: TestClient, clock: FakeClock, cic: FakeCicGateway, client: TestClient,
) -> None:
    loan_id = disbursed_loan(team, customer, clock, cic)
    customer.post(f"/loans/{loan_id}/payments", json={"amount": "2836788"}).raise_for_status()

    clock.advance(days=27)
    run_nightly(client)
    clock.advance(days=18)  # kỳ 1 lẽ ra quá hạn 15 ngày
    run_nightly(client)

    schedule = schedule_of(relogin(customer), loan_id)
    assert schedule["status"] == "ACTIVE"
    assert schedule["debt_group"] == 1
    assert schedule["installments"][0]["status"] == "PAID"
    assert not any(
        n["type"] in {"PAYMENT_REMINDER", "PAYMENT_OVERDUE"} for n in notifications_of(customer)
    )


def test_paying_every_overdue_installment_brings_the_loan_back_to_active(
    team: Team, customer: TestClient, clock: FakeClock, cic: FakeCicGateway, client: TestClient,
) -> None:
    loan_id = disbursed_loan(team, customer, clock, cic)
    clock.advance(days=45)
    run_nightly(client)
    schedule = schedule_of(relogin(customer), loan_id)

    response = customer.post(
        f"/loans/{loan_id}/payments", json={"amount": schedule["amount_due"]}
    )

    assert response.status_code == 200, response.text
    assert response.json()["loan_status"] == "ACTIVE"  # 3.4b T03
    schedule = schedule_of(customer, loan_id)
    assert schedule["debt_group"] == 1
    assert schedule["installments"][0]["status"] == "PAID"


def test_more_than_90_days_overdue_becomes_bad_debt_and_managers_are_told(
    team: Team, customer: TestClient, clock: FakeClock, cic: FakeCicGateway, client: TestClient,
) -> None:
    loan_id = disbursed_loan(team, customer, clock, cic)
    clock.advance(days=30 + 90)  # 27/01/2027: kỳ 1 quá hạn 90 ngày
    run_nightly(client)
    assert schedule_of(relogin(customer), loan_id)["status"] == "OVERDUE"

    clock.advance(days=1)  # quá hạn 91 ngày
    run_nightly(client)

    schedule = schedule_of(relogin(customer), loan_id)
    assert schedule["status"] == "BAD_DEBT"
    assert schedule["debt_group"] == 3
    approver = team.relogin(team.approver)
    assert [n["type"] for n in notifications_of(approver)].count("LOAN_BAD_DEBT") == 1
    run_nightly(client)
    assert [n["type"] for n in notifications_of(approver)].count("LOAN_BAD_DEBT") == 1


def test_br11_application_not_supplemented_within_15_days_is_cancelled(
    team: Team, customer: TestClient, clock: FakeClock, client: TestClient,
) -> None:
    app_id = request_front_id(team, customer)
    clock.advance(days=14)
    run_nightly(client)
    assert relogin(customer).get(f"/applications/{app_id}").json()["status"] == "NEED_INFO"

    clock.advance(days=1, seconds=1)
    run_nightly(client)

    detail = relogin(customer).get(f"/applications/{app_id}").json()
    assert detail["status"] == "CANCELLED"
    assert any(n["type"] == "APPLICATION_CANCELLED" for n in notifications_of(customer))


def test_uc18_4a_application_stuck_in_verified_is_scored_again_after_an_hour(
    team: Team, customer: TestClient, clock: FakeClock, cic: FakeCicGateway, client: TestClient,
) -> None:
    # CIC trả dữ liệu ngoài miền giá trị: chấm điểm lỗi, hồ sơ vay ở lại "Hợp lệ".
    cic.respond(NATIONAL_ID, cic_report(highest_debt_group=7))
    app_id = verified(team, customer)
    assert status_of(customer, app_id) == "VERIFIED"
    cic.respond(NATIONAL_ID, cic_report())

    clock.advance(minutes=30)
    run_nightly(client)
    assert status_of(relogin(customer), app_id) == "VERIFIED"  # chưa quá 1 giờ

    clock.advance(minutes=31)
    run_nightly(client)

    assert status_of(relogin(customer), app_id) == "APPRAISING"


def test_uc18_4a_model_still_tampered_keeps_alerting_the_admin(
    team: Team, customer: TestClient, clock: FakeClock, cic: FakeCicGateway, client: TestClient,
    scoring_model_dir: Path,
) -> None:
    cic.respond(NATIONAL_ID, cic_report())
    model_file = scoring_model_dir / "scorecard-2026.1.json"
    model_file.write_bytes(model_file.read_bytes().replace(b'"RENT": 30', b'"RENT": 300'))
    app_id = verified(team, customer)
    alerts = alerts_of(team.admin.client)

    clock.advance(hours=1, minutes=1)
    run_nightly(client)

    assert status_of(relogin(customer), app_id) == "VERIFIED"
    assert alerts_of(team.relogin(team.admin)) == alerts + 1  # Q14: tiếp tục cảnh báo


def alerts_of(admin: TestClient) -> int:
    return [n["type"] for n in notifications_of(admin)].count("MODEL_INTEGRITY_FAIL")
