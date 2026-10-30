"""Build/verify the offline Windows assistant payload from a trusted installation.

This is a build-time copier, not a Python installer or process launcher. Callers
own the build session, publication, freshness policy and ``-I -B`` startup.
The output must be new; failed builds stay available without a valid manifest.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import os
import platform
import re
import stat
import sys
import sysconfig
from collections import deque
from importlib import metadata
from pathlib import Path, PurePosixPath
from typing import Any

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

_HASH = re.compile(r"^[0-9a-f]{64}$")
_SKIP_DIRS = {"__pycache__", ".git", ".venv", "node_modules", "workspace", "runtime",
              ".runtime", "logs", "cache", ".cache", "tests", "fixtures", ".pytest_cache",
              "data", "credentials", "sessions", "agent_config"}
_SOURCE_SUFFIXES = {".py", ".md", ".json", ".yaml", ".yml", ".txt"}
# These JSON files are shipped program resources (competition/resources.py),
# rather than runtime state. Keep the exception rooted at its product owner.
_STATIC_DATA_DIRS = ("core/research/competition/data",)
_ASSET_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".ico", ".avif",
                   ".bmp", ".wav", ".mp3", ".ogg", ".json", ".md", ".zip"}
_ROOT_SOURCE = ("agent.py", "vibelution_storage.py", "VERSION", "AGENTS.md", "requirements.txt")
_REQUIRED_SOURCE = (*_ROOT_SOURCE, "scripts/assistant_host.py", "core/__init__.py",
                    "core/external_agent/contracts.py",
                    "config/__init__.py", "tools/__init__.py", "core/core_prompt/COMMON.md",
                    "core/core_prompt/SOUL.md")
_ENTRYPOINT = "source/scripts/assistant_host.py"
_PYTHON_ENTRYPOINT = "python/pythonw.exe"
# The snapshot's copy of the external-Agent wire contract. Its hash is sealed
# into the manifest ("contractsSha256") so a packaged source tree whose
# contracts module was modified without a rebuild is refused at every verify
# step (build, managed-desktop seal, startup).
_CONTRACTS_MODULE = "source/core/external_agent/contracts.py"
_PTH_CONTENT = b"Lib\nDLLs\nLib/site-packages\n../source\nimport site\n"
_MANIFEST_MAX_BYTES = 32 * 1024 * 1024
_READ_CHUNK_BYTES = 1024 * 1024
_INSTALL_METADATA = {"direct_url.json", "origin.json", "provenance.json", "uv_cache.json", "installer", "requested"}
_DEVELOPMENT_PTH = {"a1_coverage.pth", "distutils-precedence.pth"}


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _file_identity(info: os.stat_result) -> tuple[int, ...]:
    # Windows derives executable permission bits from path suffixes in lstat,
    # while fstat reports handle permissions. Only their file type is shared.
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, stat.S_IFMT(info.st_mode))


def _read_stable_file(path: Path, *, expected_size: int | None = None,
                      limit: int | None = None, capture: bool = False,
                      target=None, digests=()) -> tuple[int, bytes]:
    """Read at most the initial/declared size plus one byte, and pin identity.

    The extra byte detects growth without an EOF-seeking unbounded hash/copy.
    No extra byte reaches a copied output or digest. Existing payload helpers
    use the same gate for captures, hashes and ordinary build copies.
    """
    _reject_link(path)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode):
        raise ValueError("assistant payload input is not a regular file")
    size = before.st_size if expected_size is None else expected_size
    if type(size) is not int or size < 0 or before.st_size != size or (limit is not None and size > limit):
        raise ValueError("assistant payload file size exceeds bound or changed")
    identity = _file_identity(before)
    count = 0
    pieces = []
    with path.open("rb") as handle:
        if _file_identity(os.fstat(handle.fileno())) != identity:
            raise ValueError("assistant payload read identity changed")
        while True:
            chunk = handle.read(min(_READ_CHUNK_BYTES, size - count + 1))
            if not chunk:
                break
            count += len(chunk)
            if count > size:
                raise ValueError("assistant payload input grew during read")
            if capture:
                pieces.append(chunk)
            if target is not None:
                target.write(chunk)
            for digest in digests:
                digest.update(chunk)
        if count != size or _file_identity(os.fstat(handle.fileno())) != identity:
            raise ValueError("assistant payload input changed during read")
    _reject_link(path)
    if _file_identity(path.lstat()) != identity:
        raise ValueError("assistant payload path changed during read")
    return count, b"".join(pieces)


def _file_sha256(path: Path, *, expected_size: int | None = None) -> str:
    digest = hashlib.sha256()
    _read_stable_file(path, expected_size=expected_size, digests=(digest,))
    return digest.hexdigest()


def _relative(value: str) -> str:
    if not isinstance(value, str) or not value or any(char in value for char in '\\:*?"<>|\x00'):
        raise ValueError("invalid relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in value.split("/")):
        raise ValueError("invalid relative path")
    # Windows silently aliases trailing spaces/dots and reserved devices.
    for part in path.parts:
        if part != part.rstrip(" .") or part.split(".")[0].upper() in {
            "CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
            *(f"LPT{i}" for i in range(1, 10)),
        }:
            raise ValueError("invalid Windows path")
    return path.as_posix()


def _reject_link(path: Path) -> None:
    if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
        raise ValueError(f"links are not allowed: {path}")


def _public_path(value: Path | str) -> str:
    """Keep device namespaces out of returned paths and caller-owned metadata."""
    raw = os.fspath(value)
    if os.name == "nt":
        if raw.startswith("\\\\?\\UNC\\"):
            return "\\\\" + raw[8:]
        if raw.startswith("\\\\?\\") and re.match(r"^[A-Za-z]:\\", raw[4:]):
            return raw[4:]
        if raw.startswith(("\\\\?\\", "\\\\.\\", "\\??\\")):
            raise ValueError("unsupported filesystem namespace")
    return raw


def _io_path(value: Path | str) -> Path:
    """Use Win32 extended paths only for absolute drive/UNC filesystem I/O."""
    absolute = os.path.abspath(_public_path(value))
    if os.name != "nt":
        return Path(absolute)
    if absolute.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + absolute[2:])
    if not re.match(r"^[A-Za-z]:\\", absolute):
        raise ValueError("unsupported filesystem namespace")
    return Path("\\\\?\\" + absolute)


def _trusted_root(value: Path | str) -> Path:
    path = _io_path(value)
    for ancestor in (path, *path.parents):
        _reject_link(ancestor)
    return _io_path(path.resolve())


def _checked(root: Path, relative: str) -> Path:
    relative = _relative(relative)
    _reject_link(root)
    target = root
    for part in PurePosixPath(relative).parts:
        target = target / part
        _reject_link(target)
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"path escapes its root: {relative}")
    return target


def _walk(root: Path, *, skip: set[str] | None = None, skip_bytecode: bool = False):
    _reject_link(root)
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(name for name in dirs if name not in (skip or set()))
        for name in dirs:
            _reject_link(Path(directory) / name)
        for name in sorted(files):
            path = Path(directory) / name
            _reject_link(path)
            if not skip_bytecode or path.suffix != ".pyc":
                yield path


def _source_files(root: Path) -> list[Path]:
    result = [_checked(root, name) for name in _ROOT_SOURCE]
    for directory in ("core", "config", "tools", "schemas", "assets"):
        base = _checked(root, directory)
        if not base.is_dir():
            raise ValueError(f"required product directory missing: {directory}")
        suffixes = (_ASSET_SUFFIXES if directory == "assets" else
                    {".py", ".md"} if directory == "config" else _SOURCE_SUFFIXES)
        for path in _walk(base, skip=_SKIP_DIRS):
            if path.suffix.lower() in suffixes:
                result.append(path)
    for directory in _STATIC_DATA_DIRS:
        base = _checked(root, directory)
        if base.is_dir():
            result.extend(path for path in _walk(base, skip=_SKIP_DIRS) if path.suffix.lower() == ".json")
    scripts = _checked(root, "scripts")
    for path in sorted(scripts.glob("*.py")):
        _reject_link(path)
        result.append(path)
    for name in _REQUIRED_SOURCE:
        if not _checked(root, name).is_file():
            raise ValueError(f"required product file missing: {name}")
    return sorted(set(result), key=lambda path: path.relative_to(root).as_posix())


def _runtime_requirements(path: Path) -> list[Requirement]:
    text = path.read_text(encoding="utf-8-sig")
    boundary = "# 开发/测试依赖"
    if boundary not in text:
        raise ValueError("requirements runtime/development boundary is missing")
    requirements = []
    for line in text.split(boundary, 1)[0].splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            try:
                requirement = Requirement(line)
            except ValueError:
                raise ValueError("invalid runtime requirement declaration") from None
            if requirement.url:
                raise ValueError("URL requirements cannot be verified against installed versions")
            requirements.append(requirement)
    if not requirements:
        raise ValueError("runtime requirements are empty")
    return requirements


def _distributions(requirements: list[Requirement], site: Path):
    installed: dict[str, tuple[Any, Path]] = {}
    for info in sorted(site.glob("*.dist-info")):
        info = _checked(site, info.relative_to(site).as_posix())
        distribution = metadata.Distribution.at(info)
        name = canonicalize_name(distribution.metadata["Name"] or "")
        if not name or name in installed:
            raise ValueError(f"ambiguous installed distribution: {name}")
        installed[name] = (distribution, info)
    environment = default_environment()
    extras: dict[str, set[str]] = {}
    completed: dict[str, frozenset[str]] = {}
    pending: deque[str] = deque()

    def include(requirement: Requirement) -> None:
        if requirement.url:
            raise ValueError(f"unverifiable URL dependency: {requirement.name}")
        name = canonicalize_name(requirement.name)
        candidate = installed.get(name)
        if candidate is None:
            raise ValueError(f"runtime dependency not installed: {name}")
        distribution, _ = candidate
        if requirement.specifier and not requirement.specifier.contains(distribution.version, prereleases=True):
            raise ValueError(f"installed {name}=={distribution.version} does not satisfy {requirement}")
        requested = extras.setdefault(name, set())
        requested.update(requirement.extras)
        if completed.get(name) != frozenset(requested):
            pending.append(name)

    for requirement in requirements:
        if requirement.marker is None or requirement.marker.evaluate({**environment, "extra": ""}):
            include(requirement)
    while pending:
        name = pending.popleft()
        wanted = frozenset(extras[name])
        if completed.get(name) == wanted:
            continue
        completed[name] = wanted
        for raw in installed[name][0].requires or []:
            requirement = Requirement(raw)
            if requirement.marker is None or any(
                requirement.marker.evaluate({**environment, "extra": extra}) for extra in {"", *wanted}
            ):
                include(requirement)
    return [(name, *installed[name]) for name in sorted(completed)]


def _content_hash(files: list[dict], prefix: str = "") -> str:
    return _sha(_json_bytes([entry for entry in files if entry["path"].startswith(prefix)]))


def _python_names(version: str) -> tuple[str, str]:
    if not isinstance(version, str) or not re.fullmatch(r"3\.[0-9]+\.[0-9]+", version):
        raise ValueError("a complete CPython 3 version is required")
    major, minor, _ = version.split(".")
    return f"python{major}{minor}", f"cp{major}{minor}"


def _validate_pth(path: Path, site: Path, owner: str) -> None:
    """Only in-tree search paths and the known pywin32 bootstrap may execute."""
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line == "import pywin32_bootstrap" and path.name == "pywin32.pth" and owner == "pywin32":
                continue
            if line.startswith(("import ", "import\t")):
                raise ValueError("unsupported bootstrap")
            _checked(site, line.replace("\\", "/"))
    except (ValueError, UnicodeError):
        raise ValueError(f"unsafe runtime .pth in distribution {owner}") from None


def _is_build_header(parts: list[str], owner: str, python_version: str) -> bool:
    """Recognize only venv's distribution-owned C/C++ development headers."""
    python_abi_dir = "python" + ".".join(python_version.split(".")[:2])
    if len(parts) < 7 or parts[:5] != ["..", "..", "include", "site", python_abi_dir]:
        return False
    try:
        _relative("/".join(parts[5:]))
    except ValueError:
        return False
    return canonicalize_name(parts[5]) == owner and PurePosixPath(parts[-1]).suffix.lower() in {".h", ".hpp"}


