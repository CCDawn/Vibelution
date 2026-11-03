#!/usr/bin/env python3
"""Explicitly prepare or install a trusted sealed Windows desktop package."""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import json
import os
from pathlib import Path
import sys


# Preparing an offline package must not create Python caches or bootstrap config.
sys.dont_write_bytecode = True
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ValueError("Invalid install arguments")


def _absolute_directory(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts or not path.is_dir():
        raise ValueError("An existing absolute directory is required")
    # Preserve spelling: the sealed owner must reject symlinks/reparse points,
    # rather than receiving a resolved path that conceals them.
    return path


# One receipt line must still tell three different build failures apart.
FAILURE_PREFIX = "MANAGED_INSTALL_FAILED"
FAILURE_HEAD_MAX_CHARS = 500


def _failure_error(exc: BaseException, *, stage: str) -> str:
    """Format ``MANAGED_INSTALL_FAILED stage=<stage> <Type>: <first line>; tail: <output>``.

    The build chain tags its own exceptions with the exact stage and the tail
    of the captured process output; ``stage`` is the installer's coarse phase,
    used only when the exception carries no finer label.
    """

    stage = str(getattr(exc, "build_stage", "") or stage)
    message = str(exc).strip().splitlines()
    head = type(exc).__name__ + (f": {message[0][:FAILURE_HEAD_MAX_CHARS]}" if message else "")
    error = f"{FAILURE_PREFIX} stage={stage} {head}"
    tail = str(getattr(exc, "build_output_tail", "") or "").strip()
    return f"{error}; tail: {tail}" if tail else error


def main(argv: list[str] | None = None, *, managed_root: Path | None = None) -> int:
    """managed_root is a function-test seam, never a CLI or env setting."""
    stage = "arguments"
    try:
        parser = _Parser(description=__doc__, allow_abbrev=False)
        source = parser.add_mutually_exclusive_group(required=True)
        source.add_argument("--source-package", metavar="ABS")
        source.add_argument("--project", metavar="ABS")
        parser.add_argument("--apply", action="store_true")
        args = parser.parse_args(argv)
        if args.project and not args.apply:
            raise ValueError("Project builds require explicit apply")

        # The CLI emits one bounded JSON receipt, even if an owner emits logs.
        with open(os.devnull, "w", encoding="utf-8") as quiet, redirect_stdout(quiet):
            if args.project:
                project = _absolute_directory(args.project)
                from core.launcher.desktop_shell import build_desktop_shell_package

                stage = "node-build"
                built = build_desktop_shell_package(project, mode="dir")
                stage = "publish"
                if not isinstance(built, dict) or built.get("built") is not True or built.get("mode") != "dir":
                    raise ValueError("Desktop package build did not succeed")
                package = _absolute_directory(str(project / "dist/desktop/win-unpacked"))
            else:
                package = _absolute_directory(args.source_package)

            from core.launcher import managed_desktop_package as owner

            stage = "verify-apply"
            if args.apply:
                # Production uses the owner's OS KnownFolder root. No public
                # argument, environment variable or working directory selects it.
                active = (owner.install_managed_desktop_package(package) if managed_root is None
                          else owner.install_managed_desktop_package(package, managed_root=managed_root))
                receipt = {"schemaVersion": 1, "status": "installed", "packageId": active["packageId"]}
            else:
                prepared = owner.prepare_managed_desktop_package(package)
                receipt = {"schemaVersion": 1, "status": "prepared", "fileCount": len(prepared.files),
                           "bytes": sum(row["size"] for row in prepared.files),
                           "packageId": prepared.active["packageId"]}
    except Exception as exc:
        print(json.dumps({"schemaVersion": 1, "status": "failed", "error": _failure_error(exc, stage=stage)}))
        return 1
    print(json.dumps(receipt, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
