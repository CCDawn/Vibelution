"""Product version helpers for Vibelution."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
VERSION_PATH = PROJECT_ROOT / "VERSION"
FALLBACK_VERSION = "0.0.0"


@lru_cache(maxsize=1)
def get_product_version() -> str:
    """Return the canonical product version from the repository VERSION file."""

    try:
        value = VERSION_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return FALLBACK_VERSION
    return value or FALLBACK_VERSION


__version__ = get_product_version()
