"""Seam 1 (trang HTML qua TestClient): trang giới thiệu công khai, thông báo trong ứng dụng, đổi số
điện thoại/email bằng OTP (UC10) và Kiểm soát viên hủy hồ sơ vay bị khóa (ticket #11).
"""

import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from loan_system.adapters.email import FakeEmailGateway
from loan_system.adapters.sms import FakeSmsGateway
from tests.api.test_appraisal import status_of
from tests.api.test_customer_registration import otp_sent_to
from tests.api.test_disbursement import _locked
from tests.api.test_web_login import assert_forms_carry_csrf, submit
from tests.api.workflow import Team, customer_browser, notifications_of, submitted_application
from tests.conftest import FakeClock

PHONE = "0901234567"


@pytest.fixture
def team(client: TestClient, clock: FakeClock, email: FakeEmailGateway) -> Team:
    return Team(client, clock, email)


@pytest.fixture
def customer(client: TestClient, sms: FakeSmsGateway) -> TestClient:
    return customer_browser(client, sms, phone=PHONE)


# --- Trang giới thiệu -------------------------------------------------------------------------


def test_landing_page_is_public_and_leads_to_registration(client: TestClient) -> None:
    page = client.get("/")

    assert page.status_code == 200
    assert 'href="/app/register"' in page.text
    assert 'href="/app/login"' in page.text
    assert "data-estimate" in page.text


def test_landing_page_sends_a_logged_in_user_to_the_app(customer: TestClient) -> None:
    assert customer.get("/").url.path == "/app"


# --- Thông báo --------------------------------------------------------------------------------


def test_notifications_page_lists_unread_ones_and_marks_them_read(
    team: Team, customer: TestClient
) -> None:
    officer = team.officer.client
    submitted_application(customer)
    [notice] = [n for n in notifications_of(officer) if n["type"] == "APPLICATION_SUBMITTED"]

    page = officer.get("/app/notifications")

    assert page.status_code == 200
    assert notice["content"] in page.text
    assert 'class="unread"' in page.text
    assert '<span class="count" title="Chưa đọc">1</span>' in page.text
    assert_forms_carry_csrf(officer, page.text)

    after = submit(officer, f"/app/notifications/{notice['id']}/read", {})

    assert after.status_code == 200
    assert 'class="unread"' not in after.text
    assert 'class="count"' not in after.text
    assert all(n["is_read"] for n in notifications_of(officer))


def test_mark_all_read_clears_the_unread_count(team: Team, customer: TestClient) -> None:
    officer = team.officer.client
    submitted_application(customer)

    after = submit(officer, "/app/notifications/read-all", {})

    assert after.status_code == 200
    assert 'class="count"' not in after.text


def test_someone_elses_notification_cannot_be_marked_read(
    team: Team, customer: TestClient
) -> None:
    officer = team.officer.client  # phải có trước khi nộp thì mới nhận thông báo
    submitted_application(customer)
    [notice] = notifications_of(officer)

    response = submit(customer, f"/app/notifications/{notice['id']}/read", {})

    assert response.status_code == 404
    assert not notifications_of(team.officer.client)[0]["is_read"]


# --- UC10: đổi số điện thoại, email -----------------------------------------------------------


def test_customer_changes_email_after_confirming_the_otp(
    customer: TestClient, sms: FakeSmsGateway
) -> None:
    otp_page = submit(customer, "/app/profile/contact",
                      {"field": "email", "new_value": "moi@example.com"})
    assert otp_page.status_code == 200
    challenge = re.search(r'name="challenge_id" value="([^"]+)"', otp_page.text)
    assert challenge

    wrong = submit(customer, "/app/profile/contact/confirm",
                   {"challenge_id": challenge.group(1), "otp": "000000"})
    assert wrong.status_code == 400
    assert "moi@example.com" not in customer.get("/app/profile").text

    done = submit(customer, "/app/profile/contact/confirm",
                  {"challenge_id": challenge.group(1), "otp": otp_sent_to(sms, PHONE)})

    assert done.status_code == 200
    assert done.url.path == "/app/profile"
    assert "moi@example.com" in done.text


def test_contact_change_rejects_a_malformed_phone_number(customer: TestClient) -> None:
    page = submit(customer, "/app/profile/contact", {"field": "phone", "new_value": "12345"})

    assert page.status_code == 400
    assert "Số điện thoại gồm 10 chữ số" in page.text


def test_contact_change_refuses_a_phone_number_of_another_customer(
    client: TestClient, customer: TestClient, sms: FakeSmsGateway
) -> None:
    customer_browser(client, sms, phone="0907654321", email="binh@example.com")

    page = submit(customer, "/app/profile/contact", {"field": "phone", "new_value": "0907654321"})

    assert page.status_code == 409
    assert "đã thuộc về một khách hàng khác" in page.text


# --- Hồ sơ vay bị khóa ------------------------------------------------------------------------


def test_auditor_cancels_a_locked_application_from_the_locked_page(
    team: Team, customer: TestClient, clock: FakeClock, engine: Engine
) -> None:
    auditor = team.auditor.client
    app_id = _locked(team, customer, clock, engine)

    page = auditor.get("/app/locked")
    assert page.status_code == 200
    assert f"/app/locked/{app_id}/resolve" in page.text
    assert 'href="/app/locked"' in page.text  # mục menu của Kiểm soát viên

    too_short = submit(auditor, f"/app/locked/{app_id}/resolve", {"reason": "ngắn"})
    assert too_short.status_code == 400
    assert status_of(customer, app_id) == "LOCKED"

    done = submit(auditor, f"/app/locked/{app_id}/resolve",
                  {"reason": "Đã điều tra xong, không có gian lận"})

    assert done.status_code == 200
    assert "Không có hồ sơ vay nào đang bị khóa" in done.text
    assert status_of(customer, app_id) == "CANCELLED"


def test_locked_page_is_only_for_the_lock_resolver(team: Team) -> None:
    page = team.officer.client.get("/app/locked")

    assert page.status_code == 403
    assert 'href="/app/locked"' not in team.officer.client.get("/app").text
