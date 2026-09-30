"""Seam 1: UC25 Giải ngân, UC26 Sinh hợp đồng và lịch trả nợ, SUC02 Kiểm tra toàn vẹn, M08 (ticket
#10); xử lý hồ sơ vay LOCKED và giải ngân FAILED (ticket #11)."""

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from loan_system.adapters.cic import FakeCicGateway
from loan_system.adapters.email import FakeEmailGateway
from loan_system.adapters.payment import FakePaymentGateway
from loan_system.adapters.sms import FakeSmsGateway
from tests.api.staff import Staff, otp
from tests.api.test_appraisal import PHONE, status_of
from tests.api.test_approval import decide, pending_approval
from tests.api.test_credit_scoring import NATIONAL_ID, cic_report
from tests.api.workflow import LOAN, Team, customer_browser, notifications_of
from tests.conftest import FakeClock

ACCOUNT = "0123456789"


@pytest.fixture
def team(client: TestClient, clock: FakeClock, email: FakeEmailGateway) -> Team:
    return Team(client, clock, email)


@pytest.fixture
def customer(client: TestClient, sms: FakeSmsGateway) -> TestClient:
    return customer_browser(client, sms, phone=PHONE)


def approved(team: Team, customer: TestClient, **proposal: Any) -> str:
    """Hồ sơ vay 30 triệu, 12 tháng đã được một Quản lý phê duyệt."""
    app_id = pending_approval(team, customer, **{"proposed_amount": 30_000_000, **proposal})
    decide(team.approver.client, app_id, "approve").raise_for_status()
    return app_id


def disburse(team: Team, clock: FakeClock, app_id: str, staff: Staff | None = None) -> Any:
    staff = staff or team.disburser
    return staff.client.post(
        f"/applications/{app_id}/disburse", json={"otp": otp(clock, staff.totp_secret)}
    )


def test_tc01_grade_b_loan_approved_by_one_manager_is_disbursed_with_its_schedule(
    team: Team, customer: TestClient, clock: FakeClock, cic: FakeCicGateway,
    payments: FakePaymentGateway, sms: FakeSmsGateway,
) -> None:
    # Hạng B (670 điểm): nợ nhóm 2, trễ hóa đơn 3 lần; lãi suất 24%/năm.
    cic.respond(NATIONAL_ID, cic_report(highest_debt_group=2, utility_late_payments=3))
    disburser = team.disburser.client
    app_id = approved(team, customer)
    assert LOAN["requested_amount"] == 30_000_000

    screen = disburser.get(f"/applications/{app_id}/disbursement")
    assert screen.status_code == 200, screen.text
    assert screen.json()["integrity"] == "INTACT"
    assert screen.json()["receiving_account"] == "012****789"  # đã che (SR07)
    assert (screen.json()["amount"], screen.json()["annual_rate"]) == ("30000000", "0.2400")

    response = disburse(team, clock, app_id)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "SUCCESS"
    loan = body["loan"]
    assert (loan["principal"], loan["term_months"], loan["status"]) == ("30000000", 12, "ACTIVE")
    # Niên kim 30 triệu, 24%/năm, 12 kỳ: 2.836.788 mỗi kỳ, kỳ cuối 2.836.786 (mục 1.2.8a).
    assert loan["monthly_payment"] == "2836788"
    installments = loan["installments"]
    assert [i["number"] for i in installments] == list(range(1, 13))
    assert installments[0]["due_date"] == "2026-10-28"
    assert (installments[-1]["principal_due"], installments[-1]["interest_due"]) == (
        "2781163", "55623"
    )
    assert {i["status"] for i in installments} == {"UPCOMING"}
    assert len(loan["contract_sha256"]) == 64
    contract = disburser.get(f"/applications/{app_id}/contract")
    assert contract.status_code == 200
    assert contract.headers["content-type"] == "application/pdf"
    assert hashlib.sha256(contract.content).hexdigest() == loan["contract_sha256"]
    assert status_of(customer, app_id) == "DISBURSED"
    # Cổng thanh toán chuyển đúng một lần, đúng số tiền, đúng tài khoản nhận.
    [transfer] = payments.transfers
    assert (transfer.account, transfer.amount) == (ACCOUNT, Decimal(30_000_000))
    assert body["transaction_ref"] == transfer.transaction_ref
    assert "đã được giải ngân" in sms.last_to(PHONE).message
    assert any(n["type"] == "LOAN_DISBURSED" for n in notifications_of(customer))


