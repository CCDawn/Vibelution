#!/usr/bin/env python3
"""Launcher-owned, no-Workbench assistant process entry point."""

from __future__ import annotations

import argparse
import json
import ntpath
import os
import re
import socket
import sys
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE_ROOT))


def _namespace_windows_import_paths() -> None:
    """Keep the same isolated search locations usable below long install roots.

    CPython's relative _pth entries lose the executable's extended-path prefix.
    SDK resource imports can then fail at MAX_PATH and leave partially imported
    modules behind. Change only the spelling of existing absolute locations.
    """
    if os.name != "nt" or not sys.flags.isolated:
        return
    def extended(value: str) -> str:
        if not ntpath.isabs(value) or value.startswith(("\\\\?\\", "\\\\.\\")):
            return value
        normalized = ntpath.normpath(value)
        if normalized.startswith("\\\\"):
            return "\\\\?\\UNC\\" + normalized[2:]
        drive, tail = ntpath.splitdrive(normalized)
        return "\\\\?\\" + normalized if drive and tail.startswith("\\") else value
    sys.path[:] = [extended(value) for value in sys.path]


def _seed_tokenizer_cache(cache: Path) -> None:
    """Keep SDK caches writable without changing installed or packaged bytes."""
    from importlib.metadata import PackageNotFoundError, distribution
    cache.mkdir(parents=True, exist_ok=True)
    try:
        bundled = Path(distribution("litellm").locate_file("litellm/litellm_core_utils/tokenizers"))
    except PackageNotFoundError:
        return
    for source in bundled.glob("*"):
        if not re.fullmatch(r"[0-9a-f]{40}", source.name) or not source.is_file() or source.stat().st_size > 32 * 1024 * 1024:
            continue
        try:
            with (cache / source.name).open("xb") as target:
                # tiktoken validates the upstream LF table hash on use. Some
                # wheels ship CRLF; normalize only the private cache copy.
                target.write(source.read_bytes().replace(b"\r\n", b"\n"))
        except FileExistsError:
            pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile-root", required=True, type=Path)
    parser.add_argument("--runtime-dir", required=True, type=Path)
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--projects-file", type=Path)
    args = parser.parse_args()
    if not args.profile_root.is_absolute() or not args.runtime_dir.is_absolute():
        parser.error("Assistant paths must be absolute")
    token = os.environ.pop("VIBELUTION_ASSISTANT_TOKEN", "")
    if len(token) < 32:
        parser.error("Launcher private bootstrap credential is missing")
    root = args.profile_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    args.runtime_dir.mkdir(parents=True, exist_ok=True)
    os.environ["VIBELUTION_PROCESS_ROLE"] = "launcher_assistant"
    os.environ["VIBELUTION_ASSISTANT_NATIVE_ROOT"] = str(root)
    os.environ["VIBELUTION_DATA_HOME"] = str(root / "data")
    tokenizer_cache = root / "cache" / "tiktoken"
    os.environ["CUSTOM_TIKTOKEN_CACHE_DIR"] = str(tokenizer_cache)
    os.environ["TIKTOKEN_CACHE_DIR"] = str(tokenizer_cache)
    os.environ["HF_HOME"] = str(root / "cache" / "huggingface")
    # Provider/config references may be inherited. Workbench transport identity
    # must not become this independent runtime's default control context.
    for name in ("VIBELUTION_WEB_CONTROL_TOKEN", "VIBELUTION_PORT", "VIBELUTION_WORKBENCH_URL"):
        os.environ.pop(name, None)
    _namespace_windows_import_paths()
    project_snapshot = {"schemaVersion": 1, "revision": 0, "projects": {}}
    if args.projects_file is not None:
        if not args.projects_file.is_absolute():
            parser.error("Project registry file must be absolute")
        project_snapshot = json.loads(args.projects_file.read_text(encoding="utf-8"))

    # All native/config imports follow the immutable process binding above.
    import uvicorn

    from core.assistant_runtime.dispatch import DispatchError, DispatchService
    from core.assistant_runtime.host import NativeFacade, create_app
    from core.infrastructure.atomic_io import atomic_write_json
    from core.infrastructure.file_lock import cross_process_file_lock

    dispatch = DispatchService(root, {})
    try:
        dispatch.replace_projects(project_snapshot)
    except DispatchError:
        parser.error("Invalid private project registry snapshot")

    ready = args.runtime_dir / "ready.json"
    # A second Launcher cannot open another writer over the same profile.
    # OS locking releases on crashes; no PID-age heuristic transfers ownership.
    with cross_process_file_lock(root / "host-owner", timeout=0):
        _seed_tokenizer_cache(tokenizer_cache)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

        def publish_ready():
            atomic_write_json(ready, {"protocolVersion": 1, "role": "launcher_assistant",
                "instanceId": args.instance_id, "pid": os.getpid(), "port": port}, strict_replace=True)

        server = None
        def request_shutdown():
            if server is not None:
                server.should_exit = True

        app = create_app(native=NativeFacade(root), token=token,
                         dispatch=dispatch, on_ready=publish_ready,
                         on_shutdown=request_shutdown)
        # Native SSE is intentionally long lived. Bound HTTP connection drain
        # so an open renderer stream cannot prevent lifespan/native shutdown.
        # Two HTTP seconds plus native's eight-second drain fit main's deadline.
        server = uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False,
                                               timeout_graceful_shutdown=2))
        try:
            server.run(sockets=[sock])
        finally:
            sock.close()
            ready.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
