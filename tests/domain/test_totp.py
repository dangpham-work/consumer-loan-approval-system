"""Seam 2: mã TOTP cho xác thực hai yếu tố của nhân viên (SR02, UC02)."""

import base64
from datetime import UTC, datetime, timedelta

from loan_system.security.totp import new_totp_secret, totp_code, verify_totp

# Vector kiểm thử của RFC 6238 (phụ lục B), khóa SHA-1 "12345678901234567890", mã 8 chữ số.
RFC_SECRET = base64.b32encode(b"12345678901234567890").decode()


def at(unix_seconds: int) -> datetime:
    return datetime.fromtimestamp(unix_seconds, UTC)


def test_codes_match_the_rfc_6238_test_vectors() -> None:
    assert totp_code(RFC_SECRET, at(59), digits=8) == "94287082"
    assert totp_code(RFC_SECRET, at(1111111109), digits=8) == "07081804"
    assert totp_code(RFC_SECRET, at(2000000000), digits=8) == "69279037"


def test_code_is_accepted_within_one_step_either_side() -> None:
    now = at(1_800_000_000)
    secret = new_totp_secret()

    for skew in (-30, 0, 30):
        assert verify_totp(secret, totp_code(secret, now + timedelta(seconds=skew)), now) is not None
    assert verify_totp(secret, totp_code(secret, now + timedelta(seconds=90)), now) is None


def test_a_code_cannot_be_used_twice() -> None:
    now = at(1_800_000_000)
    secret = new_totp_secret()
    code = totp_code(secret, now)

    used_step = verify_totp(secret, code, now)
    assert used_step is not None
    assert verify_totp(secret, code, now, last_used_step=used_step) is None
    # Mã của bước kế tiếp vẫn dùng được
    later = now + timedelta(seconds=30)
    assert verify_totp(secret, totp_code(secret, later), later, last_used_step=used_step) is not None


def test_malformed_code_is_rejected() -> None:
    secret = new_totp_secret()
    now = at(1_800_000_000)
    assert verify_totp(secret, "12345", now) is None
    assert verify_totp(secret, "abcdef", now) is None