@contextmanager
def trigger_disabled(engine: Engine) -> Iterator[None]:
    """Kẻ tấn công có quyền quản trị CSDL tắt trigger BR07 trước khi sửa (ST04)."""
    with engine.begin() as conn:
        conn.execute(text(
            "DISABLE TRIGGER trg_loan_applications_approved_immutable ON loan_applications"
        ))
    try:
        yield
    finally:
        with engine.begin() as conn:
            conn.execute(text(
                "ENABLE TRIGGER trg_loan_applications_approved_immutable ON loan_applications"
            ))


def tamper_requested_amount(engine: Engine, app_id: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE loan_applications SET requested_amount = 90000000 WHERE id = :id"),
            {"id": app_id},
        )


def test_st04_application_edited_in_the_database_after_approval_is_locked_not_disbursed(
    team: Team, customer: TestClient, clock: FakeClock, engine: Engine,
    payments: FakePaymentGateway,
) -> None:
    auditor, approver = team.auditor.client, team.approver.client
    app_id = approved(team, customer)
    with trigger_disabled(engine):
        tamper_requested_amount(engine, app_id)

    response = disburse(team, clock, app_id)

    assert response.status_code == 409
    assert "đã bị khóa" in response.json()["detail"]
    assert status_of(customer, app_id) == "LOCKED"
    assert payments.requests == []  # không có lệnh chuyển tiền nào
    [failure] = auditor.get("/audit/logs", params={"action": "INTEGRITY_FAIL"}).json()
    assert (failure["level"], failure["target_id"]) == ("CRITICAL", app_id)
    assert any(n["type"] == "INTEGRITY_FAIL" for n in notifications_of(auditor))
    assert any(n["type"] == "INTEGRITY_FAIL" for n in notifications_of(approver))
    # Hồ sơ vay bị khóa không bao giờ được giải ngân.
    assert disburse(team, clock, app_id).status_code == 409


def test_opening_the_disbursement_screen_also_checks_the_snapshot(
    team: Team, customer: TestClient, engine: Engine
) -> None:
    app_id = approved(team, customer)
    with trigger_disabled(engine):
        tamper_requested_amount(engine, app_id)

    assert team.disburser.client.get(f"/applications/{app_id}/disbursement").status_code == 409
    assert status_of(customer, app_id) == "LOCKED"


def test_database_refuses_to_change_an_approved_application(
    team: Team, customer: TestClient, clock: FakeClock, engine: Engine
) -> None:
    app_id = approved(team, customer)

    with pytest.raises(Exception, match="BR07"):
        tamper_requested_amount(engine, app_id)

    assert disburse(team, clock, app_id).status_code == 200


def test_someone_who_approved_the_loan_cannot_disburse_it(
    team: Team, customer: TestClient, clock: FakeClock, payments: FakePaymentGateway
) -> None:
    auditor = team.auditor.client
    both = team.hire("pheduyet_giaingan", "APPROVER", "DISBURSER")
    app_id = pending_approval(team, customer, proposed_amount=30_000_000)
    decide(both.client, app_id, "approve").raise_for_status()

    # SoD được kiểm tra trước OTP (SD06): mã sai vẫn bị chặn và ghi nhận là vi phạm SoD.
    response = both.client.post(f"/applications/{app_id}/disburse", json={"otp": "000000"})

    assert response.status_code == 403  # SUC01, BR06
    assert payments.requests == []
    violations = auditor.get("/audit/logs", params={"action": "SOD_VIOLATION"}).json()
    assert [v["detail"] for v in violations] == ["DISBURSE"]
    assert disburse(team, clock, app_id).status_code == 200


