"""Seam 1: UC14 Kiểm tra hồ sơ vay, UC15 Yêu cầu bổ sung, UC17 Hủy, UC12 1a NV nộp hộ (ticket #5)."""

import re
from typing import Any

import pytest
from fastapi.testclient import TestClient

from loan_system.adapters.email import FakeEmailGateway
from loan_system.adapters.sms import FakeSmsGateway
from tests.api.staff import new_client
from tests.api.test_customer_registration import PASSWORD
from tests.api.workflow import (
    DOCUMENTS,
    FINANCES,
    JPEG,
    LOAN,
    Team,
    customer_browser,
    fill_draft,
    notifications_of,
    submitted_application,
    upload,
    verify_as,
)
from tests.conftest import FakeClock


@pytest.fixture
def team(client: TestClient, clock: FakeClock, email: FakeEmailGateway) -> Team:
    return Team(client, clock, email)


@pytest.fixture
def customer(client: TestClient, sms: FakeSmsGateway) -> TestClient:
    return customer_browser(client, sms)


def sms_code(sms: FakeSmsGateway, phone: str) -> str:
    match = re.search(r"\b(\d{6})\b", sms.last_to(phone).message)
    assert match
    return match.group(1)


def test_credit_officer_receives_checks_and_verifies_a_submitted_application(
    team: Team, customer: TestClient
) -> None:
    officer = team.officer.client
    app_id = submitted_application(customer)

    assert any(n["type"] == "APPLICATION_SUBMITTED" for n in notifications_of(officer))
    queue = officer.get("/applications", params={"status": "SUBMITTED"}).json()
    assert [a["id"] for a in queue] == [app_id]

    assert verify_as(officer, app_id).status_code == 200

    detail = customer.get(f"/applications/{app_id}").json()
    assert detail["status"] == "VERIFIED"
    assert [h["status"] for h in detail["history"]] == ["DRAFT", "SUBMITTED", "VERIFIED"]


def test_staff_see_masked_data_and_never_see_customer_drafts(
    team: Team, customer: TestClient
) -> None:
    officer = team.officer.client
    draft = customer.post("/applications", json=LOAN).json()["id"]
    customer.patch(f"/applications/{draft}", json=FINANCES).raise_for_status()

    assert officer.get(f"/applications/{draft}").status_code == 404
    assert officer.get("/applications").json() == []

    for doc_type, (filename, content) in DOCUMENTS.items():
        upload(customer, draft, doc_type, filename, content).raise_for_status()
    customer.post(f"/applications/{draft}/submit", json={"accept_data_processing": True})
    detail = officer.get(f"/applications/{draft}").json()
    assert detail["applicant"]["national_id"] == "079******234"
    assert detail["receiving_account"] == "012****789"


def test_an_application_is_received_by_only_one_officer(team: Team, customer: TestClient) -> None:
    app_id = submitted_application(customer)
    assert team.officer.client.post(f"/applications/{app_id}/claim").status_code == 200

    # UC14 2a: đã có NV khác nhận thì không nhận trùng
    assert team.officer2.client.post(f"/applications/{app_id}/claim").status_code == 409
    # và NV khác không được đánh giá giấy tờ hay xác nhận thay
    doc_id = team.officer.client.get(f"/applications/{app_id}").json()["documents"][0]["id"]
    review = team.officer2.client.put(
        f"/applications/{app_id}/documents/{doc_id}/review", json={"verdict": "PASS"}
    )
    assert review.status_code == 403
    assert team.officer2.client.post(f"/applications/{app_id}/verify").status_code == 403


def test_only_credit_officers_may_receive_applications(team: Team, customer: TestClient) -> None:
    app_id = submitted_application(customer)
    assert team.appraiser.client.post(f"/applications/{app_id}/claim").status_code == 403
    assert customer.post(f"/applications/{app_id}/claim").status_code == 403


