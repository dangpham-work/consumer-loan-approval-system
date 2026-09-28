"""Seam 1: trình xem giấy tờ trong màn hình thẩm định, có watermark tên người xem (M06, MUC06)."""

import io
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from loan_system.adapters.email import FakeEmailGateway
from loan_system.adapters.sms import FakeSmsGateway
from tests.api.workflow import (
    LOAN,
    PDF,
    Team,
    customer_browser,
    fill_draft,
    submitted_application,
    upload,
    verify_as,
)
from tests.conftest import FakeClock


def picture(fmt: str) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (400, 300), (240, 240, 240)).save(output, format=fmt)
    return output.getvalue()


PNG = picture("PNG")
JPEG = picture("JPEG")


@pytest.fixture
def team(client: TestClient, clock: FakeClock, email: FakeEmailGateway) -> Team:
    return Team(client, clock, email)


@pytest.fixture
def customer(client: TestClient, sms: FakeSmsGateway) -> TestClient:
    return customer_browser(client, sms)


def submitted_with_real_images(customer: TestClient) -> tuple[str, dict[str, str]]:
    app_id: str = customer.post("/applications", json=LOAN).json()["id"]
    fill_draft(customer, app_id)
    upload(customer, app_id, "ID_FRONT", "cccd-truoc.jpg", JPEG).raise_for_status()
    upload(customer, app_id, "ID_BACK", "cccd-sau.png", PNG).raise_for_status()
    customer.post(
        f"/applications/{app_id}/submit", json={"accept_data_processing": True}
    ).raise_for_status()
    documents = customer.get(f"/applications/{app_id}").json()["documents"]
    return app_id, {d["doc_type"]: d["id"] for d in documents}


def appraising_with_real_images(team: Team, customer: TestClient) -> tuple[str, dict[str, str]]:
    """Hồ sơ vay đang thẩm định, chuyên viên thẩm định (thamdinh1) đã mở."""
    app_id, documents = submitted_with_real_images(customer)
    assert verify_as(team.officer.client, app_id).status_code == 200
    team.appraiser.client.post(f"/applications/{app_id}/appraisal/open").raise_for_status()
    return app_id, documents


def content_url(app_id: str, document_id: str) -> str:
    return f"/applications/{app_id}/appraisal/documents/{document_id}"


@pytest.mark.parametrize(("doc_type", "original", "fmt"), [("ID_BACK", PNG, "PNG"),
                                                           ("ID_FRONT", JPEG, "JPEG")])
def test_staff_see_images_stamped_with_their_own_name(
    team: Team, customer: TestClient, doc_type: str, original: bytes, fmt: str
) -> None:
    app_id, documents = appraising_with_real_images(team, customer)

    response = team.appraiser.client.get(content_url(app_id, documents[doc_type]))

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert "thamdinh1" in unquote(response.headers["x-watermark"])
    assert response.headers["x-watermark-stamped"] == "true"
    shown = Image.open(io.BytesIO(response.content))
    assert (shown.format, shown.size) == (fmt, (400, 300))
    # Ảnh gốc một màu: có watermark thì phải có điểm ảnh khác màu nền.
    darkest, _ = shown.convert("L").getextrema()
    assert isinstance(darkest, int) and darkest < 200


def test_pdf_is_returned_with_the_watermark_for_the_viewer_to_overlay(
    team: Team, customer: TestClient
) -> None:
    app_id, documents = appraising_with_real_images(team, customer)

    response = team.appraiser.client.get(content_url(app_id, documents["INCOME_PROOF"]))

    assert response.status_code == 200
    assert response.content == PDF
    assert response.headers["x-watermark-stamped"] == "false"
    assert "thamdinh1" in unquote(response.headers["x-watermark"])


def test_unreadable_images_are_never_shown_without_a_watermark(
    team: Team, customer: TestClient
) -> None:
    # Giấy tờ mẫu chỉ đúng magic bytes JPEG, nội dung hỏng: không in được watermark thì không
    # trả file gốc.
    app_id = submitted_application(customer)
    assert verify_as(team.officer.client, app_id).status_code == 200
    team.appraiser.client.post(f"/applications/{app_id}/appraisal/open").raise_for_status()
    front = next(d["id"] for d in customer.get(f"/applications/{app_id}").json()["documents"]
                 if d["doc_type"] == "ID_FRONT")

    response = team.appraiser.client.get(content_url(app_id, front))

    assert response.status_code == 409


def test_only_the_assigned_appraiser_sees_documents_during_appraisal(
    team: Team, customer: TestClient
) -> None:
    app_id, documents = appraising_with_real_images(team, customer)
    url = content_url(app_id, documents["ID_BACK"])
    other_appraiser = team.hire("thamdinh2", "APPRAISER").client

    # Vai trò chỉ được xem dữ liệu đã che (ô "M" trong ma trận RBAC) không tải được ảnh CCCD.
    assert team.officer.client.get(url).status_code == 403
    assert team.approver.client.get(url).status_code == 403
    assert customer.get(url).status_code == 403
    assert other_appraiser.get(url).status_code == 403

    team.appraiser.client.post(
        f"/applications/{app_id}/appraisal",
        json={"recommendation": "REJECT", "comment": "Giấy tờ không rõ ràng, đề xuất từ chối."},
    ).raise_for_status()
    assert team.appraiser.client.get(url).status_code == 409  # hết bước thẩm định


def test_each_document_view_counts_as_a_pii_view(team: Team, customer: TestClient) -> None:
    app_id, documents = appraising_with_real_images(team, customer)

    team.appraiser.client.get(content_url(app_id, documents["ID_BACK"])).raise_for_status()

    views = team.auditor.client.get(
        "/audit/logs", params={"action": "VIEW_PII", "target_id": documents["ID_BACK"]}
    ).json()
    assert len(views) == 1
