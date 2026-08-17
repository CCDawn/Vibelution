"""R0/R1 source-boundary helpers for Challenge Cup tracked resources.

Manifest entries are produced from ``git ls-files`` plus content hashes.
Reports never pre-fill PASS; missing files, hash drift, local paths, secrets
and unmanifested experiment sources fail closed.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import tarfile
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .resources import CORE_BEHAVIOR_HASH, CORE_POLICY_HASH

MANIFEST_KIND = "challenge_cup_submission_source_manifest"
SCHEMA_VERSION = 1
PROGRAM_CONTRACT_VERSION = "2.2.0"
CATALOG_POLICY_VERSION = "1.2.0"
MAX_ENTRY_BYTES = 5_000_000
FORBIDDEN_SUFFIXES = (".nwb", ".cubin", ".ptx", ".pkl", ".pt", ".bin", ".exe")
LOCAL_PATH_RE = re.compile(
    r"(?i)(?:[A-Za-z]:\\|/Users/|/home/|\\\\[A-Za-z]|"
    r"C:\\Users\\|Documents\\Vibelution\\data\\)"
)
SECRET_RE = re.compile(
    r"(?i)(?:api[_-]?key|secret|password|token)\s*=\s*['\"][^'\"]{8,}['\"]"
)
TEXT_SUFFIXES = {
    ".py",
    ".md",
    ".json",
    ".toml",
    ".txt",
    ".lock",
    ".yml",
    ".yaml",
    ".ts",
    ".tsx",
    ".css",
}

INCLUDE_GLOBS: tuple[str, ...] = (
    "core/research/competition/**",
    "core/research/experiment_adapters/**",
    "schemas/challenge_*.json",
    "experiments/challenge_cup_predictive_coding/fashion_mnist_smoke.py",
    "experiments/challenge_cup_predictive_coding/requirements-cpu.lock",
    "experiments/challenge_cup_gpu_operator/NOTICE.md",
    "experiments/challenge_cup_gpu_operator/fixtures/**",
    "experiments/challenge_cup_neural_spike/NOTICE.md",
    "experiments/challenge_cup_neural_spike/fixtures/**",
    "experiments/challenge_cup_spike_coding/README.md",
    "experiments/challenge_cup_spike_coding/NOTICE.md",
    "experiments/challenge_cup_spike_coding/data_manifest.example.json",
    "experiments/challenge_cup_spike_coding/sci096_*.py",
    "scripts/challenge_cup/**",
    "tests/test_competition_program_core_resources.py",
    "tests/test_platform_flow_readiness.py",
    "tests/test_challenge_cup_source_boundary.py",
    "tests/test_challenge_cup_submission_source_manifest_schema.py",
    "tests/test_challenge_cup_spike_coding_*.py",
    "tests/test_experiment_adapter_*.py",
)

REQUIRED_PATHS: tuple[str, ...] = (
    "core/research/competition/resources.py",
    "core/research/competition/data/science_125_questions.json",
    "core/research/experiment_adapters/gpu_operator.py",
    "core/research/experiment_adapters/neural_spike.py",
    "core/research/experiment_adapters/fashion_mnist.py",
    "schemas/challenge_cup_submission_source_manifest.schema.json",
    "experiments/challenge_cup_gpu_operator/NOTICE.md",
    "experiments/challenge_cup_gpu_operator/fixtures/cpu_correctness_v1.json",
    "experiments/challenge_cup_neural_spike/NOTICE.md",
    "experiments/challenge_cup_neural_spike/fixtures/dev_fixture_v1.json",
    "experiments/challenge_cup_predictive_coding/fashion_mnist_smoke.py",
    "experiments/challenge_cup_spike_coding/sci096_dandi_probe.py",
    "experiments/challenge_cup_spike_coding/sci096_dandi000121_adapter.py",
    "experiments/challenge_cup_spike_coding/sci096_dandi000121_multisession.py",
    "experiments/challenge_cup_spike_coding/sci096_epoch_discrimination.py",
    "scripts/challenge_cup/source_manifest.py",
    "scripts/challenge_cup/clean_clone_verify.py",
)

R1_PYTEST_TARGETS: tuple[str, ...] = (
    "tests/test_competition_program_core_resources.py",
    "tests/test_experiment_adapter_gpu_operator.py",
    "tests/test_experiment_adapter_neural_spike.py",
    "tests/test_experiment_adapter_fashion_mnist.py",
    "tests/test_challenge_cup_source_boundary.py",
    "tests/test_platform_flow_readiness.py",
)


class SourceBoundaryError(ValueError):
    """Source integrity or clean-clone verification failed."""


@dataclass(frozen=True, slots=True)
class SourceBoundaryPolicy:
    include_globs: tuple[str, ...] = INCLUDE_GLOBS
    required_paths: tuple[str, ...] = REQUIRED_PATHS
    r1_pytest_targets: tuple[str, ...] = R1_PYTEST_TARGETS
    max_entry_bytes: int = MAX_ENTRY_BYTES


DEFAULT_POLICY = SourceBoundaryPolicy()


def repo_schema_path(repo: Path) -> Path:
    return repo / "schemas" / "challenge_cup_submission_source_manifest.schema.json"


def posix_relpath(path: str) -> str:
    return path.replace("\\", "/")


def path_matches(path: str, pattern: str) -> bool:
    normalized = posix_relpath(path)
    glob = posix_relpath(pattern)
    if glob.endswith("/**"):
        prefix = glob[:-3].rstrip("/")
        return normalized == prefix or normalized.startswith(prefix + "/")
    return fnmatch.fnmatch(normalized, glob)


def classify_kind(path: str) -> str:
    normalized = posix_relpath(path)
    name = Path(normalized).name
    suffix = Path(normalized).suffix.lower()
    if name in {"NOTICE.md", "THIRD_PARTY_NOTICES.md"}:
        return "notice"
    if suffix == ".lock":
        return "lock"
    if "schema" in name and suffix == ".json":
        return "schema"
    if "/fixtures/" in f"/{normalized}/" or name.endswith(".example.json"):
        return "fixture"
    if normalized.startswith("tests/") or "/test_" in normalized:
        return "test"
    if suffix == ".md":
        return "documentation"
    return "source"


def classify_license(path: str) -> str:
    normalized = posix_relpath(path)
    if normalized.startswith("experiments/challenge_cup_spike_coding/"):
        return "reviewed_not_applicable"
    return "project_owned"


def provenance_for(path: str) -> str:
    normalized = posix_relpath(path)
    if normalized.startswith("experiments/challenge_cup_spike_coding/"):
        return "Reviewed SCI-096 reference implementation; raw DANDI data is not included"
    if normalized.startswith("experiments/challenge_cup_gpu_operator/"):
        return "SCI-091 DEV fixture; no CUDA kernels or timing claims"
    if normalized.startswith("experiments/challenge_cup_neural_spike/"):
        return "SCI-096 DEV fixture; no DANDI download or scientific conclusion"
    if normalized.startswith("core/research/competition/"):
        return "Tracked Challenge Cup competition contract"
    return "Vibelution project source"


def git_output(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "git command failed").strip()
        raise SourceBoundaryError(detail)
    return result.stdout


def git_ls_files(repo: Path, *pathspecs: str) -> tuple[str, ...]:
    args = ["ls-files", "-z", "--"]
    args.extend(pathspecs or [])
    raw = git_output(repo, *args)
    paths = [posix_relpath(item) for item in raw.split("\0") if item]
    return tuple(sorted(paths))


def git_is_dirty(repo: Path) -> bool:
    result = subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SourceBoundaryError((result.stderr or "git status failed").strip())
    return bool(result.stdout.strip())


def sha256_upper(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def selected_paths(tracked: Sequence[str], policy: SourceBoundaryPolicy) -> tuple[str, ...]:
    selected = [
        path
        for path in tracked
        if any(path_matches(path, pattern) for pattern in policy.include_globs)
    ]
    return tuple(sorted(dict.fromkeys(selected)))


def should_audit_path(path: str) -> bool:
    normalized = posix_relpath(path)
    if normalized.startswith(("tests/", "schemas/", "core/research/competition/data/")):
        return False
    if normalized.endswith("source_boundary.py"):
        return False
    return True


def audit_text(path: str, text: str) -> list[str]:
    failures: list[str] = []
    if LOCAL_PATH_RE.search(text):
        failures.append(f"machine-local path in {path}")
    if SECRET_RE.search(text):
        failures.append(f"secret-like assignment in {path}")
    return failures


def build_entry(repo: Path, path: str, *, max_entry_bytes: int) -> tuple[dict[str, Any], list[str]]:
    failures: list[str] = []
    normalized = posix_relpath(path)
    if normalized.startswith("/") or ".." in Path(normalized).parts or "\\" in path:
        failures.append(f"unsafe path {path}")
        return {}, failures
    lower = normalized.lower()
    if any(lower.endswith(suffix) for suffix in FORBIDDEN_SUFFIXES):
        failures.append(f"forbidden source suffix {normalized}")
    file_path = repo / Path(*normalized.split("/"))
    try:
        payload = file_path.read_bytes()
    except OSError as exc:
        failures.append(f"unreadable {normalized}: {exc}")
        return {}, failures
    size = len(payload)
    if size < 1:
        failures.append(f"empty file {normalized}")
    if size > max_entry_bytes:
        failures.append(f"oversized file {normalized}: {size} bytes")
    if file_path.suffix.lower() in TEXT_SUFFIXES or not file_path.suffix:
        try:
            if should_audit_path(normalized):
                failures.extend(audit_text(normalized, payload.decode("utf-8")))
        except UnicodeDecodeError:
            failures.append(f"non-utf8 text file {normalized}")
    if file_path.is_symlink():
        failures.append(f"symlink not allowed in source manifest: {normalized}")
    entry = {
        "path": normalized,
        "kind": classify_kind(normalized),
        "sha256": sha256_upper(payload),
        "sizeBytes": size,
        "provenance": provenance_for(normalized),
        "licenseStatus": classify_license(normalized),
        "requiredAtRuntime": normalized.startswith("core/research/")
        or normalized.startswith("schemas/"),
    }
    return entry, failures


def build_source_manifest(
    repo: Path,
    *,
    policy: SourceBoundaryPolicy = DEFAULT_POLICY,
    require_clean: bool = False,
) -> dict[str, Any]:
    repo = repo.resolve()
    failures: list[str] = []
    if require_clean and git_is_dirty(repo):
        raise SourceBoundaryError("working tree is dirty; refuse to freeze a source manifest")
    commit = git_output(repo, "rev-parse", "HEAD").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise SourceBoundaryError(f"HEAD is not a 40-character commit: {commit}")
    tracked = git_ls_files(repo)
    selected = selected_paths(tracked, policy)
    required_missing = [path for path in policy.required_paths if path not in tracked]
    if required_missing:
        failures.extend(f"required path is not tracked: {path}" for path in required_missing)
    experiment_tracked = [path for path in tracked if path.startswith("experiments/challenge_cup_")]
    unmanifested = [path for path in experiment_tracked if path not in selected]
    if unmanifested:
        failures.extend(
            f"unmanifested tracked experiment file: {path}" for path in unmanifested
        )
    entries: list[dict[str, Any]] = []
    for path in selected:
        entry, entry_failures = build_entry(
            repo, path, max_entry_bytes=policy.max_entry_bytes
        )
        failures.extend(entry_failures)
        if entry:
            entries.append(entry)
    if not entries:
        failures.append("source manifest has no entries")
    manifest = {
        "schemaVersion": SCHEMA_VERSION,
        "manifestKind": MANIFEST_KIND,
        "sourceCommit": commit,
        "programContract": {
            "version": PROGRAM_CONTRACT_VERSION,
            "coreBehaviorHash": CORE_BEHAVIOR_HASH,
        },
        "catalogPolicy": {
            "version": CATALOG_POLICY_VERSION,
            "corePolicyHash": CORE_POLICY_HASH,
        },
        "entries": entries,
    }
    schema_file = repo_schema_path(repo)
    if schema_file.is_file():
        schema = json.loads(schema_file.read_text(encoding="utf-8"))
        schema_errors = [
            error.message for error in Draft202012Validator(schema).iter_errors(manifest)
        ]
        failures.extend(f"schema: {message}" for message in schema_errors)
    if failures:
        raise SourceBoundaryError("; ".join(failures))
    return manifest


def extract_head_archive(repo: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(
        ["git", "-C", str(repo), "archive", "--format=tar", "HEAD"],
        stdout=subprocess.PIPE,
    )
    if proc.stdout is None:
        raise SourceBoundaryError("git archive produced no stdout")
    with tarfile.open(fileobj=proc.stdout, mode="r|") as archive:
        try:
            archive.extractall(dest, filter="data")
        except TypeError:
            archive.extractall(dest)
    if proc.wait() != 0:
        raise SourceBoundaryError("git archive failed")


def verify_manifest_on_tree(tree: Path, manifest: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    for entry in manifest.get("entries") or []:
        if not isinstance(entry, dict):
            failures.append("manifest entry is not an object")
            continue
        rel = posix_relpath(str(entry.get("path") or ""))
        file_path = tree / Path(*rel.split("/"))
        if not file_path.is_file():
            failures.append(f"clone missing {rel}")
            continue
        payload = file_path.read_bytes()
        actual = sha256_upper(payload)
        expected = str(entry.get("sha256") or "")
        if actual != expected:
            failures.append(f"hash mismatch {rel}: expected {expected}, got {actual}")
        if int(entry.get("sizeBytes") or 0) != len(payload):
            failures.append(f"size mismatch {rel}")
    return failures


def run_r1_pytest(tree: Path, *, python: str, targets: Sequence[str]) -> list[str]:
    existing = [item for item in targets if (tree / item).is_file()]
    missing = [item for item in targets if item not in existing]
    failures = [f"R1 test is missing from clone: {item}" for item in missing]
    if not existing:
        return failures or ["R1 pytest target list is empty"]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(tree)
    result = subprocess.run(
        [python, "-m", "pytest", *existing, "-q", "--tb=short"],
        cwd=tree,
        capture_output=True,
        text=True,
        env=env,
    )
    if result.returncode != 0:
        detail = (result.stdout or "")[-2000:] + (result.stderr or "")[-1000:]
        failures.append(f"R1 pytest failed ({result.returncode}): {detail.strip()}")
    return failures


def evaluate_source_integrity(
    repo: Path,
    *,
    policy: SourceBoundaryPolicy = DEFAULT_POLICY,
    require_clean: bool = False,
) -> dict[str, Any]:
    try:
        manifest = build_source_manifest(
            repo, policy=policy, require_clean=require_clean
        )
        return {
            "source_integrity": "PASS",
            "sourceCommit": manifest["sourceCommit"],
            "entryCount": len(manifest["entries"]),
            "manifest": manifest,
            "failures": [],
        }
    except SourceBoundaryError as exc:
        return {
            "source_integrity": "FAIL",
            "sourceCommit": "",
            "entryCount": 0,
            "manifest": None,
            "failures": [str(exc)],
        }


def evaluate_clean_clone(
    repo: Path,
    dest: Path,
    *,
    policy: SourceBoundaryPolicy = DEFAULT_POLICY,
    require_clean: bool = True,
    run_pytest: bool = False,
    python: str | None = None,
) -> dict[str, Any]:
    integrity = evaluate_source_integrity(
        repo, policy=policy, require_clean=require_clean
    )
    failures = list(integrity["failures"])
    clone_status = "FAIL"
    if integrity["source_integrity"] == "PASS" and integrity["manifest"] is not None:
        extract_head_archive(repo, dest)
        failures.extend(verify_manifest_on_tree(dest, integrity["manifest"]))
        if run_pytest:
            failures.extend(
                run_r1_pytest(
                    dest,
                    python=python or os.environ.get("PYTHON", "python"),
                    targets=policy.r1_pytest_targets,
                )
            )
        if not failures:
            clone_status = "PASS"
    return {
        "source_integrity": integrity["source_integrity"],
        "clean_clone_reproduction": clone_status,
        "sourceCommit": integrity["sourceCommit"],
        "entryCount": integrity["entryCount"],
        "failures": failures,
        "clonePath": str(dest),
        "manifest": integrity["manifest"],
    }
