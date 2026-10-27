"""Bounded source snapshots for assistant migration, never an execution engine."""
from __future__ import annotations

import hashlib
import json
import math
import os
import stat
from dataclasses import dataclass
from contextlib import ExitStack, contextmanager
from pathlib import Path


class MigrationIOError(ValueError):
    """A stable diagnostic code, without source content or native errors."""


@dataclass(frozen=True)
class FileSnapshot:
    path: Path
    raw: bytes
    sha256: str
    identity: tuple


class TreeSnapshots(list):
    """File snapshots plus bounded traversal cost for multi-root callers."""

    def __init__(self, items=(), *, visited_entries=0, directories=()):
        super().__init__(items)
        self.visited_entries = visited_entries
        self.directories = tuple(directories)


def strict_json(raw: bytes | str):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate_key")
            result[key] = value
        return result

    def constant(_value):
        raise ValueError("nonfinite_json")

    def number(value):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError("nonfinite_json")
        return result

    try:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8-sig")
        result = json.loads(raw, object_pairs_hook=pairs, parse_constant=constant, parse_float=number)
        # JSON escape sequences must not smuggle unpaired surrogates into a
        # later model result or manifest encoding operation.
        json.dumps(result, ensure_ascii=False).encode("utf-8")
        return result
    except (ValueError, TypeError, RecursionError):
        raise MigrationIOError("invalid_source_json") from None


def _stamp(value):
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns,
            getattr(value, "st_birthtime_ns", value.st_ctime_ns), value.st_mode, value.st_nlink)


def path_identity(path: Path) -> tuple:
    return _stamp(path.stat())


def check_path(path: Path) -> Path:
    path = validate_path(path)
    try:
        for node in (*reversed(path.parents), path):
            value = node.lstat()
            if stat.S_ISLNK(value.st_mode) or getattr(value, "st_file_attributes", 0) & 0x400:
                raise MigrationIOError("linked_source")
            if node != path and not stat.S_ISDIR(value.st_mode):
                raise MigrationIOError("source_type_mismatch")
    except OSError:
        raise MigrationIOError("source_unavailable") from None
    return path


def validate_path(path: Path) -> Path:
    """Validate lexical input before any stat, mkdir, lock or resolver call."""
    path = Path(path)
    text = str(path)
    if not path.is_absolute():
        raise MigrationIOError("absolute_source_required")
    if text.startswith(("\\\\?\\", "\\\\.\\", "\\\\")):
        raise MigrationIOError("source_path_alias")
    if any(part in {"..", "."} or part.endswith((".", " "))
           or (os.name == "nt" and ":" in part)
           for part in path.parts if part != path.anchor):
        raise MigrationIOError("source_path_alias")
    return path


@contextmanager
def pinned_target_directory(path: Path, *, create: bool = False):
    """Pin every target ancestor through creation and writes, on Windows."""
    path = validate_path(path)
    if os.name != "nt":
        raise MigrationIOError("migration_writes_require_windows")
    from core.web.services.personal_assistant_project.windows_read import lock_source_directory
    missing = []
    ancestor = path
    while not ancestor.exists() and not ancestor.is_symlink():
        missing.append(ancestor.name)
        ancestor = ancestor.parent
    check_path(ancestor)
    if missing and not create:
        raise MigrationIOError("target_directory_unavailable")
    try:
        with ExitStack() as stack:
            stack.enter_context(lock_source_directory(Path(ancestor.anchor), ancestor, allow_child_replacement=True))
            current = ancestor
            for part in reversed(missing):
                current = current / part
                current.mkdir(exist_ok=True)
                # No child is written until this just-created directory is
                # itself verified and pinned against replacement.
                stack.enter_context(lock_source_directory(Path(current.anchor), current, allow_child_replacement=True))
            check_path(current)
            yield current.resolve()
    except (OSError, ValueError) as error:
        if isinstance(error, (MigrationIOError, TimeoutError)):
            raise
        raise MigrationIOError("target_namespace_unavailable") from None


