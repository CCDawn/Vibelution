"""Model-input image variant builder for session image attachments.

Claim scope: build the downscaled/re-encoded image payload handed to the LLM
from a stored session image artifact (longest edge <= 2000px, base64 payload
<= 5MiB, aligned with the ZCode LLM input budget), with an atomic sibling
cache beside the original artifact. Upload validation, artifact storage, UI
preview and journal paths are out of scope; original artifact bytes are never
modified.

Variants are always re-encoded as JPEG (alpha flattened onto white, EXIF
orientation applied and stripped), so the sibling cache name is deterministic
for a given strategy marker.

Fail-open contract: any decode/encode failure returns the original bytes with
the source content type, so a turn never fails because of preprocessing.
"""

from __future__ import annotations

import io
import os
import tempfile
from pathlib import Path
from typing import Any

from core.logging import debug as _debug_logger

# Bump when the policy below changes so stale sibling caches are never hit.
MODEL_VARIANT_STRATEGY = "model-v1"

MODEL_VARIANT_MAX_EDGE = 2000
MODEL_VARIANT_MAX_BASE64_BYTES = 5 * 1024 * 1024
MODEL_VARIANT_CONTENT_TYPE = "image/jpeg"

# Deterministic downscale ladder as (longest edge, JPEG quality). A rung is
# accepted once its base64 payload fits the budget; the last rung is the hard
# floor and is used even if it still exceeds the budget.
_MODEL_VARIANT_LADDER: tuple[tuple[int, int], ...] = (
    (2000, 90),
    (1600, 85),
    (1280, 80),
    (1024, 75),
    (800, 70),
)


def model_variant_cache_path(source_path: Path) -> Path:
    """Sibling cache path next to the original artifact (original untouched)."""
    source_name = Path(source_path).name
    return Path(source_path).with_name(f"{Path(source_name).stem}.{MODEL_VARIANT_STRATEGY}.jpg")


def build_model_image_variant(
    source_path: Path,
    original_payload: bytes,
    *,
    source_content_type: str = "image/png",
) -> dict[str, Any]:
    """Return the model-input bytes for a stored image artifact.

    Returns {"payload", "contentType", "downscaled", "cacheHit"}. Never
    raises: on any failure the original bytes pass through unchanged.
    """
    original_payload = bytes(original_payload or b"")
    normalized_content_type = str(source_content_type or "image/png").strip() or "image/png"
    passthrough: dict[str, Any] = {
        "payload": original_payload,
        "contentType": normalized_content_type,
        "downscaled": False,
        "cacheHit": False,
    }
    try:
        from PIL import Image  # noqa: F401  (imported for the probe below)

        with Image.open(io.BytesIO(original_payload)) as probe:
            source_width, source_height = probe.size
        needs_transform = (
            max(source_width, source_height) > MODEL_VARIANT_MAX_EDGE
            or _base64_encoded_size(len(original_payload)) > MODEL_VARIANT_MAX_BASE64_BYTES
        )
        if not needs_transform:
            return passthrough

        cache_path = model_variant_cache_path(source_path)
        cached = _read_variant_cache(cache_path)
        if cached is not None:
            return {
                "payload": cached,
                "contentType": MODEL_VARIANT_CONTENT_TYPE,
                "downscaled": True,
                "cacheHit": True,
            }
        variant_payload, (variant_width, variant_height) = _render_model_variant(original_payload)
        _write_variant_cache_atomic(cache_path, variant_payload)
        _debug_logger.info(
            "image model variant built: "
            f"source={Path(source_path).name} {source_width}x{source_height} {len(original_payload)}B "
            f"-> {variant_width}x{variant_height} {len(variant_payload)}B strategy={MODEL_VARIANT_STRATEGY}",
            tag="LOGS",
        )
        return {
            "payload": variant_payload,
            "contentType": MODEL_VARIANT_CONTENT_TYPE,
            "downscaled": True,
            "cacheHit": False,
        }
    except Exception as exc:
        _debug_logger.warning(
            "image model variant failed, passing original bytes through: "
            f"source={Path(source_path).name} {type(exc).__name__}: {exc}",
            tag="LOGS",
        )
        return passthrough


def _base64_encoded_size(byte_count: int) -> int:
    return 4 * ((byte_count + 2) // 3)


def _fit_size(size: tuple[int, int], max_edge: int) -> tuple[int, int]:
    width, height = int(size[0]), int(size[1])
    longest = max(width, height)
    if longest <= 0 or longest <= max_edge:
        return width, height
    scale = max_edge / longest
    return max(1, round(width * scale)), max(1, round(height * scale))


def _render_model_variant(payload: bytes) -> tuple[bytes, tuple[int, int]]:
    from PIL import Image, ImageOps

    with Image.open(io.BytesIO(payload)) as source:
        source.load()
        frame = ImageOps.exif_transpose(source)
        if frame.mode == "P":
            frame = frame.convert("RGBA")
        encoded: bytes | None = None
        final_size = (int(frame.size[0]), int(frame.size[1]))
        for max_edge, quality in _MODEL_VARIANT_LADDER:
            if max(frame.size) > max_edge:
                frame = frame.resize(_fit_size(frame.size, max_edge), Image.Resampling.LANCZOS)
            final_size = (int(frame.size[0]), int(frame.size[1]))
            encoded = _encode_jpeg(frame, quality)
            if encoded is not None and _base64_encoded_size(len(encoded)) <= MODEL_VARIANT_MAX_BASE64_BYTES:
                return encoded, final_size
        if encoded is None:
            raise ValueError("image model variant produced no payload")
        return encoded, final_size


def _encode_jpeg(frame: Any, quality: int) -> bytes | None:
    import io

    try:
        if frame.mode not in ("RGB", "L"):
            frame = _flatten_for_jpeg(frame)
        buffer = io.BytesIO()
        frame.save(buffer, format="JPEG", quality=quality)
        return buffer.getvalue()
    except Exception:
        return None


def _flatten_for_jpeg(frame: Any) -> Any:
    from PIL import Image

    if frame.mode in ("RGBA", "LA"):
        rgba = frame.convert("RGBA")
        flattened = Image.new("RGB", rgba.size, (255, 255, 255))
        flattened.paste(rgba, mask=rgba.getchannel("A"))
        return flattened
    return frame.convert("RGB")


def _read_variant_cache(cache_path: Path) -> bytes | None:
    try:
        cached = cache_path.read_bytes()
    except OSError:
        return None
    if not cached or not cached.startswith(b"\xff\xd8\xff"):
        return None
    return cached


def _write_variant_cache_atomic(cache_path: Path, payload: bytes) -> bool:
    """Write the sibling cache via temp file + rename; concurrent-safe."""
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        handle_fd, temporary_name = tempfile.mkstemp(
            dir=str(cache_path.parent),
            prefix=f"{cache_path.name}.",
            suffix=".tmp",
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(handle_fd, "wb") as handle:
                handle.write(payload)
            os.replace(temporary_path, cache_path)
        except BaseException:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise
        return True
    except OSError as exc:
        _debug_logger.warning(
            f"image model variant cache write skipped: {cache_path.name} {type(exc).__name__}: {exc}",
            tag="LOGS",
        )
        return False
