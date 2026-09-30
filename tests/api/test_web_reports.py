"""Seam 1 (trang HTML qua TestClient): M11 Báo cáo thống kê (UC32).

Chọn khoảng ngày (tối đa 12 tháng), biểu đồ hồ sơ vay theo trạng thái, tỷ lệ duyệt/từ chối, thời gian
xử lý trung bình, dư nợ theo nhóm nợ, tỷ lệ quá hạn; xuất CSV và PDF. Dùng lại tầng nghiệp vụ của
ticket #18.
"""

import pytest
from fastapi.testclient import TestClient

from loan_system.adapters.email import FakeEmailGateway
from loan_system.adapters.sms import FakeSmsGateway
from tests.api.test_disbursement import approved, disburse
from tests.api.test_reports import REJECTED_NATIONAL_ID, TODAY
from tests.api.workflow import Team, customer_browser, submitted_application, verify_as
from tests.conftest import FakeClock


@pytest.fixture
def team(client: TestClient, clock: FakeClock, email: FakeEmailGateway) -> Team:
    return Team(client, clock, email)


def bar_of(page_text: str, label: str) -> str:
    """Hàng biểu đồ mang nhãn `label` (từ nhãn đến hết hàng)."""
    row = page_text.split(f'<span class="bar-label">{label}</span>', 1)[1]
    return row.split("</div>\n", 1)[0]


def test_approver_sees_the_statistics_of_the_chosen_range(
    team: Team, client: TestClient, clock: FakeClock, sms: FakeSmsGateway,
) -> None:
    approved_customer = customer_browser(client, sms, phone="0901111111", email="a1@example.com")
    disburse(team, clock, approved(team, approved_customer))
    rejected_customer = customer_browser(client, sms, phone="0902222222", email="a2@example.com")
    rejected_id = submitted_application(rejected_customer, national_id=REJECTED_NATIONAL_ID)
    assert verify_as(team.officer.client, rejected_id).status_code == 200

    page = team.approver.client.get("/app/reports", params=TODAY)

    assert page.status_code == 200
    assert 'value="2026-09-28"' in page.text  # khoảng ngày đã chọn hiện lại trên biểu mẫu
    assert "Tổng số hồ sơ vay" in page.text
    assert '<strong class="figure">2</strong>' in page.text
    assert "50,00%" in page.text  # tỷ lệ duyệt: 1 duyệt, 1 từ chối
    assert "ngày" in page.text  # thời gian xử lý trung bình
    assert "30.000.000 đ" in page.text  # dư nợ gốc của khoản vay giải ngân trong kỳ
    assert "0,00%" in page.text  # tỷ lệ quá hạn
    # Biểu đồ hồ sơ vay theo trạng thái và khoản vay theo nhóm nợ.
    assert ">1<" in bar_of(page.text, "Đã giải ngân")
    assert ">1<" in bar_of(page.text, "Bị từ chối")
    assert ">0<" in bar_of(page.text, "Nháp")
    assert ">1<" in bar_of(page.text, "Nhóm 1")
    assert ">0<" in bar_of(page.text, "Nhóm 3")
    # Liên kết xuất theo đúng khoảng ngày đang xem.
    assert 'href="/app/reports/export?from=2026-09-28&amp;to=2026-09-28&amp;format=CSV"' in page.text
    assert 'href="/app/reports/export?from=2026-09-28&amp;to=2026-09-28&amp;format=PDF"' in page.text


def test_the_page_opens_on_the_current_month_by_default(team: Team, client: TestClient,
                                                         sms: FakeSmsGateway) -> None:
    submitted_application(customer_browser(client, sms))

    page = team.approver.client.get("/app/reports")

    assert page.status_code == 200
    assert 'value="2026-09-01"' in page.text and 'value="2026-09-28"' in page.text
    assert '<strong class="figure">1</strong>' in page.text


def test_an_empty_range_shows_no_rate_instead_of_zero(team: Team) -> None:
    page = team.approver.client.get("/app/reports", params={"from": "2025-01-01", "to": "2025-01-31"})

    assert page.status_code == 200
    assert "Chưa có dữ liệu" in page.text


@pytest.mark.parametrize(
    ("params", "message"),
    [
        ({"from": "2025-01-01", "to": "2026-03-01"}, "tối đa 12 tháng"),
        ({"from": "2026-09-28", "to": "2026-09-01"}, "ngày kết thúc phải sau ngày bắt đầu"),
        ({"from": "28/09/2026", "to": "2026-09-28"}, "Ngày không hợp lệ"),
        ({"from": "2026-09-28x", "to": "2026-09-28"}, "Ngày không hợp lệ"),
    ],
)
def test_an_invalid_range_is_explained_on_the_form(
    team: Team, params: dict[str, str], message: str,
) -> None:
    page = team.approver.client.get("/app/reports", params=params)

    assert page.status_code == 400
    assert message in page.text
    assert f'value="{params["from"]}"' in page.text  # giữ giá trị đã nhập để sửa


def test_approver_exports_csv_and_pdf_and_each_export_is_logged(team: Team) -> None:
    csv_export = team.approver.client.get("/app/reports/export", params={**TODAY, "format": "CSV"})
    assert csv_export.status_code == 200
    assert csv_export.headers["content-type"].startswith("text/csv")
    assert "attachment" in csv_export.headers["content-disposition"]
    assert csv_export.text.lstrip("﻿").startswith("Báo cáo thống kê")

    pdf_export = team.approver.client.get("/app/reports/export", params={**TODAY, "format": "PDF"})
    assert pdf_export.status_code == 200
    assert pdf_export.headers["content-type"].startswith("application/pdf")
    assert pdf_export.content.startswith(b"%PDF")

    logs = team.auditor.client.get("/audit/logs", params={"action": "REPORT_EXPORT"}).json()
    assert len(logs) == 2


def test_an_invalid_export_range_shows_the_page_with_the_message(team: Team) -> None:
    response = team.approver.client.get(
        "/app/reports/export", params={"from": "2025-01-01", "to": "2026-03-01", "format": "CSV"}
    )

    assert response.status_code == 400
    assert "tối đa 12 tháng" in response.text
    logs = team.auditor.client.get("/audit/logs", params={"action": "REPORT_EXPORT"}).json()
    assert logs == []


def test_only_holders_of_report_view_open_m11(team: Team) -> None:
    assert team.officer.client.get("/app/reports").status_code == 403
    assert team.officer.client.get("/app/reports/export", params=TODAY).status_code == 403
    assert 'href="/app/reports"' in team.approver.client.get("/app/reports").text  # mục menu
