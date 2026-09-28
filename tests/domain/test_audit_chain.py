"""Seam 2: chuỗi băm của nhật ký kiểm toán (SR09, UC08)."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from loan_system.domain.audit import GENESIS_HASH, AuditContent, AuditRecord, seal, verify_chain

T0 = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)


def build_chain(length: int) -> list[AuditRecord]:
    records: list[AuditRecord] = []
    prev_hash = GENESIS_HASH
    for i in range(1, length + 1):
        content = AuditContent(
            actor_id=None,
            action="LOGIN_SUCCESS",
            target_type="USER",
            target_id=f"user-{i}",
            ip_address="10.0.0.1",
            level="INFO",
            created_at=T0 + timedelta(minutes=i),
        )
        record = seal(i, content, prev_hash)
        records.append(record)
        prev_hash = record.hash
    return records


def test_intact_chain_verifies() -> None:
    assert verify_chain(build_chain(100)) is None


def test_ut07_tampered_record_57_is_reported() -> None:
    records = build_chain(100)
    tampered = replace(records[56].content, action="LOGIN_FAIL")
    records[56] = replace(records[56], content=tampered)

    assert verify_chain(records) == 57


def test_recomputing_the_hash_of_a_tampered_record_still_breaks_at_the_next_one() -> None:
    # MUC07 bước 2: kẻ gian tính lại hash của bản ghi đã sửa
    records = build_chain(100)
    tampered = replace(records[56].content, action="LOGIN_FAIL")
    records[56] = seal(57, tampered, records[55].hash)

    assert verify_chain(records) == 58


def test_deleted_record_is_reported_as_a_gap() -> None:
    records = build_chain(100)
    del records[56]

    assert verify_chain(records) == 57
