"""Mã hóa mức trường ChaCha20-Poly1305 (SR06, ADR 0005) và blind index cho tra cứu không cần giải mã
(4.1.2).

Bản mã = phiên bản định dạng (1 byte) ‖ nonce (12 byte) ‖ ciphertext kèm tag 16 byte. Phiên bản định
dạng cho biết thuật toán và cách dẫn xuất khóa, nhờ đó đổi thuật toán mà dữ liệu cũ vẫn giải mã được
(4.2.5):

- 2 (hiện hành): ChaCha20-Poly1305 (RFC 8439), khóa dẫn xuất từ DATA_ENC_KEY bằng HKDF-SHA256.
- 1 (chỉ còn giải mã): AES-256-GCM, khóa SHA-256(DATA_ENC_KEY). Trường được ghi lại sẽ mang định dạng 2.

`context` (bảng.cột:id bản ghi) được đưa vào associated data, nên bản mã chép sang cột hay bản ghi khác
sẽ không giải mã được. Ở định dạng 2, byte phiên bản cũng nằm trong associated data.
"""

import hashlib
import hmac
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM, ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

FORMAT_AES_GCM = 1
FORMAT_CHACHA20_POLY1305 = 2
CURRENT_FORMAT = FORMAT_CHACHA20_POLY1305
NONCE_BYTES = 12  # 96 bit, như nhau ở cả hai định dạng
# Mỗi khóa dẫn xuất chỉ dùng cho một thuật toán, một mục đích (HKDF info).
_CHACHA20_KEY_INFO = b"loan_system/field-encryption/chacha20-poly1305"


class DecryptionFailed(Exception):
    """Bản mã bị sửa, sai khóa, sai ngữ cảnh hoặc không rõ định dạng."""


def _legacy_key(secret: str) -> bytes:
    # Định dạng 1: biến môi trường là chuỗi ngẫu nhiên tùy độ dài, rút về đúng 256 bit cho AES-256.
    return hashlib.sha256(secret.encode()).digest()


def _derive_key(secret: str, info: bytes) -> bytes:
    """Khóa 256 bit cho một mục đích (HKDF-SHA256, RFC 5869), độc lập với khóa của định dạng 1."""
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=info).derive(secret.encode())


def _associated_data(fmt: int, context: str) -> bytes:
    if fmt == FORMAT_AES_GCM:
        return context.encode()
    return bytes([fmt]) + context.encode()


class FieldCipher:
    def __init__(self, secret: str) -> None:
        self._aeads: dict[int, ChaCha20Poly1305 | AESGCM] = {
            FORMAT_CHACHA20_POLY1305: ChaCha20Poly1305(_derive_key(secret, _CHACHA20_KEY_INFO)),
            FORMAT_AES_GCM: AESGCM(_legacy_key(secret)),
        }

    def encrypt(self, plaintext: str, *, context: str) -> bytes:
        nonce = os.urandom(NONCE_BYTES)
        sealed = self._aeads[CURRENT_FORMAT].encrypt(
            nonce, plaintext.encode(), _associated_data(CURRENT_FORMAT, context)
        )
        return bytes([CURRENT_FORMAT]) + nonce + sealed

    def decrypt(self, data: bytes, *, context: str) -> str:
        aead = self._aeads.get(data[0]) if data else None
        if aead is None or len(data) <= 1 + NONCE_BYTES:
            raise DecryptionFailed
        nonce, sealed = data[1 : 1 + NONCE_BYTES], data[1 + NONCE_BYTES :]
        try:
            return aead.decrypt(nonce, sealed, _associated_data(data[0], context)).decode()
        except InvalidTag as exc:
            raise DecryptionFailed from exc


def blind_index(secret: str, value: str) -> str:
    """HMAC-SHA256 dạng hex với khóa BLIND_INDEX_KEY riêng: so khớp chính xác mà không lộ giá trị."""
    return hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()
