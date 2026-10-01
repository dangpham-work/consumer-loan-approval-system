"""Seam 1: UC31 Tất toán khoản vay: báo giá trong ngày, tất toán, hủy kỳ còn lại (ticket #14, TC05)."""

from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from loan_system.adapters.cic import FakeCicGateway
from loan_system.adapters.email import FakeEmailGateway
from loan_system.adapters.payment import FakePaymentGateway
from loan_system.adapters.sms import FakeSmsGateway
from tests.api.test_appraisal import PHONE
from tests.api.test_nightly_job import relogin
from tests.api.test_payment import disbursed_loan, mark_overdue
from tests.api.workflow import Team, customer_browser, notifications_of
from tests.conftest import FakeClock

# Giải ngân 28/09/2026; kỳ 6 đến hạn 28/03/2027 (181 ngày sau), kỳ 11 đến hạn 28/08/2027.
DAYS_TO_INSTALLMENT_6 = 181
DAYS_TO_INSTALLMENT_11 = 334


@pytest.fixture
def team(client: TestClient, clock: FakeClock, email: FakeEmailGateway) -> Team:
    return Team(client, clock, email)


@pytest.fixture
def customer(client: TestClient, sms: FakeSmsGateway) -> TestClient:
    return customer_browser(client, sms, phone=PHONE)


def pay_installments(customer: TestClient, loan_id: str, count: int) -> None:
    installments = customer.get(f"/loans/{loan_id}/schedule").json()["installments"][:count]
    amount = sum(
        (Decimal(i["principal_due"]) + Decimal(i["interest_due"]) for i in installments),
        Decimal(0),
    )
    customer.post(f"/loans/{loan_id}/payments", json={"amount": str(amount)}).raise_for_status()


def quote_of(browser: TestClient, loan_id: str) -> dict[str, Any]:
    response = browser.get(f"/loans/{loan_id}/payoff-quote")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def settle(browser: TestClient, loan_id: str, quote: dict[str, Any], **extra: Any) -> Any:
    body = {"amount": quote["total"], "quoted_on": quote["quoted_on"], **extra}
    return browser.post(f"/loans/{loan_id}/settlement", json=body)


def test_tc05_early_payoff_in_month_6(
    team: Team, customer: TestClient, clock: FakeClock, payments: FakePaymentGateway,
    cic: FakeCicGateway,
) -> None:
    loan_id = disbursed_loan(team, customer, clock, cic)
    pay_installments(customer, loan_id, 6)
    clock.advance(days=DAYS_TO_INSTALLMENT_6 + 10)  # 07/04/2027
    relogin(customer)

    quote = quote_of(customer, loan_id)

    assert quote["quoted_on"] == "2027-04-07"
    assert quote["principal"] == "15890071"
    assert quote["accrued_interest"] == "104483"  # 15.890.071 × 24% / 365 × 10
    assert quote["penalty"] == "0"
    assert quote["prepayment_fee"] == "476702"  # 3% dư nợ gốc còn lại
    assert quote["total"] == "16471256"

    response = settle(customer, loan_id, quote)

    assert response.status_code == 200, response.text
    assert response.json()["loan_status"] == "SETTLED"
    assert response.json()["outstanding_principal"] == "0"
    assert payments.charges[-1].amount == Decimal(16_471_256)
    schedule = customer.get(f"/loans/{loan_id}/schedule").json()
    assert schedule["status"] == "SETTLED"
    statuses = [i["status"] for i in schedule["installments"]]
    assert statuses == ["PAID"] * 6 + ["CANCELLED"] * 6
    assert any(n["type"] == "LOAN_SETTLED" for n in notifications_of(customer))

    again = settle(customer, loan_id, quote)
    assert again.status_code == 409  # khoản vay đã tất toán


def test_payoff_in_the_final_installment_waives_the_prepayment_fee(
    team: Team, customer: TestClient, clock: FakeClock, cic: FakeCicGateway,
) -> None:
    loan_id = disbursed_loan(team, customer, clock, cic)
    pay_installments(customer, loan_id, 11)
    clock.advance(days=DAYS_TO_INSTALLMENT_11 + 5)
    relogin(customer)

    quote = quote_of(customer, loan_id)

    assert quote["prepayment_fee"] == "0"  # BR10
    assert settle(customer, loan_id, quote).json()["loan_status"] == "SETTLED"


