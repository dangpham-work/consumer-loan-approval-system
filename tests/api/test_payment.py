"""Seam 1: UC27 Xem lịch trả nợ, UC28 Thanh toán kỳ, phân bổ và chống ghi nhận trùng (ticket #12)."""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from loan_system.adapters.cic import FakeCicGateway
from loan_system.adapters.email import FakeEmailGateway
from loan_system.adapters.payment import FakePaymentGateway
from loan_system.adapters.sms import FakeSmsGateway
from tests.api.test_appraisal import PHONE
from tests.api.test_credit_scoring import NATIONAL_ID, cic_report
from tests.api.test_disbursement import approved, disburse
from tests.api.workflow import Team, customer_browser, notifications_of
from tests.conftest import FakeClock

# Niên kim 30 triệu, 24%/năm, 12 kỳ (mục 1.2.8a). Kỳ 1: lãi 600.000, gốc 2.236.788.
FIRST_INSTALLMENT = Decimal(2_836_788)
FIRST_INTEREST = Decimal(600_000)
FIRST_PRINCIPAL = Decimal(2_236_788)


@pytest.fixture
def team(client: TestClient, clock: FakeClock, email: FakeEmailGateway) -> Team:
    return Team(client, clock, email)


@pytest.fixture
def customer(client: TestClient, sms: FakeSmsGateway) -> TestClient:
    return customer_browser(client, sms, phone=PHONE)


def disbursed_loan(team: Team, customer: TestClient, clock: FakeClock, cic: FakeCicGateway) -> str:
    # Hạng B (670 điểm): nợ nhóm 2, trễ hóa đơn 3 lần; lãi suất 24%/năm (như TC01, ticket #10).
    cic.respond(NATIONAL_ID, cic_report(highest_debt_group=2, utility_late_payments=3))
    app_id = approved(team, customer)
    response = disburse(team, clock, app_id)
    response.raise_for_status()
    loan_id: str = response.json()["loan"]["id"]
    return loan_id


def mark_overdue(engine: Engine, loan_id: str, number: int, penalty: int) -> None:
    """Đặt sẵn một kỳ quá hạn với phí phạt cho trước, không phụ thuộc cách tác vụ hằng đêm tính."""
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE installments SET status = 'OVERDUE', penalty = :penalty "
                "WHERE loan_id = :loan_id AND number = :number"
            ),
            {"loan_id": loan_id, "number": number, "penalty": penalty},
        )


def test_customer_pays_the_first_installment_online(
    team: Team, customer: TestClient, clock: FakeClock, payments: FakePaymentGateway,
    cic: FakeCicGateway,
) -> None:
    loan_id = disbursed_loan(team, customer, clock, cic)

    schedule = customer.get(f"/loans/{loan_id}/schedule")
    assert schedule.status_code == 200, schedule.text
    body = schedule.json()
    assert body["amount_due"] == "0"  # chưa đến hạn kỳ nào
    assert body["next_due_date"] == "2026-10-28"
    assert len(body["installments"]) == 12

    response = customer.post(f"/loans/{loan_id}/payments", json={"amount": str(FIRST_INSTALLMENT)})

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["channel"] == "ONLINE"
    assert result["allocations"] == [
        {"installment_number": 1, "component": "INTEREST", "amount": str(FIRST_INTEREST)},
        {"installment_number": 1, "component": "PRINCIPAL", "amount": str(FIRST_PRINCIPAL)},
    ]
    assert result["loan_status"] == "ACTIVE"
    assert result["outstanding_principal"] == str(30_000_000 - FIRST_PRINCIPAL)
    [charge] = payments.charges
    assert charge.amount == FIRST_INSTALLMENT
    assert result["external_ref"] == charge.transaction_ref
    assert any(n["type"] == "PAYMENT_RECEIVED" for n in notifications_of(customer))

    installments = customer.get(f"/loans/{loan_id}/schedule").json()["installments"]
    assert installments[0]["status"] == "PAID"
    assert installments[0]["paid_amount"] == str(FIRST_INSTALLMENT)
    assert installments[1]["status"] == "UPCOMING"


def test_overpayment_is_credited_as_an_advance_on_the_next_installment(
    team: Team, customer: TestClient, clock: FakeClock, cic: FakeCicGateway,
) -> None:
    loan_id = disbursed_loan(team, customer, clock, cic)
    amount = FIRST_INSTALLMENT + Decimal(1_000_000)

    response = customer.post(f"/loans/{loan_id}/payments", json={"amount": str(amount)})

    assert response.status_code == 200, response.text
    installments = customer.get(f"/loans/{loan_id}/schedule").json()["installments"]
    assert installments[0]["status"] == "PAID"
    # Trả trước một phần kỳ chưa đến hạn: kỳ vẫn Chưa đến hạn (3.4c chỉ có T03 khi trả đủ).
    assert installments[1]["status"] == "UPCOMING"
    assert installments[1]["paid_amount"] == "1000000"


