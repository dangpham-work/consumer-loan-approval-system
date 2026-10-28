"""Seam 2: mã hóa trường nhạy cảm ChaCha20-Poly1305 (SR06, ADR 0005) và blind index để tra cứu CCCD."""

import hashlib
import os

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from loan_system.security.crypto import DecryptionFailed, FieldCipher, blind_index

KEY = "khoa-du-lieu-chi-dung-trong-test-0123456789"


def legacy_aes_gcm(plaintext: str, context: str) -> bytes:
    """Bản mã định dạng 1 đúng như các bản ghi đã lưu trước ADR 0005."""
    nonce = os.urandom(12)
    key = hashlib.sha256(KEY.encode()).digest()
    return bytes([1]) + nonce + AESGCM(key).encrypt(nonce, plaintext.encode(), context.encode())


def test_new_values_use_the_chacha20_poly1305_format() -> None:
    sealed = FieldCipher(KEY).encrypt("079095001234", context="x")

    assert sealed[0] == 2
    # 1 byte định dạng + 12 byte nonce + 12 byte ciphertext (bằng bản rõ) + 16 byte tag
    assert len(sealed) == 1 + 12 + len("079095001234") + 16


def test_values_stored_as_aes_gcm_still_decrypt() -> None:
    sealed = legacy_aes_gcm("079095001234", "customers.national_id:1")

    assert FieldCipher(KEY).decrypt(sealed, context="customers.national_id:1") == "079095001234"


def test_legacy_value_with_wrong_context_is_rejected() -> None:
    sealed = legacy_aes_gcm("079095001234", "customers.national_id:1")

    with pytest.raises(DecryptionFailed):
        FieldCipher(KEY).decrypt(sealed, context="customers.national_id:2")


@pytest.mark.parametrize("forged_format", [0, 1, 3, 255])
def test_changing_the_format_byte_is_rejected(forged_format: int) -> None:
    cipher = FieldCipher(KEY)
    sealed = bytearray(cipher.encrypt("0123456789", context="x"))
    sealed[0] = forged_format

    with pytest.raises(DecryptionFailed):
        cipher.decrypt(bytes(sealed), context="x")


def test_empty_or_truncated_value_is_rejected() -> None:
    cipher = FieldCipher(KEY)
    for data in (b"", bytes([2]), cipher.encrypt("0123456789", context="x")[:13]):
        with pytest.raises(DecryptionFailed):
            cipher.decrypt(data, context="x")


def test_encrypted_value_round_trips_and_hides_the_plaintext() -> None:
    cipher = FieldCipher(KEY)

    sealed = cipher.encrypt("079095001234", context="customers.national_id:1")

    assert b"079095001234" not in sealed
    assert cipher.decrypt(sealed, context="customers.national_id:1") == "079095001234"


def test_same_plaintext_encrypts_differently_each_time() -> None:
    cipher = FieldCipher(KEY)
    assert cipher.encrypt("123", context="x") != cipher.encrypt("123", context="x")


def test_tampered_ciphertext_is_rejected() -> None:
    cipher = FieldCipher(KEY)
    sealed = bytearray(cipher.encrypt("0123456789", context="x"))
    sealed[-1] ^= 0x01

    with pytest.raises(DecryptionFailed):
        cipher.decrypt(bytes(sealed), context="x")


def test_ciphertext_copied_to_another_row_or_column_is_rejected() -> None:
    cipher = FieldCipher(KEY)
    sealed = cipher.encrypt("0123456789", context="loan_applications.receiving_account:A")

    with pytest.raises(DecryptionFailed):
        cipher.decrypt(sealed, context="loan_applications.receiving_account:B")


def test_wrong_key_cannot_decrypt() -> None:
    sealed = FieldCipher(KEY).encrypt("bi mat", context="x")
    with pytest.raises(DecryptionFailed):
        FieldCipher("mot-khoa-khac-hoan-toan-0123456789abcdef").decrypt(sealed, context="x")


def test_blind_index_is_stable_keyed_and_does_not_reveal_the_value() -> None:
    first = blind_index(KEY, "079095001234")

    assert first == blind_index(KEY, "079095001234")
    assert first != blind_index("khoa-khac-0123456789-0123456789", "079095001234")
    assert "079095001234" not in first
    assert len(first) == 64
