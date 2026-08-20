from pathlib import Path
from struct import unpack

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SVG = ROOT / "assets" / "icons" / "vibelution-icon.svg"
ICO = ROOT / "assets" / "icons" / "vibelution.ico"
PNG = ROOT / "web" / "public" / "vibelution-icon.png"
MASKABLE = ROOT / "web" / "public" / "vibelution-icon-maskable-512.png"


def _ico_sizes(path: Path) -> list[tuple[int, int]]:
    data = path.read_bytes()
    _reserved, itype, count = unpack("<HHH", data[:6])
    assert itype == 1
    sizes: list[tuple[int, int]] = []
    offset = 6
    for _ in range(count):
        width, height, _colors, _reserved2, _planes, _bitcount, _nbytes, _off = unpack(
            "<BBBBHHII", data[offset : offset + 16]
        )
        sizes.append((width or 256, height or 256))
        offset += 16
    return sizes


def test_nested_v_stays_inside_outline_counter() -> None:
    from shapely.geometry import Polygon

    hole = Polygon([(5.04, 5.08), (13.08, 5.08), (24.0, 27.16), (34.92, 5.08), (42.96, 5.08), (24.0, 40.12)])
    inner = Polygon([(8.4, 7.08), (11.84, 7.08), (24.0, 29.16), (36.16, 7.08), (39.6, 7.08), (24.0, 35.92)])
    assert hole.contains(inner)
    assert hole.exterior.distance(inner) >= 0.9
    text = SVG.read_text(encoding="utf-8")
    assert text.count("<path") == 2
    assert 'fill="#000"' in text
    assert "d8a75b" not in text.lower()
    assert "27.4 22.9" not in text


def test_vibelution_ico_includes_taskbar_and_large_sizes() -> None:
    sizes = set(_ico_sizes(ICO))
    assert (16, 16) in sizes
    assert (24, 24) in sizes
    assert (32, 32) in sizes
    assert (256, 256) in sizes


def test_icon_png_keeps_transparent_field_and_solid_mark() -> None:
    image = Image.open(PNG).convert("RGBA")
    assert image.size == (512, 512)
    assert image.getpixel((0, 0))[3] == 0
    assert image.getpixel((256, 352))[3] > 200
    assert image.getpixel((256, 352))[:3] == (0, 0, 0)


def test_maskable_icon_is_opaque_black_on_white() -> None:
    image = Image.open(MASKABLE).convert("RGBA")
    assert image.size == (512, 512)
    assert image.getpixel((0, 0))[:3] == (255, 255, 255)
    assert image.getpixel((0, 0))[3] == 255
    pixel = image.getpixel((256, 330))
    assert pixel[3] == 255
    assert pixel[0] < 20
    assert pixel[1] < 20
    assert pixel[2] < 20
