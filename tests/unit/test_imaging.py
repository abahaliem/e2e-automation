from io import BytesIO

from PIL import Image

from qa_agent.imaging import annotate, highlight, solid_png, to_jpeg
from qa_agent.models import Element


def pixel(data, xy):
    return Image.open(BytesIO(data)).convert("RGB").getpixel(xy)


def test_solid_png():
    data = solid_png((255, 255, 255), (40, 30))
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert Image.open(BytesIO(data)).size == (40, 30)


def test_annotate_draws_box_and_keeps_size():
    base = solid_png((255, 255, 255), (200, 100))
    out = annotate(base, [Element(index=1, role="button", name="A", bbox=(50, 40, 60, 30)), Element(index=2, role="link", name="B", bbox=(0, 0, 0, 0))])
    assert Image.open(BytesIO(out)).size == (200, 100)
    assert pixel(out, (50, 55)) != (255, 255, 255)  # garis kiri kotak
    assert pixel(out, (80, 55)) == (255, 255, 255)  # isi kotak tetap


def test_highlight_red_border():
    out = highlight(solid_png((255, 255, 255), (100, 100)), (20, 20, 40, 40))
    r, g, b = pixel(out, (20, 40))
    assert r > 200 and g < 80 and b < 80


def test_to_jpeg_resizes_wide_images():
    out = to_jpeg(solid_png((0, 128, 0), (2000, 1000)))
    assert out[:3] == b"\xff\xd8\xff"
    assert Image.open(BytesIO(out)).size == (1280, 640)


def test_to_jpeg_keeps_small_images():
    assert Image.open(BytesIO(to_jpeg(solid_png((0, 0, 0), (300, 200))))).size == (300, 200)
