#!/usr/bin/env python3
"""Resolve the read-only Python toolchain shared by linked Git worktrees.

Phase 1 deliberately does not create or mutate virtual environments.  A task
worktree may reuse the integration worktree's ``.venv`` when that environment can
actually run the checkout: either both ``requirements.txt`` files are
byte-identical, or every requirement the checkout declares is already satisfied
there.

Comparing bytes alone refused safe reuse.  A comment edit, a reordered block, or a
bound the shared environment already meets all failed the gate even though the
interpreter was perfectly usable, which made dependency changes unlandable without
an environment rebuild.  The property that matters is satisfiability, so that is
what gets checked; a requirement the environment cannot satisfy still fails closed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Literal, Mapping, Sequence

from packaging.markers import default_environment
from packaging.requirements import InvalidRequirement, Requirement
from packaging.version import InvalidVersion, Version

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


def _run_captured(argv: list[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
    """Run a probe without a visible window and without inheriting stdin."""

    kwargs: dict[str, object] = {}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.run(
        argv,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
        **kwargs,
    )


def _normalize_distribution_name(name: str) -> str:
    """PEP 503 normalization, matching the key form the probes emit."""

    return re.sub(r"[-_.]+", "-", str(name)).lower()


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
    completed = _run_captured([str(python_executable), "-I", "-c", probe], timeout=15)
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


def _probe_distributions(python_executable: Path) -> dict[str, str]:
    """Return the interpreter's installed distributions as name -> version."""

    probe = (
        "import importlib.metadata,json,re;"
        "print(json.dumps({"
        "re.sub(r'[-_.]+','-',str(d.metadata.get('Name') or '')).lower(): d.version "
        "for d in importlib.metadata.distributions()"
        "},sort_keys=True))"
    )
    completed = _run_captured([str(python_executable), "-I", "-c", probe], timeout=30)
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(detail or f"distribution probe exited {completed.returncode}")
    payload = json.loads(completed.stdout)
    if not isinstance(payload, dict):
        raise RuntimeError("distribution probe returned a non-object payload")
    return {
        _normalize_distribution_name(str(name)): str(version).strip()
        for name, version in payload.items()
    }


def _pip_check(python_executable: Path) -> None:
    completed = _run_captured(
        [str(python_executable), "-I", "-m", "pip", "check"],
        timeout=30,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(detail or f"pip check exited {completed.returncode}")


_REQUIREMENT_COMMENT = re.compile(r"(^|\s)#")


def _iter_requirement_lines(
    path: Path,
    _seen: frozenset[Path] = frozenset(),
) -> Iterator[str]:
    """Yield logical requirement lines from a requirements file.

    Comments (a ``#`` at line start or after whitespace, so a URL fragment
    survives), blank lines, and backslash continuations are resolved, and
    ``-r``/``--requirement`` includes are followed recursively.  Anything else
    is yielded verbatim so the caller can report it as unverifiable.
    """

    resolved = path.resolve()
    if resolved in _seen:
        raise ValueError(f"requirements include cycle at {resolved}")
    try:
        text = resolved.read_text(encoding="utf-8")
    except OSError as error:
        raise ValueError(f"cannot read {resolved}: {error}") from error

    pending = ""
    for raw in text.splitlines():
        comment = _REQUIREMENT_COMMENT.search(raw)
        line = (raw[: comment.start(1)] if comment else raw).strip()
        if pending:
            line = f"{pending} {line}".strip()
            pending = ""
        if not line:
            continue
        if line.endswith("\\"):
            pending = line[:-1].strip()
            continue
        if line.startswith("-r") or line.startswith("--requirement"):
            parts = line.split(None, 1)
            if len(parts) == 2:
                yield from _iter_requirement_lines(
                    (resolved.parent / parts[1].strip()).resolve(),
                    _seen | {resolved},
                )
                continue
        yield line
    if pending:
        raise ValueError(f"dangling line continuation in {resolved}")


def _unsatisfied_requirements(
    requirements_path: Path,
    installed: Mapping[str, str],
) -> list[str]:
    """Return one human-readable reason per requirement the environment misses."""

    try:
        lines = list(_iter_requirement_lines(requirements_path))
    except ValueError as error:
        return [str(error)]

    reasons: list[str] = []
    marker_environment = default_environment()
    for line in lines:
        try:
            requirement = Requirement(line)
        except InvalidRequirement:
            reasons.append(f"{line} (unverifiable requirement line)")
            continue
        if requirement.url:
            reasons.append(f"{line} (direct URL reference is unverifiable)")
            continue
        if requirement.marker is not None and not requirement.marker.evaluate(
            marker_environment
        ):
            continue
        current = installed.get(_normalize_distribution_name(requirement.name))
        if current is None:
            reasons.append(f"{line} (not installed)")
            continue
        try:
            if Version(current) not in requirement.specifier:
                reasons.append(f"{line} (installed {current})")
        except InvalidVersion:
            reasons.append(f"{line} (unparsable installed version {current!r})")
    return reasons


def _assert_requirements_satisfied(
    requirements_path: Path,
    python_executable: Path,
) -> None:
    """Refuse reuse the installed distributions cannot honour."""

    installed = _probe_distributions(python_executable)
    reasons = _unsatisfied_requirements(requirements_path, installed)
    if not reasons:
        return
    shown = "; ".join(reasons[:3])
    more = "" if len(reasons) <= 3 else f" (+{len(reasons) - 3} more)"
    raise ValidationToolchainError(
        "validation_toolchain_mismatch",
        f"{requirements_path.name} is not satisfied by the shared environment: "
        f"{shown}{more}",
    )


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

    python_executable = venv_python(integration_root / ".venv").resolve()
    if not python_executable.is_file():
        raise ValidationToolchainError(
            "validation_toolchain_missing",
            f"integration worktree interpreter is missing: {python_executable}",
        )
    try:
        identity = _probe_python(python_executable)
        _pip_check(python_executable)
        if checkout_sha256 != integration_sha256:
            # The files differ, so reuse is safe only if the shared environment
            # already satisfies what this checkout declares. Identical bytes need
            # no probe: that is the pre-existing contract for every other task.
            _assert_requirements_satisfied(checkout_requirements, python_executable)
    except ValidationToolchainError:
        raise
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
