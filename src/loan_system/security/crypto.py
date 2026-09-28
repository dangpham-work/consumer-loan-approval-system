"""Mã hóa mức trường AES-256-GCM (SR06) và blind index cho tra cứu không cần giải mã (4.1.2).

Bản mã = phiên bản khóa (1 byte) ‖ nonce (12 byte) ‖ ciphertext kèm tag. Phiên bản khóa cho phép
xoay khóa mà vẫn giải mã được dữ liệu cũ (4.2.5). `context` (bảng.cột:id bản ghi) được đưa vào
associated data, nên bản mã chép sang cột hay bản ghi khác sẽ không giải mã được.
"""

import hashlib
import hmac
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEY_VERSION = 1
NONCE_BYTES = 12


class DecryptionFailed(Exception):
    """Bản mã bị sửa, sai khóa hoặc sai ngữ cảnh."""


def _derive_key(secret: str) -> bytes:
    # Biến môi trường là chuỗi ngẫu nhiên tùy độ dài; rút về đúng 256 bit cho AES-256.
    return hashlib.sha256(secret.encode()).digest()


class FieldCipher:
    def __init__(self, secret: str) -> None:
        self._aead = AESGCM(_derive_key(secret))

    def encrypt(self, plaintext: str, *, context: str) -> bytes:
        nonce = os.urandom(NONCE_BYTES)
        sealed = self._aead.encrypt(nonce, plaintext.encode(), context.encode())
        return bytes([KEY_VERSION]) + nonce + sealed

    def decrypt(self, data: bytes, *, context: str) -> str:
        if len(data) <= 1 + NONCE_BYTES or data[0] != KEY_VERSION:
            raise DecryptionFailed
        nonce, sealed = data[1 : 1 + NONCE_BYTES], data[1 + NONCE_BYTES :]
        try:
            return self._aead.decrypt(nonce, sealed, context.encode()).decode()
        except InvalidTag as exc:
            raise DecryptionFailed from exc


def blind_index(secret: str, value: str) -> str:
    """HMAC-SHA256 dạng hex với khóa BLIND_INDEX_KEY riêng: so khớp chính xác mà không lộ giá trị."""
    return hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()
