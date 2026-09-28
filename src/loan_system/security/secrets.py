"""Băm mật khẩu (SR01), sinh và băm OTP, token phiên (SR11)."""

import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError

_hasher = PasswordHasher()  # Argon2id với salt ngẫu nhiên
# Băm sẵn một mật khẩu giả để thời gian xử lý tài khoản không tồn tại giống tài khoản có thật.
_DUMMY_HASH = _hasher.hash("dummy-password-for-timing")


def hash_password(raw: str) -> str:
    return _hasher.hash(raw)


def verify_password(password_hash: str | None, raw: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, raw) and password_hash is not None
    except VerificationError:
        return False


def keyed_hash(secret: str, value: str) -> str:
    """HMAC-SHA256 dạng hex; dùng cho OTP và token phiên để bản lưu trong CSDL vô dụng nếu bị lộ."""
    return hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()


def matches(secret: str, value: str, expected_hash: str) -> bool:
    return hmac.compare_digest(keyed_hash(secret, value), expected_hash)


def new_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def new_session_token() -> str:
    return secrets.token_urlsafe(32)
