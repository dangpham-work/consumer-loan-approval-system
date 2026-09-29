"""Seam 1: ticket #15 Kiểm toán — tra cứu, lọc, xuất CSV, kiểm tra toàn vẹn chuỗi; ST08, UT07."""

import csv
import io
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from loan_system.adapters.email import FakeEmailGateway
from loan_system.adapters.sms import FakeSmsGateway
from tests.api.staff import bootstrap_admin, otp
from tests.api.test_login_lockout import WRONG, login
from tests.api.workflow import Team, customer_browser, submitted_application
from tests.conftest import FakeClock


def session_of(client: TestClient) -> dict[str, Any]:
    response = client.get("/auth/session")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def test_only_auditor_can_view_or_verify_logs(
    client: TestClient, clock: FakeClock, email: FakeEmailGateway
) -> None:
    team = Team(client, clock, email)

    assert team.officer.client.get("/audit/logs").status_code == 403
    assert team.officer.client.get("/audit/verify").status_code == 403
    assert team.auditor.client.get("/audit/logs").status_code == 200
    assert team.auditor.client.get("/audit/verify").status_code == 200


def test_auditor_can_filter_logs_by_level_and_actor(
    client: TestClient, clock: FakeClock, email: FakeEmailGateway
) -> None:
    team = Team(client, clock, email)
    admin_id = session_of(team.admin.client)["user_id"]
    officer_id = session_of(team.officer.client)["user_id"]

    # ROLE_ASSIGN (INFO, actor = admin) và một lần đăng nhập sai (WARNING, không actor).
    team.admin.client.put(
        f"/admin/users/{officer_id}/roles",
        json={"roles": ["CREDIT_OFFICER"], "otp": otp(clock, team.admin.totp_secret)},
    ).raise_for_status()
    login(client, WRONG, username=team.officer.username)

    by_level = team.auditor.client.get("/audit/logs", params={"level": "WARNING"})
    assert by_level.status_code == 200
    rows = by_level.json()
    assert any(row["action"] == "LOGIN_FAIL" for row in rows)
    assert all(row["level"] == "WARNING" for row in rows)

    by_actor = team.auditor.client.get("/audit/logs", params={"actor_id": admin_id})
    assert by_actor.status_code == 200
    assert by_actor.json()
    assert all(row["actor_id"] == admin_id for row in by_actor.json())


def test_search_respects_the_limit_parameter(
    client: TestClient, clock: FakeClock, email: FakeEmailGateway
) -> None:
    team = Team(client, clock, email)  # bootstrap_admin đã ghi ít nhất một bản ghi

    limited = team.auditor.client.get("/audit/logs", params={"limit": 1})
    assert limited.status_code == 200
    assert len(limited.json()) == 1


def test_csv_export_contains_the_filtered_rows(
    client: TestClient, clock: FakeClock, email: FakeEmailGateway
) -> None:
    team = Team(client, clock, email)
    login(client, WRONG, username=team.officer.username)

    export = team.auditor.client.get("/audit/logs/export", params={"level": "WARNING"})
    assert export.status_code == 200
    assert export.headers["content-type"].startswith("text/csv")

    rows = list(csv.reader(io.StringIO(export.text)))
    assert rows[0] == [
        "seq", "created_at", "actor_id", "action", "target_type", "target_id", "ip_address",
        "level", "detail",
    ]
    assert any(row[3] == "LOGIN_FAIL" for row in rows[1:])


def test_verify_reports_an_intact_chain_after_real_activity(
    client: TestClient, clock: FakeClock, email: FakeEmailGateway
) -> None:
    team = Team(client, clock, email)
    login(client, WRONG, username=team.officer.username)

    verified = team.auditor.client.get("/audit/verify")
    assert verified.status_code == 200
    assert verified.json() == {"intact": True, "broken_at_seq": None}