def _restored_tokenizer_bytes(path: Path, relative: str, owner: str, record_hash: str, record_size: int | None) -> bytes | None:
    """Recover a known text-cache newline rewrite only by exact RECORD proof."""
    allowed = r"python/Lib/site-packages/litellm/litellm_core_utils/tokenizers/[0-9a-f]{40}"
    limit = 16 * 1024 * 1024
    if (owner != "litellm" or not re.fullmatch(allowed, relative)
        or not re.fullmatch(r"sha256=[A-Za-z0-9_-]{43}", record_hash)
        or record_size is None or not 0 < record_size <= limit or path.stat().st_size > limit):
        return None
    _, data = _read_stable_file(path, limit=limit, capture=True)
    if b"\x00" in data or b"\n" not in data:
        return None
    try:
        data.decode("utf-8")
    except UnicodeError:
        return None
    lf = data.replace(b"\r\n", b"\n")
    if b"\r" in lf:
        return None
    for candidate in (lf, lf.replace(b"\n", b"\r\n")):
        if candidate == data or len(candidate) != record_size:
            continue
        digest = base64.urlsafe_b64encode(hashlib.sha256(candidate).digest()).decode().rstrip("=")
        if "sha256=" + digest == record_hash:
            return candidate
    return None


def _coalesced_records(rows: list[list[str]], owner: str) -> tuple[list[list[str]], list[dict]]:
    """Merge only separator spellings, retaining every nonempty constraint."""
    merged: dict[str, list[str]] = {}
    case_keys: dict[str, str] = {}
    duplicates = []
    for row in rows:
        if len(row) != 3:
            raise ValueError(f"invalid RECORD row: {owner}")
        relative, digest, size = row
        relative = relative.replace("\\", "/")
        previous_spelling = case_keys.setdefault(relative.casefold(), relative)
        if previous_spelling != relative:
            raise ValueError(f"payload file conflict in RECORD for {owner}")
        previous = merged.get(relative)
        if previous is None:
            merged[relative] = [relative, digest, size]
            continue
        if any(old and new and old != new for old, new in zip(previous[1:], (digest, size), strict=True)):
            raise ValueError(f"payload file conflict in RECORD for {owner}")
        previous[1] = previous[1] or digest
        previous[2] = previous[2] or size
        if len(duplicates) >= 128:
            raise ValueError("too many duplicate RECORD rows")
        duplicates.append({"distribution": owner, "path": relative, "reason": "duplicate_record"})
    return list(merged.values()), duplicates


