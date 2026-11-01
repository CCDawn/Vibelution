"""Bound assistant avatar projection through the native Agent directory owner."""

from __future__ import annotations

import hashlib
from pathlib import Path

from config import public_config
from core.web.services import agent_directory_service as directory

from . import operator_assets as assets

_UNAVAILABLE = "assistant_avatar_unavailable"


def _bundled_root() -> Path:
    # The Launcher profile is the native data root, not the shipped code root.
    return Path(__file__).resolve().parents[2]


def _config_path() -> Path:
    path = public_config.resolve_config_path()
    assets._path_identity(path)
    owner = Path(directory.CONFIG_PATH).expanduser().absolute()
    assets._path_identity(owner)
    if owner.resolve() != path.resolve():
        raise ValueError(_UNAVAILABLE)
    return path


def _selection(agent: dict) -> tuple[str, Path | None, int]:
    metadata = agent.get("metadata") or {}
    if not isinstance(metadata, dict):
        raise TypeError(_UNAVAILABLE)
    raw = next((metadata.get(key) for key in ("avatarImagePath", "agentAvatarImagePath", "avatarPath")
                if metadata.get(key)), "")
    source = metadata.get("avatarImageSource") or metadata.get("agentAvatarImageSource") or ""
    if raw and source != "default" and (not isinstance(raw, str) or not directory.agent_avatar_filename(raw)):
        raise ValueError(_UNAVAILABLE)
    source_root = _bundled_root()
    bundled = source_root / "assets" / directory.AGENT_AVATAR_ASSET_DIR_NAME
    available = [name for name in directory._available_agent_avatar_filenames()
                 if name not in directory.AGENT_AVATAR_MODEL_FILENAMES]
    for name in directory.AGENT_AVATAR_MODEL_FILENAMES:
        candidate = bundled / name
        assets._path_identity(candidate, missing_ok=True)
        if candidate.is_file():
            available.append(name)
    selected = directory.resolve_agent_avatar_path_for_projection(agent, available_avatar_filenames=available)
    if not selected:
        return "", None, directory.MAX_AGENT_AVATAR_IMAGE_BYTES
    filename = directory.agent_avatar_filename(selected)
    if not filename:
        raise ValueError(_UNAVAILABLE)
    config = Path(directory.CONFIG_PATH).expanduser().absolute()
    native_bundled = Path(directory._active_project_root()).absolute() / "assets" / directory.AGENT_AVATAR_ASSET_DIR_NAME
    custom = config.parent / directory.AGENT_AVATAR_CONFIG_DIR_NAME / directory.AGENT_AVATAR_CONFIG_AGENT_DIR_NAME
    legacy = Path(directory._workspace_path("avatars", seed=False)).absolute()
    is_model = filename in directory.AGENT_AVATAR_MODEL_FILENAMES
    roots = [bundled] if is_model else [custom, native_bundled, legacy]
    for root in roots:
        assets._path_identity(root / filename, missing_ok=True)
    if is_model:
        with directory.scoped_project_root(source_root):
            path = directory.resolve_agent_avatar_file(filename)
    else:
        path = directory.resolve_agent_avatar_file(filename)
    if path not in [root / filename for root in roots]:
        raise ValueError(_UNAVAILABLE)
    assets._path_identity(path)
    return selected, path, directory.MAX_AGENT_AVATAR_IMAGE_BYTES


def _snapshot(agent: dict) -> tuple:
    selected, path, limit = _selection(agent)
    if path is None:
        return selected, path, limit, None
    chain = assets._path_identity(path)
    info = path.stat()
    stamp = assets._file_stamp(info)
    if not 0 < info.st_size <= limit or chain != assets._path_identity(path):
        raise ValueError(_UNAVAILABLE)
    return selected, path, limit, (*stamp, info.st_ctime_ns)


def revision(agent: dict) -> str:
    config = _config_path()
    before = assets._path_identity(config)
    config_stat = config.stat()
    config_stamp = (*assets._file_stamp(config_stat), config_stat.st_ctime_ns)
    selected, _, _, stamp = _snapshot(agent)
    after = config.stat()
    if (before != assets._path_identity(config)
            or config_stamp != (*assets._file_stamp(after), after.st_ctime_ns)):
        raise ValueError(_UNAVAILABLE)
    return hashlib.sha256(repr((agent.get("agentId"), selected, stamp, config_stamp)).encode("utf-8")).hexdigest()


def read(agent: dict) -> dict:
    config = _config_path()
    before = assets._path_identity(config)
    first = _snapshot(agent)
    _, path, limit, _ = first
    image = None
    if path is not None:
        trusted_svg = path.suffix.lower() == ".svg" and path.name in directory.AGENT_AVATAR_MODEL_FILENAMES
        image = assets._read_image(path, limit, trusted_svg=trusted_svg)
    if before != assets._path_identity(config) or first != _snapshot(agent):
        raise ValueError(_UNAVAILABLE)
    return {"schemaVersion": 1, "agentId": agent["agentId"], "image": image}
