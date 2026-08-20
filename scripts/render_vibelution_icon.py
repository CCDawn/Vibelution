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
ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 256)


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


def render_mark(size: int, *, background: tuple[int, int, int, int] | None = None, inset: float = 0.0) -> Image.Image:
    aa = 3 if size <= 48 else 2
    sample = size * aa
    coords = (np.arange(sample, dtype=np.float64) + 0.5) / sample
    usable = 1.0 - 2.0 * inset
    xs = (coords - inset) / usable * VIEW
    ys = (coords - inset) / usable * VIEW
    xx, yy = np.meshgrid(xs, ys)
    in_frame = (coords >= inset) & (coords <= 1.0 - inset)
    in_x, in_y = np.meshgrid(in_frame, in_frame)
    mark = (_evenodd(xx, yy, OUTER) ^ _evenodd(xx, yy, HOLE) | _evenodd(xx, yy, INNER)) & in_x & in_y
    alpha = (mark.astype(np.uint8) * 255).reshape(sample, sample)
    alpha_img = Image.fromarray(alpha, mode="L").resize((size, size), Image.Resampling.LANCZOS)
    if background is None:
        canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    else:
        canvas = Image.new("RGBA", (size, size), background)
    canvas.paste(Image.new("RGBA", (size, size), (0, 0, 0, 255)), mask=alpha_img)
    return canvas


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
    ico_images[-1].save(
        icons / "vibelution.ico",
        format="ICO",
        append_images=ico_images[:-1],
        sizes=[(size, size) for size in ICO_SIZES],
    )
    ico_images[-1].save(
        public / "favicon.ico",
        format="ICO",
        append_images=ico_images[:-1],
        sizes=[(size, size) for size in ICO_SIZES],
    )


if __name__ == "__main__":
    main()
