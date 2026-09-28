"""Watermark tên người xem trên giấy tờ (M06, MUC06): ảnh chụp màn hình bị lộ vẫn truy được người xem.

Chữ được in chéo lặp lại khắp ảnh và bỏ dấu tiếng Việt, vì phông chữ mặc định của Pillow không có
đủ dấu. Ảnh được mã hóa lại nên siêu dữ liệu (EXIF) của file gốc cũng bị bỏ.
"""

import io
import unicodedata
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError

_FORMATS = {"image/jpeg": "JPEG", "image/png": "PNG"}


def watermark_text(username: str, full_name: str, viewed_at: datetime) -> str:
    folded = unicodedata.normalize("NFD", full_name.replace("đ", "d").replace("Đ", "D"))
    name = "".join(c for c in folded if not unicodedata.combining(c))
    return f"{username} - {name} - {viewed_at:%Y-%m-%d %H:%M} UTC"


def stamp_image(content: bytes, content_type: str, text: str) -> bytes | None:
    """Ảnh đã in watermark, hoặc None nếu không đọc được ảnh (khi đó không được trả file gốc)."""
    try:
        with Image.open(io.BytesIO(content)) as source:
            image = source.convert("RGBA")
    except (UnidentifiedImageError, OSError):
        return None
    size = max(14, min(image.size) // 25)
    font = ImageFont.load_default(size=size)
    tile = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(tile)
    step_x, step_y = size * len(text) // 2 + size * 4, size * 5
    for y in range(-image.height, image.height * 2, step_y):
        for x in range(-image.width, image.width * 2, step_x):
            draw.text((x + (y // step_y % 2) * step_x // 2, y), text, font=font,
                      fill=(200, 0, 0, 90))
    overlay = tile.rotate(30, center=(image.width / 2, image.height / 2))
    stamped = Image.alpha_composite(image, overlay)
    output = io.BytesIO()
    fmt = _FORMATS[content_type]
    (stamped.convert("RGB") if fmt == "JPEG" else stamped).save(output, format=fmt)
    return output.getvalue()
