#!/usr/bin/env python3
"""Resolve the read-only Python toolchain shared by linked Git worktrees.

Phase 1 deliberately does not create or mutate virtual environments.  A task
worktree may reuse the integration worktree's ``.venv`` only when both
``requirements.txt`` files have identical bytes and the interpreter is
healthy enough to report a stable Python identity.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.infrastructure.branch_workspace import resolve_branch_workspace

TOOLCHAIN_SCHEMA_VERSION = 1
ToolchainSource = Literal["checkout_venv", "integration_venv"]


class ValidationToolchainError(RuntimeError):
    """A stable, user-actionable validation toolchain resolution failure."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = str(detail).splitlines()[0].strip()[:500]
        super().__init__(f"{code}: {self.detail}" if self.detail else code)


@dataclass(frozen=True)
class PythonIdentity:
    implementation: str
    version: str
    cache_tag: str
    architecture: str
    distributions_sha256: str

    def snapshot(self) -> dict[str, str]:
        return {
            "implementation": self.implementation,
            "version": self.version,
            "cacheTag": self.cache_tag,
            "architecture": self.architecture,
            "distributionsSha256": self.distributions_sha256,
        }


@dataclass(frozen=True)
class ValidationToolchain:
    checkout_root: Path
    integration_root: Path
    python_executable: Path
    source: ToolchainSource
    requirements_sha256: str
    python_identity: PythonIdentity
    fingerprint: str

    def snapshot(self) -> dict[str, object]:
        return {
            "schemaVersion": TOOLCHAIN_SCHEMA_VERSION,
            "source": self.source,
            "fingerprint": self.fingerprint,
            "requirementsSha256": self.requirements_sha256,
            "pythonExecutable": str(self.python_executable),
            "integrationRoot": str(self.integration_root),
            "python": self.python_identity.snapshot(),
        }


def venv_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _requirements_sha256(path: Path) -> str:
    try:
        content = path.read_bytes()
    except OSError as error:
        raise ValidationToolchainError(
            "validation_toolchain_requirements_missing",
            f"cannot read {path}: {error}",
        ) from error
    return hashlib.sha256(content).hexdigest()


def _probe_python(python_executable: Path) -> PythonIdentity:
    probe = (
        "import hashlib,importlib.metadata,json,platform,re,sys;"
        "packages=sorted("
        "re.sub(r'[-_.]+','-',str(d.metadata.get('Name') or '')).lower()+'=='+d.version "
        "for d in importlib.metadata.distributions());"
        "print(json.dumps({"
        "'implementation':sys.implementation.name,"
        "'version':platform.python_version(),"
        "'cacheTag':sys.implementation.cache_tag or '',"
        "'architecture':platform.machine(),"
        "'distributionsSha256':hashlib.sha256(('\\n'.join(packages)).encode()).hexdigest()"
        "},sort_keys=True))"
    )
    kwargs: dict[str, object] = {}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    completed = subprocess.run(
        [str(python_executable), "-I", "-c", probe],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
        check=False,
        **kwargs,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(detail or f"python probe exited {completed.returncode}")
    payload = json.loads(completed.stdout)
    if not isinstance(payload, dict):
        raise RuntimeError("python probe returned a non-object payload")
    values = {
        key: str(payload.get(key) or "").strip()
        for key in (
            "implementation",
            "version",
            "cacheTag",
            "architecture",
            "distributionsSha256",
        )
    }
    if not all(values.values()):
        raise RuntimeError("python probe returned an incomplete identity")
    return PythonIdentity(
        implementation=values["implementation"],
        version=values["version"],
        cache_tag=values["cacheTag"],
        architecture=values["architecture"],
        distributions_sha256=values["distributionsSha256"],
    )


def _pip_check(python_executable: Path) -> None:
    kwargs: dict[str, object] = {}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    completed = subprocess.run(
        [str(python_executable), "-I", "-m", "pip", "check"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
        **kwargs,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(detail or f"pip check exited {completed.returncode}")


def _toolchain_fingerprint(
    requirements_sha256: str,
    identity: PythonIdentity,
) -> str:
    payload = {
        "schemaVersion": TOOLCHAIN_SCHEMA_VERSION,
        "requirementsSha256": requirements_sha256,
        "python": identity.snapshot(),
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def resolve_validation_toolchain(checkout: Path | str) -> ValidationToolchain:
    layout = resolve_branch_workspace(checkout)
    checkout_root = layout.worktree_root.resolve()
    integration_root = layout.integration_root.resolve()
    checkout_requirements = checkout_root / "requirements.txt"
    integration_requirements = integration_root / "requirements.txt"
    checkout_sha256 = _requirements_sha256(checkout_requirements)
    integration_sha256 = _requirements_sha256(integration_requirements)
    if checkout_sha256 != integration_sha256:
        raise ValidationToolchainError(
            "validation_toolchain_mismatch",
            "requirements.txt differs from the integration worktree; "
            "phase 1 refuses unsafe shared-environment reuse",
        )

    python_executable = venv_python(integration_root / ".venv").resolve()
    if not python_executable.is_file():
        raise ValidationToolchainError(
            "validation_toolchain_missing",
            f"integration worktree interpreter is missing: {python_executable}",
        )
    try:
        identity = _probe_python(python_executable)
        _pip_check(python_executable)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        raise ValidationToolchainError(
            "validation_toolchain_unhealthy",
            f"{python_executable}: {error}",
        ) from error

    source: ToolchainSource = (
        "checkout_venv"
        if checkout_root == integration_root
        else "integration_venv"
    )
    return ValidationToolchain(
        checkout_root=checkout_root,
        integration_root=integration_root,
        python_executable=python_executable,
        source=source,
        requirements_sha256=checkout_sha256,
        python_identity=identity,
        fingerprint=_toolchain_fingerprint(checkout_sha256, identity),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", type=Path, default=Path.cwd())
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        toolchain = resolve_validation_toolchain(args.checkout)
    except ValidationToolchainError as error:
        payload: dict[str, object] = {
            "ok": False,
            "error": error.code,
            "detail": error.detail,
        }
        exit_code = 1
    else:
        payload = {"ok": True, **toolchain.snapshot()}
        exit_code = 0
    if args.json:
        print(json.dumps(payload, ensure_ascii=True, sort_keys=True))
    elif payload["ok"]:
        print(payload["pythonExecutable"])
    else:
        print(f"{payload['error']}: {payload['detail']}", file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