def test_disbursement_needs_the_disbursers_otp(
    team: Team, customer: TestClient, payments: FakePaymentGateway
) -> None:
    app_id = approved(team, customer)
    disburser = team.disburser.client

    wrong = disburser.post(f"/applications/{app_id}/disburse", json={"otp": "000000"})
    officer = team.officer.client.post(f"/applications/{app_id}/disburse", json={"otp": "123456"})

    assert wrong.status_code == 403
    assert wrong.json()["detail"] == "Mã OTP không đúng"
    assert officer.status_code == 403  # thiếu quyền DISBURSE
    assert payments.requests == []
    assert status_of(customer, app_id) == "APPROVED"


def test_only_approved_applications_can_be_disbursed(
    team: Team, customer: TestClient, clock: FakeClock
) -> None:
    app_id = pending_approval(team, customer)
    assert team.disburser.client.get(f"/applications/{app_id}/contract").status_code == 409

    assert disburse(team, clock, app_id).status_code == 409
    assert team.disburser.client.get(f"/applications/{app_id}/disbursement").status_code == 409


def test_retry_after_a_temporary_gateway_error_reuses_the_idempotency_key(
    team: Team, customer: TestClient, clock: FakeClock, payments: FakePaymentGateway
) -> None:
    disburser = team.disburser.client
    app_id = approved(team, customer)
    payments.unavailable_for(1)

    first = disburse(team, clock, app_id)

    assert first.status_code == 409
    assert "thử lại" in first.json()["detail"]
    assert status_of(customer, app_id) == "APPROVED"
    assert disburser.get(f"/applications/{app_id}/disbursement").json()["pending"] is True

    second = disburse(team, clock, app_id)

    assert second.status_code == 200, second.text
    assert len(set(payments.requests)) == 1  # UC25 7a: thử lại với cùng idempotency key
    assert len(payments.transfers) == 1
    assert status_of(customer, app_id) == "DISBURSED"


def test_gateway_refusal_fails_the_disbursement(
    team: Team, customer: TestClient, clock: FakeClock, payments: FakePaymentGateway
) -> None:
    app_id = approved(team, customer)
    payments.reject_account(ACCOUNT)

    response = disburse(team, clock, app_id)

    assert response.status_code == 409
    assert "từ chối lệnh giải ngân" in response.json()["detail"]
    assert payments.transfers == []
    assert status_of(customer, app_id) == "APPROVED"
    screen = team.disburser.client.get(f"/applications/{app_id}/disbursement").json()
    assert (screen["failed"], screen["pending"]) == (True, False)
    # Tài khoản nhận không đổi được (BR07): không lập lệnh mới tới cùng tài khoản đó.
    again = disburse(team, clock, app_id)
    assert again.status_code == 409
    assert "hủy hồ sơ vay" in again.json()["detail"]
    assert len(payments.requests) == 1


def test_customer_with_an_active_loan_cannot_open_another_application(
    team: Team, customer: TestClient, clock: FakeClock
) -> None:
    app_id = approved(team, customer)
    disburse(team, clock, app_id).raise_for_status()

    response = customer.post("/applications", json=LOAN)

    assert response.status_code == 409  # BR02: khoản vay chưa tất toán


# --- Ticket #11: hồ sơ vay LOCKED và giải ngân FAILED ------------------------------------------


def test_a_failed_disbursement_notifies_the_credit_officer_and_can_be_cancelled_to_redo(
    team: Team, customer: TestClient, clock: FakeClock, payments: FakePaymentGateway,
) -> None:
    officer, auditor, disburser = team.officer.client, team.auditor.client, team.disburser.client
    app_id = approved(team, customer)
    payments.reject_account(ACCOUNT)
    disburse(team, clock, app_id)  # 409: FAILED (Q13)

    assert any(n["type"] == "DISBURSE_FAILED" for n in notifications_of(officer))

    response = disburser.post(f"/applications/{app_id}/disbursement/cancel")

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "CANCELLED"
    assert status_of(customer, app_id) == "CANCELLED"
    [entry] = auditor.get("/audit/logs", params={"action": "DISBURSE_CANCEL"}).json()
    assert entry["target_id"] == app_id
    # Hồ sơ vay đang xử lý đã kết thúc (BR02): khách hàng nộp hồ sơ vay mới được.
    new_app = customer.post("/applications", json=LOAN)
    assert new_app.status_code == 201, new_app.text


