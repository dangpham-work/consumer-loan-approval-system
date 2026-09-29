"""Seam 2: mã hóa trường nhạy cảm AES-GCM (SR06) và blind index để tra cứu CCCD."""

import pytest

from loan_system.security.crypto import DecryptionFailed, FieldCipher, blind_index

KEY = "khoa-du-lieu-chi-dung-trong-test-0123456789"


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
