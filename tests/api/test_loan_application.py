"""Seam 1: UC12 Tạo và nộp hồ sơ vay, UC13 Tải lên giấy tờ, UC16 Theo dõi trạng thái; ST01, ST05."""

import hashlib
import re
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from loan_system.adapters.sms import FakeSmsGateway
from loan_system.domain.applications import CEILING_RATE
from loan_system.domain.calculations import annuity_payment
from tests.api.staff import new_client
from tests.api.test_customer_registration import PASSWORD, PHONE, register_and_verify

JPEG = b"\xff\xd8\xff\xe0" + b"\x01" * 2048
PNG = b"\x89PNG\r\n\x1a\n" + b"\x02" * 2048
PDF = b"%PDF-1.7\n" + b"\x03" * 2048

LOAN = {"requested_amount": 30_000_000, "term_months": 12, "purpose": "CONSUMER_GOODS"}
FINANCES = {
    "national_id": "079095001234",
    "occupation": "Kỹ sư phần mềm",
    "employer": "Công ty ABC",
    "employment_years": 4,
    "monthly_income": 25_000_000,
    "existing_monthly_debt": 2_000_000,
    "housing_type": "RENT",
    "address": "12 Lê Lợi, Quận 1, TP.HCM",
    "receiving_account": "0123456789",
}
DOCUMENTS = {
    "ID_FRONT": ("cccd-truoc.jpg", JPEG),
    "ID_BACK": ("cccd-sau.png", PNG),
    "INCOME_PROOF": ("sao-ke-luong.pdf", PDF),
    "UTILITY_BILL": ("hoa-don-dien.pdf", PDF + b"\x04"),
}


def logged_in_customer(
    client: TestClient, sms: FakeSmsGateway, phone: str = PHONE, email: str = "an@example.com"
) -> TestClient:
    register_and_verify(client, sms, phone=phone, email=email)
    browser = new_client(client)
    browser.post("/auth/login", json={"username": phone, "password": PASSWORD}).raise_for_status()
    return browser


@pytest.fixture
def customer(client: TestClient, sms: FakeSmsGateway) -> TestClient:
    return logged_in_customer(client, sms)


@pytest.fixture
def other_customer(client: TestClient, sms: FakeSmsGateway) -> TestClient:
    return logged_in_customer(client, sms, phone="0987654321", email="binh@example.com")


def create_draft(browser: TestClient, **overrides: Any) -> dict[str, Any]:
    response = browser.post("/applications", json={**LOAN, **overrides})
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def upload(browser: TestClient, app_id: str, doc_type: str, filename: str, content: bytes) -> Any:
    return browser.post(
        f"/applications/{app_id}/documents",
        data={"doc_type": doc_type},
        files={"file": (filename, content, "application/octet-stream")},
    )


def complete_draft(browser: TestClient, **finances: Any) -> str:
    app_id: str = create_draft(browser)["id"]
    browser.patch(f"/applications/{app_id}", json={**FINANCES, **finances}).raise_for_status()
    for doc_type, (filename, content) in DOCUMENTS.items():
        upload(browser, app_id, doc_type, filename, content).raise_for_status()
    return app_id


def submit(browser: TestClient, app_id: str, **body: Any) -> Any:
    return browser.post(
        f"/applications/{app_id}/submit", json={"accept_data_processing": True, **body}
    )


def test_customer_saves_a_draft_uploads_documents_and_submits(customer: TestClient) -> None:
    draft = create_draft(customer)
    assert draft["status"] == "DRAFT"
    assert draft["code"] is None  # mã hồ sơ vay chỉ cấp khi nộp

    customer.patch(f"/applications/{draft['id']}", json=FINANCES).raise_for_status()
    for doc_type, (filename, content) in DOCUMENTS.items():
        assert upload(customer, draft["id"], doc_type, filename, content).status_code == 201

    submitted = submit(customer, draft["id"])
    assert submitted.status_code == 200, submitted.text
    assert re.fullmatch(r"HS2026\d{6}", submitted.json()["code"])

    detail = customer.get(f"/applications/{draft['id']}").json()
    assert detail["status"] == "SUBMITTED"
    assert detail["submitted_at"] is not None
    assert {d["doc_type"]: d["sha256"] for d in detail["documents"]} == {
        doc_type: hashlib.sha256(content).hexdigest()
        for doc_type, (_, content) in DOCUMENTS.items()
    }


