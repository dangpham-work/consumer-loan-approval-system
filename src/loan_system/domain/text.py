"""Định dạng văn bản dùng chung: số tiền kiểu Việt Nam, bỏ dấu cho phông chữ không đủ dấu."""

import unicodedata
from decimal import Decimal


def fold_diacritics(text: str) -> str:
    """Bỏ dấu tiếng Việt: "Nguyễn Văn Đức" -> "Nguyen Van Duc"."""
    folded = unicodedata.normalize("NFD", text.replace("đ", "d").replace("Đ", "D"))
    return "".join(c for c in folded if not unicodedata.combining(c))


def vnd(amount: Decimal) -> str:
    """25000000 -> 25.000.000 (cách viết số tiền của người Việt)."""
    return f"{amount:,.0f}".replace(",", ".")
