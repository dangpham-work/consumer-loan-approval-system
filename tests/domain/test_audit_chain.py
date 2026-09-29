"""Seam 2: chuỗi băm của nhật ký kiểm toán (SR09, UC08)."""

import hashlib
import json
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


def test_detail_is_covered_by_the_hash() -> None:
    records = build_chain(3)
    detailed = seal(4, replace(records[2].content, detail="roles: [A] -> [B]"), records[2].hash)
    records.append(detailed)
    assert verify_chain(records) is None

    records[3] = replace(detailed, content=replace(detailed.content, detail="roles: [A] -> [A]"))
    assert verify_chain(records) == 4


def test_records_without_detail_keep_their_original_hash() -> None:
    # Bản ghi cũ (trước khi có cột detail) vẫn kiểm tra được: detail rỗng không vào nội dung băm.
    record = build_chain(1)[0]
    content = record.content
    legacy_canonical = {
        "seq": 1, "actor_id": content.actor_id, "action": content.action,
        "target_type": content.target_type, "target_id": content.target_id,
        "ip_address": content.ip_address, "level": content.level,
        "created_at": content.created_at.isoformat(),
    }
    legacy_hash = hashlib.sha256(
        (GENESIS_HASH + json.dumps(legacy_canonical, sort_keys=True, ensure_ascii=False)).encode()
    ).hexdigest()
    assert record.hash == legacy_hash
