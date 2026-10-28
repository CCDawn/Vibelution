"""Read the operator's selected images for the private assistant UI channel."""

from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path
import stat
from typing import Any

from config import public_config
from core.web.services import avatar_image_service as avatars
from core.web.services import theme_background_service as backgrounds


_CONTENT_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
_UNAVAILABLE = "operator_asset_unavailable"


def _path_identity(path: Path, *, missing_ok: bool = False) -> tuple:
    """Check lexical ancestors before the canonical owners resolve their paths."""
    if not path.is_absolute():
        raise ValueError(_UNAVAILABLE)
    identities = []
    for part in (*reversed(path.parents), path):
        try:
            info = part.lstat()
        except FileNotFoundError:
            if missing_ok:
                break
            raise
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError(_UNAVAILABLE)
        if part != path and not stat.S_ISDIR(info.st_mode):
            raise ValueError(_UNAVAILABLE)
        if part == path and not stat.S_ISDIR(info.st_mode):
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError(_UNAVAILABLE)
        identities.append((str(part), info.st_dev, info.st_ino))
    return tuple(identities)


def _table(source: dict[str, Any], key: str) -> dict[str, Any]:
    value = source.get(key, {})
    if not isinstance(value, dict):
        raise ValueError(_UNAVAILABLE)
    return value


def _selection(kind: str, config_path: Path) -> tuple[str, str]:
    before = _path_identity(config_path)
    raw = public_config.read_existing_config_snapshot(config_path)
    if before != _path_identity(config_path):
        raise ValueError(_UNAVAILABLE)
    if kind == "avatar":
        selected = _table(raw, "user_profile").get("avatar_image_path", "")
        readability = "standard"
    else:
        theme = _table(_table(raw, "ui"), "workbench_theme")
        # Same missing-key default and explicit-empty semantics as config bootstrap.
        selected = theme.get("background_image_path", backgrounds.DEFAULT_THEME_BACKGROUND_PATH)
        readability = theme.get("background_readability", "standard")
        if not isinstance(readability, str):
            raise ValueError(_UNAVAILABLE)
        readability = readability.strip().lower() or "standard"
        if readability not in {"soft", "standard", "strong"}:
            readability = "standard"
    if not isinstance(selected, str):
        raise ValueError(_UNAVAILABLE)
    return selected.strip().replace("\\", "/"), readability


def _owner_config(kind: str, config_path: Path) -> Path:
    owner = avatars if kind == "avatar" else backgrounds
    owner_config = Path(owner.CONFIG_PATH).expanduser().absolute()
    _path_identity(owner_config)
    if owner_config.resolve() != config_path:
        raise ValueError(_UNAVAILABLE)
    return owner_config


def _asset_path(kind: str, selection: str, config_path: Path) -> tuple[Path, int]:
    owner_config = _owner_config(kind, config_path)
    if kind == "avatar":
        filename = avatars.user_avatar_filename(selection)
        roots = [owner_config.parent / avatars.USER_AVATAR_DIR_NAME]
        # Preserve the owner's legacy fallback, without hiding linked ancestors.
        roots.append(avatars._legacy_user_avatar_dir())
        resolve = avatars.resolve_user_avatar_file
        limit = avatars.MAX_USER_AVATAR_IMAGE_BYTES
    else:
        filename = backgrounds.theme_background_filename(selection)
        roots = [owner_config.parent / backgrounds.THEME_BACKGROUND_DIR_NAME]
        if filename in backgrounds.DEFAULT_THEME_BACKGROUND_FILENAMES:
            roots.append(backgrounds.BUNDLED_THEME_BACKGROUND_DIR)
        resolve = backgrounds.resolve_theme_background_file
        limit = backgrounds.MAX_THEME_BACKGROUND_IMAGE_BYTES
    if not filename:
        raise ValueError(_UNAVAILABLE)
    for root in roots:
        _path_identity(root / filename, missing_ok=True)
    resolved = resolve(filename)
    if resolved not in [root.absolute() / filename for root in roots]:
        raise ValueError(_UNAVAILABLE)
    _path_identity(resolved)
    return resolved, limit


def _file_stamp(info: os.stat_result) -> tuple:
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError(_UNAVAILABLE)
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def operator_asset_revisions() -> dict[str, str | None]:
    """Return opaque change markers without reading or transferring image bytes."""
    result: dict[str, str | None] = {"avatar": None, "background": None}
    for kind in result:
        try:
            config_path = public_config.resolve_config_path()
            config_identity = _path_identity(config_path)
            _owner_config(kind, config_path)
            selection, readability = _selection(kind, config_path)
            stamp = None
            if selection:
                path, limit = _asset_path(kind, selection, config_path)
                chain = _path_identity(path)
                info = path.stat()
                stamp = _file_stamp(info)
                if not 0 < info.st_size <= limit or chain != _path_identity(path):
                    raise ValueError(_UNAVAILABLE)
                stamp = (*stamp, info.st_ctime_ns)
            if config_identity != _path_identity(config_path) or (selection, readability) != _selection(kind, config_path):
                raise ValueError(_UNAVAILABLE)
            value = repr((kind, selection, readability, stamp)).encode("utf-8")
            result[kind] = hashlib.sha256(value).hexdigest()
        except (OSError, ValueError, TypeError):
            pass
    return result


def _read_image(path: Path, limit: int) -> dict[str, str]:
    chain = _path_identity(path)
    before = path.stat()
    if not 0 < before.st_size <= limit:
        raise ValueError(_UNAVAILABLE)
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        payload = stream.read(limit + 1)
        finished = os.fstat(stream.fileno())
    after = path.stat()
    if (chain != _path_identity(path) or len(payload) != before.st_size or len(payload) > limit
            or not (_file_stamp(before) == _file_stamp(opened) == _file_stamp(finished) == _file_stamp(after))
            or before.st_ctime_ns != after.st_ctime_ns or opened.st_ctime_ns != finished.st_ctime_ns):
        raise ValueError(_UNAVAILABLE)
    content_type = _CONTENT_TYPES[path.suffix.lower()]
    valid = (
        content_type == "image/png" and payload.startswith(b"\x89PNG\r\n\x1a\n")
        or content_type == "image/jpeg" and payload.startswith(b"\xff\xd8\xff")
        or content_type == "image/webp" and payload.startswith(b"RIFF") and payload[8:12] == b"WEBP"
    )
    if not valid:
        raise ValueError(_UNAVAILABLE)
    return {"contentType": content_type, "dataBase64": base64.b64encode(payload).decode("ascii"),
            "sha256": hashlib.sha256(payload).hexdigest()}


def read_operator_asset(kind: str) -> dict[str, Any]:
    """Return only a bounded image projection; never initialize or write config."""
    try:
        if kind not in {"avatar", "background"}:
            raise ValueError(_UNAVAILABLE)
        config_path = public_config.resolve_config_path()
        config_root = _path_identity(config_path.parent)
        owner_config = _owner_config(kind, config_path)
        selection = _selection(kind, config_path)
        image = None
        if selection[0]:
            path, limit = _asset_path(kind, selection[0], config_path)
            image = _read_image(path, limit)
        if (selection != _selection(kind, config_path) or config_root != _path_identity(config_path.parent)
                or owner_config != _owner_config(kind, config_path)):
            raise ValueError(_UNAVAILABLE)
        return {"schemaVersion": 1, "kind": kind, "image": image, "readability": selection[1]}
    except Exception:
        # This channel must not disclose local paths, raw config or internal errors.
        raise ValueError(_UNAVAILABLE) from None
