"""Seam 2: quy tắc lập và nộp Hồ sơ vay (UC12, BR02)."""

from loan_system.domain.applications import (
    DOCUMENT_TYPES,
    IN_PROGRESS,
    REQUIRED_FIELDS,
    INFO_ITEMS,
    ApplicationStatus,
    outside_request,
    application_code,
    mask,
    missing_for_submission,
)


def test_complete_application_has_nothing_missing() -> None:
    assert missing_for_submission(REQUIRED_FIELDS, DOCUMENT_TYPES) == []


def test_missing_fields_come_before_missing_documents() -> None:
    missing = missing_for_submission(
        [f for f in REQUIRED_FIELDS if f != "monthly_income"],
        ["ID_FRONT", "ID_BACK", "INCOME_PROOF"],
    )
    assert missing == ["monthly_income", "UTILITY_BILL"]


def test_only_finished_applications_let_the_customer_apply_again() -> None:
    finished = set(ApplicationStatus) - IN_PROGRESS
    assert finished == {
        ApplicationStatus.REJECTED,
        ApplicationStatus.CANCELLED,
        ApplicationStatus.DISBURSED,
    }


def test_application_code_is_year_and_six_digit_sequence() -> None:
    assert application_code(2026, 123) == "HS2026000123"


def test_mask_follows_the_sr07_pattern() -> None:
    assert mask("0791234123") == "079****123"
    assert mask("079095001234") == "079******234"
    assert mask("123456") == "******"


def test_a_supplement_may_only_touch_the_requested_items() -> None:
    assert outside_request({"monthly_income", "ID_FRONT"}, {"monthly_income", "ID_FRONT"}) == set()
    assert outside_request({"receiving_account"}, {"ID_FRONT"}) == {"receiving_account"}


def test_loan_terms_can_never_be_requested_as_a_supplement() -> None:
    assert not {"requested_amount", "term_months", "purpose"} & set(INFO_ITEMS)
