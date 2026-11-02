"""Private Launcher identity, initialized only by the locked assistant host.

Backend verification always reads the fixed production profile. Neither a request
path nor the process-local client credential can initialize backend authority.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import stat
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

_FILE_NAME = "launcher-authority.json"
_MAX_BYTES = 4096
_TOKEN = re.compile(r"[A-Za-z0-9_-]{32,128}", re.ASCII)
_process_authority: str | None = None


def _valid_token(token: object) -> bool:
    return isinstance(token, str) and _TOKEN.fullmatch(token) is not None


def _production_profile() -> Path | None:
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        user = os.environ.get("USERPROFILE")
        if not user:
            return None
        local = str(Path(user) / "AppData" / "Local")
    base = Path(local)
    if not base.is_absolute() or ".." in base.parts:
        return None
    return base / "Vibelution" / "DesktopShell" / "assistant" / "profile"


def _check_ancestors(root: Path, *, missing_ok: bool = False) -> None:
    for directory in (*reversed(root.parents), root):
        try:
            info = directory.lstat()
        except FileNotFoundError:
            if missing_ok:
                continue
            raise
        if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & 0x400):
            raise ValueError("Authority profile must use ordinary directories.")


@contextmanager
def _directory_lease(root: Path) -> Iterator[int | None]:
    if os.name == "nt":
        from core.web.services.personal_assistant_project.windows_read import lock_source_directory

        with lock_source_directory(root, root, allow_child_replacement=True):
            yield None
        return
    # Open every component without following symlinks, pinning the namespace
    # for relative file opens on platforms with directory descriptors.
    handles: list[int] = []
    try:
        for component in root.parts:
            handle = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                             dir_fd=handles[-1] if handles else None)
            handles.append(handle)
        yield handles[-1]
    finally:
        for handle in reversed(handles):
            os.close(handle)


def _read_bytes(root: Path) -> bytes:
    path = root / _FILE_NAME
    if os.name == "nt":
        from core.web.services.personal_assistant_project.windows_read import read_source_bytes

        return read_source_bytes(root, path, _MAX_BYTES)
    with _directory_lease(root) as directory_fd:
        handle = os.open(_FILE_NAME, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
        try:
            info = os.fstat(handle)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > _MAX_BYTES:
                raise ValueError("Authority must be a bounded ordinary single-link file.")
            with os.fdopen(handle, "rb", closefd=False) as stream:
                content = stream.read(_MAX_BYTES + 1)
            final = os.fstat(handle)
            if (len(content) != info.st_size or final.st_nlink != 1
                    or final.st_size != info.st_size or final.st_mtime_ns != info.st_mtime_ns):
                raise ValueError("Authority changed during its read.")
            return content
        finally:
            os.close(handle)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate authority field.")
        result[key] = value
    return result


def _read_enabled_token(root: Path) -> str | None:
    try:
        payload = json.loads(_read_bytes(root), object_pairs_hook=_unique_object)
        if (not isinstance(payload, dict) or set(payload) != {"schemaVersion", "status", "token"}
                or type(payload["schemaVersion"]) is not int or payload["schemaVersion"] != 1
                or payload["status"] != "enabled" or not _valid_token(payload["token"])):
            return None
        return payload["token"]
    except (OSError, ValueError, UnicodeError, RecursionError):
        return None


def ensure_launcher_authority(profile_root: Path) -> str | None:
    """Initialize once; the caller MUST already hold the host-owner lock.

    A nonproduction profile has no privileged identity. Existing disabled,
    revoked, malformed or unsafe files are never repaired by host startup.
    """
    root = _production_profile()
    try:
        supplied = Path(profile_root)
        if (root is None or not supplied.is_absolute() or ".." in supplied.parts
                or os.path.normcase(str(supplied)) != os.path.normcase(str(root))):
            return None
        _check_ancestors(root, missing_ok=True)
        root.mkdir(parents=True, exist_ok=True)
        with _directory_lease(root) as directory_fd:
            path = root / _FILE_NAME
            if os.path.lexists(path):
                return _read_enabled_token(root)
            token = secrets.token_urlsafe(32)
            payload = {"schemaVersion": 1, "status": "enabled", "token": token}
            try:
                handle = os.open(path if directory_fd is None else _FILE_NAME,
                                 os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=directory_fd)
            except FileExistsError:
                return _read_enabled_token(root)
            with os.fdopen(handle, "wb") as stream:
                stream.write(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
                stream.flush()
                os.fsync(stream.fileno())
            return _read_enabled_token(root)
    except (OSError, TypeError, ValueError):
        return None


def verify_launcher_authority(token: object) -> bool:
    """Read-only verification; missing, disabled or rotated identities fail closed."""
    if not _valid_token(token):
        return False
    root = _production_profile()
    expected = _read_enabled_token(root) if root is not None else None
    return expected is not None and hmac.compare_digest(expected, token)


def launcher_authority_fingerprint() -> str:
    """Return only a digest for worker binding, never creating authority."""
    root = _production_profile()
    token = _read_enabled_token(root) if root is not None else None
    return hashlib.sha256(token.encode("ascii")).hexdigest() if token else ""


def install_launcher_authority(token: str | None) -> None:
    """Install a host-supplied credential in this process only, never in its env."""
    if token is not None and not _valid_token(token):
        raise ValueError("Invalid Launcher authority credential.")
    global _process_authority
    _process_authority = token


def current_launcher_authority() -> str | None:
    """Read the explicitly installed process identity without filesystem access."""
    return _process_authority
