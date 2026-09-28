"""Chuỗi băm của nhật ký kiểm toán (SR09).

hash = SHA256(prev_hash ‖ seq ‖ nội dung chuẩn hóa). Bản ghi đầu tiên (seq 1) nối vào GENESIS_HASH.
`seq` do ứng dụng cấp trong cùng giao dịch ghi nhật ký nên liên tục tuyệt đối, khác với IDENTITY
của SQL Server vốn có thể nhảy số khi giao dịch bị hoàn tác hoặc máy chủ khởi động lại.
"""

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

GENESIS_HASH = "0" * 64


@dataclass(frozen=True)
class AuditContent:
    actor_id: str | None
    action: str
    target_type: str | None
    target_id: str | None
    ip_address: str | None
    level: str
    created_at: datetime


@dataclass(frozen=True)
class AuditRecord:
    seq: int
    content: AuditContent
    prev_hash: str
    hash: str


def compute_hash(prev_hash: str, seq: int, content: AuditContent) -> str:
    canonical = json.dumps(
        {
            "seq": seq,
            "actor_id": content.actor_id,
            "action": content.action,
            "target_type": content.target_type,
            "target_id": content.target_id,
            "ip_address": content.ip_address,
            "level": content.level,
            "created_at": content.created_at.isoformat(),
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256((prev_hash + canonical).encode("utf-8")).hexdigest()


def seal(seq: int, content: AuditContent, prev_hash: str) -> AuditRecord:
    return AuditRecord(seq, content, prev_hash, compute_hash(prev_hash, seq, content))


def verify_chain(records: Sequence[AuditRecord]) -> int | None:
    """Trả về seq đầu tiên mà chuỗi bị phá vỡ (sửa, xóa hoặc chèn), hoặc None nếu toàn vẹn.

    Với một khoảng không bắt đầu từ seq 1, prev_hash của bản ghi đầu tiên được coi là mốc tin cậy.
    Giới hạn: xóa các bản ghi ở cuối chuỗi không phát hiện được bằng hash; lớp phòng thủ cho
    trường hợp đó là quyền CSDL (app_rw bị DENY DELETE trên audit_logs).
    """
    if not records:
        return None
    first = records[0]
    expected_prev = GENESIS_HASH if first.seq == 1 else first.prev_hash
    for offset, record in enumerate(records):
        expected_seq = first.seq + offset
        if record.seq != expected_seq:
            return expected_seq
        if record.prev_hash != expected_prev or record.hash != compute_hash(
            record.prev_hash, record.seq, record.content
        ):
            return record.seq
        expected_prev = record.hash
    return None