@contextmanager
def migration_target_lock(path: Path):
    """Serialize migration writers without opening an attacker-swappable sidecar."""
    path = validate_path(path)
    if os.name != "nt":
        raise MigrationIOError("migration_writes_require_windows")
    import ctypes
    from ctypes import wintypes
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    api.CreateMutexW.restype = wintypes.HANDLE
    api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    api.WaitForSingleObject.restype = wintypes.DWORD
    api.ReleaseMutex.argtypes = [wintypes.HANDLE]
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    key = hashlib.sha256(str(path.resolve()).casefold().encode()).hexdigest()
    handle = api.CreateMutexW(None, False, "Local\\Vibelution.AssistantMigration." + key)
    if not handle:
        raise MigrationIOError("migration_lock_unavailable")
    acquired = False
    try:
        result = api.WaitForSingleObject(handle, 5000)
        # An abandoned lock grants ownership; the importer still verifies all
        # immutable pending bytes before resuming an interrupted operation.
        if result not in (0, 0x80):
            raise MigrationIOError("migration_lock_unavailable")
        acquired = True
        yield
    finally:
        if acquired:
            api.ReleaseMutex(handle)
        api.CloseHandle(handle)


@contextmanager
def pinned_source_files(snapshots):
    """Hold verified source files stable through a snapshot visibility commit.

    Ancestors permit ordinary writes but deny rename/delete while pinned. File
    handles deny write/delete sharing. This does not freeze directory contents
    or establish that a live source is quiescent.
    """
    if os.name != "nt":
        raise MigrationIOError("migration_writes_require_windows")
    import ctypes
    from core.web.services.personal_assistant_project.windows_read import _api, _verify

    unique = {}
    for snapshot in snapshots:
        if not isinstance(snapshot, FileSnapshot):
            raise MigrationIOError("source_authority_required")
        path = check_path(snapshot.path)
        key = str(path).casefold()
        if key in unique and unique[key] != snapshot:
            raise MigrationIOError("source_changed")
        unique[key] = snapshot
    if not unique:
        raise MigrationIOError("source_authority_required")
    files = [snapshot.path for snapshot in unique.values()]
    directories = {parent for path in files for parent in path.parents if parent != Path(path.anchor)}
    api = _api()
    with ExitStack() as stack:
        try:
            for path, directory in [(path, True) for path in sorted(directories, key=lambda p: (len(p.parts), str(p).casefold()))] + \
                    [(path, False) for path in sorted(files, key=lambda p: str(p).casefold())]:
                check_path(path)
                handle = api.CreateFileW(str(path), 0x80000000, 3 if directory else 1,
                                         None, 3, 0x02200000 if directory else 0x00200000, None)
                if handle is None or handle == ctypes.c_void_p(-1).value:
                    raise MigrationIOError("source_guard_unavailable")
                stack.callback(api.CloseHandle, handle)
                _verify(api, handle, path, directory=directory)
            for snapshot in unique.values():
                verify_snapshot(snapshot)
        except (OSError, ValueError) as error:
            if isinstance(error, (MigrationIOError, TimeoutError)):
                raise
            raise MigrationIOError("source_guard_unavailable") from None
        # Do not translate failures from the caller's protected operation.
        yield


def publish_directory(pending: Path, final: Path, expected_identity: tuple) -> None:
    """Publish the verified pending object by handle, never a reusable path."""
    pending, final = validate_path(pending), validate_path(final)
    if pending.parent != final.parent or os.name != "nt":
        raise MigrationIOError("target_publish_invalid")
    import ctypes
    from ctypes import wintypes
    from core.web.services.personal_assistant_project.windows_read import _api, _verify

    class RenameInfo(ctypes.Structure):
        _fields_ = [("replace", ctypes.c_ubyte), ("root", wintypes.HANDLE),
                    ("length", wintypes.DWORD), ("name", wintypes.WCHAR * 1)]

    api = _api()
    api.SetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    api.SetFileInformationByHandle.restype = wintypes.BOOL
    with pinned_target_directory(final.parent):
        handle = api.CreateFileW(str(pending), 0x80000000 | 0x10000, 3, None, 3, 0x02200000, None)
        if handle == ctypes.c_void_p(-1).value:
            raise MigrationIOError("target_publish_unavailable")
        try:
            _verify(api, handle, pending, directory=True)
            if path_identity(pending) != expected_identity:
                raise MigrationIOError("target_pending_changed")
            name = str(final).encode("utf-16-le")
            buffer = ctypes.create_string_buffer(RenameInfo.name.offset + len(name) + 2)
            info = ctypes.cast(buffer, ctypes.POINTER(RenameInfo)).contents
            info.replace = 0
            info.root = None
            info.length = len(name)
            ctypes.memmove(ctypes.addressof(buffer) + RenameInfo.name.offset, name, len(name))
            if not api.SetFileInformationByHandle(handle, 3, buffer, len(buffer)):
                raise MigrationIOError("target_publish_unavailable")
            _verify(api, handle, final, directory=True)
        except (OSError, ValueError) as error:
            if isinstance(error, MigrationIOError):
                raise
            raise MigrationIOError("target_publish_unavailable") from None
        finally:
            api.CloseHandle(handle)