def test_revealing_pii_past_the_threshold_raises_a_critical_alert(
    client: TestClient, clock: FakeClock, email: FakeEmailGateway, sms: FakeSmsGateway
) -> None:
    team = Team(client, clock, email)
    browser = customer_browser(client, sms)
    submitted_application(browser)
    customer_id = browser.get("/customers/me").json()["id"]

    for _ in range(21):  # ngưỡng mặc định 20 lượt/giờ (Settings.pii_view_alert_threshold)
        revealed = team.appraiser.client.post(f"/customers/{customer_id}/reveal-pii")
        assert revealed.status_code == 200, revealed.text

    alerts = team.auditor.client.get(
        "/audit/logs", params={"action": "PII_VIEW_THRESHOLD_EXCEEDED", "level": "CRITICAL"}
    ).json()
    assert len(alerts) == 1
    assert alerts[0]["target_type"] == "CUSTOMER"
    assert alerts[0]["target_id"] == customer_id

    # 20 VIEW_PII bình thường + 1 CRITICAL: không ghi trùng VIEW_PII cho lượt vượt ngưỡng.
    views = team.auditor.client.get(
        "/audit/logs", params={"action": "VIEW_PII", "target_id": customer_id}
    ).json()
    assert len(views) == 21


def test_st08_app_rw_is_denied_update_and_delete_on_audit_logs(
    client: TestClient, clock: FakeClock, email: FakeEmailGateway, engine: Engine
) -> None:
    """4.1.2e: DENY UPDATE, DELETE cho app_rw trên audit_logs; kiểm tra bằng SQL Server thật."""
    bootstrap_admin(client, clock)  # ghi ít nhất một bản ghi nhật ký (USER_CREATE)

    probe = f"probe_{uuid.uuid4().hex[:8]}"
    with engine.connect() as setup:
        setup = setup.execution_options(isolation_level="AUTOCOMMIT")
        setup.execute(text(f"CREATE USER [{probe}] WITHOUT LOGIN"))
        setup.execute(text(f"ALTER ROLE app_rw ADD MEMBER [{probe}]"))
        setup.execute(text(f"GRANT SELECT, INSERT ON dbo.audit_logs TO [{probe}]"))

    with engine.connect() as check:
        before = check.execute(
            text("SELECT TOP 1 seq, action FROM audit_logs ORDER BY seq")
        ).one()

    try:
        conn = engine.connect().execution_options(isolation_level="AUTOCOMMIT")
        try:
            conn.execute(text(f"EXECUTE AS USER = '{probe}'"))
            with pytest.raises(DBAPIError):
                conn.execute(
                    text("UPDATE audit_logs SET action = 'TAMPERED' WHERE seq = :seq"),
                    {"seq": before.seq},
                )
            with pytest.raises(DBAPIError):
                conn.execute(text("DELETE FROM audit_logs WHERE seq = :seq"), {"seq": before.seq})
            # Chỉ ghi thêm bị từ chối; ghi mới (INSERT) vẫn được phép cho vai trò app_rw.
            conn.execute(
                text(
                    "INSERT INTO audit_logs (seq, action, level, created_at, prev_hash, hash) "
                    "VALUES (999999, 'PROBE_INSERT', 'INFO', SYSDATETIMEOFFSET(), "
                    "REPLICATE('0', 64), REPLICATE('1', 64))"
                )
            )
        finally:
            try:
                conn.execute(text("REVERT"))
            except DBAPIError:
                pass
            conn.close()
    finally:
        # Dọn dẹp cả khi assertion ở trên thất bại, để không để lại principal thừa trong DB test.
        with engine.connect() as cleanup:
            cleanup = cleanup.execution_options(isolation_level="AUTOCOMMIT")
            cleanup.execute(text(f"DROP USER [{probe}]"))

    with engine.connect() as check:
        unchanged: str = check.execute(
            text("SELECT action FROM audit_logs WHERE seq = :seq"), {"seq": before.seq}
        ).scalar_one()
        inserted: str = check.execute(
            text("SELECT action FROM audit_logs WHERE seq = 999999")
        ).scalar_one()
    assert unchanged == before.action
    assert inserted == "PROBE_INSERT"
