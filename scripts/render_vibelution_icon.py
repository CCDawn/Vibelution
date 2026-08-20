"""Rasterize the Vibelution mark into PNG/ICO sizes.

Taskbar frames (<=72px) use a filled V silhouette. Nested outline geometry is
kept for 256px ICO and the web PNGs, where the hole still has enough pixels.
"""

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
FILLED_MAX = 72


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


def _map_poly(poly: np.ndarray, size: int, inset: float) -> np.ndarray:
    usable = 1.0 - 2.0 * inset
    return poly / VIEW * (size * usable) + (size * inset)


def _coverage_mask(size: int, *, inset: float = 0.0, filled: bool) -> np.ndarray:
    aa = _supersample(size)
    sample = size * aa
    in_frame = np.ones((size, size), dtype=bool)
    if inset > 0:
        lo = int(np.floor(size * inset))
        hi = int(np.ceil(size * (1.0 - inset)))
        in_frame = np.zeros((size, size), dtype=bool)
        in_frame[lo:hi, lo:hi] = True
    if filled:
        poly = np.round(_map_poly(OUTER, size, inset) * 2.0) / 2.0
        coords = (np.arange(sample, dtype=np.float64) + 0.5) / aa
        xx, yy = np.meshgrid(coords, coords)
        mark = _evenodd(xx, yy, poly)
    else:
        coords = (np.arange(sample, dtype=np.float64) + 0.5) / sample
        usable = 1.0 - 2.0 * inset
        xs = (coords - inset) / usable * VIEW
        ys = (coords - inset) / usable * VIEW
        xx, yy = np.meshgrid(xs, ys)
        mark = _evenodd(xx, yy, OUTER) ^ _evenodd(xx, yy, HOLE) | _evenodd(xx, yy, INNER)
    coverage = mark.astype(np.float32).reshape(size, aa, size, aa).mean(axis=(1, 3))
    coverage = np.where(in_frame, coverage, 0.0)
    return np.clip(coverage, 0.0, 1.0)


def render_mark(size: int, *, background: tuple[int, int, int, int] | None = None, inset: float = 0.0) -> Image.Image:
    filled = size <= FILLED_MAX
    coverage = _coverage_mask(size, inset=inset, filled=filled)
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
