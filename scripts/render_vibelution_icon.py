"""Rasterize the clipped nested Vibelution mark into PNG/ICO sizes."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

VIEW = 48.0
OUTER = np.array(
    [(1.2, 2.8), (14.64, 2.8), (24.0, 22.48), (33.36, 2.8), (46.8, 2.8), (24.0, 47.8)],
    dtype=np.float64,
)
HOLE = np.array(
    [(5.04, 5.08), (24.0, 40.12), (42.96, 5.08), (34.92, 5.08), (24.0, 27.16), (13.08, 5.08)],
    dtype=np.float64,
)
INNER = np.array(
    [(9.12, 8.32), (14.68, 8.32), (24.0, 27.16), (33.32, 8.32), (38.88, 8.32), (24.0, 34.12)],
    dtype=np.float64,
)
# Exact matches for Windows/Electron DPI (100/125/150/200%) plus 72 for 300%.
ICO_SIZES = (16, 20, 24, 28, 30, 32, 36, 40, 48, 64, 72, 256)


def _evenodd(xx: np.ndarray, yy: np.ndarray, poly: np.ndarray) -> np.ndarray:
    inside = np.zeros(xx.shape, dtype=bool)
    x1 = poly[:, 0]
    y1 = poly[:, 1]
    x2 = np.roll(x1, -1)
    y2 = np.roll(y1, -1)
    for i in range(len(poly)):
        dy = y2[i] - y1[i]
        with np.errstate(divide="ignore", invalid="ignore"):
            xinters = (x2[i] - x1[i]) * (yy - y1[i]) / dy + x1[i]
        hit = ((y1[i] > yy) != (y2[i] > yy)) & (xx < xinters)
        inside ^= hit
    return inside


def _supersample(size: int) -> int:
    if size <= 72:
        return 8
    if size <= 256:
        return 4
    return 3


def _optical_divide(size: int) -> float:
    # Taskbar frames are ~24–40px; a 2px outline needs extra weight or diagonals stair-step.
    if size <= 16:
        return 0.68
    if size <= 24:
        return 0.74
    if size <= 36:
        return 0.80
    return 1.0


def render_mark(size: int, *, background: tuple[int, int, int, int] | None = None, inset: float = 0.0) -> Image.Image:
    aa = _supersample(size)
    sample = size * aa
    usable = 1.0 - 2.0 * inset
    coords = (np.arange(sample, dtype=np.float64) + 0.5) / sample
    xs = (coords - inset) / usable * VIEW
    ys = (coords - inset) / usable * VIEW
    xx, yy = np.meshgrid(xs, ys)
    in_frame = (coords >= inset) & (coords <= 1.0 - inset)
    in_x, in_y = np.meshgrid(in_frame, in_frame)
    mark = (_evenodd(xx, yy, OUTER) ^ _evenodd(xx, yy, HOLE) | _evenodd(xx, yy, INNER)) & in_x & in_y
    coverage = mark.astype(np.float32).reshape(size, aa, size, aa).mean(axis=(1, 3))
    coverage = np.clip(coverage / _optical_divide(size), 0.0, 1.0)
    alpha = np.clip(np.rint(coverage * 255.0), 0, 255).astype(np.uint8)
    alpha_img = Image.fromarray(alpha, mode="L")
    if background is None:
        canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        canvas.putalpha(alpha_img)
        return canvas
    canvas = Image.new("RGBA", (size, size), background)
    mark_img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    mark_img.putalpha(alpha_img)
    return Image.alpha_composite(canvas, mark_img)


def _save_ico(path: Path, images: list[Image.Image]) -> None:
    images[-1].save(
        path,
        format="ICO",
        append_images=images[:-1],
        sizes=[(size, size) for size in ICO_SIZES],
    )


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    icons = root / "assets" / "icons"
    public = root / "web" / "public"
    png_512 = render_mark(512)
    png_192 = render_mark(192)
    maskable = render_mark(512, background=(255, 255, 255, 255), inset=0.1)
    png_512.save(icons / "vibelution-icon.png", format="PNG")
    png_512.save(public / "vibelution-icon.png", format="PNG")
    png_512.save(public / "vibelution-icon-512.png", format="PNG")
    png_192.save(public / "vibelution-icon-192.png", format="PNG")
    maskable.save(public / "vibelution-icon-maskable-512.png", format="PNG")
    ico_images = [render_mark(size) for size in ICO_SIZES]
    _save_ico(icons / "vibelution.ico", ico_images)
    _save_ico(public / "favicon.ico", ico_images)


if __name__ == "__main__":
    main()