def test_draft_can_be_resumed_later(customer: TestClient) -> None:
    app_id = create_draft(customer)["id"]
    customer.patch(
        f"/applications/{app_id}", json={"occupation": "Giáo viên", "monthly_income": 12_000_000}
    ).raise_for_status()
    customer.patch(f"/applications/{app_id}", json={"term_months": 24}).raise_for_status()

    detail = customer.get(f"/applications/{app_id}").json()
    assert detail["status"] == "DRAFT"
    assert detail["term_months"] == 24
    assert detail["applicant"]["occupation"] == "Giáo viên"
    assert Decimal(detail["applicant"]["monthly_income"]) == 12_000_000


def test_estimated_monthly_payment_uses_the_ceiling_rate(customer: TestClient) -> None:
    draft = create_draft(customer)
    # Chưa có Hạng nên ước tính theo lãi suất trần (hạng C = 28%/năm, ADR 0001).
    expected = annuity_payment(Decimal(30_000_000), CEILING_RATE, 12)
    assert Decimal(draft["estimated_monthly_payment"]) == expected


@pytest.mark.parametrize(
    "overrides",
    [
        {"requested_amount": 4_999_999},
        {"requested_amount": 100_000_001},
        {"requested_amount": 30_000_000.5},
        {"term_months": 5},
        {"term_months": 37},
        {"purpose": "CASINO"},
    ],
)
def test_amount_term_and_purpose_must_follow_br02(
    customer: TestClient, overrides: dict[str, Any]
) -> None:
    assert customer.post("/applications", json={**LOAN, **overrides}).status_code == 400


def test_boundary_amounts_and_terms_are_accepted(customer: TestClient) -> None:
    app_id = create_draft(customer, requested_amount=5_000_000, term_months=6)["id"]
    edited = customer.patch(
        f"/applications/{app_id}", json={"requested_amount": 100_000_000, "term_months": 36}
    )
    assert edited.status_code == 200
    assert customer.patch(f"/applications/{app_id}", json={"term_months": 37}).status_code == 400


def test_br02_only_one_application_in_progress_per_customer(customer: TestClient) -> None:
    app_id = complete_draft(customer)
    assert customer.post("/applications", json=LOAN).status_code == 409  # bản nháp cũng tính

    submit(customer, app_id).raise_for_status()
    assert customer.post("/applications", json=LOAN).status_code == 409


def test_submit_requires_consent_to_data_processing(customer: TestClient) -> None:
    app_id = complete_draft(customer)

    assert submit(customer, app_id, accept_data_processing=False).status_code == 400
    assert customer.post(f"/applications/{app_id}/submit", json={}).status_code == 400
    assert customer.get(f"/applications/{app_id}").json()["status"] == "DRAFT"


def test_submit_lists_what_is_still_missing(customer: TestClient) -> None:
    app_id = create_draft(customer)["id"]
    customer.patch(f"/applications/{app_id}", json={"occupation": "Kế toán"}).raise_for_status()
    upload(customer, app_id, "ID_FRONT", "a.jpg", JPEG).raise_for_status()

    response = submit(customer, app_id)

    assert response.status_code == 400
    missing = {item["field"] for item in response.json()["errors"]}
    assert {"national_id", "monthly_income", "receiving_account", "ID_BACK", "INCOME_PROOF"} <= missing
    assert "occupation" not in missing and "ID_FRONT" not in missing


def test_uploaded_file_must_really_be_an_image_or_pdf_of_at_most_5mb(customer: TestClient) -> None:
    app_id = create_draft(customer)["id"]

    renamed_exe = upload(customer, app_id, "ID_FRONT", "cccd.jpg", b"MZ\x90\x00" + b"\x00" * 64)
    too_big = upload(customer, app_id, "INCOME_PROOF", "a.pdf", PDF + b"\x00" * (5 * 1024 * 1024))
    unknown_type = upload(customer, app_id, "SELFIE", "a.jpg", JPEG)

    assert renamed_exe.status_code == too_big.status_code == unknown_type.status_code == 400
    assert customer.get(f"/applications/{app_id}").json()["documents"] == []


