"""Fail-closed runtime-data isolation for session benchmark tooling."""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
from pathlib import Path
from typing import Any

from core.ui.chat_state import formal_chat_state_path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT_SENTINEL = ".vibelution-session-benchmark-root.json"
DATA_ROOT_SENTINEL_PAYLOAD = {
    "schemaVersion": 1,
    "purpose": "vibelution_session_query_benchmark",
    "storageClass": "disposable_test_data",
}
SYNTHETIC_SESSION_ID = re.compile(r"^session-\d{5}$")


class BenchmarkIsolationError(RuntimeError):
    """Raised before or after a benchmark when operator isolation is unsafe."""


def formal_operator_workspace() -> Path:
    return formal_chat_state_path(PROJECT_ROOT).parent.parent.resolve(strict=False)


def is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(parent.resolve(strict=False))
    except ValueError:
        return False
    return True


def paths_overlap(left: Path, right: Path) -> bool:
    return is_within(left, right) or is_within(right, left)


def git_primary_checkout_root() -> Path | None:
    dot_git = PROJECT_ROOT / ".git"
    if dot_git.is_dir():
        return PROJECT_ROOT.resolve(strict=False)
    if not dot_git.is_file():
        return None
    first_line = dot_git.read_text(encoding="utf-8").splitlines()[0].strip()
    if not first_line.lower().startswith("gitdir:"):
        return None
    git_dir = Path(first_line.split(":", 1)[1].strip())
    if not git_dir.is_absolute():
        git_dir = (PROJECT_ROOT / git_dir).resolve(strict=False)
    common_dir_path = git_dir / "commondir"
    if not common_dir_path.is_file():
        return None
    common_dir = Path(common_dir_path.read_text(encoding="utf-8").strip())
    if not common_dir.is_absolute():
        common_dir = (git_dir / common_dir).resolve(strict=False)
    return common_dir.parent.resolve(strict=False)


def launcher_mount_roots() -> set[Path]:
    checkout_roots = {PROJECT_ROOT.resolve(strict=False)}
    primary_root = git_primary_checkout_root()
    if primary_root is not None:
        checkout_roots.add(primary_root)
    mounted: set[Path] = set()
    for checkout_root in checkout_roots:
        state_path = checkout_root / ".runtime" / "launcher" / "state.json"
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            continue
        observed = str(state.get("observedState") or "").strip().lower()
        runtime_root = str(state.get("runtimeProjectRoot") or "").strip()
        if observed not in {"open", "opening", "starting"} or not runtime_root:
            continue
        mounted.add(Path(runtime_root).resolve(strict=False))
    return mounted


def validate_data_root_location(data_root: Path) -> Path:
    if data_root.is_symlink():
        raise BenchmarkIsolationError("data root must not be a symlink")
    resolved = data_root.resolve(strict=True)
    if not resolved.is_dir():
        raise BenchmarkIsolationError("data root must be an existing directory")
    system_temp = Path(tempfile.gettempdir()).resolve(strict=True)
    if resolved == system_temp or not is_within(resolved, system_temp):
        raise BenchmarkIsolationError(
            "data root must be an explicit child of the system temporary directory"
        )
    operator_workspace = formal_operator_workspace()
    if paths_overlap(resolved, operator_workspace):
        raise BenchmarkIsolationError(
            "data root overlaps the operator formal workspace"
        )
    if paths_overlap(resolved, PROJECT_ROOT):
        raise BenchmarkIsolationError(
            "data root overlaps the source checkout instead of temporary storage"
        )
    for mounted_root in launcher_mount_roots():
        if paths_overlap(resolved, mounted_root):
            raise BenchmarkIsolationError(
                "data root overlaps a project currently mounted by Launcher"
            )
    return resolved


def initialize_benchmark_data_root(data_root: Path) -> Path:
    resolved = validate_data_root_location(data_root)
    sentinel_path = resolved / DATA_ROOT_SENTINEL
    temporary_path = resolved / f"{DATA_ROOT_SENTINEL}.tmp"
    temporary_path.write_text(
        f"{json.dumps(DATA_ROOT_SENTINEL_PAYLOAD, ensure_ascii=False, indent=2)}\n",
        encoding="utf-8",
    )
    temporary_path.replace(sentinel_path)
    return sentinel_path


