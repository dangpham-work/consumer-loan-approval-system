"""Seam 1 (trang HTML qua TestClient): M10 Nhật ký kiểm toán.

UC07 Tra cứu nhật ký (lọc theo thời gian, người, hành động; xuất CSV), UC08 Kiểm tra toàn vẹn chuỗi
băm; dùng lại tầng nghiệp vụ của ticket #15. ST08 qua giao diện: sửa thẳng một bản ghi trong CSDL
thì nút "Kiểm tra toàn vẹn chuỗi" chỉ ra bản ghi bị phá vỡ.
"""

import csv
import io

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from loan_system.adapters.email import FakeEmailGateway
from tests.api.test_login_lockout import WRONG, login
from tests.api.test_web_login import assert_forms_carry_csrf, submit
from tests.api.workflow import Team
from tests.conftest import FakeClock


@pytest.fixture
def team(client: TestClient, clock: FakeClock, email: FakeEmailGateway) -> Team:
    return Team(client, clock, email)


def rows_of(page_text: str) -> list[str]:
    body = page_text.split("<tbody>", 1)[1].split("</tbody>", 1)[0]
    return body.split("<tr>")[1:]


def test_auditor_sees_the_log_with_actor_names_and_filters_it(
    team: Team, client: TestClient,
) -> None:
    auditor = team.auditor.client  # Quản trị viên tạo nhân viên: USER_CREATE
    login(client, WRONG, username=team.officer.username)  # LOGIN_FAIL, WARNING

    page = auditor.get("/app/audit")
    assert page.status_code == 200
    assert "USER_CREATE" in page.text and "LOGIN_FAIL" in page.text
    assert "quantri" in page.text  # tên đăng nhập người thực hiện thay cho mã định danh

    by_action = auditor.get("/app/audit", params={"action": "LOGIN_FAIL"})
    assert rows_of(by_action.text)
    assert all("LOGIN_FAIL" in row for row in rows_of(by_action.text))
    assert 'value="LOGIN_FAIL"' in by_action.text  # bộ lọc giữ giá trị đã chọn

    by_actor = auditor.get("/app/audit", params={"actor": "quantri"})
    assert rows_of(by_actor.text)
    assert all("quantri" in row for row in rows_of(by_actor.text))
    assert "Không có bản ghi" in auditor.get("/app/audit", params={"actor": "khongco"}).text

    # Ngày theo giờ Việt Nam, tính trọn ngày ở cả hai đầu khoảng lọc (đồng hồ test: 28/09/2026).
    today = auditor.get("/app/audit", params={"from": "2026-09-28", "to": "2026-09-28"})
    assert any("LOGIN_FAIL" in row for row in rows_of(today.text))
    for other_day in ({"to": "2026-09-27"}, {"from": "2026-09-29"}):
        assert "Không có bản ghi" in auditor.get("/app/audit", params=other_day).text


def test_invalid_filters_show_a_message_instead_of_an_error(team: Team) -> None:
    page = team.auditor.client.get("/app/audit", params={"from": "30/09/2026", "level": "X"})

    assert page.status_code == 400
    assert "Bộ lọc không hợp lệ" in page.text


def test_auditor_exports_the_filtered_log_as_csv(
    team: Team, client: TestClient,
) -> None:
    login(client, WRONG, username=team.officer.username)

    page = team.auditor.client.get("/app/audit", params={"level": "WARNING"})
    assert 'href="/app/audit/export?level=WARNING' in page.text

    export = team.auditor.client.get("/app/audit/export", params={"level": "WARNING"})
    assert export.status_code == 200
    assert export.headers["content-type"].startswith("text/csv")
    assert "attachment" in export.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(export.text)))
    assert rows[0][0] == "seq"
    assert rows[1:] and all(row[7] == "WARNING" for row in rows[1:])
    assert any(row[3] == "LOGIN_FAIL" for row in rows[1:])


def test_st08_integrity_check_points_at_the_tampered_record(
    team: Team, engine: Engine,
) -> None:
    auditor = team.auditor.client
    page = auditor.get("/app/audit")
    assert 'action="/app/audit/verify"' in page.text
    assert_forms_carry_csrf(auditor, page.text)

    intact = submit(auditor, "/app/audit/verify", {})
    assert intact.status_code == 200
    assert "Chuỗi nhật ký toàn vẹn" in intact.text

    # Kẻ có quyền quản trị CSDL (không phải tài khoản ứng dụng, vốn không có quyền UPDATE) sửa
    # một bản ghi cũ.
    with engine.connect() as conn:
        seq: int = conn.execute(text("SELECT MIN(seq) FROM audit_logs")).scalar_one()
        conn.execute(text("UPDATE audit_logs SET detail = 'đã sửa' WHERE seq = :seq"),
                     {"seq": seq})
        conn.commit()

    broken = submit(auditor, "/app/audit/verify", {})
    assert broken.status_code == 200
    assert "Chuỗi nhật ký bị phá vỡ" in broken.text
    assert f"bản ghi số {seq}" in broken.text


def test_only_the_auditor_opens_m10(team: Team) -> None:
    for staff in (team.officer, team.admin):
        assert staff.client.get("/app/audit").status_code == 403
        assert staff.client.get("/app/audit/export").status_code == 403
        assert submit(staff.client, "/app/audit/verify", {}).status_code == 403
    assert 'href="/app/audit"' in team.auditor.client.get("/app").text