def test_cannot_cancel_an_approved_application_without_a_failed_disbursement(
    team: Team, customer: TestClient
) -> None:
    app_id = approved(team, customer)

    response = team.disburser.client.post(f"/applications/{app_id}/disbursement/cancel")

    assert response.status_code == 409
    assert status_of(customer, app_id) == "APPROVED"


def test_cannot_cancel_while_a_disbursement_is_only_pending(
    team: Team, customer: TestClient, clock: FakeClock, payments: FakePaymentGateway
) -> None:
    """Lỗi tạm thời (PENDING) vẫn thử lại được, khác với FAILED (UC25 7a vs 7b)."""
    app_id = approved(team, customer)
    payments.unavailable_for(1)
    disburse(team, clock, app_id)

    response = team.disburser.client.post(f"/applications/{app_id}/disbursement/cancel")

    assert response.status_code == 409
    assert status_of(customer, app_id) == "APPROVED"
    assert disburse(team, clock, app_id).status_code == 200  # vẫn thử lại được bình thường


def test_only_a_disburser_can_cancel_a_failed_disbursement(
    team: Team, customer: TestClient, clock: FakeClock, payments: FakePaymentGateway
) -> None:
    app_id = approved(team, customer)
    payments.reject_account(ACCOUNT)
    disburse(team, clock, app_id)

    response = team.officer.client.post(f"/applications/{app_id}/disbursement/cancel")

    assert response.status_code == 403
    assert status_of(customer, app_id) == "APPROVED"


def _locked(team: Team, customer: TestClient, clock: FakeClock, engine: Engine) -> str:
    app_id = approved(team, customer)
    with trigger_disabled(engine):
        tamper_requested_amount(engine, app_id)
    disburse(team, clock, app_id)  # 409: SUC02 khóa hồ sơ vay (ST04)
    assert status_of(customer, app_id) == "LOCKED"
    return app_id


def test_auditor_resolves_a_locked_application_after_investigating(
    team: Team, customer: TestClient, clock: FakeClock, engine: Engine
) -> None:
    auditor = team.auditor.client
    app_id = _locked(team, customer, clock, engine)

    response = auditor.post(
        f"/applications/{app_id}/resolve-lock",
        json={"reason": "Đã điều tra xong, không có gian lận"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "CANCELLED"
    assert status_of(customer, app_id) == "CANCELLED"
    [entry] = auditor.get("/audit/logs", params={"action": "APPLICATION_LOCK_RESOLVE"}).json()
    assert entry["target_id"] == app_id
    new_app = customer.post("/applications", json=LOAN)
    assert new_app.status_code == 201, new_app.text


def test_resolve_lock_requires_a_reason_of_at_least_ten_characters(
    team: Team, customer: TestClient, clock: FakeClock, engine: Engine
) -> None:
    app_id = _locked(team, customer, clock, engine)

    response = team.auditor.client.post(
        f"/applications/{app_id}/resolve-lock", json={"reason": "quá ngắn"}
    )

    assert response.status_code == 400  # UC24 2a: cùng quy ước với lý do từ chối, trả về
    assert status_of(customer, app_id) == "LOCKED"


def test_only_an_auditor_can_resolve_a_locked_application(
    team: Team, customer: TestClient, clock: FakeClock, engine: Engine
) -> None:
    app_id = _locked(team, customer, clock, engine)

    response = team.disburser.client.post(
        f"/applications/{app_id}/resolve-lock",
        json={"reason": "Đã điều tra xong, hủy hồ sơ vay"},
    )

    assert response.status_code == 403
    assert status_of(customer, app_id) == "LOCKED"


def test_only_locked_applications_can_be_resolved(team: Team, customer: TestClient) -> None:
    app_id = approved(team, customer)

    response = team.auditor.client.post(
        f"/applications/{app_id}/resolve-lock", json={"reason": "Hồ sơ vay này không bị khóa"}
    )

    assert response.status_code == 409
    assert status_of(customer, app_id) == "APPROVED"
