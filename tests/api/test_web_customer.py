"""Seam 1 (trang HTML qua TestClient): màn hình khách hàng M02 Trang chủ và M03 Nộp hồ sơ vay.

UC10 Cập nhật thông tin cá nhân, UC12 Tạo và nộp hồ sơ vay, UC13 Tải lên giấy tờ, UC15 bổ sung hồ sơ
vay (phía khách hàng), UC16 Theo dõi trạng thái, UC17 Hủy hồ sơ vay; TC01 (phần khách hàng), ST01.
"""

import re
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from loan_system.adapters.cic import FakeCicGateway
from loan_system.adapters.email import FakeEmailGateway
from loan_system.adapters.sms import FakeSmsGateway
from loan_system.domain.applications import CEILING_RATE
from loan_system.domain.calculations import annuity_payment
from loan_system.domain.text import vnd
from tests.api.test_credit_scoring import NATIONAL_ID, cic_report
from tests.api.test_disbursement import approved, disburse
from tests.api.test_web_login import submit, web_login
from tests.api.workflow import DOCUMENTS, FINANCES, Team, customer_browser, submitted_application
from tests.conftest import FakeClock

PHONE = "0901234567"


@pytest.fixture
def team(client: TestClient, clock: FakeClock, email: FakeEmailGateway) -> Team:
    return Team(client, clock, email)


@pytest.fixture
def customer(client: TestClient, sms: FakeSmsGateway) -> TestClient:
    return customer_browser(client, sms, phone=PHONE)


def upload_page(browser: TestClient, app_id: str, doc_type: str) -> Any:
    filename, content = DOCUMENTS[doc_type]
    browser.get("/app/login")
    return browser.post(
        f"/app/applications/{app_id}/documents",
        data={"doc_type": doc_type, "csrf": browser.cookies["csrf"]},
        files={"file": (filename, content, "application/octet-stream")},
    )


def start_application(browser: TestClient, **overrides: str) -> Any:
    form = {"requested_amount": "30000000", "term_months": "12", "purpose": "CONSUMER_GOODS"}
    return submit(browser, "/app/applications/new", {**form, **overrides})


def app_id_of(page: Any) -> str:
    match = re.search(r"/app/applications/([0-9a-f-]{36})/", str(page.url))
    assert match, f"Không thấy mã hồ sơ vay trong {page.url}"
    return match.group(1)


FINANCE_FORM = {k: str(v) for k, v in FINANCES.items()}


# --- M02 --------------------------------------------------------------------------------------


def test_customer_home_offers_a_new_loan_when_nothing_is_in_progress(customer: TestClient) -> None:
    home = customer.get("/app")

    assert home.status_code == 200
    assert "Vay mới" in home.text
    assert "Bạn chưa có hồ sơ vay nào" in home.text


# --- M03, TC01 phần khách hàng ----------------------------------------------------------------


def test_customer_completes_the_four_step_form_and_submits(customer: TestClient) -> None:
    step1 = customer.get("/app/applications/new")
    assert step1.status_code == 200
    assert f'data-ceiling-rate="{CEILING_RATE}"' in step1.text  # ước tính ngay trên trình duyệt

    step2 = start_application(customer)
    assert step2.status_code == 200
    assert step2.url.path.endswith("/finance")
    estimate = annuity_payment(Decimal(30_000_000), CEILING_RATE, 12)
    assert vnd(estimate) in step2.text
    app_id = app_id_of(step2)

    step3 = submit(customer, f"/app/applications/{app_id}/finance", FINANCE_FORM)
    assert step3.url.path == f"/app/applications/{app_id}/documents"
    for doc_type in DOCUMENTS:
        page = upload_page(customer, app_id, doc_type)
        assert page.url.path == f"/app/applications/{app_id}/documents", page.text
    assert "Còn thiếu" not in page.text

    step4 = customer.get(f"/app/applications/{app_id}/confirm")
    assert step4.status_code == 200
    assert "Công ty ABC" in step4.text  # tóm tắt thông tin đã khai
    assert FINANCES["national_id"] not in step4.text  # CCCD luôn hiển thị đã che

    no_consent = submit(customer, f"/app/applications/{app_id}/confirm", {})
    assert no_consent.status_code == 400
    assert "Bạn cần đồng ý" in no_consent.text

    detail = submit(customer, f"/app/applications/{app_id}/confirm",
                    {"accept_data_processing": "true"})
    assert detail.url.path == f"/app/applications/{app_id}"
    assert "Đã nộp" in detail.text
    assert re.search(r"HS\d{10}", detail.text)

    home = customer.get("/app")
    assert "Đã nộp" in home.text
    assert "Vay mới" not in home.text  # BR02: đang có hồ sơ vay chưa kết thúc


