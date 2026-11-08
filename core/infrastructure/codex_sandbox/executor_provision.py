"""Automated provisioning of the pinned MXC sandbox executor (wxc-exec.exe).

The MXC backend (``core.infrastructure.codex_sandbox.mxc``) expects the
executor binary at ``%LOCALAPPDATA%\\Vibelution\\sandbox\\wxc-exec.exe`` with
the hard 1.0.x PE ``FileVersion`` lock. Until now that binary had to be
installed manually; this module closes the gap: it downloads the pinned GitHub
release asset, verifies it end to end and installs it atomically, so a future
launcher hook can bring a machine to the pinned executor with one call::

    from core.infrastructure.codex_sandbox.executor_provision import (
        ensure_executor_installed,
    )

    status = ensure_executor_installed(allow_download=False)  # probe only
    status = ensure_executor_installed(allow_download=True)   # download+install

Security/robustness contract (anchors verified 2026-11-08):

- Everything runs in-process (``urllib`` + ``zipfile``, no subprocess), so no
  console window can ever appear (product red line) and no secrets are
  involved. Only stdlib plus read-only reuse of ``mxc.py`` (path rule, PE
  version reader, 1.0.x version gate) is used.
- The release asset and the extracted executor are both SHA256-pinned. The
  archive is streamed with a running hash and a hard byte cap (pinned declared
  size + 1 byte): an oversized/poisoned download is aborted and deleted before
  it can amplify on disk.
- Extraction is zip-slip safe: every member name is normalized and rejected
  when absolute or containing ``..`` path parts; only the single expected
  member (``x64/wxc-exec.exe``) is ever written.
- The extracted executor must additionally match the pinned SHA256 and the
  1.0.x version lock before anything is installed.
- Installation is atomic on Windows: parent ``mkdir(parents=True)``, write a
  temporary file in the same directory, then ``os.replace`` onto the target.
- Conservative no-overwrite: an existing target that fails hash/version
  verification is NEVER overwritten or deleted. Provisioning reports
  ``failed`` with the verification flags and leaves the decision (manual
  remediation or an explicit supervised upgrade) to the caller.
- Network failures/timeouts leave the target path untouched and report
  ``failed`` with the transport detail. Diagnostics go through ``logging``
  only; the CLI prints exactly one JSON document to stdout (ASCII-safe for
  GBK consoles).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import shutil
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath

from core.infrastructure.codex_sandbox.mxc import (
    EXECUTOR_RELATIVE_PARTS,
    _read_pe_file_version,
    _version_is_allowed,
    executor_path as mxc_executor_path,
)

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

# Pinned release anchors. Verified via the GitHub API for microsoft/mxc
# release v1.0.1 on 2026-11-08 (asset name, byte size and sha256 digest match
# exactly). The executor SHA256 was measured independently on this host from
# both the PoC-verified installed binary and the pristine release archive
# member ``bin/x64/wxc-exec.exe`` (identical); note the head comment of
# tests/test_codex_sandbox_mxc_real.py records this same hash with a one-char
# typo (65 hex chars), so it must not be transcribed from there verbatim.
PINNED_RELEASE_TAG = "v1.0.1"
PINNED_ASSET_URL = (
    "https://github.com/microsoft/mxc/releases/download/v1.0.1/"
    "mxc-release-binaries.zip"
)
PINNED_ZIP_FILENAME = "mxc-release-binaries.zip"
PINNED_ZIP_SHA256 = (
    "0e832239454ba7fcd338ff56218a287eef4c0a01c1484084b869f55feff8abe9"
)
PINNED_ZIP_SIZE_BYTES = 542051775
PINNED_EXECUTOR_SHA256 = (
    "090f5d1f7bb93104ab08dcd4e8034ef954aeefcdaf6658dde5f7dff4cfc12f3a"
)
ZIP_MEMBER = "x64/wxc-exec.exe"

# ProvisionStatus.action values.
ACTION_ALREADY_PRESENT = "already_present"
ACTION_DOWNLOADED = "downloaded"
ACTION_FAILED = "failed"
ACTION_MISSING = "missing"

_TEMP_DIR_PREFIX = "wxc-exec-provision-"
_DOWNLOAD_CHUNK_BYTES = 1024 * 1024
_USER_AGENT = "Vibelution-executor-provision/1.0"


class ExecutorProvisionError(Exception):
    """Provisioning setup/transport failure (callers get ``failed`` status)."""


@dataclass
class ProvisionStatus:
    """One provisioning verdict for the pinned MXC executor.

    ``installed`` is true only when the pinned-verified executor is in place
    (action ``already_present`` or ``downloaded``). The ``*_ok`` flags record
    which verification steps held for the final verdict: on success all three
    are true (for ``already_present`` the archive itself was not fetched, but
    ``zip_sha_ok=True`` expresses the equivalent guarantee that the on-disk
    executor hash equals the pin); on failure they show how far the chain got.
    """

    installed: bool
    action: str  # already_present | downloaded | failed | missing
    executor_path: str
    detail: str = ""
    zip_sha_ok: bool = False
    exec_sha_ok: bool = False
    version_ok: bool = False


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(_DOWNLOAD_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _default_target(environ: dict[str, str] | None = None) -> Path:
    """Resolve the product install path (same rule as ``mxc.executor_path``).

    ``mxc.executor_path`` only returns a path when the binary already exists;
    provisioning must also know the destination while it is missing, so the
    same ``LOCALAPPDATA`` relative parts are reused read-only here.
    """
    source = environ if environ is not None else os.environ
    existing = mxc_executor_path(source)
    if existing is not None:
        return existing
    local_app_data = str(source.get("LOCALAPPDATA") or "").strip()
    if not local_app_data:
        raise ExecutorProvisionError(
            "LOCALAPPDATA is not set; cannot resolve the wxc-exec.exe install path"
        )
    return Path(local_app_data).joinpath(*EXECUTOR_RELATIVE_PARTS)


def _member_name_is_safe(name: str) -> bool:
    """Zip-slip guard: reject absolute paths, drives and ``..`` traversal."""
    normalized = name.replace("\\", "/")
    if not normalized or normalized.startswith("/"):
        return False
    if len(normalized) >= 2 and normalized[1] == ":":
        return False
    return ".." not in PurePosixPath(normalized).parts


def _extract_executor(zip_path: Path, dest_dir: Path) -> Path:
    """Extract exactly one verified member to ``dest_dir`` (zip-slip safe)."""
    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            if not _member_name_is_safe(info.filename):
                raise ExecutorProvisionError(
                    f"refusing unsafe zip member name: {info.filename!r}"
                )
        target_info = None
        for info in archive.infolist():
            if info.filename.replace("\\", "/") == ZIP_MEMBER:
                target_info = info
                break
        if target_info is None:
            raise ExecutorProvisionError(
                f"zip does not contain the expected member {ZIP_MEMBER!r}"
            )
        dest_path = dest_dir / PurePosixPath(ZIP_MEMBER).name
        with archive.open(target_info) as source, open(dest_path, "wb") as out:
            shutil.copyfileobj(source, out)
        return dest_path


def _download_streaming(
    url: str, dest_path: Path, *, max_bytes: int, timeout_s: float
) -> None:
    """Stream ``url`` to ``dest_path`` with byte cap and overall deadline."""
    deadline = time.monotonic() + max(float(timeout_s), 1.0)
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=float(timeout_s)) as response:
            total = 0
            with open(dest_path, "wb") as out:
                while True:
                    if time.monotonic() > deadline:
                        raise ExecutorProvisionError(
                            f"download exceeded timeout_s={timeout_s} "
                            f"after {total} bytes"
                        )
                    chunk = response.read(_DOWNLOAD_CHUNK_BYTES)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        raise ExecutorProvisionError(
                            f"download exceeded size cap: {total} > {max_bytes} "
                            "bytes; aborted and discarded (anti-amplification)"
                        )
                    out.write(chunk)
    except ExecutorProvisionError:
        raise
    except Exception as exc:  # urllib.error.HTTPError / URLError / OSError
        raise ExecutorProvisionError(f"{type(exc).__name__}: {exc}") from exc


def _pinned_version_ok(path: Path) -> bool:
    """PE FileVersion gate (read-only reuse of the mxc.py 1.0.x lock)."""
    parts = _read_pe_file_version(path)
    if parts is None:
        return False
    return _version_is_allowed(".".join(str(part) for part in parts))


def _failed(target_str: str, detail: str, **flags: bool) -> ProvisionStatus:
    logger.warning("executor provisioning failed for %s: %s", target_str, detail)
    return ProvisionStatus(
        installed=False,
        action=ACTION_FAILED,
        executor_path=target_str,
        detail=detail,
        **flags,
    )


def ensure_executor_installed(
    executor_path: Path | None = None,
    *,
    allow_download: bool = True,
    timeout_s: float = 600,
) -> ProvisionStatus:
    """Ensure the pinned MXC executor is installed and verified.

    Verdict order:

    1. Existing target matching the pinned SHA256 and the 1.0.x PE version
       lock -> ``already_present`` (no network).
    2. Existing target that fails verification -> ``failed``; the file is
       never overwritten or deleted (conservative no-overwrite, see module
       docstring) even when ``allow_download=True``.
    3. Missing target with ``allow_download=False`` -> ``missing`` (probe
       only, no network).
    4. Missing target with ``allow_download=True`` -> stream-download the
       pinned release asset, verify zip SHA256, extract the single pinned
       member (zip-slip safe), verify executor SHA256 + 1.0.x version, then
       atomically install via ``os.replace`` -> ``downloaded``.

    Any transport/verification failure returns ``failed`` and leaves the
    target path exactly as it was. ``executor_path`` overrides the default
    product install path (tests/repair use).
    """
    if executor_path is not None:
        target = Path(executor_path)
    else:
        try:
            target = _default_target()
        except ExecutorProvisionError as exc:
            return _failed("", str(exc))
    target_str = str(target)

    if target.exists():
        if not target.is_file():
            return _failed(target_str, f"target exists and is not a file: {target}")
        exec_sha_ok = _sha256_file(target) == PINNED_EXECUTOR_SHA256
        version_ok = _pinned_version_ok(target)
        if exec_sha_ok and version_ok:
            logger.info("pinned executor already present: %s", target_str)
            return ProvisionStatus(
                installed=True,
                action=ACTION_ALREADY_PRESENT,
                executor_path=target_str,
                detail=(
                    f"executor already pinned-verified at {target_str} "
                    f"(release {PINNED_RELEASE_TAG})"
                ),
                zip_sha_ok=True,
                exec_sha_ok=True,
                version_ok=True,
            )
        return _failed(
            target_str,
            "existing executor failed pinned verification "
            f"(sha256 ok={exec_sha_ok}, 1.0.x version ok={version_ok}); "
            "conservative no-overwrite, manual remediation required",
            exec_sha_ok=exec_sha_ok,
            version_ok=version_ok,
        )

    if not allow_download:
        logger.info("executor missing, check-only mode: %s", target_str)
        return ProvisionStatus(
            installed=False,
            action=ACTION_MISSING,
            executor_path=target_str,
            detail="executor not installed and allow_download=False (check-only)",
        )

    max_bytes = PINNED_ZIP_SIZE_BYTES + 1
    temp_root = Path(tempfile.mkdtemp(prefix=_TEMP_DIR_PREFIX))
    try:
        zip_path = temp_root / PINNED_ZIP_FILENAME
        try:
            _download_streaming(
                PINNED_ASSET_URL,
                zip_path,
                max_bytes=max_bytes,
                timeout_s=timeout_s,
            )
        except ExecutorProvisionError as exc:
            return _failed(target_str, f"download failed: {exc}")

        zip_digest = _sha256_file(zip_path)
        if zip_digest != PINNED_ZIP_SHA256:
            return _failed(
                target_str,
                f"zip sha256 mismatch (got {zip_digest}, "
                f"want {PINNED_ZIP_SHA256}); temp files removed, "
                "target untouched",
            )

        try:
            exe_temp = _extract_executor(zip_path, temp_root)
        except (ExecutorProvisionError, zipfile.BadZipFile, OSError) as exc:
            return _failed(target_str, f"zip extraction failed: {exc}")

        exec_sha_ok = _sha256_file(exe_temp) == PINNED_EXECUTOR_SHA256
        version_ok = _pinned_version_ok(exe_temp)
        if not exec_sha_ok:
            return _failed(
                target_str,
                "extracted executor sha256 mismatch; temp files removed, "
                "target untouched",
                zip_sha_ok=True,
            )
        if not version_ok:
            return _failed(
                target_str,
                "extracted executor PE FileVersion is not 1.0.x; temp files "
                "removed, target untouched",
                zip_sha_ok=True,
                exec_sha_ok=True,
            )

        # Atomic install: temp file in the target directory, then os.replace.
        if target.exists():  # conservative: never race-replace a new file
            return _failed(
                target_str,
                "target appeared during provisioning; no-overwrite policy kept",
                zip_sha_ok=True,
                exec_sha_ok=True,
                version_ok=True,
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        handle, temp_name = tempfile.mkstemp(
            dir=str(target.parent), prefix=".wxc-exec-", suffix=".tmp"
        )
        os.close(handle)
        temp_target = Path(temp_name)
        try:
            shutil.copyfile(exe_temp, temp_target)
            os.replace(temp_target, target)
        except OSError:
            temp_target.unlink(missing_ok=True)
            raise
        logger.info("pinned executor installed: %s", target_str)
        return ProvisionStatus(
            installed=True,
            action=ACTION_DOWNLOADED,
            executor_path=target_str,
            detail=(
                f"downloaded release {PINNED_RELEASE_TAG} and installed "
                f"pinned-verified executor at {target_str}"
            ),
            zip_sha_ok=True,
            exec_sha_ok=True,
            version_ok=True,
        )
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    """CLI: ``--check`` (default, probe only) or ``--install``; JSON stdout."""
    parser = argparse.ArgumentParser(
        prog="python -m core.infrastructure.codex_sandbox.executor_provision",
        description=(
            "Provision the pinned MXC sandbox executor (wxc-exec.exe "
            f"{PINNED_RELEASE_TAG})."
        ),
    )
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument(
        "--check",
        action="store_true",
        help="report install state only; never downloads (default)",
    )
    actions.add_argument(
        "--install",
        action="store_true",
        help="download and install the pinned executor when missing",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit ProvisionStatus as JSON on stdout (output is always JSON)",
    )
    parser.add_argument(
        "--executor-path",
        default=None,
        help="override the default product install path",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="also log diagnostics to stderr (stdout stays pure JSON)",
    )
    args = parser.parse_args(argv)

    if args.verbose:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

    allow_download = bool(args.install)
    try:
        status = ensure_executor_installed(
            Path(args.executor_path) if args.executor_path else None,
            allow_download=allow_download,
        )
    except ExecutorProvisionError as exc:
        status = _failed(args.executor_path or "", str(exc))
    print(json.dumps(asdict(status), ensure_ascii=True, sort_keys=True))
    return 0 if status.installed else 1


if __name__ == "__main__":
    raise SystemExit(main())
