"""Cài đặt ChaCha20-Poly1305 (RFC 8439) bằng Python thuần, chỉ để minh họa cho báo cáo (mục 2.2).

KHÔNG dùng trong hệ thống: hệ thống dùng `cryptography` (OpenSSL, thời gian hằng, có SIMD) qua
`loan_system.security.crypto.FieldCipher`. Script này in trạng thái trung gian của hàm khối ChaCha20
và của Poly1305, kiểm tra với vector thử của RFC 8439, đối chiếu với thư viện `cryptography` và giải mã
một bản mã do chính FieldCipher của hệ thống sinh ra.

Chạy: uv run python docs/bao-cao-atbmhttt/scripts/chacha20_minh_hoa.py
"""

import os
import struct

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

from loan_system.security.crypto import (
    _CHACHA20_KEY_INFO,
    CURRENT_FORMAT,
    FieldCipher,
    _derive_key,
)

MASK32 = 0xFFFFFFFF
# "expand 32-byte k" đọc thành 4 từ little-endian
CONSTANTS = (0x61707865, 0x3320646E, 0x79622D32, 0x6B206574)


def rotl32(x: int, n: int) -> int:
    return ((x << n) | (x >> (32 - n))) & MASK32


def quarter_round(s: list[int], a: int, b: int, c: int, d: int) -> None:
    """RFC 8439 mục 2.1: chỉ gồm cộng mod 2^32, XOR và xoay bit (ARX)."""
    s[a] = (s[a] + s[b]) & MASK32; s[d] = rotl32(s[d] ^ s[a], 16)
    s[c] = (s[c] + s[d]) & MASK32; s[b] = rotl32(s[b] ^ s[c], 12)
    s[a] = (s[a] + s[b]) & MASK32; s[d] = rotl32(s[d] ^ s[a], 8)
    s[c] = (s[c] + s[d]) & MASK32; s[b] = rotl32(s[b] ^ s[c], 7)


def initial_state(key: bytes, counter: int, nonce: bytes) -> list[int]:
    """Ma trận 4x4 từ 32 bit: hằng số | khóa 256 bit | bộ đếm 32 bit | nonce 96 bit."""
    return [
        *CONSTANTS,
        *struct.unpack("<8I", key),
        counter & MASK32,
        *struct.unpack("<3I", nonce),
    ]


def chacha20_block(
    key: bytes, counter: int, nonce: bytes, trace: dict[str, list[int]] | None = None
) -> bytes:
    """RFC 8439 mục 2.3: 10 vòng kép (vòng cột + vòng chéo) = 20 vòng, rồi cộng lại trạng thái đầu."""
    state = initial_state(key, counter, nonce)
    working = state[:]
    for _ in range(10):
        quarter_round(working, 0, 4, 8, 12)  # 4 cột
        quarter_round(working, 1, 5, 9, 13)
        quarter_round(working, 2, 6, 10, 14)
        quarter_round(working, 3, 7, 11, 15)
        quarter_round(working, 0, 5, 10, 15)  # 4 đường chéo
        quarter_round(working, 1, 6, 11, 12)
        quarter_round(working, 2, 7, 8, 13)
        quarter_round(working, 3, 4, 9, 14)
    output = [(w + s) & MASK32 for w, s in zip(working, state)]
    if trace is not None:
        trace.update(initial=state, after_rounds=working, output=output)
    return struct.pack("<16I", *output)