@contextmanager
def pinned_mutable_file(path: Path):
    """Pin a regular lock leaf while the existing native lock owner writes it."""
    path = validate_path(path)
    if os.name != "nt":
        raise MigrationIOError("migration_writes_require_windows")
    import ctypes
    from core.web.services.personal_assistant_project.windows_read import _api, _verify
    with pinned_target_directory(path.parent):
        api = _api()
        handle = api.CreateFileW(str(path), 0x80000000, 3, None, 4, 0x00200000, None)
        if handle == ctypes.c_void_p(-1).value:
            raise MigrationIOError("target_lock_leaf_unavailable")
        try:
            _verify(api, handle, path, directory=False)
            yield
        except (OSError, ValueError) as error:
            if isinstance(error, (MigrationIOError, TimeoutError)):
                raise
            raise MigrationIOError("target_lock_leaf_unavailable") from None
        finally:
            api.CloseHandle(handle)


def read_stable_file(path: Path, max_bytes: int, expected: tuple | None = None) -> FileSnapshot:
    if type(max_bytes) is not int or not 0 <= max_bytes <= 16 * 1024 * 1024:
        raise MigrationIOError("invalid_source_budget")
    try:
        path = check_path(path)
        before = path_identity(path)
        if not stat.S_ISREG(before[5]) or before[6] != 1:
            raise MigrationIOError("source_type_or_link_invalid")
        if expected is not None and before != expected:
            raise MigrationIOError("source_changed")
        if before[2] > max_bytes:
            raise MigrationIOError("file_byte_limit")
        if os.name == "nt":
            from core.web.services.personal_assistant_project.windows_read import read_source_bytes
            raw = read_source_bytes(Path(path.anchor), path, max_bytes)
        else:
            with path.open("rb") as stream:
                if _stamp(os.fstat(stream.fileno())) != before:
                    raise MigrationIOError("source_changed")
                raw = stream.read(max_bytes + 1)
                if _stamp(os.fstat(stream.fileno())) != before:
                    raise MigrationIOError("source_changed")
        check_path(path)
        if len(raw) != before[2] or len(raw) > max_bytes or path_identity(path) != before:
            raise MigrationIOError("source_changed")
    except (OSError, ValueError) as error:
        if isinstance(error, MigrationIOError):
            raise
        raise MigrationIOError("source_unavailable_or_changed") from None
    return FileSnapshot(path, raw, hashlib.sha256(raw).hexdigest(), before)


def verify_snapshot(snapshot: FileSnapshot) -> None:
    current = read_stable_file(snapshot.path, len(snapshot.raw), expected=snapshot.identity)
    if current.sha256 != snapshot.sha256:
        raise MigrationIOError("source_changed")


def fingerprint_tree(root: Path, *, max_file_bytes: int = 16 * 1024 * 1024,
                     max_files: int = 10000, max_total_bytes: int = 128 * 1024 * 1024) -> list[FileSnapshot]:
    if any(type(n) is not int or n < 1 for n in (max_file_bytes, max_files, max_total_bytes)):
        raise MigrationIOError("invalid_source_budget")
    root = check_path(root)
    if root.is_file():
        return TreeSnapshots([read_stable_file(root, min(max_file_bytes, max_total_bytes))], visited_entries=1)
    if not root.is_dir():
        raise MigrationIOError("source_type_mismatch")
    result, directories, pending = [], [], [root]
    visited = total = 0
    while pending:
        directory = check_path(pending.pop())
        directories.append((directory, path_identity(directory)))
        try:
            with os.scandir(directory) as children:
                for child in children:
                    visited += 1
                    if visited > max_files:
                        raise MigrationIOError("file_limit")
                    path = check_path(Path(child.path))
                    if path.is_dir():
                        pending.append(path)
                    elif path.is_file():
                        value = read_stable_file(path, min(max_file_bytes, max_total_bytes - total))
                        result.append(value)
                        total += len(value.raw)
                    else:
                        raise MigrationIOError("source_type_mismatch")
        except OSError:
            raise MigrationIOError("source_unavailable_or_changed") from None
    for path, before in directories:
        check_path(path)
        if path_identity(path) != before:
            raise MigrationIOError("source_changed")
    return TreeSnapshots(sorted(result, key=lambda item: item.path.as_posix()),
                         visited_entries=visited, directories=directories)