def test_verify_needs_every_document_marked_as_passed(team: Team, customer: TestClient) -> None:
    officer = team.officer.client
    app_id = submitted_application(customer)
    officer.post(f"/applications/{app_id}/claim").raise_for_status()
    documents = officer.get(f"/applications/{app_id}").json()["documents"]
    for document in documents[:-1]:
        officer.put(
            f"/applications/{app_id}/documents/{document['id']}/review", json={"verdict": "PASS"}
        ).raise_for_status()

    assert officer.post(f"/applications/{app_id}/verify").status_code == 409  # còn giấy tờ chưa xem
    officer.put(
        f"/applications/{app_id}/documents/{documents[-1]['id']}/review",
        json={"verdict": "FAIL", "note": "Ảnh mờ"},
    ).raise_for_status()
    assert officer.post(f"/applications/{app_id}/verify").status_code == 409  # có giấy tờ không đạt


def test_request_info_then_customer_supplements_and_resubmits(
    team: Team, customer: TestClient, clock: FakeClock, sms: FakeSmsGateway
) -> None:
    officer = team.officer.client
    app_id = submitted_application(customer)
    officer.post(f"/applications/{app_id}/claim").raise_for_status()
    front = next(
        d for d in officer.get(f"/applications/{app_id}").json()["documents"]
        if d["doc_type"] == "ID_FRONT"
    )
    officer.put(
        f"/applications/{app_id}/documents/{front['id']}/review",
        json={"verdict": "FAIL", "note": "Ảnh mờ"},
    ).raise_for_status()

    requested = officer.post(
        f"/applications/{app_id}/request-info",
        json={"message": "Vui lòng chụp lại CCCD mặt trước rõ nét.", "items": ["ID_FRONT"]},
    )
    assert requested.status_code == 200

    detail = customer.get(f"/applications/{app_id}").json()
    assert detail["status"] == "NEED_INFO"
    assert detail["need_info"]["message"] == "Vui lòng chụp lại CCCD mặt trước rõ nét."
    assert detail["need_info"]["deadline"].startswith("2026-10-")  # hôm nay + 15 ngày (BR11)
    assert any(n["type"] == "NEED_INFO" for n in notifications_of(customer))
    assert "0901234567" in [m.phone for m in sms.outbox]

    upload(customer, app_id, "ID_FRONT", "cccd-moi.jpg", JPEG + b"\x09").raise_for_status()
    resubmitted = customer.post(f"/applications/{app_id}/submit", json={"accept_data_processing": True})
    assert resubmitted.status_code == 200
    assert resubmitted.json()["status"] == "SUBMITTED"

    # Hồ sơ vay trở lại hàng đợi của chính NV đã nhận; giấy tờ mới phải được xem lại.
    assert verify_as_receiver(officer, app_id).status_code == 200


def verify_as_receiver(officer: TestClient, app_id: str) -> Any:
    for document in officer.get(f"/applications/{app_id}").json()["documents"]:
        if document["review"] is None:
            officer.put(
                f"/applications/{app_id}/documents/{document['id']}/review",
                json={"verdict": "PASS"},
            ).raise_for_status()
    return officer.post(f"/applications/{app_id}/verify")


def test_customer_cancels_before_appraisal_and_may_apply_again(
    team: Team, customer: TestClient
) -> None:
    app_id = submitted_application(customer)

    cancelled = customer.post(f"/applications/{app_id}/cancel", json={"reason": "Không cần vay nữa"})
    assert cancelled.status_code == 200
    assert customer.get(f"/applications/{app_id}").json()["status"] == "CANCELLED"
    assert customer.post("/applications", json=LOAN).status_code == 201


def test_customer_cannot_cancel_after_verification(team: Team, customer: TestClient) -> None:
    app_id = submitted_application(customer)
    verify_as(team.officer.client, app_id).raise_for_status()

    assert customer.post(f"/applications/{app_id}/cancel", json={}).status_code == 409


def test_another_customer_cannot_cancel_my_application(
    client: TestClient, sms: FakeSmsGateway, customer: TestClient
) -> None:
    app_id = submitted_application(customer)
    stranger = customer_browser(client, sms, phone="0987654321", email="binh@example.com")

    assert stranger.post(f"/applications/{app_id}/cancel", json={}).status_code == 404
    assert customer.get(f"/applications/{app_id}").json()["status"] == "SUBMITTED"


# --- UC12 1a: NV tín dụng nộp hộ tại quầy -------------------------------------------------------

WALK_IN = {
    "full_name": "Lê Thị Cúc",
    "date_of_birth": "1990-02-03",
    "phone": "0912345678",
    "email": "cuc@example.com",
}


