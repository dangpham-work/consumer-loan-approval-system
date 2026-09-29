"""HMAC-SHA256 cho snapshot phê duyệt (SR08) bằng khóa HMAC_INTEGRITY_KEY có phiên bản (4.2.5).

Phiên bản khóa được lưu cùng mã băm, nên sau khi xoay khóa vẫn kiểm tra được hồ sơ vay đã duyệt
bằng khóa cũ; khóa đã bị loại khỏi cấu hình thì không kiểm tra được nữa (không coi là khớp).
"""

import hashlib
import hmac
from collections.abc import Mapping
from dataclasses import dataclass


class UnknownKeyVersion(Exception):
    """Không có khóa toàn vẹn với phiên bản này."""


@dataclass(frozen=True)
class Signature:
    key_version: int
    digest: str  # hex, 64 ký tự


class IntegrityKeyring:
    def __init__(self, keys: Mapping[int, str], current: int) -> None:
        if current not in keys:
            raise UnknownKeyVersion(current)
        self._keys = dict(keys)
        self._current = current

    def sign(self, message: str) -> Signature:
        return Signature(self._current, self._digest(self._current, message))

    def verify(self, message: str, signature: Signature) -> bool:
        """So sánh thời gian hằng (SUC02 bước 3)."""
        return hmac.compare_digest(
            self._digest(signature.key_version, message), signature.digest
        )

    def _digest(self, version: int, message: str) -> str:
        key = self._keys.get(version)
        if key is None:
            raise UnknownKeyVersion(version)
        return hmac.new(key.encode(), message.encode(), hashlib.sha256).hexdigest()
