"""Seam 1 (trang HTML qua TestClient): M04 Lịch trả nợ, thanh toán và tất toán khoản vay.

UC27 Xem lịch trả nợ, UC28 Thanh toán kỳ (trực tuyến và tại quầy), UC31 Tất toán trước hạn; dùng lại
tầng nghiệp vụ của ticket #12 và #14.
"""

import re
from typing import Any

import pytest
from fastapi.testclient import TestClient

from loan_system.adapters.cic import FakeCicGateway
from loan_system.adapters.email import FakeEmailGateway
from loan_system.adapters.payment import FakePaymentGateway
from loan_system.adapters.sms import FakeSmsGateway
from tests.api.test_appraisal import PHONE
from tests.api.test_credit_scoring import NATIONAL_ID, cic_report
from tests.api.test_disbursement import approved, disburse
from tests.api.test_nightly_job import relogin
from tests.api.test_payment import disbursed_loan
from tests.api.test_web_login import assert_forms_carry_csrf, submit
from tests.api.workflow import Team, customer_browser
from tests.conftest import FakeClock


@pytest.fixture
def team(client: TestClient, clock: FakeClock, email: FakeEmailGateway) -> Team:
    return Team(client, clock, email)


@pytest.fixture
def customer(client: TestClient, sms: FakeSmsGateway) -> TestClient:
    return customer_browser(client, sms, phone=PHONE)


def hidden(page_text: str, name: str, form_action: str | None = None) -> str:
    """Giá trị ô ẩn `name`; có `form_action` thì chỉ tìm trong biểu mẫu gửi tới đường dẫn đó."""
    text = page_text
    if form_action is not None:
        match = re.search(rf'<form[^>]*action="{re.escape(form_action)}".*?</form>', text, re.S)
        assert match, f"trang không có biểu mẫu {form_action}"
        text = match.group(0)
    found = re.search(rf'name="{name}" value="([^"]*)"', text)
    assert found, f"trang không có ô {name}"
    return found.group(1)


def pay_on_web(browser: TestClient, loan_id: str, amount: str, **extra: str) -> tuple[str, Any]:
    """Mở M04, lấy khóa thanh toán vừa sinh rồi gửi biểu mẫu thanh toán trực tuyến."""
    path = f"/app/loans/{loan_id}/payments"
    key = hidden(browser.get(f"/app/loans/{loan_id}").text, "idempotency_key", path)
    return key, submit(browser, path, {"amount": amount, "idempotency_key": key, **extra})


def test_customer_sees_the_schedule_and_downloads_it_as_pdf(
    team: Team, customer: TestClient, clock: FakeClock, cic: FakeCicGateway,
) -> None:
    loan_id = disbursed_loan(team, customer, clock, cic)

    home = customer.get("/app")
    assert f'href="/app/loans/{loan_id}"' in home.text
    loans = customer.get("/app/loans")
    assert loans.status_code == 200
    assert f'href="/app/loans/{loan_id}"' in loans.text

    page = customer.get(f"/app/loans/{loan_id}")
    assert page.status_code == 200
    assert "Đang vay" in page.text
    assert "30.000.000 đ" in page.text  # số tiền vay, dư nợ gốc
    assert "2.836.788 đ" in page.text  # số tiền kỳ tới
    assert "28/10/2026" in page.text  # hạn kỳ 1
    assert page.text.count("Chưa đến hạn") >= 12
    assert f'href="/app/loans/{loan_id}/schedule.pdf"' in page.text
    assert_forms_carry_csrf(customer, page.text)

    pdf = customer.get(f"/app/loans/{loan_id}/schedule.pdf")
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.headers["cache-control"] == "no-store"
    assert pdf.content.startswith(b"%PDF")


def test_customer_pays_online_and_a_resubmitted_form_is_charged_only_once(
    team: Team, customer: TestClient, clock: FakeClock, cic: FakeCicGateway,
    payments: FakePaymentGateway,
) -> None:
    loan_id = disbursed_loan(team, customer, clock, cic)

    key, paid = pay_on_web(customer, loan_id, "1000000")
    assert paid.status_code == 200
    assert "Đã ghi nhận thanh toán" in paid.text
    assert "1.000.000 đ" in paid.text
    # Lượt thanh toán kế tiếp có khóa mới.
    assert hidden(paid.text, "idempotency_key") != key

    again = submit(customer, f"/app/loans/{loan_id}/payments",
                   {"amount": "1000000", "idempotency_key": key})
    assert again.status_code == 200
    assert len(payments.charges) == 1
    assert customer.get(f"/loans/{loan_id}/schedule").json()["installments"][0][
        "paid_amount"] == "1000000"


def test_a_refused_charge_shows_the_message_and_issues_a_new_key(
    team: Team, customer: TestClient, clock: FakeClock, cic: FakeCicGateway,
    payments: FakePaymentGateway,
) -> None:
    loan_id = disbursed_loan(team, customer, clock, cic)
    payments.reject_next_charge("Không đủ số dư")

    key, refused = pay_on_web(customer, loan_id, "1000000")

    assert refused.status_code == 409
    assert "Cổng thanh toán từ chối giao dịch" in refused.text
    retry_key = hidden(refused.text, "idempotency_key",
                       f"/app/loans/{loan_id}/payments")
    assert retry_key != key
    retry = submit(customer, f"/app/loans/{loan_id}/payments",
                   {"amount": "1000000", "idempotency_key": retry_key})
    assert retry.status_code == 200
    assert "Đã ghi nhận thanh toán" in retry.text