def walk_in_customer(officer: TestClient, sms: FakeSmsGateway) -> str:
    started = officer.post("/counter/customers", json=WALK_IN)
    assert started.status_code == 202, started.text
    confirmed = officer.post(
        "/counter/customers/confirm",
        json={"challenge_id": started.json()["challenge_id"], "otp": sms_code(sms, WALK_IN["phone"])},
    )
    assert confirmed.status_code == 201, confirmed.text
    customer_id: str = confirmed.json()["customer_id"]
    return customer_id


def filed_at_counter(officer: TestClient, sms: FakeSmsGateway) -> str:
    customer_id = walk_in_customer(officer, sms)
    created = officer.post("/counter/applications", json={"customer_id": customer_id, **LOAN})
    assert created.status_code == 201, created.text
    app_id: str = created.json()["id"]
    fill_draft(officer, app_id, national_id="001190000123", receiving_account="9876543210")
    challenge = officer.post(f"/applications/{app_id}/submit-on-behalf")
    assert challenge.status_code == 202, challenge.text
    confirmed = officer.post(
        f"/applications/{app_id}/submit-on-behalf/confirm",
        json={"challenge_id": challenge.json()["challenge_id"], "otp": sms_code(sms, WALK_IN["phone"])},
    )
    assert confirmed.status_code == 200, confirmed.text
    return app_id


def test_officer_files_an_application_for_a_walk_in_customer_who_confirms_by_otp(
    team: Team, sms: FakeSmsGateway
) -> None:
    officer = team.officer.client
    app_id = filed_at_counter(officer, sms)

    detail = officer.get(f"/applications/{app_id}").json()
    assert detail["status"] == "SUBMITTED"
    assert detail["created_by"] is not None


def test_creator_of_an_application_cannot_also_receive_it(team: Team, sms: FakeSmsGateway) -> None:
    app_id = filed_at_counter(team.officer.client, sms)

    # SoD (BR06): người tạo không được tự xác nhận hồ sơ vay mình nộp hộ.
    assert team.officer.client.post(f"/applications/{app_id}/claim").status_code == 403
    assert verify_as(team.officer2.client, app_id).status_code == 200


def test_wrong_consent_otp_does_not_submit(team: Team, sms: FakeSmsGateway) -> None:
    officer = team.officer.client
    customer_id = walk_in_customer(officer, sms)
    app_id = officer.post("/counter/applications", json={"customer_id": customer_id, **LOAN}).json()["id"]
    fill_draft(officer, app_id, national_id="001190000123")
    challenge = officer.post(f"/applications/{app_id}/submit-on-behalf").json()["challenge_id"]
    right = sms_code(sms, WALK_IN["phone"])

    wrong = officer.post(
        f"/applications/{app_id}/submit-on-behalf/confirm",
        json={"challenge_id": challenge, "otp": "000000" if right != "000000" else "111111"},
    )
    assert wrong.status_code == 400
    assert officer.get(f"/applications/{app_id}").json()["status"] == "DRAFT"


def test_walk_in_customer_with_a_registered_phone_is_rejected(
    team: Team, customer: TestClient
) -> None:
    response = team.officer.client.post(
        "/counter/customers", json={**WALK_IN, "phone": "0901234567"}
    )
    assert response.status_code == 409


def test_officer_cannot_touch_drafts_filed_by_another_officer(
    team: Team, sms: FakeSmsGateway
) -> None:
    officer = team.officer.client
    customer_id = walk_in_customer(officer, sms)
    app_id = officer.post("/counter/applications", json={"customer_id": customer_id, **LOAN}).json()["id"]

    other = team.officer2.client
    assert other.patch(f"/applications/{app_id}", json={"term_months": 24}).status_code == 404
    assert other.get(f"/applications/{app_id}").status_code == 404


def test_counter_application_still_follows_br02(team: Team, customer: TestClient) -> None:
    submitted_application(customer)
    customer_id = customer.get("/applications").json()[0]["customer_id"]

    response = team.officer.client.post(
        "/counter/applications", json={"customer_id": customer_id, **LOAN}
    )
    assert response.status_code == 409


def test_customers_cannot_use_counter_endpoints(customer: TestClient, client: TestClient) -> None:
    assert customer.post("/counter/customers", json=WALK_IN).status_code == 403
    assert new_client(client).post("/counter/customers", json=WALK_IN).status_code == 401


