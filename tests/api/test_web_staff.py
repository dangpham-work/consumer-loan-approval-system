"""Seam 1 (trang HTML qua TestClient): màn hình nhân viên M05 Hàng đợi hồ sơ vay và M06 Chi tiết,
thẩm định hồ sơ vay.

UC11 (xem thông tin khách hàng đã che, "Hiện" ghi VIEW_PII), UC12 1a nộp hộ, UC14 Kiểm tra hồ sơ vay,
UC15 Yêu cầu bổ sung, UC20 Giải thích điểm, UC22 Thẩm định; ST03 phân tách nhiệm vụ.
"""

import re
import pytest
from fastapi.testclient import TestClient

from loan_system.adapters.email import FakeEmailGateway
from loan_system.adapters.sms import FakeSmsGateway
from tests.api.test_application_review import WALK_IN, sms_code
from tests.api.test_web_customer import FINANCE_FORM, app_id_of, upload_page
from tests.api.test_web_login import submit
from tests.api.workflow import (
    DOCUMENTS,
    FINANCES,
    Team,
    customer_browser,
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


def code_of(customer: TestClient, app_id: str) -> str:
    code: str = customer.get(f"/applications/{app_id}").json()["code"]
    return code


def status_of(customer: TestClient, app_id: str) -> str:
    status: str = customer.get(f"/applications/{app_id}").json()["status"]
    return status


def appraising(team: Team, customer: TestClient) -> str:
    app_id = submitted_application(customer)
    assert verify_as(team.officer.client, app_id).status_code == 200
    return app_id


def view_pii_count(team: Team, customer: TestClient) -> int:
    customer_id = customer.get("/customers/me").json()["id"]
    logs = team.auditor.client.get(
        "/audit/logs", params={"action": "VIEW_PII", "target_id": customer_id}
    ).json()
    return len(logs)


# --- M05 --------------------------------------------------------------------------------------


def test_officer_lands_on_the_queue_of_submitted_applications(
    team: Team, customer: TestClient
) -> None:
    app_id = submitted_application(customer)
    code = code_of(customer, app_id)

    home = team.officer.client.get("/app")

    assert home.status_code == 200
    assert "Hàng đợi hồ sơ vay" in home.text
    assert code in home.text
    assert "Nguyễn Văn An" in home.text  # họ tên khách hàng
    assert f'href="/app/queue/{app_id}"' in home.text


def test_each_role_sees_the_work_waiting_for_it_by_default(
    team: Team, customer: TestClient
) -> None:
    app_id = submitted_application(customer)
    code = code_of(customer, app_id)

    # Hồ sơ vay Đã nộp là việc của NV tín dụng, chưa phải việc của Chuyên viên thẩm định.
    assert code not in team.appraiser.client.get("/app/queue").text
    everything = team.appraiser.client.get("/app/queue", params={"status": "ALL"})
    assert code in everything.text

    assert verify_as(team.officer.client, app_id).status_code == 200
    assert code in team.appraiser.client.get("/app/queue").text
    assert code not in team.officer.client.get("/app/queue").text


def test_queue_filters_by_status_and_searches_by_code_or_name(
    team: Team, customer: TestClient
) -> None:
    app_id = submitted_application(customer)
    code = code_of(customer, app_id)
    officer = team.officer.client

    assert code in officer.get("/app/queue", params={"status": "SUBMITTED"}).text
    assert code not in officer.get("/app/queue", params={"status": "APPRAISING"}).text
    assert code in officer.get("/app/queue", params={"status": "ALL", "q": code[-4:]}).text
    assert code in officer.get("/app/queue", params={"status": "ALL", "q": "văn an"}).text
    assert code not in officer.get("/app/queue", params={"status": "ALL", "q": "Trần"}).text


def test_admin_without_application_view_keeps_the_plain_home_page(team: Team) -> None:
    home = team.admin.client.get("/app")

    assert "Xin chào" in home.text
    assert team.admin.client.get("/app/queue").status_code == 403


# --- M06: UC14, UC15 -------------------------------------------------------------------------


def test_officer_receives_checks_documents_and_verifies_on_the_web(
    team: Team, customer: TestClient
) -> None:
    app_id = submitted_application(customer)
    officer = team.officer.client

    detail = officer.get(f"/app/queue/{app_id}")
    assert detail.status_code == 200
    assert "Nhận xử lý" in detail.text
    assert FINANCES["national_id"] not in detail.text  # NV tín dụng chỉ thấy dữ liệu đã che
    assert "data-reveal-url" not in detail.text  # không có CUSTOMER_VIEW_PII

    page = submit(officer, f"/app/queue/{app_id}/claim", {})
    assert page.url.path == f"/app/queue/{app_id}"
    assert "Xác nhận hợp lệ" in page.text

    early = submit(officer, f"/app/queue/{app_id}/verify", {})
    assert early.status_code == 409
    assert "giấy tờ" in early.text

    document_ids = re.findall(rf"/app/queue/{app_id}/documents/([0-9a-f-]{{36}})/review",
                              page.text)
    assert len(document_ids) == len(DOCUMENTS)
    for document_id in document_ids:
        reviewed = submit(officer, f"/app/queue/{app_id}/documents/{document_id}/review",
                          {"verdict": "PASS", "note": ""})
        assert reviewed.url.path == f"/app/queue/{app_id}"

    verified = submit(officer, f"/app/queue/{app_id}/verify", {})
    assert verified.url.path == f"/app/queue/{app_id}"
    # Hợp lệ kích hoạt chấm điểm ngay (UC18), hồ sơ vay sang Đang thẩm định.
    assert status_of(customer, app_id) == "APPRAISING"
    assert "Đang thẩm định" in verified.text


def test_officer_requests_more_information_from_the_customer(
    team: Team, customer: TestClient
) -> None:
    app_id = submitted_application(customer)
    officer = team.officer.client
    submit(officer, f"/app/queue/{app_id}/claim", {})

    too_short = submit(officer, f"/app/queue/{app_id}/request-info",
                       {"message": "Thiếu", "items": "INCOME_PROOF"})
    assert too_short.status_code == 400
    assert "Lời nhắn từ 10 đến 500 ký tự" in too_short.text

    officer.get("/app/login")
    page = officer.post(
        f"/app/queue/{app_id}/request-info",
        data={"message": "Vui lòng bổ sung sao kê lương 3 tháng gần nhất.",
              "items": ["INCOME_PROOF", "monthly_income"], "csrf": officer.cookies["csrf"]},
    )
    assert page.url.path == f"/app/queue/{app_id}"
    assert "Cần bổ sung" in page.text
    assert status_of(customer, app_id) == "NEED_INFO"
    assert "sao kê lương 3 tháng" in customer.get(f"/app/applications/{app_id}").text


def test_an_application_held_by_another_officer_offers_no_actions(
    team: Team, customer: TestClient
) -> None:
    app_id = submitted_application(customer)
    submit(team.officer.client, f"/app/queue/{app_id}/claim", {})

    page = team.officer2.client.get(f"/app/queue/{app_id}")

    assert "Nhận xử lý" not in page.text
    assert "Xác nhận hợp lệ" not in page.text
    assert submit(team.officer2.client, f"/app/queue/{app_id}/claim", {}).status_code == 409


def test_staff_cannot_open_the_edit_steps_of_a_customer_application(
    team: Team, customer: TestClient
) -> None:
    app_id = submitted_application(customer)
    officer = team.officer.client
    submit(officer, f"/app/queue/{app_id}/claim", {})
    officer.get("/app/login")
    officer.post(f"/app/queue/{app_id}/request-info", data={
        "message": "Vui lòng bổ sung sao kê lương 3 tháng gần nhất.", "items": "INCOME_PROOF",
        "csrf": officer.cookies["csrf"],
    })

    # Chỉ chủ hồ sơ vay (hoặc Người tạo khi nộp hộ) mới mở được các bước sửa.
    for step in ("loan", "finance", "documents", "confirm"):
        page = officer.get(f"/app/applications/{app_id}/{step}")
        assert page.url.path == f"/app/queue/{app_id}", step


# --- M06: UC20, UC22 -------------------------------------------------------------------------


def test_appraiser_sees_masked_data_with_a_reveal_button_score_and_cic(
    team: Team, customer: TestClient
) -> None:
    app_id = appraising(team, customer)
    appraiser = team.appraiser.client

    detail = appraiser.get(f"/app/queue/{app_id}")
    assert "Nhận thẩm định" in detail.text

    page = submit(appraiser, f"/app/queue/{app_id}/appraisal/open", {})

    assert page.url.path == f"/app/queue/{app_id}"
    assert FINANCES["national_id"] not in page.text  # che mặc định, chỉ hiện khi bấm "Hiện"
    customer_id = customer.get("/customers/me").json()["id"]
    assert f'data-reveal-url="/customers/{customer_id}/reveal-pii"' in page.text
    assert view_pii_count(team, customer) == 0  # mở màn hình chưa phải là xem PII
    assert "Hạng A" in page.text  # CIC giả lập mặc định: nhóm 1, hạng A
    assert "Nhóm nợ cao nhất" in page.text
    assert "Lập tờ trình" in page.text


def test_appraiser_recomputes_dti_then_submits_the_report(
    team: Team, customer: TestClient
) -> None:
    app_id = appraising(team, customer)
    appraiser = team.appraiser.client
    submit(appraiser, f"/app/queue/{app_id}/appraisal/open", {})
    form = {"recommendation": "APPROVE", "proposed_amount": "25000000", "proposed_term": "12",
            "comment": COMMENT}

    preview = submit(appraiser, f"/app/queue/{app_id}/appraisal", {**form, "action": "preview"})
    assert preview.status_code == 200
    assert "DTI" in preview.text
    assert re.search(r"\d+,\d{2}%", preview.text)  # DTI dạng phần trăm
    assert status_of(customer, app_id) == "APPRAISING"
    assert 'value="25000000"' in preview.text  # giữ nguyên dữ liệu đã nhập

    too_much = submit(appraiser, f"/app/queue/{app_id}/appraisal",
                      {**form, "proposed_amount": "90000000", "action": "submit"})
    assert too_much.status_code == 400

    done = submit(appraiser, f"/app/queue/{app_id}/appraisal", {**form, "action": "submit"})
    assert done.url.path == f"/app/queue/{app_id}"
    assert status_of(customer, app_id) == "PENDING_APPROVAL"
    assert "Chờ phê duyệt" in done.text
    assert COMMENT in done.text  # tờ trình hiển thị lại cho người xem sau


def test_document_viewer_shows_the_viewer_watermark_only_to_the_appraiser(
    team: Team, customer: TestClient
) -> None:
    app_id = appraising(team, customer)
    appraiser = team.appraiser.client
    page = submit(appraiser, f"/app/queue/{app_id}/appraisal/open", {})
    match = re.search(rf'href="/app/queue/{app_id}/documents/([0-9a-f-]{{36}})"[^>]*>Chứng minh',
                      page.text)
    assert match, "Trang thẩm định phải có liên kết xem giấy tờ"
    viewer_path = f"/app/queue/{app_id}/documents/{match.group(1)}"

    viewer = appraiser.get(viewer_path)

    assert viewer.status_code == 200
    assert viewer.headers["cache-control"] == "no-store"
    assert "thamdinh1" in viewer.text  # watermark tên người xem
    assert "data:application/pdf;base64," in viewer.text
    views = team.auditor.client.get(
        "/audit/logs", params={"action": "VIEW_PII", "target_id": match.group(1)}
    ).json()
    assert len(views) == 1  # mỗi lượt xem giấy tờ là một lượt VIEW_PII
    assert team.officer.client.get(viewer_path).status_code == 403


# --- ST03: phân tách nhiệm vụ ----------------------------------------------------------------


def test_st03_a_person_who_received_the_file_cannot_appraise_it(
    team: Team, customer: TestClient
) -> None:
    both = team.hire("tindung_thamdinh", "CREDIT_OFFICER", "APPRAISER").client
    app_id = appraising_by(both, customer)

    page = both.get(f"/app/queue/{app_id}")

    assert "Nhận thẩm định" not in page.text  # thao tác bị ẩn
    assert "phân tách nhiệm vụ" in page.text
    forced = submit(both, f"/app/queue/{app_id}/appraisal/open", {})
    assert forced.status_code == 403
    assert "phân tách nhiệm vụ" in forced.text
    violations = team.auditor.client.get("/audit/logs", params={"action": "SOD_VIOLATION"}).json()
    assert len(violations) == 1


def appraising_by(officer: TestClient, customer: TestClient) -> str:
    app_id = submitted_application(customer)
    assert verify_as(officer, app_id).status_code == 200
    return app_id


# --- UC12 1a: nộp hộ tại quầy ----------------------------------------------------------------


def test_officer_files_an_application_for_a_walk_in_customer_on_the_web(
    team: Team, sms: FakeSmsGateway
) -> None:
    officer = team.officer.client
    counter = officer.get("/app/counter")
    assert counter.status_code == 200

    otp_page = submit(officer, "/app/counter/walk-in", {**WALK_IN})
    assert otp_page.status_code == 200
    challenge = re.search(r'name="challenge_id" value="([^"]+)"', otp_page.text)
    assert challenge

    wrong = submit(officer, "/app/counter/walk-in/confirm",
                   {"challenge_id": challenge.group(1), "otp": "000000"})
    assert wrong.status_code == 400

    step1 = submit(officer, "/app/counter/walk-in/confirm",
                   {"challenge_id": challenge.group(1), "otp": sms_code(sms, WALK_IN["phone"])})
    assert step1.status_code == 200
    action = re.search(r'<form method="post" action="(/app/counter/customers/[^"]+)"', step1.text)
    assert action, "Bước 1 phải gửi tới trang lập hồ sơ vay hộ"

    step2 = submit(officer, action.group(1),
                   {"requested_amount": "30000000", "term_months": "12",
                    "purpose": "CONSUMER_GOODS"})
    assert step2.url.path.endswith("/finance")
    app_id = app_id_of(step2)
    finance = {**FINANCE_FORM, "national_id": "001190000123", "receiving_account": "9876543210"}
    submit(officer, f"/app/applications/{app_id}/finance", finance)
    for doc_type in DOCUMENTS:
        assert upload_page(officer, app_id, doc_type).status_code == 200

    confirm = officer.get(f"/app/applications/{app_id}/confirm")
    assert "Gửi mã OTP cho khách hàng" in confirm.text

    consent = submit(officer, f"/app/applications/{app_id}/consent", {})
    assert consent.status_code == 200
    challenge = re.search(r'name="challenge_id" value="([^"]+)"', consent.text)
    assert challenge

    done = submit(officer, f"/app/applications/{app_id}/consent/confirm",
                  {"challenge_id": challenge.group(1), "otp": sms_code(sms, WALK_IN["phone"])})
    assert done.url.path == f"/app/queue/{app_id}"
    assert "Đã nộp" in done.text


def test_customers_cannot_open_staff_pages(customer: TestClient) -> None:
    assert customer.get("/app/queue").status_code == 403
    assert customer.get("/app/counter").status_code == 403

