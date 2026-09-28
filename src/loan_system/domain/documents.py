"""Quy tắc file giấy tờ của hồ sơ vay (UC13, SR10): chỉ JPEG, PNG, PDF, tối đa 5MB.

Kiểu file được xác định từ magic bytes chứ không tin phần mở rộng hay Content-Type trình duyệt gửi;
phần mở rộng vẫn phải khớp với nội dung thật.
"""

MAX_DOCUMENT_BYTES = 5 * 1024 * 1024

_SIGNATURES: dict[str, bytes] = {
    "image/jpeg": b"\xff\xd8\xff",
    "image/png": b"\x89PNG\r\n\x1a\n",
    "application/pdf": b"%PDF-",
}
_EXTENSIONS: dict[str, str] = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".pdf": "application/pdf",
}


class InvalidDocument(Exception):
    """File không hợp lệ; thông điệp an toàn để hiển thị cho người dùng."""


def check_document(filename: str, content: bytes) -> str:
    """Trả về kiểu MIME thật của file, hoặc ném InvalidDocument kèm lý do."""
    if not content:
        raise InvalidDocument("File rỗng.")
    if len(content) > MAX_DOCUMENT_BYTES:
        raise InvalidDocument("File vượt quá dung lượng cho phép (5MB).")
    dot = filename.rfind(".")
    claimed = _EXTENSIONS.get(filename[dot:].lower()) if dot >= 0 else None
    if claimed is None:
        raise InvalidDocument("Chỉ chấp nhận file JPG, PNG hoặc PDF.")
    actual = next((kind for kind, sig in _SIGNATURES.items() if content.startswith(sig)), None)
    if actual != claimed:
        raise InvalidDocument("Nội dung file không đúng định dạng JPG, PNG hoặc PDF.")
    return actual