def test_step_one_values_outside_br02_are_explained(customer: TestClient) -> None:
    page = start_application(customer, requested_amount="1000000", term_months="48")

    assert page.status_code == 400
    assert "Số tiền vay từ 5.000.000 đến 100.000.000 đồng" in page.text
    assert "Kỳ hạn từ 6 đến 36 tháng" in page.text
    assert 'value="1000000"' in page.text


def test_draft_can_be_resumed_from_the_home_page(customer: TestClient) -> None:
    app_id = app_id_of(start_application(customer))

    home = customer.get("/app")

    assert "Nháp" in home.text
    assert f"/app/applications/{app_id}/finance" in home.text  # "Tiếp tục hoàn thiện"


def test_submitting_an_incomplete_application_lists_what_is_missing(customer: TestClient) -> None:
    app_id = app_id_of(start_application(customer))

    page = submit(customer, f"/app/applications/{app_id}/confirm",
                  {"accept_data_processing": "true"})

    assert page.status_code == 400
    assert "Số CCCD" in page.text
    assert "CCCD mặt trước" in page.text


def test_wrong_file_type_is_rejected_with_the_reason(customer: TestClient) -> None:
    app_id = app_id_of(start_application(customer))
    customer.get("/app/login")

    page = customer.post(
        f"/app/applications/{app_id}/documents",
        data={"doc_type": "ID_FRONT", "csrf": customer.cookies["csrf"]},
        files={"file": ("virus.jpg", b"MZ" + b"\x00" * 100, "image/jpeg")},
    )

    assert page.status_code == 400
    assert "alert" in page.text


def test_second_application_is_refused_while_one_is_in_progress(customer: TestClient) -> None:
    start_application(customer)

    again = start_application(customer)

    assert again.status_code == 409
    assert "đang có một hồ sơ vay hoặc khoản vay chưa kết thúc" in again.text


# --- UC17 -------------------------------------------------------------------------------------


def test_customer_cancels_a_submitted_application(customer: TestClient) -> None:
    app_id = submitted_application(customer)
    detail = customer.get(f"/app/applications/{app_id}")
    assert "data-confirm" in detail.text  # hủy là thao tác không hoàn tác: hỏi lại

    home = submit(customer, f"/app/applications/{app_id}/cancel", {"reason": "Đổi ý"})

    assert home.url.path == "/app"
    assert "Đã hủy" in home.text
    assert "Vay mới" in home.text


# --- UC15: bổ sung hồ sơ vay khi NEED_INFO -----------------------------------------------------