def request_front_id(team: Team, customer: TestClient, message: str = "Chụp lại CCCD mặt trước.") -> str:
    officer = team.officer.client
    app_id = submitted_application(customer)
    officer.post(f"/applications/{app_id}/claim").raise_for_status()
    officer.post(
        f"/applications/{app_id}/request-info", json={"message": message, "items": ["ID_FRONT"]}
    ).raise_for_status()
    return app_id


def test_a_supplement_may_only_change_what_was_requested(team: Team, customer: TestClient) -> None:
    app_id = request_front_id(team, customer)

    # Không đổi được khoản vay hay tài khoản nhận khi chỉ được yêu cầu chụp lại CCCD.
    assert customer.patch(f"/applications/{app_id}", json={"term_months": 24}).status_code == 409
    assert customer.patch(
        f"/applications/{app_id}", json={"receiving_account": "1111111111"}
    ).status_code == 409
    assert upload(customer, app_id, "INCOME_PROOF", "a.pdf", DOCUMENTS["INCOME_PROOF"][1]).status_code == 409
    assert upload(customer, app_id, "ID_FRONT", "moi.jpg", JPEG + b"\x07").status_code == 201


def test_supplement_after_the_15_day_deadline_is_refused(
    team: Team, customer: TestClient, clock: FakeClock
) -> None:
    app_id = request_front_id(team, customer)
    clock.advance(days=15, seconds=1)
    # Phiên cũ đã hết hạn sau 15 ngày; khách hàng đăng nhập lại.
    customer.post("/auth/login", json={"username": "0901234567", "password": PASSWORD})

    assert upload(customer, app_id, "ID_FRONT", "a.jpg", JPEG).status_code == 409
    assert customer.post(
        f"/applications/{app_id}/submit", json={"accept_data_processing": True}
    ).status_code == 409


def test_request_info_accepts_a_long_message_but_only_known_items(
    team: Team, customer: TestClient, client: TestClient, sms: FakeSmsGateway
) -> None:
    app_id = request_front_id(team, customer, message="Vui lòng bổ sung. " * 25)
    assert customer.get(f"/applications/{app_id}").json()["status"] == "NEED_INFO"

    other = submitted_application(
        customer_browser(client, sms, phone="0987654321", email="b@example.com"),
        national_id="079095009999",
    )
    team.officer.client.post(f"/applications/{other}/claim").raise_for_status()
    bad = team.officer.client.post(
        f"/applications/{other}/request-info",
        json={"message": "Bổ sung số tiền vay.", "items": ["requested_amount"]},
    )
    assert bad.status_code == 400


def test_staff_do_not_see_income_and_customers_do_not_see_staff_ids(
    team: Team, customer: TestClient
) -> None:
    app_id = submitted_application(customer)
    team.officer.client.post(f"/applications/{app_id}/claim").raise_for_status()

    staff_view = team.officer.client.get(f"/applications/{app_id}").json()
    own_view = customer.get(f"/applications/{app_id}").json()

    assert staff_view["applicant"]["monthly_income"] is None
    assert staff_view["received_by"] is not None
    assert own_view["applicant"]["monthly_income"] == "25000000"
    assert own_view["received_by"] is None


def test_consent_is_void_if_the_loan_changes_after_the_code_was_sent(
    team: Team, sms: FakeSmsGateway
) -> None:
    officer = team.officer.client
    customer_id = walk_in_customer(officer, sms)
    app_id = officer.post("/counter/applications", json={"customer_id": customer_id, **LOAN}).json()["id"]
    fill_draft(officer, app_id, national_id="001190000123")
    challenge = officer.post(f"/applications/{app_id}/submit-on-behalf").json()["challenge_id"]
    code = sms_code(sms, WALK_IN["phone"])
    assert "30,000,000" in sms.last_to(WALK_IN["phone"]).message  # khách biết mình đồng ý gì

    officer.patch(f"/applications/{app_id}", json={"requested_amount": 90_000_000}).raise_for_status()
    confirmed = officer.post(
        f"/applications/{app_id}/submit-on-behalf/confirm",
        json={"challenge_id": challenge, "otp": code},
    )

    assert confirmed.status_code == 400
    assert officer.get(f"/applications/{app_id}").json()["status"] == "DRAFT"