def chacha20_xor(key: bytes, counter: int, nonce: bytes, data: bytes) -> bytes:
    """RFC 8439 mục 2.4: XOR với dòng khóa; mã hóa và giải mã là cùng một phép."""
    out = bytearray()
    for i in range(0, len(data), 64):
        keystream = chacha20_block(key, counter + i // 64, nonce)
        out += bytes(x ^ y for x, y in zip(data[i : i + 64], keystream))
    return bytes(out)


P1305 = (1 << 130) - 5


def poly1305_mac(key: bytes, message: bytes, trace: list[tuple[int, int]] | None = None) -> bytes:
    """RFC 8439 mục 2.5: đánh giá đa thức theo r trên trường mod 2^130 - 5, cộng s."""
    r = int.from_bytes(key[:16], "little") & 0x0FFFFFFC0FFFFFFC0FFFFFFC0FFFFFFF  # "kẹp" r
    s = int.from_bytes(key[16:], "little")
    acc = 0
    for i in range(0, len(message), 16):
        n = int.from_bytes(message[i : i + 16] + b"\x01", "little")
        acc = (acc + n) * r % P1305
        if trace is not None:
            trace.append((n, acc))
    return ((acc + s) & ((1 << 128) - 1)).to_bytes(16, "little")


def _pad16(data: bytes) -> bytes:
    return b"\x00" * (-len(data) % 16)


def _mac_data(aad: bytes, ciphertext: bytes) -> bytes:
    return (
        aad + _pad16(aad) + ciphertext + _pad16(ciphertext)
        + struct.pack("<Q", len(aad)) + struct.pack("<Q", len(ciphertext))
    )


def aead_encrypt(key: bytes, nonce: bytes, plaintext: bytes, aad: bytes) -> bytes:
    """RFC 8439 mục 2.8. Trả về ciphertext ‖ tag, cùng định dạng ChaCha20Poly1305.encrypt."""
    otk = chacha20_block(key, 0, nonce)[:32]  # khóa Poly1305 dùng một lần, từ khối đếm 0
    ciphertext = chacha20_xor(key, 1, nonce, plaintext)  # dữ liệu bắt đầu từ khối đếm 1
    return ciphertext + poly1305_mac(otk, _mac_data(aad, ciphertext))


class InvalidTagError(Exception):
    pass


def aead_decrypt(key: bytes, nonce: bytes, sealed: bytes, aad: bytes) -> bytes:
    """Tính lại tag và so sánh TRƯỚC khi giải mã; sai thì không trả ra byte bản rõ nào."""
    ciphertext, tag = sealed[:-16], sealed[-16:]
    otk = chacha20_block(key, 0, nonce)[:32]
    expected = poly1305_mac(otk, _mac_data(aad, ciphertext))
    diff = 0
    for x, y in zip(expected, tag):  # không dừng sớm ở byte sai đầu tiên
        diff |= x ^ y
    if diff or len(tag) != 16:
        raise InvalidTagError
    return chacha20_xor(key, 1, nonce, ciphertext)


# --- Chạy minh họa ----------------------------------------------------------------------------------

SUNSCREEN = (
    b"Ladies and Gentlemen of the class of '99: If I could offer you only one tip for the "
    b"future, sunscreen would be it."
)


def _matrix(words: list[int]) -> str:
    return "\n".join("    " + " ".join(f"{w:08x}" for w in words[r * 4 : r * 4 + 4]) for r in range(4))


def _check(label: str, actual: bytes, expected_hex: str) -> None:
    ok = actual == bytes.fromhex(expected_hex)
    print(f"[{'PASS' if ok else 'FAIL'}] {label}: {actual.hex()}")
    if not ok:
        raise SystemExit(f"expected {expected_hex}")


def main() -> None:
    print("== 1. Quarter round, RFC 8439 section 2.1.1 ==")
    s = [0] * 16
    s[0:4] = [0x11111111, 0x01020304, 0x9B8D6F43, 0x01234567]
    quarter_round(s, 0, 1, 2, 3)
    print("in : a=11111111 b=01020304 c=9b8d6f43 d=01234567")
    print(f"out: a={s[0]:08x} b={s[1]:08x} c={s[2]:08x} d={s[3]:08x}")
    _check("quarter round", struct.pack(">4I", *s[:4]), "ea2a92f4cb1cf8ce4581472e5881c4bb")

    print("\n== 2. Block function, RFC 8439 section 2.3.2 ==")
    key = bytes(range(32))
    nonce = bytes.fromhex("000000090000004a00000000")
    trace: dict[str, list[int]] = {}
    block = chacha20_block(key, 1, nonce, trace)
    print("initial state (constants | key | counter | nonce):")
    print(_matrix(trace["initial"]))
    print("after 20 rounds:")
    print(_matrix(trace["after_rounds"]))
    print("output = after 20 rounds + initial state:")
    print(_matrix(trace["output"]))
    _check(
        "serialized block",
        block,
        "10f1e7e4d13b5915500fdd1fa32071c4c7d1f4c733c068030422aa9ac3d46c4e"
        "d2826446079faa0914c2d705d98b02a2b5129cd1de164eb9cbd083e8a2503c4e",
    )

    print("\n== 3. Encryption, RFC 8439 section 2.4.2 ==")
    nonce = bytes.fromhex("000000000000004a00000000")
    ciphertext = chacha20_xor(key, 1, nonce, SUNSCREEN)
    _check("first 16 bytes of ciphertext", ciphertext[:16], "6e2e359a2568f98041ba0728dd0d6981")
    library = Cipher(algorithms.ChaCha20(key, struct.pack("<I", 1) + nonce), mode=None).encryptor()
    assert ciphertext == library.update(SUNSCREEN)
    assert chacha20_xor(key, 1, nonce, ciphertext) == SUNSCREEN
    print(f"[PASS] all {len(SUNSCREEN)} bytes equal cryptography's ChaCha20; decrypt(encrypt(m)) == m")

    print("\n== 4. Poly1305, RFC 8439 section 2.5.2 ==")
    mac_key = bytes.fromhex("85d6be7857556d337f4452fe42d506a80103808afb0db2fd4abff6af4149f51b")
    steps: list[tuple[int, int]] = []
    tag = poly1305_mac(mac_key, b"Cryptographic Forum Research Group", steps)
    r = int.from_bytes(mac_key[:16], "little") & 0x0FFFFFFC0FFFFFFC0FFFFFFC0FFFFFFF
    print(f"r (clamped) = {r:032x}")
    print(f"s           = {int.from_bytes(mac_key[16:], 'little'):032x}")
    for i, (n, acc) in enumerate(steps, 1):
        print(f"block {i}: n = {n:033x}  acc = {acc:033x}")
    _check("Poly1305 tag", tag, "a8061dc1305136c6c22b8baf0c0127a9")

    print("\n== 5. AEAD ChaCha20-Poly1305, RFC 8439 section 2.8.2 ==")
    key = bytes(range(0x80, 0xA0))
    nonce = bytes.fromhex("070000004041424344454647")
    aad = bytes.fromhex("50515253c0c1c2c3c4c5c6c7")
    sealed = aead_encrypt(key, nonce, SUNSCREEN, aad)
    _check("first 16 bytes of ciphertext", sealed[:16], "d31a8d34648e60db7b86afbc53ef7ec2")
    _check("tag", sealed[-16:], "1ae10b594f09e26a7e902ecbd0600691")
    assert sealed == ChaCha20Poly1305(key).encrypt(nonce, SUNSCREEN, aad)
    print("[PASS] identical to cryptography.ChaCha20Poly1305")

    print("\n== 6. Own AEAD vs cryptography on random inputs ==")
    for n in range(50):
        k, iv = os.urandom(32), os.urandom(12)
        msg, ad = os.urandom(n * 13), os.urandom(n % 7 * 5)
        ours = aead_encrypt(k, iv, msg, ad)
        assert ours == ChaCha20Poly1305(k).encrypt(iv, msg, ad)
        assert aead_decrypt(k, iv, ours, ad) == msg
    print("[PASS] 50/50 random cases identical to cryptography.ChaCha20Poly1305")

    print("\n== 7. A value encrypted by the system's FieldCipher, opened by this code ==")
    secret = "demo-only-data-enc-key-0123456789abcdef"
    context = "customers.national_id:3f2b0c4e11114222833394445555666"
    stored = FieldCipher(secret).encrypt("079095001234", context=context)
    fmt, iv, body = stored[0], stored[1:13], stored[13:]
    print(f"stored ({len(stored)} bytes): {stored.hex()}")
    print(f"  format={fmt:02x} nonce={iv.hex()} ciphertext={body[:-16].hex()} tag={body[-16:].hex()}")
    field_key = _derive_key(secret, _CHACHA20_KEY_INFO)
    ad = bytes([CURRENT_FORMAT]) + context.encode()
    print(f"[PASS] decrypted: {aead_decrypt(field_key, iv, body, ad).decode()}")
    tampered = bytearray(body)
    tampered[0] ^= 0x01
    for label, data, other_ad in (
        ("flip 1 bit of ciphertext", bytes(tampered), ad),
        ("copy to another customer", body, bytes([CURRENT_FORMAT]) + b"customers.national_id:x"),
    ):
        try:
            aead_decrypt(field_key, iv, data, other_ad)
            raise SystemExit(f"[FAIL] {label}: accepted")
        except InvalidTagError:
            print(f"[PASS] {label}: rejected, tag mismatch")


if __name__ == "__main__":
    main()
