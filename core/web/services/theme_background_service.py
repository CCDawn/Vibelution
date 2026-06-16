"""Workbench theme background image storage helpers."""

from __future__ import annotations

import base64
import binascii
import re
import secrets
import time
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote

from config.public_config import CONFIG_PATH

from .runtime_scene_service import record_runtime_scene_event


THEME_BACKGROUND_DIR_NAME = "theme_backgrounds"
THEME_BACKGROUND_RELATIVE_DIR = PurePosixPath(THEME_BACKGROUND_DIR_NAME)
MAX_THEME_BACKGROUND_IMAGE_BYTES = 10 * 1024 * 1024
PROJECT_ROOT = Path(__file__).resolve().parents[3]
BUNDLED_THEME_BACKGROUND_DIR = PROJECT_ROOT / "assets" / THEME_BACKGROUND_DIR_NAME
DEFAULT_THEME_BACKGROUND_FILENAME = "default-graphite-command-center.png"
DEFAULT_THEME_BACKGROUND_PATH = str(THEME_BACKGROUND_RELATIVE_DIR / DEFAULT_THEME_BACKGROUND_FILENAME)
DEFAULT_THEME_BACKGROUNDS = (
    {
        "filename": DEFAULT_THEME_BACKGROUND_FILENAME,
        "label": {"zh": "石墨命令中心", "en": "Graphite Command Center"},
    },
    {
        "filename": "default-midnight-glass.png",
        "label": {"zh": "深夜玻璃厅", "en": "Midnight Glass"},
    },
    {
        "filename": "default-sunrise-research.png",
        "label": {"zh": "清晨研究室", "en": "Sunrise Research"},
    },
    {
        "filename": "default-glass-observatory.png",
        "label": {"zh": "玻璃观测站", "en": "Glass Observatory"},
    },
    {
        "filename": "default-sunlit-wink.png",
        "label": {"zh": "阳光眨眼", "en": "Sunlit Wink"},
    },
)
DEFAULT_THEME_BACKGROUND_FILENAMES = {str(item["filename"]) for item in DEFAULT_THEME_BACKGROUNDS}
_CONTENT_TYPE_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}


def _theme_background_dir() -> Path:
    return Path(CONFIG_PATH).expanduser().resolve().parent / THEME_BACKGROUND_DIR_NAME


def list_default_theme_background_options(lang: str) -> list[dict[str, str]]:
    language = "zh" if str(lang or "").lower().startswith("zh") else "en"
    options: list[dict[str, str]] = []
    for item in DEFAULT_THEME_BACKGROUNDS:
        filename = str(item["filename"])
        label_map = item["label"] if isinstance(item.get("label"), dict) else {}
        label = str(label_map.get(language) or label_map.get("en") or filename)
        options.append(
            {
                "value": str(THEME_BACKGROUND_RELATIVE_DIR / filename),
                "label": label,
            }
        )
    return options


def _record_theme_background_event(
    event_code: str,
    *,
    outcome: str,
    level: str = "info",
    fields: dict[str, Any] | None = None,
) -> None:
    try:
        record_runtime_scene_event(
            "config",
            "theme_background",
            event_code,
            message=event_code,
            level=level,
            outcome=outcome,
            fields=fields or {},
            lifecycle=True,
        )
    except Exception:
        return


def _theme_background_error(message: str, *, reason: str) -> ValueError:
    _record_theme_background_event(
        "config.theme_background.rejected",
        outcome="failed",
        level="warning",
        fields={"reason": reason},
    )
    return ValueError(message)


def _sanitize_stem(filename: str) -> str:
    raw_stem = Path(str(filename or "background")).stem.lower()
    stem = re.sub(r"[^a-z0-9_-]+", "-", raw_stem).strip("-_")
    return stem[:40] or "background"


def _decode_image_payload(data_base64: str) -> bytes:
    try:
        payload = base64.b64decode(str(data_base64 or ""), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise _theme_background_error("背景图片数据不是有效的 base64。", reason="invalid_base64") from exc
    if not payload:
        raise _theme_background_error("背景图片不能为空。", reason="empty_payload")
    if len(payload) > MAX_THEME_BACKGROUND_IMAGE_BYTES:
        raise _theme_background_error("背景图片不能超过 10MB。", reason="oversized")
    return payload


def _validate_image_signature(payload: bytes, content_type: str) -> None:
    if content_type == "image/png" and payload.startswith(b"\x89PNG\r\n\x1a\n"):
        return
    if content_type == "image/jpeg" and payload.startswith(b"\xff\xd8\xff"):
        return
    if content_type == "image/webp" and payload.startswith(b"RIFF") and payload[8:12] == b"WEBP":
        return
    raise _theme_background_error("背景图片格式与文件内容不匹配。", reason="signature_mismatch")


def theme_background_image_url(background_image_path: object) -> str:
    filename = theme_background_filename(background_image_path)
    if not filename:
        return ""
    return f"/api/config/theme-background-image/{quote(filename)}"


def theme_background_filename(background_image_path: object) -> str:
    value = str(background_image_path or "").strip().replace("\\", "/")
    if not value:
        return ""
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        return ""
    if path.parent != THEME_BACKGROUND_RELATIVE_DIR:
        return ""
    filename = path.name
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", filename):
        return ""
    if Path(filename).suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
        return ""
    return filename


def resolve_theme_background_file(filename: str) -> Path:
    safe_filename = theme_background_filename(str(THEME_BACKGROUND_RELATIVE_DIR / str(filename or "")))
    if not safe_filename:
        raise FileNotFoundError("invalid theme background image path")
    background_dir = _theme_background_dir().resolve()
    path = (background_dir / safe_filename).resolve()
    if background_dir != path.parent:
        raise FileNotFoundError("invalid theme background image path")
    if path.exists() and path.is_file():
        return path
    if safe_filename in DEFAULT_THEME_BACKGROUND_FILENAMES:
        bundled_dir = BUNDLED_THEME_BACKGROUND_DIR.resolve()
        bundled_path = (bundled_dir / safe_filename).resolve()
        if bundled_dir == bundled_path.parent and bundled_path.exists() and bundled_path.is_file():
            return bundled_path
    return path


def store_theme_background_image(*, filename: str, content_type: str, data_base64: str) -> dict[str, Any]:
    normalized_type = str(content_type or "").split(";")[0].strip().lower()
    extension = _CONTENT_TYPE_EXTENSIONS.get(normalized_type)
    if not extension:
        raise _theme_background_error("背景图片只支持 PNG、JPG 或 WebP 图片。", reason="unsupported_content_type")

    payload = _decode_image_payload(data_base64)
    _validate_image_signature(payload, normalized_type)

    _theme_background_dir().mkdir(parents=True, exist_ok=True)
    safe_stem = _sanitize_stem(filename)
    output_name = f"background-{int(time.time())}-{secrets.token_hex(4)}-{safe_stem}{extension}"
    output_path = resolve_theme_background_file(output_name)
    output_path.write_bytes(payload)
    relative_path = str(THEME_BACKGROUND_RELATIVE_DIR / output_name)
    _record_theme_background_event(
        "config.theme_background.uploaded",
        outcome="succeeded",
        fields={
            "contentType": normalized_type,
            "sizeBytes": len(payload),
            "extension": extension,
        },
    )
    return {
        "path": relative_path,
        "url": theme_background_image_url(relative_path),
        "contentType": normalized_type,
        "sizeBytes": len(payload),
    }
