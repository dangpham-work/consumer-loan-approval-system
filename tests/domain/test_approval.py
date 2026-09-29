"""Seam 2: quyết định phê duyệt (UC23, UC24, AD04) và snapshot HMAC có phiên bản khóa (SR08, SUC02)."""

import uuid
from dataclasses import replace
from decimal import Decimal

import pytest

from loan_system.domain.approval import (
    ApprovalSnapshot,
    Decision,
    Outcome,
    RejectionReason,
    outcome_of,
)
from loan_system.security.integrity import IntegrityKeyring, UnknownKeyVersion

SNAPSHOT = ApprovalSnapshot(
    application_id=uuid.UUID("0b8e2c1a-6f4d-4a55-9d1e-3c2b7a9f0e11"),
    code="HS2026000001",
    requested_amount=Decimal(30_000_000),
    approved_amount=Decimal(25_000_000),
    approved_term=12,
    annual_rate=Decimal("0.2000"),
    receiving_account="0123456789",
)
KEY_V1 = "khoa-toan-ven-phien-ban-1-chi-dung-trong-test"
KEY_V2 = "khoa-toan-ven-phien-ban-2-chi-dung-trong-test"


def test_snapshot_is_serialized_in_a_fixed_order() -> None:
    assert SNAPSHOT.canonical() == (
        "0b8e2c1a-6f4d-4a55-9d1e-3c2b7a9f0e11|HS2026000001|30000000|25000000|12|0.2000|0123456789"
    )


def test_equal_values_serialize_the_same_whatever_their_decimal_scale() -> None:
    # Đọc lại từ CSDL, DECIMAL(5,4) trả 0.2000 còn DECIMAL(15,0) trả 25000000: snapshot vẫn khớp.
    reloaded = replace(
        SNAPSHOT, annual_rate=Decimal("0.2"), approved_amount=Decimal("25000000.0")
    )
    assert reloaded.canonical() == SNAPSHOT.canonical()


def test_signature_matches_only_the_unchanged_snapshot() -> None:
    keyring = IntegrityKeyring({1: KEY_V1}, current=1)
    signature = keyring.sign(SNAPSHOT.canonical())

    assert signature.key_version == 1
    assert len(signature.digest) == 64
    assert keyring.verify(SNAPSHOT.canonical(), signature)
    # ST04: sửa số tiền yêu cầu sau khi đã duyệt thì không khớp.
    tampered = replace(SNAPSHOT, requested_amount=Decimal(90_000_000))
    assert not keyring.verify(tampered.canonical(), signature)
    tampered_account = replace(SNAPSHOT, receiving_account="9999999999")
    assert not keyring.verify(tampered_account.canonical(), signature)


def test_signature_depends_on_the_key() -> None:
    signed = IntegrityKeyring({1: KEY_V1}, current=1).sign(SNAPSHOT.canonical())
    other = IntegrityKeyring({1: KEY_V2}, current=1)
    assert not other.verify(SNAPSHOT.canonical(), signed)


def test_snapshot_signed_before_a_key_rotation_is_verified_with_its_own_key_version() -> None:
    signed = IntegrityKeyring({1: KEY_V1}, current=1).sign(SNAPSHOT.canonical())
    rotated = IntegrityKeyring({1: KEY_V1, 2: KEY_V2}, current=2)

    assert rotated.sign(SNAPSHOT.canonical()).key_version == 2
    assert rotated.verify(SNAPSHOT.canonical(), signed)


def test_snapshot_signed_with_a_retired_key_cannot_be_verified() -> None:
    signed = IntegrityKeyring({1: KEY_V1}, current=1).sign(SNAPSHOT.canonical())
    with pytest.raises(UnknownKeyVersion):
        IntegrityKeyring({2: KEY_V2}, current=2).verify(SNAPSHOT.canonical(), signed)


def test_keyring_needs_its_current_key() -> None:
    with pytest.raises(UnknownKeyVersion):
        IntegrityKeyring({1: KEY_V1}, current=2)


@pytest.mark.parametrize(
    ("decisions", "required", "expected"),
    [
        ([Decision.APPROVE], 1, Outcome.APPROVED),
        ([], 1, Outcome.PENDING),
        ([Decision.APPROVE], 2, Outcome.PENDING),
        ([Decision.APPROVE, Decision.APPROVE], 2, Outcome.APPROVED),
        # AD04: một Từ chối là đủ để từ chối, một Trả về đưa hồ sơ vay về thẩm định.
        ([Decision.REJECT], 1, Outcome.REJECTED),
        ([Decision.APPROVE, Decision.REJECT], 2, Outcome.REJECTED),
        ([Decision.RETURN], 1, Outcome.RETURNED),
        ([Decision.APPROVE, Decision.RETURN], 2, Outcome.RETURNED),
    ],
)
def test_outcome_of_the_decisions_on_one_appraisal_report(
    decisions: list[Decision], required: int, expected: Outcome
) -> None:
    assert outcome_of(decisions, required) == expected


def test_customer_is_told_only_the_general_rejection_reason() -> None:
    assert RejectionReason.FINANCIAL_CAPACITY.label == "năng lực tài chính"
    assert RejectionReason.FRAUD_SUSPECTED.label == "nghi ngờ gian lận"
    assert {r.label for r in RejectionReason} == {
        "năng lực tài chính", "lịch sử tín dụng", "nghi ngờ gian lận", "lý do khác"
    }