def build_launcher_assistant_payload(
    project_root: Path | str,
    output_root: Path | str,
    *,
    python_root: Path | str | None = None,
    site_packages: Path | str | None = None,
    python_version: str | None = None,
) -> dict[str, Any]:
    """Copy trusted installed bytes into one new, independently verifiable tree.

    The optional paths/version support offline fixtures or an explicitly chosen
    trusted installation. They must describe the current build host's Windows
    ABI; this function does not cross-build or install dependencies.
    """
    project = _trusted_root(project_root)
    base = _trusted_root(python_root or sys.base_prefix)
    site = _trusted_root(site_packages or sysconfig.get_path("purelib"))
    output = _trusted_root(output_root)
    if output.is_relative_to(base) or output.is_relative_to(site) or any(
        output.is_relative_to(project / name) for name in ("core", "config", "tools", "scripts", "schemas", "assets")
    ):
        raise ValueError("output cannot be inside an input payload directory")
    output.mkdir(parents=True, exist_ok=False)
    version = python_version or platform.python_version()
    python_name, abi = _python_names(version)
    if sys.platform != "win32":
        raise ValueError("assistant runtime packaging currently requires a Windows build host")
    source_files = _source_files(project)
    requirements_hash = _file_sha256(_checked(project, "requirements.txt"))
    selected = _distributions(_runtime_requirements(project / "requirements.txt"), site)
    entries: dict[str, dict] = {}
    owners: dict[str, str] = {}
    excluded = []
    restored_files = []
    duplicate_count = 0

    def copy(path: Path, relative: str, owner: str, record=None) -> None:
        relative = _relative(relative)
        key = relative.casefold()
        if key in owners:
            raise ValueError(f"payload file conflict: {relative} ({owners[key]}, {owner})")
        owners[key] = owner
        _reject_link(path)
        if not path.is_file():
            raise ValueError(f"payload input missing for {owner}: {relative}")
        if path.suffix == ".pth":
            _validate_pth(path, site, owner)
        destination = _checked(output, relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        record_hash, record_size = record if record is not None else ("", None)
        hash_algorithm, hash_value = record_hash.split("=", 1) if record_hash else ("", "")
        if hash_algorithm and hash_algorithm not in {"sha256", "sha384", "sha512"}:
            raise ValueError(f"unsupported RECORD hash: {relative}")
        record_digest = hashlib.new(hash_algorithm) if hash_algorithm else None
        with destination.open("xb") as target:
            size, _ = _read_stable_file(path, target=target,
                digests=(digest, record_digest) if record_digest is not None else (digest,))
        if record is not None:
            size_mismatch = record_size is not None and record_size != size
            actual = base64.urlsafe_b64encode(record_digest.digest()).decode().rstrip("=") if record_digest else ""
            hash_mismatch = record_digest is not None and actual != hash_value
            if size_mismatch or hash_mismatch:
                restored = _restored_tokenizer_bytes(destination, relative, owner, record_hash, record_size)
                if restored is None:
                    fault = "size" if size_mismatch else "hash"
                    raise ValueError(f"RECORD {fault} mismatch: {relative}")
                if len(restored_files) >= 32:
                    raise ValueError("too many tokenizer line-ending restorations")
                # Only the task's newly created copy changes. The trusted
                # installation remains untouched, and the recovered bytes
                # already match both the original RECORD size and SHA-256.
                destination.write_bytes(restored)
                size = len(restored)
                digest = hashlib.sha256(restored)
                restored_files.append({"distribution": owner, "path": relative, "reason": "record_line_endings"})
        entries[relative] = {"path": relative, "size": size, "sha256": digest.hexdigest()}

    for path in source_files:
        copy(path, "source/" + path.relative_to(project).as_posix(), "product_source")
    required_binaries = ("python.exe", "pythonw.exe", "python3.dll", f"{python_name}.dll", "vcruntime140.dll")
    for name in required_binaries:
        copy(_checked(base, name), "python/" + name, "cpython")
    for path in sorted(base.glob("*.dll")):
        if path.name not in required_binaries:
            copy(_checked(base, path.name), "python/" + path.name, "cpython")
    licenses = sorted(path for path in base.glob("LICENSE*") if path.is_file())
    if not licenses:
        raise ValueError("required CPython LICENSE is missing")
    for path in licenses:
        copy(path, "python/" + path.name, "cpython_license")
    for name in ("Lib", "DLLs", "tcl"):
        directory = _checked(base, name)
        if not directory.is_dir():
            if name == "tcl":
                continue
            raise ValueError(f"required CPython directory missing: {name}")
        for path in _walk(directory, skip={"site-packages", "__pycache__"}, skip_bytecode=True):
            copy(path, "python/" + path.relative_to(base).as_posix(), "cpython")
    for name, distribution, info in selected:
        record_path = _checked(site, (info / "RECORD").relative_to(site).as_posix())
        if not record_path.is_file():
            raise ValueError(f"installed distribution has no complete RECORD: {name}")
        records, duplicates = _coalesced_records(
            list(csv.reader(io.StringIO(record_path.read_text(encoding="utf-8")))), name,
        )
        duplicate_count += len(duplicates)
        if duplicate_count > 128:
            raise ValueError("too many duplicate RECORD rows")
        excluded.extend(duplicates)
        required_metadata = {(info / filename).relative_to(site).as_posix() for filename in ("RECORD", "METADATA")}
        if not records or not required_metadata <= {row[0] for row in records if len(row) == 3}:
            raise ValueError(f"installed distribution has no complete RECORD: {name}")
        for row in records:
            relative, record_hash, size = row
            relative = relative.replace("\\", "/")
            parts = relative.split("/")
            if len(parts) == 4 and parts[:3] == ["..", "..", "Scripts"]:
                _relative(parts[-1])
                excluded.append({"distribution": name, "path": relative, "reason": "console_entrypoint"})
                continue
            if len(parts) == 5 and parts[:4] == ["..", "..", "Scripts", "__pycache__"] and parts[-1].endswith(".pyc"):
                _relative(parts[-1])
                excluded.append({"distribution": name, "path": relative, "reason": "bytecode_cache"})
                continue
            if _is_build_header(parts, name, version):
                excluded.append({"distribution": name, "path": relative, "reason": "build_header"})
                continue
            try:
                relative = _relative(relative)
            except ValueError:
                raise ValueError(f"unsafe RECORD path for {name}") from None
            reason = None
            if "__pycache__" in parts or relative.endswith(".pyc"):
                reason = "bytecode_cache"
            elif any(part.endswith(".dist-info") for part in parts[:-1]) and parts[-1].lower() in _INSTALL_METADATA:
                reason = "installation_provenance"
            elif parts[-1] in _DEVELOPMENT_PTH or (parts[-1].startswith("__editable__") and relative.endswith(".pth")):
                reason = "development_bootstrap"
            if reason:
                excluded.append({"distribution": name, "path": relative, "reason": reason})
                continue
            if record_hash and "=" not in record_hash:
                raise ValueError(f"invalid RECORD hash: {name}")
            record_size = int(size) if size else None
            if record_size is not None and record_size < 0:
                raise ValueError(f"invalid RECORD size: {name}")
            copy(_checked(site, relative), "python/Lib/site-packages/" + relative, name, (record_hash, record_size))
    pth_name = f"python/{python_name}._pth"
    pth = _PTH_CONTENT
    _checked(output, pth_name).write_bytes(pth)
    entries[pth_name] = {"path": pth_name, "size": len(pth), "sha256": _sha(pth)}
    files = [entries[key] for key in sorted(entries)]
    # A source writer may run during the longer dependency copy. Do not publish
    # a manifest for a source snapshot that no longer matches its build inputs.
    if source_files != _source_files(project) or any(
        _file_sha256(path, expected_size=entries["source/" + path.relative_to(project).as_posix()]["size"])
        != entries["source/" + path.relative_to(project).as_posix()]["sha256"]
        for path in source_files
    ):
        raise ValueError("product source changed during payload construction")
    # Drift guard: the packaged copy must carry the wire-contract identity so a
    # snapshot whose contracts module was dropped or separately rewritten is
    # refused here instead of failing later with an opaque runtime mismatch.
    contracts_entry = entries.get(_CONTRACTS_MODULE)
    if contracts_entry is None:
        raise ValueError("assistant payload snapshot is missing the external-agent contracts module")
    manifest = {
        "schemaVersion": 1, "protocolVersion": 1, "platform": sys.platform, "machine": platform.machine(),
        "pythonVersion": version, "pythonAbi": abi, "entrypoint": _ENTRYPOINT,
        "pythonEntrypoint": _PYTHON_ENTRYPOINT, "requirementsSha256": requirements_hash,
        "dependencies": [{"name": name, "version": distribution.version} for name, distribution, _ in selected],
        "excludedFiles": sorted(excluded, key=lambda item: (item["distribution"], item["path"])),
        "sourceContentSha256": _content_hash(files, "source/"),
        "runtimeContentSha256": _content_hash(files, "python/"),
        "payloadContentSha256": _content_hash(files),
        "contractsSha256": contracts_entry["sha256"], "files": files,
    }
    _verify_files(output, manifest)
    content = _json_bytes(manifest)
    with (output / "manifest.json").open("xb") as handle:
        handle.write(content)
    return {"manifest": manifest, "manifestSha256": _sha(content), "manifestPath": _public_path(output / "manifest.json"),
            "restoredFiles": restored_files,
            "sourceRoot": _public_path(output / "source"), "pythonRoot": _public_path(output / "python")}


def _verify_files(root: Path, manifest: dict) -> None:
    if manifest.get("schemaVersion") != 1 or manifest.get("protocolVersion") != 1:
        raise ValueError("unsupported assistant payload manifest")
    python_name, abi = _python_names(manifest.get("pythonVersion", ""))
    if manifest.get("platform") != "win32" or manifest.get("pythonAbi") != abi or not manifest.get("machine"):
        raise ValueError("invalid assistant Python platform/ABI")
    if manifest.get("entrypoint") != _ENTRYPOINT or manifest.get("pythonEntrypoint") != _PYTHON_ENTRYPOINT:
        raise ValueError("invalid required assistant entrypoint")
    files = manifest.get("files")
    if not isinstance(files, list) or not files or len(files) > 200_000:
        raise ValueError("invalid assistant file manifest")
    seen = set()
    for entry in files:
        if not isinstance(entry, dict) or set(entry) != {"path", "size", "sha256"}:
            raise ValueError("invalid assistant file entry")
        relative = _relative(entry["path"])
        if not relative.startswith(("source/", "python/")) or relative.casefold() in seen:
            raise ValueError("duplicate or invalid assistant file path")
        seen.add(relative.casefold())
        if type(entry["size"]) is not int or entry["size"] < 0 or not _HASH.fullmatch(str(entry["sha256"])):
            raise ValueError("invalid assistant file size/hash")
        path = _checked(root, relative)
        if not path.is_file() or path.stat().st_size != entry["size"]:
            raise ValueError(f"assistant payload file missing or size mismatch: {relative}")
        digest = _file_sha256(path, expected_size=entry["size"])
        if digest != entry["sha256"]:
            raise ValueError(f"assistant payload hash mismatch: {relative}")
    actual = {path.relative_to(root).as_posix().casefold() for path in _walk(root)
              if path.relative_to(root).as_posix() != "manifest.json"}
    if actual != seen:
        raise ValueError("assistant payload contains unlisted or missing files")
    required = {"source/" + name for name in _REQUIRED_SOURCE} | {
        _PYTHON_ENTRYPOINT, "python/python.exe", "python/python3.dll", f"python/{python_name}.dll",
        f"python/{python_name}._pth", "python/Lib/encodings/__init__.py", "python/Lib/site.py",
    }
    if not {path.casefold() for path in required} <= seen or not any(path.startswith("python/license") for path in seen):
        raise ValueError("required assistant payload files are missing")
    _, pth_content = _read_stable_file(_checked(root, f"python/{python_name}._pth"),
                                      limit=len(_PTH_CONTENT), capture=True)
    if pth_content != _PTH_CONTENT:
        raise ValueError("invalid isolated Python search paths")
    dependencies = manifest.get("dependencies")
    if not isinstance(dependencies, list) or not dependencies or any(
        not isinstance(item, dict) or set(item) != {"name", "version"}
        or not isinstance(item["name"], str) or not isinstance(item["version"], str)
        or not item["name"] or not item["version"] for item in dependencies
    ):
        raise ValueError("invalid assistant dependency inventory")
    installed = _distributions(_runtime_requirements(root / "source/requirements.txt"), root / "python/Lib/site-packages")
    if dependencies != [{"name": name, "version": distribution.version} for name, distribution, _ in installed]:
        raise ValueError("assistant dependency inventory does not match its runtime closure")
    for name, _, info in installed:
        if not {f"python/Lib/site-packages/{info.name}/{part}".casefold() for part in ("METADATA", "RECORD")} <= seen:
            raise ValueError(f"assistant dependency metadata is incomplete: {name}")
    for path in (root / "python/Lib/site-packages").glob("*.pth"):
        owner = "pywin32" if path.name == "pywin32.pth" else "unknown"
        _validate_pth(path, root / "python/Lib/site-packages", owner)
    for field, prefix in (("sourceContentSha256", "source/"), ("runtimeContentSha256", "python/"),
                          ("payloadContentSha256", "")):
        if not _HASH.fullmatch(str(manifest.get(field, ""))) or manifest[field] != _content_hash(files, prefix):
            raise ValueError(f"assistant manifest content hash mismatch: {field}")
    requirements = next(entry for entry in files if entry["path"] == "source/requirements.txt")
    if manifest.get("requirementsSha256") != requirements["sha256"]:
        raise ValueError("assistant requirements hash mismatch")
    # Contract drift guard: the sealed contracts hash must match the exact
    # packaged bytes, so a snapshot whose contracts module was edited without
    # a rebuild is refused at verification (managed-desktop seal included).
    contracts = next((entry for entry in files if entry["path"] == _CONTRACTS_MODULE), None)
    if contracts is None or manifest.get("contractsSha256") != contracts["sha256"]:
        raise ValueError("assistant contracts identity mismatch")


def verify_launcher_assistant_payload(
    payload_root: Path | str, *, expected_manifest_sha256: str | None = None,
) -> dict[str, Any]:
    """Verify every listed byte and reject extra files; startup should pin SHA."""
    root = _trusted_root(payload_root)
    path = _checked(root, "manifest.json")
    if not path.is_file() or path.stat().st_size > _MANIFEST_MAX_BYTES:
        raise ValueError("assistant payload manifest missing or too large")
    _, content = _read_stable_file(path, limit=_MANIFEST_MAX_BYTES, capture=True)
    if expected_manifest_sha256 is not None and (
        not isinstance(expected_manifest_sha256, str) or not _HASH.fullmatch(expected_manifest_sha256)
        or _sha(content) != expected_manifest_sha256
    ):
        raise ValueError("assistant manifest SHA-256 mismatch")
    try:
        manifest = json.loads(content)
    except (ValueError, UnicodeError) as exc:
        raise ValueError("invalid assistant payload manifest JSON") from exc
    if not isinstance(manifest, dict):
        raise ValueError("invalid assistant payload manifest shape")  # noqa: TRY004 -- malformed input, not a caller type error
    _verify_files(root, manifest)
    return manifest
