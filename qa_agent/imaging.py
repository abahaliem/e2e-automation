from __future__ import annotations

from io import BytesIO
from typing import Sequence

from PIL import Image, ImageDraw, ImageFont

from qa_agent.models import Element

_COLORS = ["#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4", "#0f8a9d", "#c2185b", "#9a6324"]


def _open(data: bytes) -> Image.Image:
    return Image.open(BytesIO(data)).convert("RGB")


def _png(img: Image.Image) -> bytes:
    buf = BytesIO()
    img.save(buf, "PNG", compress_level=1)  # cepat di laptop lemah; file sedikit lebih besar
    return buf.getvalue()


def solid_png(color: tuple[int, int, int], size: tuple[int, int]) -> bytes:
    return _png(Image.new("RGB", size, color))


def annotate(png: bytes, elements: list[Element]) -> bytes:
    """Gambar kotak bernomor (Set-of-Mark) di setiap elemen, khusus untuk AI."""
    img = _open(png)
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()
    for el in elements:
        x, y, w, h = el.bbox
        if w <= 0 or h <= 0:
            continue
        color = _COLORS[el.index % len(_COLORS)]
        draw.rectangle([x, y, x + w, y + h], outline=color, width=2)
        label = str(el.index)
        _, _, tw, th = draw.textbbox((0, 0), label, font=font)
        ly = max(0, y - th - 4)
        draw.rectangle([x, ly, x + tw + 4, ly + th + 4], fill=color)
        draw.text((x + 2, ly + 2), label, fill="white", font=font)
    return _png(img)


def highlight(png: bytes, bbox: Sequence[float]) -> bytes:
    """Kotak merah di elemen yang diklik/diisi, untuk evidence."""
    img = _open(png)
    x, y, w, h = bbox
    if w > 0 and h > 0:
        ImageDraw.Draw(img).rectangle([x - 2, y - 2, x + w + 2, y + h + 2], outline=(220, 20, 20), width=3)
    return _png(img)


def to_jpeg(data: bytes, max_width: int = 1280, quality: int = 70) -> bytes:
    img = _open(data)
    if img.width > max_width:
        img = img.resize((max_width, round(img.height * max_width / img.width)))
    buf = BytesIO()
    img.save(buf, "JPEG", quality=quality, optimize=True)
    return buf.getvalue()