def validate_data_root(data_root: Path) -> Path:
    resolved = validate_data_root_location(data_root)
    sentinel_path = resolved / DATA_ROOT_SENTINEL
    try:
        sentinel = json.loads(sentinel_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
        raise BenchmarkIsolationError(
            f"data root is missing the required {DATA_ROOT_SENTINEL} sentinel"
        ) from exc
    if sentinel != DATA_ROOT_SENTINEL_PAYLOAD:
        raise BenchmarkIsolationError("data root sentinel does not match benchmark policy")
    return resolved


def _sha256_or_missing(path: Path) -> str:
    if not path.is_file():
        return "missing"
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _directory_names_sha256(path: Path) -> str:
    if not path.is_dir():
        return "missing"
    names = sorted(item.name for item in path.iterdir() if item.is_dir())
    return hashlib.sha256(
        json.dumps(names, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _json_mapping(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def operator_state_snapshot() -> dict[str, Any]:
    workspace = formal_operator_workspace()
    protected_files = {
        "chatState": workspace / "chat" / "chat_state.json",
        "agents": workspace / "agents" / "agents.json",
        "modeBindings": workspace / "agent_config" / "mode_bindings.json",
    }
    protected_directories = {
        "sessionDirectoryNames": workspace / "sessions",
        "agentDirectoryNames": workspace / "agents",
    }
    chat_state = _json_mapping(protected_files["chatState"])
    agent_directory = _json_mapping(protected_files["agents"])
    conversations = chat_state.get("conversations")
    agents = agent_directory.get("agents")
    tool_policies = agent_directory.get("toolPolicies")
    memory_policies = agent_directory.get("memoryPolicies")
    conversations = conversations if isinstance(conversations, list) else []
    agents = agents if isinstance(agents, list) else []
    tool_policies = tool_policies if isinstance(tool_policies, dict) else {}
    memory_policies = memory_policies if isinstance(memory_policies, dict) else {}
    return {
        "files": {
            key: _sha256_or_missing(path)
            for key, path in protected_files.items()
        },
        "directories": {
            key: _directory_names_sha256(path)
            for key, path in protected_directories.items()
        },
        "counts": {
            "conversations": len(conversations),
            "agents": len(agents),
            "toolPolicies": len(tool_policies),
            "memoryPolicies": len(memory_policies),
            "sessionDirectories": (
                len(list(protected_directories["sessionDirectoryNames"].iterdir()))
                if protected_directories["sessionDirectoryNames"].is_dir()
                else 0
            ),
            "agentDirectories": (
                len(
                    [
                        item
                        for item in protected_directories[
                            "agentDirectoryNames"
                        ].iterdir()
                        if item.is_dir()
                    ]
                )
                if protected_directories["agentDirectoryNames"].is_dir()
                else 0
            ),
        },
        "policyHashes": {
            "toolPolicies": canonical_sha256(tool_policies),
            "memoryPolicies": canonical_sha256(memory_policies),
        },
        "anomalies": {
            "syntheticSessionIds": sum(
                1
                for item in conversations
                if isinstance(item, dict)
                and SYNTHETIC_SESSION_ID.fullmatch(
                    str(item.get("conversation_id") or item.get("id") or "")
                )
            ),
            "sessionRepairAgents": sum(
                1
                for item in agents
                if isinstance(item, dict)
                and str(item.get("createdBy") or "") == "session_repair"
            ),
        },
    }


def assert_operator_state_unchanged(
    before: dict[str, Any],
    after: dict[str, Any],
) -> None:
    if before != after:
        raise BenchmarkIsolationError(
            "operator state changed while the isolated benchmark was running"
        )


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    temporary_path = path.with_name(f"{path.name}.tmp")
    temporary_path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    temporary_path.replace(path)


def validate_output_path(output_path: Path, *, data_root: Path) -> Path:
    if output_path.is_symlink():
        raise BenchmarkIsolationError("output path must not be a symlink")
    resolved_root = validate_data_root(data_root)
    resolved_parent = output_path.parent.resolve(strict=True)
    if not resolved_parent.is_dir():
        raise BenchmarkIsolationError("output parent must be an existing directory")
    resolved_output = resolved_parent / output_path.name
    if not is_within(resolved_output, resolved_root):
        raise BenchmarkIsolationError(
            "output path must remain inside the explicit temporary data root"
        )
    if paths_overlap(resolved_output, formal_operator_workspace()):
        raise BenchmarkIsolationError("output path overlaps operator storage")
    return resolved_output
