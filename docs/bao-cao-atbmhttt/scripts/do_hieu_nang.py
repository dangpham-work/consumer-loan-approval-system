"""Đo hiệu năng các thuật toán dùng trong hệ thống (báo cáo mục 2.2.5 và 3.5.3).

Chạy: uv run python docs/bao-cao-atbmhttt/scripts/do_hieu_nang.py [--json ket_qua.json]
Mô phỏng thiết bị không có AES-NI (điện thoại, máy cũ) bằng cách tắt AES-NI và PCLMULQDQ của OpenSSL:
    OPENSSL_ia32cap="~0x200000200000000" uv run python docs/bao-cao-atbmhttt/scripts/do_hieu_nang.py

Mỗi phép đo lặp đủ lâu (>= 0,2 giây) rồi lấy trung vị của 7 lần. Kết quả phụ thuộc máy chạy.
"""

import argparse
import hashlib
import hmac
import json
import os
import platform
import statistics
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import cryptography
from cryptography.hazmat.backends.openssl.backend import backend
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM, ChaCha20Poly1305

from loan_system.domain.audit import GENESIS_HASH, AuditContent, seal, verify_chain
from loan_system.security.crypto import FieldCipher, blind_index
from loan_system.security.secrets import hash_password, verify_password
from loan_system.security.totp import new_totp_secret, totp_code, verify_totp


def per_call(fn: Callable[[], object], min_seconds: float = 0.2, repeats: int = 7) -> float:
    """Thời gian trung vị cho một lần gọi, tính bằng giây."""
    n = 1
    while True:
        start = time.perf_counter()
        for _ in range(n):
            fn()
        if time.perf_counter() - start >= min_seconds / 4:
            break
        n *= 2
    n = max(1, int(n * min_seconds / max(time.perf_counter() - start, 1e-9)))
    samples = []
    for _ in range(repeats):
        start = time.perf_counter()
        for _ in range(n):
            fn()
        samples.append((time.perf_counter() - start) / n)
    return statistics.median(samples)


KEY = os.urandom(32)
MAC_KEY = os.urandom(32)
NONCE = os.urandom(12)


def chacha_seal(data: bytes) -> bytes:
    return ChaCha20Poly1305(KEY).encrypt(NONCE, data, b"ctx")


def gcm_seal(data: bytes) -> bytes:
    return AESGCM(KEY).encrypt(NONCE, data, b"ctx")


def cbc_hmac_seal(data: bytes) -> bytes:
    """AES-256-CBC + HMAC-SHA256 (encrypt-then-MAC): cách ghép thủ công trước khi có AEAD."""
    iv = os.urandom(16)
    padder = padding.PKCS7(128).padder()
    padded = padder.update(data) + padder.finalize()
    enc = Cipher(algorithms.AES(KEY), modes.CBC(iv)).encryptor()
    body = iv + enc.update(padded) + enc.finalize()
    return body + hmac.new(MAC_KEY, body, hashlib.sha256).digest()


SIZES = [64, 1024, 16 * 1024, 1024 * 1024, 5 * 1024 * 1024]


def throughput() -> dict[str, dict[str, float]]:
    results: dict[str, dict[str, float]] = {}
    for name, fn in (
        ("ChaCha20-Poly1305", chacha_seal),
        ("AES-256-GCM", gcm_seal),
        ("AES-256-CBC + HMAC-SHA256", cbc_hmac_seal),
    ):
        results[name] = {}
        for size in SIZES:
            data = os.urandom(size)
            seconds = per_call(lambda: fn(data), min_seconds=0.3 if size > 16384 else 0.2)
            results[name][str(size)] = size / seconds / 1e6  # MB/s
    return results


def field_level() -> dict[str, dict[str, float]]:
    """Một trường: hai thuật toán gọi cùng một cách (nonce mới + AAD), và FieldCipher đầy đủ của hệ
    thống (đổi chuỗi sang byte, ghép byte định dạng, dựng AAD) với định dạng 2."""
    secret = "bench-only-data-enc-key-0123456789abcdef"
    cipher = FieldCipher(secret)
    chacha = ChaCha20Poly1305(os.urandom(32))
    gcm = AESGCM(os.urandom(32))
    context = "customers.national_id:3f2b0c4e11114222833394445555666"
    aad = bytes([2]) + context.encode()
    samples = {
        "CCCD (12 B)": "079095001234",
        "Tai khoan nhan (14 B)": "19036600712345",
        "Khoa TOTP (32 B)": new_totp_secret(),
        "Du lieu cho OTP (~300 B)": json.dumps({"full_name": "x" * 40, "items": list(range(60))}),
    }
    out: dict[str, dict[str, float]] = {}
    for label, value in samples.items():
        data = value.encode()
        nonce = os.urandom(12)
        sealed_chacha = chacha.encrypt(nonce, data, aad)
        sealed_gcm = gcm.encrypt(nonce, data, aad)
        stored = cipher.encrypt(value, context=context)
        out[label] = {
            "chacha_encrypt_us": per_call(lambda: chacha.encrypt(os.urandom(12), data, aad)) * 1e6,
            "chacha_decrypt_us": per_call(lambda: chacha.decrypt(nonce, sealed_chacha, aad)) * 1e6,
            "aesgcm_encrypt_us": per_call(lambda: gcm.encrypt(os.urandom(12), data, aad)) * 1e6,
            "aesgcm_decrypt_us": per_call(lambda: gcm.decrypt(nonce, sealed_gcm, aad)) * 1e6,
            "fieldcipher_encrypt_us": per_call(
                lambda: cipher.encrypt(value, context=context)
            ) * 1e6,
            "fieldcipher_decrypt_us": per_call(
                lambda: cipher.decrypt(stored, context=context)
            ) * 1e6,
            "stored_bytes": len(stored),
        }
    return out


