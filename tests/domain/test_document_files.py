"""Seam 2: kiểm tra file giấy tờ tải lên theo phần mở rộng và magic bytes (UC13, SR10)."""

import pytest

from loan_system.domain.documents import MAX_DOCUMENT_BYTES, InvalidDocument, check_document

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 100
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
PDF = b"%PDF-1.7\n" + b"\x00" * 100


@pytest.mark.parametrize(
    ("filename", "content", "media_type"),
    [
        ("cccd.jpg", JPEG, "image/jpeg"),
        ("CCCD.JPEG", JPEG, "image/jpeg"),
        ("sao-ke.png", PNG, "image/png"),
        ("luong.pdf", PDF, "application/pdf"),
    ],
)
def test_accepted_files_report_their_real_media_type(
    filename: str, content: bytes, media_type: str
) -> None:
    assert check_document(filename, content) == media_type


def test_executable_renamed_to_jpg_is_rejected() -> None:
    with pytest.raises(InvalidDocument):
        check_document("cccd.jpg", b"MZ\x90\x00" + b"\x00" * 100)


def test_extension_must_match_the_content() -> None:
    with pytest.raises(InvalidDocument):
        check_document("cccd.pdf", JPEG)


def test_unsupported_extension_is_rejected() -> None:
    with pytest.raises(InvalidDocument):
        check_document("script.html", b"<html>")


def test_file_of_exactly_5mb_is_accepted_but_one_byte_more_is_not() -> None:
    padding = MAX_DOCUMENT_BYTES - len(PDF)
    assert check_document("a.pdf", PDF + b"\x00" * padding) == "application/pdf"
    with pytest.raises(InvalidDocument):
        check_document("a.pdf", PDF + b"\x00" * (padding + 1))


def test_empty_file_is_rejected() -> None:
    with pytest.raises(InvalidDocument):
        check_document("a.pdf", b"")