def test_uploading_the_same_document_type_again_replaces_it(customer: TestClient) -> None:
    app_id = create_draft(customer)["id"]
    upload(customer, app_id, "ID_FRONT", "cu.jpg", JPEG).raise_for_status()
    newer = JPEG + b"\x05"
    upload(customer, app_id, "ID_FRONT", "moi.jpg", newer).raise_for_status()

    documents = customer.get(f"/applications/{app_id}").json()["documents"]
    assert [(d["doc_type"], d["sha256"]) for d in documents] == [
        ("ID_FRONT", hashlib.sha256(newer).hexdigest())
    ]


def test_submitted_application_can_no_longer_be_changed(customer: TestClient) -> None:
    app_id = complete_draft(customer)
    submit(customer, app_id).raise_for_status()

    assert customer.patch(f"/applications/{app_id}", json={"term_months": 24}).status_code == 409
    assert upload(customer, app_id, "ID_FRONT", "a.jpg", JPEG).status_code == 409
    assert submit(customer, app_id).status_code == 409


def test_sensitive_values_are_masked_when_shown(customer: TestClient) -> None:
    app_id = complete_draft(customer)

    detail = customer.get(f"/applications/{app_id}").json()

    assert detail["receiving_account"] == "012****789"
    assert detail["applicant"]["national_id"] == "079******234"
    assert "0123456789" not in str(detail) and "079095001234" not in str(detail)


def test_a_national_id_belongs_to_only_one_customer(
    customer: TestClient, other_customer: TestClient
) -> None:
    complete_draft(customer)
    app_id = create_draft(other_customer)["id"]

    response = other_customer.patch(
        f"/applications/{app_id}", json={"national_id": FINANCES["national_id"]}
    )
    assert response.status_code == 409


def test_customer_tracks_the_status_of_their_own_applications(
    customer: TestClient, other_customer: TestClient
) -> None:
    mine = complete_draft(customer)
    submit(customer, mine).raise_for_status()
    create_draft(other_customer)

    listed = customer.get("/applications").json()

    assert [(a["id"], a["status"]) for a in listed] == [(mine, "SUBMITTED")]


def test_st01_customer_cannot_reach_another_customers_application(
    customer: TestClient, other_customer: TestClient
) -> None:
    theirs = complete_draft(other_customer)
    nonexistent = "00000000-0000-0000-0000-000000000001"

    for app_id in (theirs, nonexistent):
        assert customer.get(f"/applications/{app_id}").status_code == 404
        assert customer.patch(f"/applications/{app_id}", json={"term_months": 24}).status_code == 404
        assert upload(customer, app_id, "ID_FRONT", "a.jpg", JPEG).status_code == 404
        assert submit(customer, app_id).status_code == 404
    # Không phân biệt được "không tồn tại" với "của người khác"
    assert customer.get(f"/applications/{theirs}").json() == customer.get(
        f"/applications/{nonexistent}"
    ).json()
    assert other_customer.get(f"/applications/{theirs}").json()["status"] == "DRAFT"


def test_st05_extra_fields_cannot_set_status_owner_or_code(
    customer: TestClient, other_customer: TestClient
) -> None:
    other_customer_id = other_customer.get("/auth/session").json()["user_id"]
    injected = {"status": "APPROVED", "customer_id": other_customer_id, "code": "HS2026999999",
                "annual_rate": 0.01, "version": 99}

    draft = create_draft(customer, **injected)
    assert draft["status"] == "DRAFT" and draft["code"] is None

    customer.patch(f"/applications/{draft['id']}", json={**FINANCES, **injected}).raise_for_status()
    for doc_type, (filename, content) in DOCUMENTS.items():
        upload(customer, draft["id"], doc_type, filename, content).raise_for_status()
    submitted = submit(customer, draft["id"], **injected)

    assert submitted.json()["status"] == "SUBMITTED"
    assert submitted.json()["code"] != "HS2026999999"
    assert customer.get(f"/applications/{draft['id']}").status_code == 200
    assert other_customer.get("/applications").json() == []


def test_applications_require_a_logged_in_customer(client: TestClient) -> None:
    assert new_client(client).post("/applications", json=LOAN).status_code == 401
    assert new_client(client).get("/applications").status_code == 401