def supporting() -> dict[str, float]:
    password_hash = hash_password("Demo@NhanVien2026")
    secret = new_totp_secret()
    now = datetime(2026, 10, 28, 8, 0, tzinfo=UTC)
    code = totp_code(secret, now)
    records = []
    prev = GENESIS_HASH
    for i in range(1, 10_001):
        content = AuditContent(
            actor_id=None, action="LOGIN_SUCCESS", target_type="USER", target_id=f"u{i}",
            ip_address="10.0.0.1", level="INFO", created_at=now + timedelta(seconds=i),
        )
        record = seal(i, content, prev)
        records.append(record)
        prev = record.hash
    return {
        "argon2id_hash_ms": per_call(lambda: hash_password("Demo@NhanVien2026"), 1.0, 5) * 1e3,
        "argon2id_verify_ms": per_call(
            lambda: verify_password(password_hash, "Demo@NhanVien2026"), 1.0, 5
        ) * 1e3,
        "hmac_blind_index_us": per_call(lambda: blind_index("k" * 48, "079095001234")) * 1e6,
        "totp_verify_us": per_call(lambda: verify_totp(secret, code, now)) * 1e6,
        "field_cipher_init_us": per_call(lambda: FieldCipher("k" * 48)) * 1e6,
        "audit_chain_verify_10000_ms": per_call(lambda: verify_chain(records), 1.0, 5) * 1e3,
    }


def environment() -> dict[str, str]:
    cpu = platform.processor() or platform.machine()
    try:
        with open("/proc/cpuinfo", encoding="ascii", errors="ignore") as f:
            cpu = next(line.split(":", 1)[1].strip() for line in f if line.startswith("model name"))
    except (OSError, StopIteration):
        pass
    return {
        "cpu": cpu,
        "cores": str(os.cpu_count()),
        "python": platform.python_version(),
        "cryptography": cryptography.__version__,
        "openssl": backend.openssl_version_text(),
        "OPENSSL_ia32cap": os.environ.get("OPENSSL_ia32cap", "(not set: AES-NI enabled)"),
        "measured_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", help="ghi kết quả ra file JSON")
    parser.add_argument("--quick", action="store_true", help="chỉ đo thông lượng")
    args = parser.parse_args()

    env = environment()
    result: dict[str, object] = {"environment": env}
    for key, value in env.items():
        print(f"{key:>16}: {value}")

    print("\nThroughput, MB/s (encrypt + tag, higher is better)")
    tp = throughput()
    result["throughput_mb_s"] = tp
    print(f"{'algorithm':<28}" + "".join(f"{s:>12}" for s in ("64 B", "1 KB", "16 KB", "1 MB", "5 MB")))
    for name, row in tp.items():
        print(f"{name:<28}" + "".join(f"{row[str(s)]:>12.1f}" for s in SIZES))

    if not args.quick:
        print("\nField-level encryption, microseconds per call")
        fl = field_level()
        result["field_level_us"] = fl
        for label, row in fl.items():
            print(
                f"{label:<26} ChaCha enc {row['chacha_encrypt_us']:5.2f} dec "
                f"{row['chacha_decrypt_us']:5.2f} | AES-GCM enc {row['aesgcm_encrypt_us']:5.2f} "
                f"dec {row['aesgcm_decrypt_us']:5.2f} | FieldCipher enc "
                f"{row['fieldcipher_encrypt_us']:5.2f} dec {row['fieldcipher_decrypt_us']:5.2f} "
                f"| stored {int(row['stored_bytes'])} B"
            )
        print("\nSupporting mechanisms")
        sp = supporting()
        result["supporting"] = sp
        for key, value in sp.items():
            print(f"{key:<30} {value:10.3f}")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