def test_partly_paying_an_overdue_installment_keeps_it_overdue(
    team: Team, customer: TestClient, clock: FakeClock, engine: Engine, cic: FakeCicGateway,
) -> None:
    loan_id = disbursed_loan(team, customer, clock, cic)
    mark_overdue(engine, loan_id, 1, penalty=20_000)

    response = customer.post(f"/loans/{loan_id}/payments", json={"amount": "1000000"})

    assert response.status_code == 200, response.text
    installments = customer.get(f"/loans/{loan_id}/schedule").json()["installments"]
    assert installments[0]["status"] == "OVERDUE"  # 3.4c T08: chỉ trả đủ mới thành Đã thanh toán
    assert installments[0]["paid_amount"] == "1000000"


def test_overdue_installment_and_its_penalty_are_settled_before_the_current_one(
    team: Team, customer: TestClient, clock: FakeClock, engine: Engine, cic: FakeCicGateway,
) -> None:
    loan_id = disbursed_loan(team, customer, clock, cic)
    mark_overdue(engine, loan_id, 1, penalty=20_000)
    installments = customer.get(f"/loans/{loan_id}/schedule").json()["installments"]
    ky1, ky2 = installments[0], installments[1]
    # Đủ trả hết kỳ 1 (phí phạt, lãi, gốc) và lãi kỳ 2, còn thiếu gốc kỳ 2.
    amount = (
        Decimal(ky1["penalty"]) + Decimal(ky1["interest_due"]) + Decimal(ky1["principal_due"])
        + Decimal(ky2["interest_due"])
    )

    response = customer.post(f"/loans/{loan_id}/payments", json={"amount": str(amount)})

    assert response.status_code == 200, response.text
    allocations = response.json()["allocations"]
    assert allocations[0] == {"installment_number": 1, "component": "PENALTY", "amount": "20000"}
    assert [a["installment_number"] for a in allocations] == [1, 1, 1, 2]
    assert allocations[-1]["component"] == "INTEREST"


def test_paying_off_every_remaining_installment_settles_the_loan(
    team: Team, customer: TestClient, clock: FakeClock, cic: FakeCicGateway,
) -> None:
    loan_id = disbursed_loan(team, customer, clock, cic)
    installments = customer.get(f"/loans/{loan_id}/schedule").json()["installments"]
    total = sum(
        (Decimal(i["principal_due"]) + Decimal(i["interest_due"]) for i in installments),
        Decimal(0),
    )

    response = customer.post(f"/loans/{loan_id}/payments", json={"amount": str(total)})

    assert response.status_code == 200, response.text
    assert response.json()["loan_status"] == "SETTLED"
    assert response.json()["outstanding_principal"] == "0"

    again = customer.post(f"/loans/{loan_id}/payments", json={"amount": "1000"})
    assert again.status_code == 409  # UC28: chỉ khoản vay Đang hoạt động hoặc Quá hạn
    assert any(n["type"] == "LOAN_SETTLED" for n in notifications_of(customer))  # T05


def test_paying_more_than_the_total_remaining_schedule_is_rejected(
    team: Team, customer: TestClient, clock: FakeClock, payments: FakePaymentGateway,
    cic: FakeCicGateway,
) -> None:
    loan_id = disbursed_loan(team, customer, clock, cic)
    installments = customer.get(f"/loans/{loan_id}/schedule").json()["installments"]
    total = sum(
        (Decimal(i["principal_due"]) + Decimal(i["interest_due"]) for i in installments),
        Decimal(0),
    )

    response = customer.post(
        f"/loans/{loan_id}/payments", json={"amount": str(total + Decimal(1))}
    )

    assert response.status_code == 400
    assert payments.charges == []  # bị từ chối trước khi gọi cổng thanh toán


