"""TOTP theo RFC 6238 (HMAC-SHA1, bước 30 giây) cho xác thực hai yếu tố của nhân viên (SR02, UC02)."""

import base64
import hashlib
import hmac
import secrets
from datetime import datetime
from urllib.parse import quote

STEP_SECONDS = 30
DIGITS = 6
# UC02 bước 3: chấp nhận lệch ±30 giây, tức một bước trước và một bước sau.
ALLOWED_DRIFT_STEPS = 1


def new_totp_secret() -> str:
    """Khóa 160 bit dạng base32, định dạng mà ứng dụng xác thực (Google Authenticator...) nhận."""
    return base64.b32encode(secrets.token_bytes(20)).decode()


def provisioning_uri(secret: str, account: str, issuer: str) -> str:
    label = quote(f"{issuer}:{account}")
    return f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}"


def _step(at: datetime) -> int:
    return int(at.timestamp()) // STEP_SECONDS


def _code_for_step(secret: str, step: int, digits: int) -> str:
    key = base64.b32decode(secret, casefold=True)
    digest = hmac.new(key, step.to_bytes(8, "big"), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = int.from_bytes(digest[offset : offset + 4], "big") & 0x7FFFFFFF
    return str(value % 10**digits).zfill(digits)


def totp_code(secret: str, at: datetime, digits: int = DIGITS) -> str:
    return _code_for_step(secret, _step(at), digits)


def verify_totp(
    secret: str, code: str, at: datetime, last_used_step: int | None = None
) -> int | None:
    """Trả về bước thời gian khớp với mã, hoặc None nếu sai.

    Mã thuộc bước đã dùng (hoặc cũ hơn) bị từ chối để không phát lại được mã vừa bị nhìn trộm.
    """
    if len(code) != DIGITS or not code.isdigit():
        return None
    current = _step(at)
    for step in range(current - ALLOWED_DRIFT_STEPS, current + ALLOWED_DRIFT_STEPS + 1):
        if last_used_step is not None and step <= last_used_step:
            continue
        if hmac.compare_digest(_code_for_step(secret, step, DIGITS), code):
            return step
    return None
