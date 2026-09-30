"""Seam 1: UC32 Xem báo cáo thống kê, xuất Excel/PDF, màn hình M11 (FR08.1, ticket #18)."""

import csv
import io
from typing import Any

import pytest
from fastapi.testclient import TestClient

from loan_system.adapters.email import FakeEmailGateway
from loan_system.adapters.sms import FakeSmsGateway
from tests.api.test_disbursement import approved, disburse
from tests.api.workflow import Team, customer_browser, submitted_application, verify_as
from tests.conftest import FakeClock

TODAY = {"from": "2026-09-28", "to": "2026-09-28"}
# Chữ số cuối "8": kịch bản CIC giả lập mặc định trả về nợ nhóm 3, tự động từ chối
# (adapters/cic.py) mà không cần cấu hình `cic.respond`.
REJECTED_NATIONAL_ID = "079095009998"


@pytest.fixture
def team(client: TestClient, clock: FakeClock, email: FakeEmailGateway) -> Team:
    return Team(client, clock, email)


def statistics(caller: TestClient, **params: str) -> dict[str, Any]:
    response = caller.get("/reports/statistics", params={**TODAY, **params})
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def test_only_approver_can_view_or_export_statistics(team: Team) -> None:
    assert team.officer.client.get("/reports/statistics", params=TODAY).status_code == 403
    assert team.officer.client.get("/reports/statistics/export", params=TODAY).status_code == 403
    assert team.approver.client.get("/reports/statistics", params=TODAY).status_code == 200
    assert team.approver.client.get("/reports/statistics/export", params=TODAY).status_code == 200


def test_statistics_aggregate_applications_and_loans_of_the_day(
    team: Team, client: TestClient, clock: FakeClock, sms: FakeSmsGateway,
) -> None:
    approved_customer = customer_browser(client, sms, phone="0901111111", email="a1@example.com")
    app_id = approved(team, approved_customer)
    disburse(team, clock, app_id)

    rejected_customer = customer_browser(client, sms, phone="0902222222", email="a2@example.com")
    rejected_id = submitted_application(rejected_customer, national_id=REJECTED_NATIONAL_ID)
    assert verify_as(team.officer.client, rejected_id).status_code == 200

    report = statistics(team.approver.client)

    assert report["total_applications"] == 2
    assert report["applications_by_status"]["DISBURSED"] == 1
    assert report["applications_by_status"]["REJECTED"] == 1
    assert (report["approved_count"], report["rejected_count"]) == (1, 1)
    assert report["approval_rate"] == "0.5000"
    assert report["avg_processing_days"] is not None
    assert report["total_disbursed"] == "30000000"
    assert report["total_loans"] == 1
    assert report["outstanding_principal"] == "30000000"
    assert report["loans_by_debt_group"] == {"1": 1, "2": 0, "3": 0, "4": 0, "5": 0}
    assert (report["overdue_loan_count"], report["overdue_loan_rate"]) == (0, "0.0000")
    # Hồ sơ vay bị loại trừ (REJECTED) cũng có bản ghi chấm điểm nhưng grade rỗng, không tính vào.
    assert sum(report["credit_grade_distribution"].values()) == 1


def test_applications_outside_the_range_are_excluded(
    team: Team, client: TestClient, clock: FakeClock, sms: FakeSmsGateway,
) -> None:
    early = customer_browser(client, sms, phone="0903333333", email="b1@example.com")
    submitted_application(early)

    clock.advance(days=40)
    late = customer_browser(client, sms, phone="0904444444", email="b2@example.com")
    submitted_application(late, national_id="079095004444")

    only_early = statistics(team.approver.client, **{"from": "2026-09-28", "to": "2026-09-28"})
    only_late = statistics(team.approver.client, **{"from": "2026-11-07", "to": "2026-11-07"})

    assert only_early["total_applications"] == 1
    assert only_late["total_applications"] == 1


def test_date_range_over_12_months_is_rejected(team: Team) -> None:
    response = team.approver.client.get(
        "/reports/statistics", params={"from": "2020-01-01", "to": "2021-03-01"}
    )
    assert response.status_code == 400, response.text


def test_export_returns_csv_and_pdf_and_logs_report_export(team: Team) -> None:
    csv_response = team.approver.client.get(
        "/reports/statistics/export", params={**TODAY, "format": "CSV"}
    )
    assert csv_response.status_code == 200, csv_response.text
    assert csv_response.headers["content-type"].startswith("text/csv")
    assert csv_response.text.startswith("﻿")  # BOM UTF-8 để Excel đọc đúng tiếng Việt
    rows = list(csv.reader(io.StringIO(csv_response.text.lstrip("﻿"))))
    assert rows[0][0] == "Báo cáo thống kê"

    pdf_response = team.approver.client.get(
        "/reports/statistics/export", params={**TODAY, "format": "PDF"}
    )
    assert pdf_response.status_code == 200, pdf_response.text
    assert pdf_response.headers["content-type"].startswith("application/pdf")
    assert pdf_response.content.startswith(b"%PDF")

    logs = team.auditor.client.get("/audit/logs", params={"action": "REPORT_EXPORT"}).json()
    assert len(logs) == 2  # một CSV, một PDF