def test_credit_officer_records_a_counter_payment_with_a_receipt_number(
    team: Team, customer: TestClient, clock: FakeClock, payments: FakePaymentGateway,
    cic: FakeCicGateway,
) -> None:
    loan_id = disbursed_loan(team, customer, clock, cic)

    response = team.officer.client.post(
        f"/loans/{loan_id}/payments",
        json={"amount": str(FIRST_INSTALLMENT), "receipt_no": "PT-0001"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["channel"] == "COUNTER"
    assert response.json()["external_ref"] == "PT-0001"
    assert payments.charges == []  # tại quầy không gọi cổng thanh toán


def test_counter_payment_without_a_receipt_number_is_rejected(
    team: Team, customer: TestClient, clock: FakeClock, cic: FakeCicGateway,
) -> None:
    loan_id = disbursed_loan(team, customer, clock, cic)

    response = team.officer.client.post(
        f"/loans/{loan_id}/payments", json={"amount": str(FIRST_INSTALLMENT)}
    )

    assert response.status_code == 400


def test_a_duplicate_receipt_number_is_recorded_only_once(
    team: Team, customer: TestClient, clock: FakeClock, cic: FakeCicGateway,
) -> None:
    loan_id = disbursed_loan(team, customer, clock, cic)
    officer = team.officer.client
    body = {"amount": "1000000", "receipt_no": "PT-0002"}

    first = officer.post(f"/loans/{loan_id}/payments", json=body)
    second = officer.post(f"/loans/{loan_id}/payments", json=body)

    assert first.status_code == second.status_code == 200
    assert first.json()["id"] == second.json()["id"]  # UC28 3b: bỏ qua, không phân bổ lại
    installments = customer.get(f"/loans/{loan_id}/schedule").json()["installments"]
    assert installments[0]["paid_amount"] == "1000000"  # không bị cộng dồn hai lần


def test_a_receipt_number_already_used_for_another_payment_is_rejected(
    team: Team, customer: TestClient, clock: FakeClock, cic: FakeCicGateway,
) -> None:
    loan_id = disbursed_loan(team, customer, clock, cic)
    officer = team.officer.client
    officer.post(
        f"/loans/{loan_id}/payments", json={"amount": "1000000", "receipt_no": "PT-0003"}
    ).raise_for_status()

    response = officer.post(
        f"/loans/{loan_id}/payments", json={"amount": "2000000", "receipt_no": "PT-0003"}
    )

    assert response.status_code == 409  # không phải xác nhận trùng mà là mã phiếu thu bị dùng lại
    installments = customer.get(f"/loans/{loan_id}/schedule").json()["installments"]
    assert installments[0]["paid_amount"] == "1000000"


def test_resubmitting_an_online_payment_with_the_same_key_charges_only_once(
    team: Team, customer: TestClient, clock: FakeClock, payments: FakePaymentGateway,
    cic: FakeCicGateway,
) -> None:
    loan_id = disbursed_loan(team, customer, clock, cic)
    body = {"amount": "1000000", "idempotency_key": "f3b1c2d4-0000-4000-8000-000000000001"}

    first = customer.post(f"/loans/{loan_id}/payments", json=body)
    second = customer.post(f"/loans/{loan_id}/payments", json=body)

    assert first.status_code == second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert len(payments.charges) == 1
    installments = customer.get(f"/loans/{loan_id}/schedule").json()["installments"]
    assert installments[0]["paid_amount"] == "1000000"


def test_customer_cannot_pay_someone_elses_loan(
    team: Team, customer: TestClient, clock: FakeClock, sms: FakeSmsGateway,
    cic: FakeCicGateway,
) -> None:
    loan_id = disbursed_loan(team, customer, clock, cic)
    other = customer_browser(team.client, sms, phone="0909999999", email="khac@example.com")

    response = other.post(f"/loans/{loan_id}/payments", json={"amount": "1000000"})

    assert response.status_code == 404
    assert customer.get(f"/loans/{loan_id}/schedule").status_code == 200
    assert other.get(f"/loans/{loan_id}/schedule").status_code == 404


def test_gateway_refusal_records_nothing(
    team: Team, customer: TestClient, clock: FakeClock, payments: FakePaymentGateway,
    cic: FakeCicGateway,
) -> None:
    loan_id = disbursed_loan(team, customer, clock, cic)
    payments.reject_next_charge("Số dư không đủ")

    response = customer.post(f"/loans/{loan_id}/payments", json={"amount": str(FIRST_INSTALLMENT)})

    assert response.status_code == 409
    assert payments.charges == []
    installments = customer.get(f"/loans/{loan_id}/schedule").json()["installments"]
    assert installments[0]["status"] == "UPCOMING"


def test_schedule_can_be_downloaded_as_a_pdf(
    team: Team, customer: TestClient, clock: FakeClock, cic: FakeCicGateway,
) -> None:
    loan_id = disbursed_loan(team, customer, clock, cic)

    response = customer.get(f"/loans/{loan_id}/schedule/pdf")

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF-")
