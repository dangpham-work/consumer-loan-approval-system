"""Seam 1 (trang HTML qua TestClient): màn hình nhân viên M07 Phê duyệt hồ sơ vay và M08 Giải ngân.

UC23 Phê duyệt, UC24 Từ chối / Trả về, UC25 Giải ngân, UC26 hợp đồng PDF; TC02 phê duyệt kép, ST03
phân tách nhiệm vụ, ST04 hồ sơ vay bị sửa trong CSDL sau khi duyệt.
"""

import hashlib
import re
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from loan_system.adapters.email import FakeEmailGateway
from loan_system.adapters.payment import FakePaymentGateway
from loan_system.adapters.sms import FakeSmsGateway
from tests.api.staff import otp
from tests.api.test_appraisal import COMMENT, PHONE, status_of
from tests.api.test_approval import pending_approval
from tests.api.test_disbursement import (
    ACCOUNT,
    approved,
    tamper_requested_amount,
    trigger_disabled,
)
from tests.api.test_dual_approval import big_loan
from tests.api.test_web_login import assert_forms_carry_csrf, submit
from tests.api.workflow import Team, customer_browser
from tests.conftest import FakeClock

REASON = "Lịch sử tín dụng chưa đủ tốt để cho vay."


@pytest.fixture
def team(client: TestClient, clock: FakeClock, email: FakeEmailGateway) -> Team:
    return Team(client, clock, email)


@pytest.fixture
def customer(client: TestClient, sms: FakeSmsGateway) -> TestClient:
    return customer_browser(client, sms, phone=PHONE)


def version_on(page_text: str) -> str:
    match = re.search(r'name="version" value="(\d+)"', page_text)
    assert match, "trang M07 không có phiên bản hồ sơ vay"
    return match.group(1)


def decide_on_web(approver: TestClient, app_id: str, action: str, **form: str) -> Any:
    """Quản lý mở M07 rồi gửi biểu mẫu quyết định với phiên bản vừa xem."""
    page = approver.get(f"/app/queue/{app_id}/approval")
    return submit(approver, f"/app/queue/{app_id}/{action}",
                  {"version": version_on(page.text), **form})


# --- M07 --------------------------------------------------------------------------------------


def test_approver_opens_the_approval_screen_from_the_queue_and_approves(
    team: Team, customer: TestClient
) -> None:
    app_id = pending_approval(team, customer)
    approver = team.approver.client

    detail = approver.get(f"/app/queue/{app_id}")
    assert f'href="/app/queue/{app_id}/approval"' in detail.text

    page = approver.get(f"/app/queue/{app_id}/approval")
    assert page.status_code == 200
    assert COMMENT in page.text  # tờ trình của chuyên viên thẩm định
    assert "25.000.000 đ" in page.text  # hạn mức đề xuất
    assert "Hạng" in page.text  # điểm tín dụng
    assert "Cần 1 – đã có 0" in page.text
    assert_forms_carry_csrf(approver, page.text)
    assert f'action="/app/queue/{app_id}/approve"' in page.text
    assert f'action="/app/queue/{app_id}/reject"' in page.text
    assert f'action="/app/queue/{app_id}/return"' in page.text
    assert "data-confirm=" in page.text  # hộp thoại xác nhận khi phê duyệt

    done = submit(approver, f"/app/queue/{app_id}/approve",
                  {"version": version_on(page.text), "comment": "Đồng ý"})

    assert done.status_code == 200
    assert done.url.path == f"/app/queue/{app_id}/approval"
    assert status_of(customer, app_id) == "APPROVED"
    assert "Nhân viên pheduyet1" in done.text  # lịch sử quyết định
    assert f'action="/app/queue/{app_id}/approve"' not in done.text


def test_tc02_a_big_loan_needs_a_second_approver_on_the_web(
    team: Team, customer: TestClient, clock: FakeClock
) -> None:
    first, second = team.approver.client, team.approver2.client
    app_id = big_loan(team, customer)
    assert "Cần 2 – đã có 0" in first.get(f"/app/queue/{app_id}/approval").text

    once = decide_on_web(first, app_id, "approve")

    assert status_of(customer, app_id) == "PENDING_APPROVAL"
    assert "Cần 2 – đã có 1" in once.text
    # Người vừa duyệt không còn nút quyết định (BR06).
    assert f'action="/app/queue/{app_id}/approve"' not in once.text
    assert "đã quyết định" in once.text

    clock.advance(minutes=5)
    page = second.get(f"/app/queue/{app_id}/approval")
    assert f'action="/app/queue/{app_id}/approve"' in page.text
    decide_on_web(second, app_id, "approve")

    assert status_of(customer, app_id) == "APPROVED"