def test_customer_supplements_only_the_requested_items(team: Team, customer: TestClient) -> None:
    app_id = submitted_application(customer)
    officer = team.officer.client
    officer.post(f"/applications/{app_id}/claim").raise_for_status()
    officer.post(f"/applications/{app_id}/request-info", json={
        "message": "Vui lòng cập nhật thu nhập và sao kê lương mới.",
        "items": ["monthly_income", "INCOME_PROOF"],
    }).raise_for_status()

    detail = customer.get(f"/app/applications/{app_id}")
    assert "Cần bổ sung" in detail.text
    assert "Vui lòng cập nhật thu nhập và sao kê lương mới." in detail.text

    finance = customer.get(f"/app/applications/{app_id}/finance")
    assert 'name="monthly_income"' in finance.text
    assert 'name="occupation"' not in finance.text  # chỉ mở những mục được yêu cầu

    after = submit(customer, f"/app/applications/{app_id}/finance", {"monthly_income": "28000000"})
    assert after.url.path == f"/app/applications/{app_id}/documents", after.text
    assert upload_page(customer, app_id, "INCOME_PROOF").status_code == 200

    done = submit(customer, f"/app/applications/{app_id}/confirm",
                  {"accept_data_processing": "true"})
    assert done.url.path == f"/app/applications/{app_id}"
    assert "Đã nộp" in done.text


# --- ST01 -------------------------------------------------------------------------------------


def test_st01_customer_cannot_see_another_customers_application(
    client: TestClient, sms: FakeSmsGateway, customer: TestClient
) -> None:
    app_id = submitted_application(customer)
    other = customer_browser(client, sms, phone="0907654321", email="binh@example.com")

    for path in ("", "/finance", "/documents", "/confirm"):
        page = other.get(f"/app/applications/{app_id}{path}")
        assert page.status_code == 404, path
        assert "Không tìm thấy hồ sơ vay" in page.text
    cancel = submit(other, f"/app/applications/{app_id}/cancel", {})
    assert cancel.status_code == 404
    assert customer.get(f"/app/applications/{app_id}").status_code == 200


def test_staff_cannot_open_the_customer_application_form(team: Team) -> None:
    page = team.officer.client.get("/app/applications/new")

    assert page.status_code == 403
    assert "Bạn không có quyền" in page.text


# --- M02: khoản vay và kỳ đến hạn -------------------------------------------------------------


def test_home_shows_the_next_installment_of_a_disbursed_loan(
    team: Team, customer: TestClient, clock: FakeClock, cic: FakeCicGateway
) -> None:
    cic.respond(NATIONAL_ID, cic_report(highest_debt_group=2, utility_late_payments=3))
    app_id = approved(team, customer)
    disburse(team, clock, app_id).raise_for_status()
    web_login(customer)  # quy trình duyệt dài hơn 15 phút: đăng nhập lại

    home = customer.get("/app")

    assert "Đang vay" in home.text
    assert "28/10/2026" in home.text  # kỳ 1 (như test_payment)
    assert vnd(Decimal(2_836_788)) in home.text


# --- UC10 -------------------------------------------------------------------------------------


def test_customer_updates_their_profile(customer: TestClient) -> None:
    page = customer.get("/app/profile")
    assert page.status_code == 200

    saved = submit(customer, "/app/profile", {
        "occupation": "Giáo viên", "employer": "Trường THPT A", "employment_years": "3",
        "monthly_income": "", "housing_type": "OWN", "address": "5 Nguyễn Huệ, Quận 1",
    })

    assert saved.url.path == "/app/profile"
    assert "Đã lưu thông tin cá nhân" in saved.text
    assert 'value="Giáo viên"' in saved.text


def test_income_cannot_change_while_an_application_is_in_progress(customer: TestClient) -> None:
    submitted_application(customer)

    page = submit(customer, "/app/profile", {"monthly_income": "40000000"})

    assert page.status_code == 409
    assert "Không thể đổi thu nhập" in page.text


def test_other_profile_fields_can_still_be_saved_while_income_is_locked(
    customer: TestClient,
) -> None:
    submitted_application(customer)
    page = customer.get("/app/profile")
    assert 'name="monthly_income"' in page.text
    assert re.search(r'name="monthly_income"[^>]*disabled', page.text)  # trình duyệt không gửi ô này

    saved = submit(customer, "/app/profile", {"address": "7 Hai Bà Trưng, Quận 3"})

    assert saved.url.path == "/app/profile"
    assert "Đã lưu thông tin cá nhân" in saved.text