def test_paying_more_than_the_remaining_schedule_keeps_the_same_key(
    team: Team, customer: TestClient, clock: FakeClock, cic: FakeCicGateway,
    payments: FakePaymentGateway,
) -> None:
    loan_id = disbursed_loan(team, customer, clock, cic)

    key, rejected = pay_on_web(customer, loan_id, "900000000")

    assert rejected.status_code == 400
    assert "Số tiền vượt quá tổng số tiền còn phải trả" in rejected.text
    assert hidden(rejected.text, "idempotency_key",
                  f"/app/loans/{loan_id}/payments") == key
    assert payments.charges == []

    empty = submit(customer, f"/app/loans/{loan_id}/payments",
                   {"amount": "", "idempotency_key": key})
    assert empty.status_code == 400
    assert "Số tiền thanh toán" in empty.text


def test_customer_settles_the_loan_from_the_payoff_quote(
    team: Team, customer: TestClient, clock: FakeClock, cic: FakeCicGateway,
) -> None:
    loan_id = disbursed_loan(team, customer, clock, cic)
    quote = customer.get(f"/loans/{loan_id}/payoff-quote").json()
    path = f"/app/loans/{loan_id}/settlement"

    page = customer.get(f"/app/loans/{loan_id}")
    assert "Tất toán" in page.text
    assert f'action="{path}"' in page.text
    assert "data-confirm=" in page.text
    assert hidden(page.text, "amount", path) == quote["total"]
    assert hidden(page.text, "quoted_on", path) == quote["quoted_on"]

    settled = submit(customer, path, {
        "amount": quote["total"], "quoted_on": quote["quoted_on"],
        "idempotency_key": hidden(page.text, "idempotency_key", path),
    })

    assert settled.status_code == 200
    assert "Đã tất toán khoản vay" in settled.text
    assert "Đã tất toán" in settled.text
    assert f'action="{path}"' not in settled.text
    assert f'action="/app/loans/{loan_id}/payments"' not in settled.text


def test_a_double_submitted_settlement_still_ends_on_the_settled_notice(
    team: Team, customer: TestClient, clock: FakeClock, cic: FakeCicGateway,
    payments: FakePaymentGateway,
) -> None:
    loan_id = disbursed_loan(team, customer, clock, cic)
    path = f"/app/loans/{loan_id}/settlement"
    page = customer.get(f"/app/loans/{loan_id}")
    form = {name: hidden(page.text, name, path)
            for name in ("amount", "quoted_on", "idempotency_key")}

    assert submit(customer, path, form).status_code == 200
    again = submit(customer, path, form)  # bấm hai lần: yêu cầu thứ hai thấy khoản vay đã tất toán

    assert again.status_code == 200
    assert "Đã tất toán khoản vay" in again.text
    assert len(payments.charges) == 1


def test_a_payoff_quote_from_another_day_asks_to_review_the_amount(
    team: Team, customer: TestClient, clock: FakeClock, cic: FakeCicGateway,
    payments: FakePaymentGateway,
) -> None:
    loan_id = disbursed_loan(team, customer, clock, cic)
    path = f"/app/loans/{loan_id}/settlement"
    page = customer.get(f"/app/loans/{loan_id}")
    form = {name: hidden(page.text, name, path)
            for name in ("amount", "quoted_on", "idempotency_key")}

    clock.advance(days=1)
    relogin(customer)
    stale = submit(customer, path, form)

    assert stale.status_code == 409
    assert "Vui lòng xem lại số tiền tất toán" in stale.text
    assert hidden(stale.text, "quoted_on", path) == clock.now().date().isoformat()
    assert payments.charges == []


def test_credit_officer_records_a_counter_payment_from_the_application(
    team: Team, customer: TestClient, clock: FakeClock, cic: FakeCicGateway,
    payments: FakePaymentGateway,
) -> None:
    cic.respond(NATIONAL_ID, cic_report(highest_debt_group=2, utility_late_payments=3))
    app_id = approved(team, customer)
    loan_id = disburse(team, clock, app_id).json()["loan"]["id"]
    officer = team.officer.client
    path = f"/app/loans/{loan_id}/payments"

    detail = officer.get(f"/app/queue/{app_id}")
    assert f'href="/app/queue/{app_id}/loan"' in detail.text
    page = officer.get(f"/app/queue/{app_id}/loan")
    assert page.status_code == 200
    assert str(page.url).endswith(f"/app/loans/{loan_id}")
    assert 'name="receipt_no"' in page.text
    assert 'name="idempotency_key"' not in page.text

    missing = submit(officer, path, {"amount": "1000000", "receipt_no": ""})
    assert missing.status_code == 400
    assert "Cần nhập mã phiếu thu" in missing.text

    paid = submit(officer, path, {"amount": "1000000", "receipt_no": "PT-2026-0001"})
    assert paid.status_code == 200
    assert "Đã ghi nhận thanh toán" in paid.text
    assert payments.charges == []  # tiền mặt tại quầy, không qua cổng thanh toán
    schedule = customer.get(f"/loans/{loan_id}/schedule").json()
    assert schedule["installments"][0]["paid_amount"] == "1000000"


def test_other_users_cannot_open_the_loan(
    team: Team, customer: TestClient, clock: FakeClock, cic: FakeCicGateway,
    sms: FakeSmsGateway,
) -> None:
    loan_id = disbursed_loan(team, customer, clock, cic)
    other = customer_browser(team.client, sms, phone="0909999999", email="khac@example.com")

    assert other.get(f"/app/loans/{loan_id}").status_code == 404
    assert other.get(f"/app/loans/{loan_id}/schedule.pdf").status_code == 404
    assert submit(other, f"/app/loans/{loan_id}/payments",
                  {"amount": "1000000", "idempotency_key": "k" * 32}).status_code == 404
    assert team.approver.client.get(f"/app/loans/{loan_id}").status_code == 403
    assert team.officer.client.get("/app/loans").status_code == 403
