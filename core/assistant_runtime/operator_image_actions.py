"""Closed operator image preferences; upload bytes stay on the private UI channel."""

from __future__ import annotations

import base64
import binascii
from contextlib import contextmanager
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from . import operator_assets as assets


class ImageKind(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["avatar", "background"]


class ImageOptions(ImageKind):
    offset: int = Field(default=0, ge=0, le=10000)
    limit: int = Field(default=6, ge=1, le=12)


class ImageSelect(ImageKind):
    path: str = Field(max_length=240)


_ACTIONS = {
    "operator_image_options": (ImageOptions, "分页读取当前 operator 可选头像图片或背景图片的逻辑路径，不返回图片内容。"),
    "operator_image_select": (ImageSelect, "选择当前 operator 已有头像或背景图片；path 空串清除自定义图片。使用预设头像前需要先清除自定义头像图片。"),
}
_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
_MAX_CANDIDATES = 1000


def contracts() -> dict:
    return {name: {"action": name, "description": description, "governed": False,
                   "parameters": model.model_json_schema()} for name, (model, description) in _ACTIONS.items()}


def _failure(code: str, *, unknown: bool = False) -> dict:
    return {"ok": False, "status": "unknown" if unknown else "not_applied", "verified": False, "error": code}


def _owner(kind: str):
    return assets.avatars if kind == "avatar" else assets.backgrounds


def _root(kind: str, config: Path) -> Path:
    name = assets.avatars.USER_AVATAR_DIR_NAME if kind == "avatar" else assets.backgrounds.THEME_BACKGROUND_DIR_NAME
    return config.parent / name


@contextmanager
def _import_directory_guard(config: Path, root: Path):
    """Pin the Windows destination namespace through import and config readback.

    Other platforms retain the existing static checks, without claiming the
    same rename protection. Ordinary canonical store calls do not take locks.
    """
    if os.name != "nt":
        yield
        return
    from core.web.services.personal_assistant_project.windows_read import lock_source_directory

    # Hold the existing parent before creating a missing resource directory.
    with lock_source_directory(config.parent, config.parent, allow_child_replacement=True):
        root.mkdir(exist_ok=True)
        with lock_source_directory(config.parent, root, allow_child_replacement=True):
            yield


def _context(kind: str) -> tuple[Path, dict]:
    config = assets.public_config.resolve_config_path()
    chain = assets._path_identity(config)
    assets._owner_config(kind, config)
    before = assets.public_config.read_existing_config_snapshot(config)
    if chain != assets._path_identity(config):
        raise ValueError("invalid config")
    return config, before


def _image_path(kind: str, selection: str, config: Path) -> tuple[Path, int]:
    owner = _owner(kind)
    filename = owner.user_avatar_filename(selection) if kind == "avatar" else owner.theme_background_filename(selection)
    if not filename or selection != str((owner.USER_AVATAR_RELATIVE_DIR if kind == "avatar" else owner.THEME_BACKGROUND_RELATIVE_DIR) / filename):
        raise ValueError("invalid selection")
    # Do not invoke the avatar owner's formal-workspace legacy fallback here.
    path = _root(kind, config) / filename
    assets._path_identity(path, missing_ok=True)
    if not path.exists() and kind == "background" and filename in owner.DEFAULT_THEME_BACKGROUND_FILENAMES:
        path = owner.BUNDLED_THEME_BACKGROUND_DIR / filename
    limit = owner.MAX_USER_AVATAR_IMAGE_BYTES if kind == "avatar" else owner.MAX_THEME_BACKGROUND_IMAGE_BYTES
    return path, limit


def _image(kind: str, selection: str, config: Path) -> dict:
    return assets._read_image(*_image_path(kind, selection, config))


def _candidate(kind: str, selection: str, config: Path) -> None:
    """Navigation snapshot only: bound each file read to its signature bytes.

    Pages are not frozen. Actual selection revalidates the entire current image.
    """
    path, limit = _image_path(kind, selection, config)
    chain = assets._path_identity(path)
    before = path.stat()
    if not 0 < before.st_size <= limit:
        raise ValueError("invalid size")
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        header = stream.read(12)
        finished = os.fstat(stream.fileno())
    after = path.stat()
    if (chain != assets._path_identity(path)
            or not (assets._file_stamp(before) == assets._file_stamp(opened)
                    == assets._file_stamp(finished) == assets._file_stamp(after))
            or before.st_ctime_ns != after.st_ctime_ns or opened.st_ctime_ns != finished.st_ctime_ns):
        raise ValueError("image changed")
    content_type = assets._CONTENT_TYPES[path.suffix.lower()]
    _owner(kind)._validate_image_signature(header, content_type)


def _selection(kind: str, selection: str, config: Path) -> str:
    if selection:
        _image(kind, selection, config)
    return selection


def _options(kind: str, config: Path) -> list[str]:
    owner = _owner(kind)
    root = _root(kind, config)
    assets._path_identity(root, missing_ok=True)
    prefix = owner.USER_AVATAR_RELATIVE_DIR if kind == "avatar" else owner.THEME_BACKGROUND_RELATIVE_DIR
    candidates = set()
    if root.exists():
        # Refuse an oversized directory instead of silently presenting an incomplete total.
        for index, item in enumerate(root.iterdir()):
            if index >= _MAX_CANDIDATES:
                raise ValueError("too many resources")
            candidates.add(str(prefix / item.name))
    if kind == "background":
        candidates.update(str(prefix / name) for name in owner.DEFAULT_THEME_BACKGROUND_FILENAMES)
    valid = []
    for candidate in sorted(candidates):
        try:
            _candidate(kind, candidate, config)
        except (ValueError, OSError, KeyError):
            continue
        valid.append(candidate)
    return valid


def _select(kind: str, selection: str, config: Path, before: dict) -> dict:
    """Apply a resource already validated by this module, then revalidate it."""
    from tools import pa_settings_actions

    result = pa_settings_actions._select_operator_image(kind, selection, config_path=config, before=before)
    if not result.get("ok"):
        code = result.get("error")
        return _failure("config_conflict" if code == "config_conflict" else "operator_image_write_failed",
                        unknown=code != "config_conflict")
    # A successful config write alone cannot prove the selected resource is still safe.
    config_after, after = _context(kind)
    if config_after != config:
        raise ValueError("config changed")
    table = ("user_profile", "avatar_image_path") if kind == "avatar" else ("ui", "workbench_theme", "background_image_path")
    if pa_settings_actions._at(after, table) != selection:
        raise ValueError("selection changed")
    _selection(kind, selection, config)
    return result


def execute(action: str, parameters: dict) -> dict:
    contract = _ACTIONS.get(action)
    if contract is None:
        return _failure("invalid_input")
    attempted = False
    try:
        args = contract[0].model_validate(parameters)
    except (ValidationError, TypeError, ValueError):
        return _failure("invalid_input")
    try:
        config, before = _context(args.kind)
        if action == "operator_image_options":
            options = _options(args.kind, config)
            end = args.offset + args.limit
            return {"ok": True, "kind": args.kind, "options": options[args.offset:end],
                    "total": len(options), "nextOffset": end if end < len(options) else None}
        _selection(args.kind, args.path, config)
        attempted = True
        return _select(args.kind, args.path, config, before)
    except Exception:
        return _failure("operator_image_unavailable", unknown=attempted)


def import_operator_image(kind: str, filename: str, content_type: str, data_base64: str) -> dict:
    """Private native upload only. Repeated imports may create another legal resource.

    A stored image survives config conflicts or unknown outcomes; no automatic retry.
    Neither the payload nor owner exceptions enter a model receipt or log.
    """
    stored = False
    try:
        if (not isinstance(kind, str) or kind not in {"avatar", "background"}
                or not isinstance(filename, str) or not 1 <= len(filename) <= 240
                or filename in {".", ".."} or any(c in filename for c in "/\\:")
                or any(ord(c) < 32 for c in filename)
                or not isinstance(content_type, str) or content_type not in _TYPES
                or not isinstance(data_base64, str)):
            return _failure("invalid_input")
        owner = _owner(kind)
        limit = owner.MAX_USER_AVATAR_IMAGE_BYTES if kind == "avatar" else owner.MAX_THEME_BACKGROUND_IMAGE_BYTES
        if not 0 < len(data_base64) <= 4 * ((limit + 2) // 3):
            return _failure("invalid_input")
        try:
            data = base64.b64decode(data_base64, validate=True)
        except (ValueError, binascii.Error):
            return _failure("invalid_input")
        if not 0 < len(data) <= limit:
            return _failure("invalid_input")
        # Validate before passing data into the owner (whose diagnostics record only fixed reasons).
        owner._validate_image_signature(data, content_type)
        config, before = _context(kind)
        root = _root(kind, config)
        assets._path_identity(root, missing_ok=True)
        store = owner.store_user_avatar_image if kind == "avatar" else owner.store_theme_background_image
        with _import_directory_guard(config, root):
            result = store(filename=filename, content_type=content_type, data_base64=data_base64)
            stored = True
            _selection(kind, result["path"], config)
            return _select(kind, result["path"], config, before)
    except Exception:
        return _failure("operator_image_import_failed", unknown=stored)
