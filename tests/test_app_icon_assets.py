from pathlib import Path
from struct import unpack

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SVG = ROOT / "assets" / "icons" / "vibelution-icon.svg"
ICO = ROOT / "assets" / "icons" / "vibelution.ico"
PNG = ROOT / "web" / "public" / "vibelution-icon.png"
MASKABLE = ROOT / "web" / "public" / "vibelution-icon-maskable-512.png"


def _load_render_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "render_vibelution_icon",
        ROOT / "scripts" / "render_vibelution_icon.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def test_inner_v_is_clipped_to_hole_not_fully_inset() -> None:
    render = _load_render_module()
    text = SVG.read_text(encoding="utf-8")
    assert text.count("<path") == 2
    assert 'fill="#000"' in text
    assert "d8a75b" not in text.lower()
    assert "27.4 22.9" not in text
    assert "8.4 7.08" not in text
    assert "9.12 8.32" in text
    assert "24 27.16" in text

    grid = np.linspace(0.25, 47.75, 96)
    xx, yy = np.meshgrid(grid, grid)
    inner = render._evenodd(xx, yy, render.INNER)
    hole = render._evenodd(xx, yy, render.HOLE)
    assert inner.any()
    assert np.all(hole[inner])
    assert render._evenodd(np.array([[24.0]]), np.array([[31.0]]), render.INNER)[0, 0]
    assert not render._evenodd(np.array([[24.0]]), np.array([[20.44]]), render.INNER)[0, 0]


def _ico_png_frame(path: Path, size: int) -> Image.Image:
    from io import BytesIO

    data = path.read_bytes()
    _reserved, itype, count = unpack("<HHH", data[:6])
    assert itype == 1
    offset = 6
    for _ in range(count):
        width, height, _colors, _reserved2, _planes, _bitcount, nbytes, blob_off = unpack(
            "<BBBBHHII", data[offset : offset + 16]
        )
        width = width or 256
        height = height or 256
        if width == size and height == size:
            blob = data[blob_off : blob_off + nbytes]
            return Image.open(BytesIO(blob)).convert("RGBA")
        offset += 16
    raise AssertionError(f"missing {size}x{size} ICO frame")


def test_vibelution_ico_includes_taskbar_and_dpi_sizes() -> None:
    sizes = set(_ico_sizes(ICO))
    for edge in (16, 20, 24, 28, 30, 32, 36, 40, 48, 64, 72, 256):
        assert (edge, edge) in sizes


def test_taskbar_frames_keep_nested_outline() -> None:
    frame = _ico_png_frame(ICO, 24)
    assert frame.size == (24, 24)
    assert frame.getpixel((0, 0))[3] == 0
    # Left-arm counter of the outline V; a filled silhouette would be opaque here.
    assert frame.getpixel((4, 3))[3] < 40
    alphas = np.array(frame)[:, :, 3]
    assert int(np.unique(alphas).size) > 8
    assert int(((alphas > 8) & (alphas < 247)).sum()) > 20


def test_large_icon_keeps_nested_outline_counter() -> None:
    image = Image.open(PNG).convert("RGBA")
    assert image.getpixel((256, 405))[3] < 40
    large = _ico_png_frame(ICO, 256)
    assert large.getpixel((128, 203))[3] < 40


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