def test_reject_and_return_need_a_reason_of_ten_characters(
    team: Team, customer: TestClient
) -> None:
    approver = team.approver.client
    app_id = pending_approval(team, customer)

    short = decide_on_web(approver, app_id, "reject",
                          reason_group="CREDIT_HISTORY", description="Kém")
    assert short.status_code == 400
    assert "ít nhất 10 ký tự" in short.text
    short = decide_on_web(approver, app_id, "return", clarification="Làm rõ")
    assert short.status_code == 400
    assert status_of(customer, app_id) == "PENDING_APPROVAL"

    done = decide_on_web(approver, app_id, "reject",
                         reason_group="CREDIT_HISTORY", description=REASON)

    assert done.status_code == 200
    assert status_of(customer, app_id) == "REJECTED"
    assert REASON in done.text


def test_return_sends_the_application_back_to_appraisal(
    team: Team, customer: TestClient
) -> None:
    app_id = pending_approval(team, customer)

    decide_on_web(team.approver.client, app_id, "return",
                  clarification="Cần làm rõ nguồn thu nhập thêm ngoài lương.")

    assert status_of(customer, app_id) == "APPRAISING"


def test_a_decision_on_a_stale_screen_asks_to_reload(
    team: Team, customer: TestClient
) -> None:
    first, second = team.approver.client, team.approver2.client
    app_id = big_loan(team, customer)
    stale = second.get(f"/app/queue/{app_id}/approval")
    decide_on_web(first, app_id, "approve")

    response = submit(second, f"/app/queue/{app_id}/approve",
                      {"version": version_on(stale.text)})

    assert response.status_code == 409
    assert "tải lại" in response.text
    assert f'href="/app/queue/{app_id}/approval"' in response.text
    assert status_of(customer, app_id) == "PENDING_APPROVAL"


def test_st03_an_approver_who_already_decided_is_refused_by_the_server(
    team: Team, customer: TestClient
) -> None:
    first = team.approver.client
    app_id = big_loan(team, customer)
    decide_on_web(first, app_id, "approve")
    version = first.get(f"/applications/{app_id}/approval").json()["version"]

    # Nút đã bị ẩn; gửi thẳng biểu mẫu vẫn bị chặn và ghi nhật ký.
    again = submit(first, f"/app/queue/{app_id}/approve", {"version": str(version)})

    assert again.status_code == 403
    assert status_of(customer, app_id) == "PENDING_APPROVAL"
    logs = team.auditor.client.get(
        "/audit/logs", params={"action": "SOD_VIOLATION", "target_id": app_id}
    ).json()
    assert len(logs) == 1


def test_only_approvers_open_the_approval_screen(team: Team, customer: TestClient) -> None:
    app_id = pending_approval(team, customer)

    assert team.officer.client.get(f"/app/queue/{app_id}/approval").status_code == 403
    assert "/approval" not in team.officer.client.get(f"/app/queue/{app_id}").text


# --- M08 --------------------------------------------------------------------------------------


def test_disburser_checks_integrity_disburses_with_totp_and_downloads_the_contract(
    team: Team, customer: TestClient, clock: FakeClock, payments: FakePaymentGateway
) -> None:
    disburser = team.disburser
    app_id = approved(team, customer)

    detail = disburser.client.get(f"/app/queue/{app_id}")
    assert f'href="/app/queue/{app_id}/disbursement"' in detail.text

    page = disburser.client.get(f"/app/queue/{app_id}/disbursement")
    assert page.status_code == 200
    assert "Toàn vẹn: khớp" in page.text
    assert "012****789" in page.text  # tài khoản nhận đã che (SR07)
    assert ACCOUNT not in page.text
    assert "30.000.000 đ" in page.text
    assert 'name="otp"' in page.text
    assert "data-confirm=" in page.text
    assert_forms_carry_csrf(disburser.client, page.text)

    done = submit(disburser.client, f"/app/queue/{app_id}/disburse",
                  {"otp": otp(clock, disburser.totp_secret)})

    assert done.status_code == 200
    assert done.url.path == f"/app/queue/{app_id}/disbursement"
    assert status_of(customer, app_id) == "DISBURSED"
    assert len(payments.transfers) == 1
    assert payments.transfers[0].transaction_ref in done.text
    assert 'name="otp"' not in done.text
    # Gửi lại biểu mẫu (bấm hai lần): không chuyển tiền lần nữa, M08 hiện kết quả đã giải ngân.
    clock.advance(seconds=30)
    twice = submit(disburser.client, f"/app/queue/{app_id}/disburse",
                   {"otp": otp(clock, disburser.totp_secret)})
    assert twice.status_code == 200
    assert "Đã giải ngân" in twice.text
    assert len(payments.transfers) == 1
    contract = disburser.client.get(f"/app/queue/{app_id}/contract")
    assert contract.status_code == 200
    assert contract.headers["content-type"] == "application/pdf"
    assert contract.content.startswith(b"%PDF")
    assert hashlib.sha256(contract.content).hexdigest() in done.text


