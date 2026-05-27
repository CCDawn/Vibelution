"""User avatar image storage helpers for the web workbench."""

from __future__ import annotations

import base64
import binascii
import re
import secrets
import time
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote

from .runtime_scene_service import record_runtime_scene_event


PROJECT_ROOT = Path(__file__).resolve().parents[3]
USER_AVATAR_DIR = PROJECT_ROOT / "workspace" / "user_avatars"
USER_AVATAR_RELATIVE_DIR = PurePosixPath("workspace/user_avatars")
MAX_USER_AVATAR_IMAGE_BYTES = 5 * 1024 * 1024
_CONTENT_TYPE_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}


def _record_avatar_event(
    event_code: str,
    *,
    outcome: str,
    level: str = "info",
    fields: dict[str, Any] | None = None,
) -> None:
    try:
        record_runtime_scene_event(
            "config",
            "avatar_image",
            event_code,
            message=event_code,
            level=level,
            outcome=outcome,
            fields=fields or {},
            lifecycle=True,
        )
    except Exception:
        return


def _avatar_error(message: str, *, reason: str) -> ValueError:
    _record_avatar_event(
        "config.avatar_image.rejected",
        outcome="failed",
        level="warning",
        fields={"reason": reason},
    )
    return ValueError(message)


def _sanitize_stem(filename: str) -> str:
    raw_stem = Path(str(filename or "avatar")).stem.lower()
    stem = re.sub(r"[^a-z0-9_-]+", "-", raw_stem).strip("-_")
    return stem[:40] or "avatar"


def _decode_image_payload(data_base64: str) -> bytes:
    try:
        payload = base64.b64decode(str(data_base64 or ""), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise _avatar_error("头像图片数据不是有效的 base64。", reason="invalid_base64") from exc
    if not payload:
        raise _avatar_error("头像图片不能为空。", reason="empty_payload")
    if len(payload) > MAX_USER_AVATAR_IMAGE_BYTES:
        raise _avatar_error("头像图片不能超过 5MB。", reason="oversized")
    return payload


def _validate_image_signature(payload: bytes, content_type: str) -> None:
    if content_type == "image/png" and payload.startswith(b"\x89PNG\r\n\x1a\n"):
        return
    if content_type == "image/jpeg" and payload.startswith(b"\xff\xd8\xff"):
        return
    if content_type == "image/webp" and payload.startswith(b"RIFF") and payload[8:12] == b"WEBP":
        return
    raise _avatar_error("头像图片格式与文件内容不匹配。", reason="signature_mismatch")


def avatar_image_url(avatar_image_path: object) -> str:
    filename = user_avatar_filename(avatar_image_path)
    if not filename:
        return ""
    return f"/api/config/avatar-image/{quote(filename)}"


def user_avatar_filename(avatar_image_path: object) -> str:
    value = str(avatar_image_path or "").strip().replace("\\", "/")
    if not value:
        return ""
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        return ""
    if path.parent != USER_AVATAR_RELATIVE_DIR:
        return ""
    filename = path.name
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", filename):
        return ""
    if Path(filename).suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
        return ""
    return filename


def resolve_user_avatar_file(filename: str) -> Path:
    safe_filename = user_avatar_filename(str(USER_AVATAR_RELATIVE_DIR / str(filename or "")))
    if not safe_filename:
        raise FileNotFoundError("invalid avatar image path")
    avatar_dir = USER_AVATAR_DIR.resolve()
    path = (avatar_dir / safe_filename).resolve()
    if avatar_dir != path.parent:
        raise FileNotFoundError("invalid avatar image path")
    return path


def store_user_avatar_image(*, filename: str, content_type: str, data_base64: str) -> dict[str, Any]:
    normalized_type = str(content_type or "").split(";")[0].strip().lower()
    extension = _CONTENT_TYPE_EXTENSIONS.get(normalized_type)
    if not extension:
        raise _avatar_error("头像只支持 PNG、JPG 或 WebP 图片。", reason="unsupported_content_type")

    payload = _decode_image_payload(data_base64)
    _validate_image_signature(payload, normalized_type)

    USER_AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    safe_stem = _sanitize_stem(filename)
    output_name = f"avatar-{int(time.time())}-{secrets.token_hex(4)}-{safe_stem}{extension}"
    output_path = resolve_user_avatar_file(output_name)
    output_path.write_bytes(payload)
    relative_path = str(USER_AVATAR_RELATIVE_DIR / output_name)
    _record_avatar_event(
        "config.avatar_image.uploaded",
        outcome="succeeded",
        fields={
            "contentType": normalized_type,
            "sizeBytes": len(payload),
            "extension": extension,
        },
    )
    return {
        "path": relative_path,
        "url": avatar_image_url(relative_path),
        "contentType": normalized_type,
        "sizeBytes": len(payload),
    }
