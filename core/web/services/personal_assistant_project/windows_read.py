"""Fail-closed Windows source reads through verified, namespace-pinning handles.

The caller owns the source allowlist. This module enforces physical containment,
rejects links, and holds every directory from the drive root through the target
without delete sharing until the operation has finished. Source reads also deny
write sharing; an explicit directory writer lease permits child replacement.
"""
from __future__ import annotations

from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
from typing import Iterator


_DIRECTORY = 0x10
_REPARSE = 0x400
_GENERIC_READ = 0x80000000
_SHARE_READ = 1
_SHARE_WRITE = 2
_OPEN_EXISTING = 3
_BACKUP_SEMANTICS = 0x02000000
_OPEN_REPARSE_POINT = 0x00200000
_INVALID_HANDLE = ctypes.c_void_p(-1).value


class _FileInformation(ctypes.Structure):
    _fields_ = [
        ("attributes", wintypes.DWORD),
        ("creation", wintypes.FILETIME),
        ("access", wintypes.FILETIME),
        ("write", wintypes.FILETIME),
        ("volume", wintypes.DWORD),
        ("size_high", wintypes.DWORD),
        ("size_low", wintypes.DWORD),
        ("links", wintypes.DWORD),
        ("index_high", wintypes.DWORD),
        ("index_low", wintypes.DWORD),
    ]


def _api():
    if os.name != "nt":
        raise ValueError("Verified source reads require Windows.")
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                               wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    api.CreateFileW.restype = wintypes.HANDLE
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    api.CloseHandle.restype = wintypes.BOOL
    api.GetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.POINTER(_FileInformation)]
    api.GetFileInformationByHandle.restype = wintypes.BOOL
    api.GetFinalPathNameByHandleW.argtypes = [wintypes.HANDLE, wintypes.LPWSTR,
                                           wintypes.DWORD, wintypes.DWORD]
    api.GetFinalPathNameByHandleW.restype = wintypes.DWORD
    api.GetFileType.argtypes = [wintypes.HANDLE]
    api.GetFileType.restype = wintypes.DWORD
    api.ReadFile.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                            ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
    api.ReadFile.restype = wintypes.BOOL
    return api


def _path_key(value: str | Path) -> str:
    text = str(value)
    if text.startswith("\\\\?\\UNC\\"):
        text = "\\\\" + text[8:]
    elif text.startswith("\\\\?\\"):
        text = text[4:]
    return os.path.normcase(os.path.normpath(text))


def _validated_paths(root: Path, path: Path) -> tuple[Path, Path]:
    root, path = Path(root), Path(path)
    for item in (root, path):
        if (not item.is_absolute() or not item.drive or item.drive.startswith("\\")
                or "\x00" in str(item)):
            raise ValueError("Source paths must be absolute local-drive paths.")
        for part in item.parts[1:]:
            if part in {".", ".."} or ":" in part or part.endswith((".", " ")):
                raise ValueError("Source path contains an unsafe component.")
    try:
        path.relative_to(root)
    except ValueError:
        raise ValueError("Source path is outside the checkout.") from None
    return root, path


def _information(api, handle) -> _FileInformation:
    info = _FileInformation()
    if not api.GetFileInformationByHandle(handle, ctypes.byref(info)):
        raise ctypes.WinError(ctypes.get_last_error())
    return info


def _verify(api, handle, path: Path, *, directory: bool) -> _FileInformation:
    info = _information(api, handle)
    if (info.attributes & _REPARSE or bool(info.attributes & _DIRECTORY) != directory
            or api.GetFileType(handle) != 1):
        raise ValueError("Source is not an ordinary disk directory/file.")
    if not directory and info.links != 1:
        raise ValueError("Source files must have exactly one hard link.")
    needed = api.GetFinalPathNameByHandleW(handle, None, 0, 0)
    if not needed or needed > 32768:
        raise ValueError("Cannot verify source handle path.")
    buffer = ctypes.create_unicode_buffer(needed + 1)
    actual = api.GetFinalPathNameByHandleW(handle, buffer, len(buffer), 0)
    if not actual or actual >= len(buffer) or _path_key(buffer.value) != _path_key(path):
        raise ValueError("Source handle does not match its approved physical path.")
    return info


@contextmanager
def _locked_source(
    root: Path, path: Path, *, directory: bool, allow_child_replacement: bool = False,
) -> Iterator[tuple]:
    root, path = _validated_paths(root, path)
    api = _api()
    handles = []
    # Pin ancestors as well: an ancestor rename must not change the root's
    # interpretation between the final-path check and the actual read.
    chain = list(reversed(path.parents)) + [path]
    try:
        for current in chain:
            is_directory = current != path or directory
            share_mode = _SHARE_READ | (_SHARE_WRITE if is_directory and allow_child_replacement else 0)
            handle = api.CreateFileW(
                # READ_ATTRIBUTES alone does not participate in Windows sharing
                # checks strongly enough to prevent a directory rename.
                str(current), _GENERIC_READ,
                share_mode, None, _OPEN_EXISTING,
                _OPEN_REPARSE_POINT | _BACKUP_SEMANTICS, None,
            )
            if handle == _INVALID_HANDLE or handle is None:
                raise ctypes.WinError(ctypes.get_last_error())
            handles.append(handle)
            info = _verify(api, handle, current, directory=is_directory)
        yield api, handles[-1], info
    finally:
        for handle in reversed(handles):
            api.CloseHandle(handle)


@contextmanager
def lock_source_directory(
    root: Path, path: Path, *, allow_child_replacement: bool = False,
) -> Iterator[None]:
    """Pin a verified directory chain against renames; reject initial reparse paths.

    The default read lease denies write sharing. Explicit writer leases permit
    atomic child-file replacement while still denying directory delete sharing.
    This is namespace pinning, not a sandbox against every same-user mutation.
    """
    if type(allow_child_replacement) is not bool:
        raise ValueError("Invalid directory lease mode.")
    with _locked_source(root, path, directory=True, allow_child_replacement=allow_child_replacement):
        yield None


def read_source_bytes(root: Path, path: Path, max_bytes: int) -> bytes:
    """Read at most max_bytes from the same verified, single-link file handle."""
    if type(max_bytes) is not int or not 0 <= max_bytes <= 16 * 1024 * 1024:
        raise ValueError("Invalid source byte budget.")
    # A single-file read pins its file against writes and replacement. Ancestor
    # directories only need rename protection; unrelated directory writers must
    # not make the requested file transiently unreadable.
    with _locked_source(root, path, directory=False, allow_child_replacement=True) as (api, handle, info):
        size = (info.size_high << 32) | info.size_low
        if size > max_bytes:
            raise ValueError("Source file exceeds the byte budget.")
        chunks = []
        total = 0
        while True:
            buffer = ctypes.create_string_buffer(min(65536, max_bytes - total + 1))
            count = wintypes.DWORD()
            if not api.ReadFile(handle, buffer, len(buffer), ctypes.byref(count), None):
                raise ctypes.WinError(ctypes.get_last_error())
            if not count.value:
                break
            total += count.value
            if total > max_bytes:
                raise ValueError("Source file exceeds the byte budget.")
            chunks.append(buffer.raw[:count.value])
        final = _verify(api, handle, Path(path), directory=False)
        if ((final.size_high << 32) | final.size_low) != size or total != size:
            raise ValueError("Source changed during its verified read.")
        return b"".join(chunks)