def test_wrong_totp_does_not_disburse(
    team: Team, customer: TestClient, payments: FakePaymentGateway
) -> None:
    disburser = team.disburser.client
    app_id = approved(team, customer)

    malformed = submit(disburser, f"/app/queue/{app_id}/disburse", {"otp": "12"})
    assert malformed.status_code == 400
    wrong = submit(disburser, f"/app/queue/{app_id}/disburse", {"otp": "000000"})

    assert wrong.status_code == 403
    assert "Mã OTP không đúng" in wrong.text
    assert payments.requests == []
    assert status_of(customer, app_id) == "APPROVED"


def test_st04_tampered_application_shows_red_integrity_and_is_locked(
    team: Team, customer: TestClient, engine: Engine, payments: FakePaymentGateway
) -> None:
    disburser = team.disburser.client
    app_id = approved(team, customer)
    with trigger_disabled(engine):
        tamper_requested_amount(engine, app_id)

    page = disburser.get(f"/app/queue/{app_id}/disbursement")

    assert page.status_code == 409
    assert "Toàn vẹn: không khớp" in page.text
    assert "đã bị khóa" in page.text
    assert 'name="otp"' not in page.text
    assert status_of(customer, app_id) == "LOCKED"
    assert payments.requests == []
    again = disburser.get(f"/app/queue/{app_id}/disbursement")
    assert "Toàn vẹn: không khớp" in again.text
    assert "Bị khóa" in again.text
    assert 'name="otp"' not in again.text


def test_refused_transfer_shows_failed_and_can_be_cancelled_to_redo(
    team: Team, customer: TestClient, clock: FakeClock, payments: FakePaymentGateway
) -> None:
    disburser = team.disburser
    app_id = approved(team, customer)
    payments.reject_account(ACCOUNT)

    refused = submit(disburser.client, f"/app/queue/{app_id}/disburse",
                     {"otp": otp(clock, disburser.totp_secret)})

    assert refused.status_code == 409
    assert "từ chối lệnh giải ngân" in refused.text
    page = disburser.client.get(f"/app/queue/{app_id}/disbursement")
    assert "Giải ngân thất bại" in page.text
    assert 'name="otp"' not in page.text
    assert f'action="/app/queue/{app_id}/disbursement/cancel"' in page.text

    cancelled = submit(disburser.client, f"/app/queue/{app_id}/disbursement/cancel", {})

    assert cancelled.status_code == 200
    assert status_of(customer, app_id) == "CANCELLED"


def test_temporary_gateway_error_says_the_order_is_pending(
    team: Team, customer: TestClient, clock: FakeClock, payments: FakePaymentGateway
) -> None:
    disburser = team.disburser
    app_id = approved(team, customer)
    payments.unavailable_for(1)

    pending = submit(disburser.client, f"/app/queue/{app_id}/disburse",
                     {"otp": otp(clock, disburser.totp_secret)})

    assert pending.status_code == 409
    assert "đang chờ" in pending.text
    assert 'name="otp"' in pending.text  # thử lại được


def test_someone_who_approved_cannot_open_the_disbursement_screen(
    team: Team, customer: TestClient
) -> None:
    both = team.hire("pheduyet_giaingan", "APPROVER", "DISBURSER")
    app_id = pending_approval(team, customer, proposed_amount=30_000_000)
    decide_on_web(both.client, app_id, "approve")

    assert both.client.get(f"/app/queue/{app_id}/disbursement").status_code == 403