def test_overdue_installment_and_its_penalty_are_part_of_the_payoff(
    team: Team, customer: TestClient, clock: FakeClock, cic: FakeCicGateway, engine: Engine,
) -> None:
    loan_id = disbursed_loan(team, customer, clock, cic)
    clock.advance(days=30 + 10)  # kỳ 1 đến hạn 28/10/2026, nay quá hạn 10 ngày
    mark_overdue(engine, loan_id, 1, penalty=20_000)
    relogin(customer)

    quote = quote_of(customer, loan_id)

    assert quote["principal"] == "30000000"
    assert quote["due_interest"] == "600000"
    assert quote["penalty"] == "20000"
    response = settle(customer, loan_id, quote)
    assert response.status_code == 200, response.text
    statuses = [i["status"] for i in customer.get(f"/loans/{loan_id}/schedule").json()["installments"]]
    assert statuses == ["PAID"] + ["CANCELLED"] * 11


def test_a_quote_from_an_earlier_day_must_be_recalculated(
    team: Team, customer: TestClient, clock: FakeClock, payments: FakePaymentGateway,
    cic: FakeCicGateway,
) -> None:
    loan_id = disbursed_loan(team, customer, clock, cic)
    quote = quote_of(customer, loan_id)
    clock.advance(days=1)
    relogin(customer)

    response = settle(customer, loan_id, quote)

    assert response.status_code == 409  # UC31 2a: báo giá chỉ có hiệu lực trong ngày
    assert payments.charges == []


def test_paying_less_than_the_quote_is_recorded_as_an_ordinary_payment(
    team: Team, customer: TestClient, clock: FakeClock, cic: FakeCicGateway,
) -> None:
    loan_id = disbursed_loan(team, customer, clock, cic)
    quote = quote_of(customer, loan_id)

    response = settle(customer, loan_id, {**quote, "total": "1000000"})

    assert response.status_code == 200, response.text  # UC31 3a
    assert response.json()["loan_status"] == "ACTIVE"
    installments = customer.get(f"/loans/{loan_id}/schedule").json()["installments"]
    assert installments[0]["paid_amount"] == "1000000"
    assert installments[1]["status"] == "UPCOMING"


def test_paying_more_than_the_quote_is_rejected(
    team: Team, customer: TestClient, clock: FakeClock, payments: FakePaymentGateway,
    cic: FakeCicGateway,
) -> None:
    loan_id = disbursed_loan(team, customer, clock, cic)
    quote = quote_of(customer, loan_id)

    response = settle(customer, loan_id, {**quote, "total": str(Decimal(quote["total"]) + 1)})

    assert response.status_code == 400
    assert payments.charges == []


def test_credit_officer_settles_at_the_counter_with_a_receipt_number(
    team: Team, customer: TestClient, clock: FakeClock, payments: FakePaymentGateway,
    cic: FakeCicGateway,
) -> None:
    loan_id = disbursed_loan(team, customer, clock, cic)
    officer = team.officer.client
    quote = quote_of(officer, loan_id)

    response = settle(officer, loan_id, quote, receipt_no="PT-TT-0001")

    assert response.status_code == 200, response.text
    assert response.json()["channel"] == "COUNTER"
    assert response.json()["loan_status"] == "SETTLED"
    assert payments.charges == []


def test_customer_cannot_quote_or_settle_someone_elses_loan(
    team: Team, customer: TestClient, clock: FakeClock, sms: FakeSmsGateway,
    cic: FakeCicGateway,
) -> None:
    loan_id = disbursed_loan(team, customer, clock, cic)
    quote = quote_of(customer, loan_id)
    other = customer_browser(team.client, sms, phone="0909999999", email="khac@example.com")

    assert other.get(f"/loans/{loan_id}/payoff-quote").status_code == 404
    assert settle(other, loan_id, quote).status_code == 404
