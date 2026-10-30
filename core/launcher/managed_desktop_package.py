"""Publish trusted desktop build outputs as immutable, content-addressed packages.

This owner does no building, configuration bootstrap, process launch or update
discovery. Hashes prove integrity, not publisher identity or release signatures.
Only the final strict atomic pointer write changes the selected package.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import struct
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from core.infrastructure.atomic_io import atomic_write_json
from core.infrastructure.file_lock import cross_process_file_lock

CATALOG_NAME = "managed-package-catalog.json"
MAX_CATALOG_BYTES = 16 * 1024 * 1024
MAX_FILES = 50000
MAX_FILE_BYTES = 512 * 1024 * 1024
MAX_TOTAL_BYTES = 4 * 1024 * 1024 * 1024
_CHUNK = 1024 * 1024
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_PROVENANCE = "resources/app.asar.unpacked/package-provenance.json"
_PAYLOAD = "resources/launcher-assistant"
_REQUIRED = {"Vibelution.exe", "resources/app.asar", _PROVENANCE, _PAYLOAD + "/manifest.json"}
_ACTIVE_KEYS = {"schemaVersion", "protocolVersion", "packageId", "exeSha256", "provenanceSha256"}
_DEVICES = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$",
            *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


@dataclass(frozen=True)
class PreparedPackage:
    source: Path
    catalog_bytes: bytes
    active: dict[str, Any]
    files: tuple[dict[str, Any], ...]
    signatures: tuple[tuple[str, tuple[int, ...]], ...]


def managed_desktop_root() -> Path:
    """The OS KnownFolder, deliberately independent of env/profile/cwd/registry."""
    if os.name != "nt":
        raise OSError("Managed desktop production location requires Windows")
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

    folder = GUID.from_buffer_copy(uuid.UUID("f1b32785-6fba-4fcf-9d55-7b8e7f157091").bytes_le)
    value = ctypes.c_wchar_p()
    shell = ctypes.WinDLL("shell32")
    shell.SHGetKnownFolderPath.argtypes = [ctypes.POINTER(GUID), wintypes.DWORD,
                                         wintypes.HANDLE, ctypes.POINTER(ctypes.c_wchar_p)]
    shell.SHGetKnownFolderPath.restype = ctypes.c_long
    result = shell.SHGetKnownFolderPath(ctypes.byref(folder), 0, None, ctypes.byref(value))
    if result != 0:
        raise OSError("Known LocalAppData is unavailable")
    try:
        return Path(value.value) / "Vibelution/Launcher/managed-desktop"
    finally:
        ole = ctypes.WinDLL("ole32")
        ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
        ole.CoTaskMemFree(ctypes.cast(value, ctypes.c_void_p))


def _relative(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value.encode("utf-16-le")) // 2 > 4096:
        raise ValueError("Invalid package path")
    if any(ord(c) < 32 or ord(c) == 127 or c in '<>:"\\|?*' for c in value):
        raise ValueError("Nonportable package path")
    for part in value.split("/"):
        # Win32 also recognizes the superscript forms of COM/LPT device names.
        device = part.split(".")[0].rstrip(" ").upper().translate(str.maketrans("¹²³", "123"))
        if not part or part in {".", ".."} or part != part.rstrip(" .") or device in _DEVICES:
            raise ValueError("Unsafe package path")
    return value


def _signature(info: os.stat_result) -> tuple[int, ...]:
    # Windows lstat infers executable permission bits from the filename;
    # fstat reports handle permissions instead. File type is comparable.
    # Directory size is index/allocation metadata: Windows can report 0 and
    # later the allocated size without changing identity, time or membership.
    # Inventory compares exact members separately; regular-file sizes remain
    # part of every read/copy signature and byte limit.
    size = 0 if stat.S_ISDIR(info.st_mode) else info.st_size
    return (info.st_dev, info.st_ino, size, info.st_mtime_ns, stat.S_IFMT(info.st_mode),
            getattr(info, "st_file_attributes", 0))


def _lstat(path: Path):
    info = os.lstat(path)
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise ValueError("Package links and reparse points are refused")
    return info


def _io_path(path: Path | str) -> Path:
    # Reuse the payload owner's drive/UNC namespace rules. A 64-byte package
    # directory plus native Python dependencies exceeds MAX_PATH routinely.
    from scripts.build_assistant_runtime import _io_path as payload_io_path
    return payload_io_path(path)


def _checked(path: Path) -> tuple[int, ...]:
    for parent in reversed(path.parents):
        if not stat.S_ISDIR(_lstat(parent).st_mode):
            raise ValueError("Invalid package ancestor")
    return _signature(_lstat(path))


def _root(path: Path | str) -> Path:
    root = Path(path)
    if not root.is_absolute() or ".." in root.parts:
        raise ValueError("An explicit absolute directory is required")
    root = _io_path(root)
    if not stat.S_ISDIR(_checked(root)[4]):
        raise ValueError("Package root is not a directory")
    return root


def _mkdir(path: Path) -> None:
    if path.exists() or path.is_symlink():
        _root(path)
        return
    _mkdir(path.parent)
    path.mkdir()
    _root(path)


def _inventory(root: Path, *, catalog: bool = False) -> dict[str, tuple[int, ...]]:
    root = _root(root)
    rows: dict[str, tuple[int, ...]] = {}
    seen = set()
    nodes = 0
    def visit(directory: Path, depth: int):
        nonlocal nodes
        if depth > 128:
            raise ValueError("Package directory nesting exceeds limit")
        before = _checked(directory)
        with os.scandir(directory) as children:
            for child in children:
                nodes += 1
                if nodes > MAX_FILES * 4:
                    raise ValueError("Package node limit exceeded")
                path = directory / child.name
                relative = _relative(path.relative_to(root).as_posix())
                folded = relative.casefold()
                if folded in seen:
                    raise ValueError("Case-aliased package paths")
                seen.add(folded)
                info = _checked(path)
                if stat.S_ISDIR(info[4]):
                    visit(path, depth + 1)
                elif stat.S_ISREG(info[4]):
                    if relative == CATALOG_NAME:
                        if not catalog:
                            raise ValueError("Build output already contains a managed catalog")
                        continue
                    if info[2] > MAX_FILE_BYTES or len(rows) >= MAX_FILES:
                        raise ValueError("Package file limit exceeded")
                    rows[relative] = info
                else:
                    raise ValueError("Package contains a nonregular file")
        after = _checked(directory)
        if after != before:
            relative = "." if directory == root else _relative(directory.relative_to(root).as_posix())
            label = json.dumps(relative[:128] + ("..." if len(relative) > 128 else ""), ensure_ascii=True)
            fields = ("st_dev", "st_ino", "size", "st_mtime_ns", "type", "attrs")
            changed = ",".join(name for name, old, new in zip(fields, before, after) if old != new)
            raise ValueError(f"Package directory changed during enumeration: directory={label}; fields={changed}")
    visit(root, 0)
    if sum(info[2] for info in rows.values()) > MAX_TOTAL_BYTES:
        raise ValueError("Package total exceeds limit")
    return rows


def _stream(path: Path, *, limit: int, expected: tuple[int, ...] | None = None,
            output=None, digest=None, capture: bool = False) -> tuple[str, bytes]:
    path = _io_path(path)
    before = _checked(path)
    if not stat.S_ISREG(before[4]) or before[2] > limit or (expected is not None and before != expected):
        raise ValueError("Package file changed or exceeds limit")
    sha = digest if digest is not None else hashlib.sha256()
    parts = []
    count = 0
    with path.open("rb") as handle:
        if _signature(os.fstat(handle.fileno())) != before:
            raise ValueError("Package read identity changed")
        while True:
            data = handle.read(min(_CHUNK, limit - count + 1))
            if not data:
                break
            count += len(data)
            if count > limit:
                raise ValueError("Package read exceeds limit")
            sha.update(data)
            if capture:
                parts.append(data)
            if output is not None:
                output.write(data)
        if count != before[2] or _signature(os.fstat(handle.fileno())) != before:
            raise ValueError("Package file changed while reading")
    if _checked(path) != before:
        raise ValueError("Package read path changed")
    return sha.hexdigest(), b"".join(parts)


def _json(data: bytes) -> dict:
    def closed_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result
    try:
        result = json.loads(data.decode("utf-8"), object_pairs_hook=closed_pairs,
                            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite JSON")))
    except (UnicodeError, RecursionError) as exc:
        raise ValueError("Invalid package JSON") from exc
    if not isinstance(result, dict):
        raise ValueError("Package JSON object required")
    return result


def _directory_content_hash(root: Path) -> str:
    """Exact frontendBundle.ts sha256DirectoryTree framing, streamed and bounded."""
    inventory = _inventory(root)
    digest = hashlib.sha256()
    for relative in sorted(inventory, key=lambda p: p.encode("utf-8")):
        encoded = relative.encode("utf-8")
        digest.update(struct.pack(">I", len(encoded)))
        digest.update(encoded)
        digest.update(struct.pack(">Q", inventory[relative][2]))
        _stream(root / relative, limit=MAX_FILE_BYTES, expected=inventory[relative], digest=digest)
    if _inventory(root) != inventory:
        raise ValueError("Sealed payload changed")
    return digest.hexdigest()


def _seal(root: Path, inventory: dict[str, tuple[int, ...]]) -> None:
    if not _REQUIRED <= inventory.keys():
        raise ValueError("Required desktop package files missing")
    with (root / "Vibelution.exe").open("rb") as exe:
        if exe.read(2) != b"MZ":
            raise ValueError("Desktop executable is not an MZ image")
    _, raw = _stream(root / _PROVENANCE, limit=MAX_CATALOG_BYTES, capture=True)
    provenance = _json(raw)
    if any(type(provenance.get(k)) is not int or provenance[k] != 1 for k in ("schemaVersion", "protocolVersion")):
        raise ValueError("Unsupported desktop provenance")
    for key in ("sourceCommit", "electronTreeHash", "frontendTreeHash", "frontendSourceCommit"):
        if not isinstance(provenance.get(key), str) or not re.fullmatch(r"[0-9a-fA-F]{40,64}", provenance[key]):
            raise ValueError("Invalid desktop provenance revision")
    for key in ("frontendContentSha256", "frontendBuildKey", "mainBundleSha256", "preloadBundleSha256"):
        if not isinstance(provenance.get(key), str) or not re.fullmatch(r"[0-9a-fA-F]{64}", provenance[key]):
            raise ValueError("Invalid desktop provenance hash")
    try:
        datetime.fromisoformat(provenance["builtAt"].replace("Z", "+00:00"))
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        raise ValueError("Invalid provenance timestamp") from exc
    capabilities = provenance.get("capabilities")
    if not isinstance(capabilities, list) or not {"desktop_actions.claim", "workbench_close.transaction.v1"} <= set(
        x for x in capabilities if isinstance(x, str)
    ):
        raise ValueError("Required desktop protocol capabilities missing")
    evidence = provenance.get("assistant")
    hashes = ("manifestSha256", "contentSha256", "sourceContentSha256", "runtimeContentSha256", "requirementsSha256",
              "contractsSha256")
    if not isinstance(evidence, dict) or any(not isinstance(evidence.get(k), str) or not _HASH.fullmatch(evidence[k]) for k in hashes):
        raise ValueError("Missing assistant seal")
    if not isinstance(evidence.get("pythonVersion"), str) or not re.fullmatch(r"3\.[0-9]+\.[0-9]+", evidence["pythonVersion"]):
        raise ValueError("Invalid assistant Python version")
    # The existing pure build owner verifies dependencies/RECORD and all files.
    # It imports no config service or product bootstrap. Our inventory/read
    # gates surround it to enforce this publisher's stricter bounds and races.
    from scripts.build_assistant_runtime import verify_launcher_assistant_payload
    manifest = verify_launcher_assistant_payload(root / _PAYLOAD,
        expected_manifest_sha256=evidence["manifestSha256"])
    if any(manifest.get(k) != evidence[k] for k in (*hashes[2:], "pythonVersion")):
        raise ValueError("Assistant provenance does not match manifest")
    if _directory_content_hash(root / _PAYLOAD) != evidence["contentSha256"]:
        raise ValueError("Assistant payload tree does not match provenance")


def _snapshot(root: Path, *, catalog: bool = False):
    inventory = _inventory(root, catalog=catalog)
    rows = [{"path": relative, "size": inventory[relative][2],
             "sha256": _stream(root / relative, limit=MAX_FILE_BYTES, expected=inventory[relative])[0]}
            for relative in sorted(inventory, key=lambda p: p.encode("utf-8"))]
    _seal(root, inventory)
    if _inventory(root, catalog=catalog) != inventory:
        raise ValueError("Package changed during inspection")
    return rows, inventory


def _active(catalog: bytes, rows: list[dict]) -> dict:
    hashes = {r["path"]: r["sha256"] for r in rows}
    return {"schemaVersion": 1, "protocolVersion": 1, "packageId": hashlib.sha256(catalog).hexdigest(),
            "exeSha256": hashes["Vibelution.exe"], "provenanceSha256": hashes[_PROVENANCE]}


def prepare_managed_desktop_package(source: Path | str) -> PreparedPackage:
    """Inspect a trusted existing build output without modifying it."""
    root = _root(source)
    rows, inventory = _snapshot(root)
    data = (json.dumps({"schemaVersion": 1, "files": rows}, ensure_ascii=False,
                       separators=(",", ":")) + "\n").encode("utf-8")
    if len(data) > MAX_CATALOG_BYTES:
        raise ValueError("Managed catalog exceeds limit")
    return PreparedPackage(root, data, _active(data, rows), tuple(rows), tuple(inventory.items()))


def _catalog(data: bytes) -> list[dict]:
    value = _json(data)
    if set(value) != {"schemaVersion", "files"} or type(value.get("schemaVersion")) is not int or value["schemaVersion"] != 1:
        raise ValueError("Invalid managed catalog schema")
    rows = value["files"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_FILES:
        raise ValueError("Invalid managed catalog files")
    seen = set()
    total = 0
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"path", "size", "sha256"}:
            raise ValueError("Invalid managed file schema")
        relative = _relative(row["path"])
        if relative.casefold() in seen or relative.casefold() == CATALOG_NAME.casefold():
            raise ValueError("Duplicate or recursive catalog path")
        seen.add(relative.casefold())
        if type(row["size"]) is not int or not 0 <= row["size"] <= MAX_FILE_BYTES:
            raise ValueError("Invalid managed file size")
        if not isinstance(row["sha256"], str) or not _HASH.fullmatch(row["sha256"]):
            raise ValueError("Invalid managed file hash")
        total += row["size"]
        if total > MAX_TOTAL_BYTES:
            raise ValueError("Managed package exceeds limit")
    return rows


def inspect_managed_desktop_package(package: Path | str, *, expected_package_id: str | None = None) -> dict:
    """Validate every installed byte and both seals, without repairing anything."""
    root = _root(package)
    _, data = _stream(root / CATALOG_NAME, limit=MAX_CATALOG_BYTES, capture=True)
    rows = _catalog(data)
    active = _active(data, rows) if _REQUIRED <= {r["path"] for r in rows} else None
    if active is None or (expected_package_id is not None and (
        not isinstance(expected_package_id, str) or not _HASH.fullmatch(expected_package_id)
        or expected_package_id != active["packageId"]
    )):
        raise ValueError("Managed package identity mismatch")
    observed, _ = _snapshot(root, catalog=True)
    if {r["path"]: r for r in rows} != {r["path"]: r for r in observed}:
        raise ValueError("Managed package bytes do not match catalog")
    # Re-read the catalog after the lengthy payload verification too.
    if _stream(root / CATALOG_NAME, limit=MAX_CATALOG_BYTES, capture=True)[1] != data:
        raise ValueError("Managed catalog changed during inspection")
    return active


def _pointer(value: dict) -> dict:
    if set(value) != _ACTIVE_KEYS or any(type(value.get(k)) is not int or value[k] != 1 for k in ("schemaVersion", "protocolVersion")):
        raise ValueError("Invalid active package schema")
    if any(not isinstance(value.get(k), str) or not _HASH.fullmatch(value[k]) for k in _ACTIVE_KEYS - {"schemaVersion", "protocolVersion"}):
        raise ValueError("Invalid active package hashes")
    return value


def inspect_active_managed_desktop_package(*, managed_root: Path | str | None = None) -> dict:
    root = _root(managed_desktop_root() if managed_root is None else managed_root)
    _, data = _stream(root / "active.json", limit=4096, capture=True)
    pointer = _pointer(_json(data))
    actual = inspect_managed_desktop_package(root / "packages" / pointer["packageId"], expected_package_id=pointer["packageId"])
    if actual != pointer:
        raise ValueError("Active package pin mismatch")
    return actual


def _copy_file(source: Path, destination: Path, expected: tuple[int, ...], sha256: str) -> None:
    _mkdir(destination.parent)
    with destination.open("xb") as output:
        digest, _ = _stream(source, limit=MAX_FILE_BYTES, expected=expected, output=output)
        output.flush()
        os.fsync(output.fileno())
    if digest != sha256:
        raise ValueError("Source bytes changed before copy")


def install_managed_desktop_package(source: Path | str, *, managed_root: Path | str | None = None) -> dict:
    """Publish and atomically select; never overwrite/delete installed versions.

    Failed fresh stages remain private diagnostic artifacts. No failure path
    removes a previous version or mutates the old active pointer in place.
    """
    source = _root(source)
    root = Path(managed_desktop_root() if managed_root is None else managed_root)
    if not root.is_absolute() or ".." in root.parts:
        raise ValueError("An explicit absolute managed root is required")
    root = _io_path(root)
    if not root.is_absolute() or ".." in root.parts or source == root or source in root.parents or root in source.parents:
        raise ValueError("Source and managed roots must be separate absolute trees")
    _mkdir(root)
    lock = root / "publisher.lock"
    if lock.exists() or lock.is_symlink():
        _checked(lock)
    with cross_process_file_lock(root / "publisher", timeout=30):
        _root(root)
        for name in ("packages", ".staging"):
            _mkdir(root / name)
        pointer_path = root / "active.json"
        if pointer_path.exists() or pointer_path.is_symlink():
            _, previous = _stream(pointer_path, limit=4096, capture=True)
            _pointer(_json(previous))
        prepared = prepare_managed_desktop_package(source)
        destination = root / "packages" / prepared.active["packageId"]
        if destination.exists() or destination.is_symlink():
            actual = inspect_managed_desktop_package(destination, expected_package_id=prepared.active["packageId"])
            if actual != prepared.active:
                raise ValueError("Existing managed package pin mismatch")
        else:
            stage = root / ".staging" / uuid.uuid4().hex
            stage.mkdir()
            signatures = dict(prepared.signatures)
            for row in prepared.files:
                _copy_file(source / row["path"], stage / row["path"], signatures[row["path"]], row["sha256"])
            with (stage / CATALOG_NAME).open("xb") as handle:
                handle.write(prepared.catalog_bytes)
                handle.flush()
                os.fsync(handle.fileno())
            if prepare_managed_desktop_package(source) != prepared:
                raise ValueError("Source changed during staging")
            if inspect_managed_desktop_package(stage, expected_package_id=prepared.active["packageId"]) != prepared.active:
                raise ValueError("Staged package pin mismatch")
            _root(root / "packages")
            # Same-volume exclusive rename. A publisher lock serializes writers;
            # an unexpectedly existing destination is refused, never replaced.
            if destination.exists() or destination.is_symlink():
                raise ValueError("Managed destination appeared during publication")
            stage.rename(destination)
        if prepare_managed_desktop_package(source) != prepared:
            raise ValueError("Source changed before activation")
        _root(root)
        for sidecar in (pointer_path, pointer_path.with_name("active.json.lock")):
            if sidecar.exists() or sidecar.is_symlink():
                _checked(sidecar)
        atomic_write_json(pointer_path, prepared.active, strict_replace=True)
        return dict(prepared.active)
