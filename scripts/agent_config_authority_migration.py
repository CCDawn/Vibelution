"""Offline, fail-closed migration for canonical Agent configuration identity.

The tool never resolves its target from operator configuration or environment
variables. It accepts only an explicit sentinel-marked data root under the
system temporary directory and defaults to a read-only dry run.
"""

from __future__ import annotations

import argparse
import copy
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.web.services.agent_config_authority import (  # noqa: E402
    AGENT_CONFIG_SCHEMA_VERSION,
    DEFAULT_PERMISSION_PRESET,
    materialize_agent_config_identity,
)
from scripts import session_benchmark_isolation as isolation  # noqa: E402


DATA_ROOT_SENTINEL = ".vibelution-agent-config-migration-root.json"
DATA_ROOT_SENTINEL_PAYLOAD = {
    "schemaVersion": 1,
    "purpose": "vibelution_agent_config_authority_migration",
    "storageClass": "isolated_migration_fixture",
}
REGISTRY_RELATIVE_PATH = Path("workspace") / "agents" / "agents.json"
ARTIFACTS_RELATIVE_PATH = Path(".migration") / "agent-config"


class AgentConfigMigrationError(RuntimeError):
    """Raised before a migration can touch its explicit isolated target."""


@dataclass(frozen=True)
class _MigrationPlan:
    data_root: Path
    registry_path: Path
    input_bytes: bytes
    candidate_bytes: bytes
    public_payload: dict[str, Any]


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _bytes_sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _translate_isolation_error(exc: Exception) -> AgentConfigMigrationError:
    return AgentConfigMigrationError(str(exc))


def _validate_data_root_location(data_root: Path) -> Path:
    try:
        resolved = isolation.validate_data_root_location(Path(data_root))
    except isolation.BenchmarkIsolationError as exc:
        raise _translate_isolation_error(exc) from exc
    formal_data_root = isolation.formal_operator_workspace().parent.resolve(
        strict=False
    )
    if isolation.paths_overlap(resolved, formal_data_root):
        raise AgentConfigMigrationError(
            "data root overlaps the operator formal data root"
        )
    return resolved


def initialize_migration_data_root(data_root: Path) -> Path:
    """Install the migration-specific sentinel inside an isolated temp root."""

    resolved = _validate_data_root_location(data_root)
    sentinel_path = resolved / DATA_ROOT_SENTINEL
    _strict_atomic_write(
        sentinel_path,
        f"{json.dumps(DATA_ROOT_SENTINEL_PAYLOAD, ensure_ascii=False, indent=2)}\n".encode(
            "utf-8"
        ),
    )
    return sentinel_path


def validate_migration_data_root(data_root: Path) -> Path:
    resolved = _validate_data_root_location(data_root)
    sentinel_path = resolved / DATA_ROOT_SENTINEL
    if sentinel_path.is_symlink():
        raise AgentConfigMigrationError("data root sentinel must not be a symlink")
    try:
        sentinel = json.loads(sentinel_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
        raise AgentConfigMigrationError(
            f"data root is missing the required {DATA_ROOT_SENTINEL} sentinel"
        ) from exc
    if sentinel != DATA_ROOT_SENTINEL_PAYLOAD:
        raise AgentConfigMigrationError(
            "data root sentinel does not match Agent config migration policy"
        )
    return resolved


def _registry_path(data_root: Path) -> Path:
    candidate = data_root / REGISTRY_RELATIVE_PATH
    if candidate.is_symlink():
        raise AgentConfigMigrationError("Agent registry must not be a symlink")
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as exc:
        raise AgentConfigMigrationError(
            f"Agent registry does not exist: {REGISTRY_RELATIVE_PATH.as_posix()}"
        ) from exc
    if not resolved.is_file():
        raise AgentConfigMigrationError("Agent registry must be a regular file")
    if not isolation.is_within(resolved, data_root):
        raise AgentConfigMigrationError(
            "Agent registry escaped the explicit migration data root"
        )
    return resolved


def _load_registry(registry_path: Path) -> tuple[bytes, dict[str, Any]]:
    try:
        input_bytes = registry_path.read_bytes()
        payload = json.loads(input_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AgentConfigMigrationError("Agent registry is not valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise AgentConfigMigrationError("Agent registry must be a JSON object")
    agents = payload.get("agents")
    if not isinstance(agents, list):
        raise AgentConfigMigrationError("Agent registry requires an agents list")
    seen_ids: set[str] = set()
    for agent in agents:
        if not isinstance(agent, dict):
            raise AgentConfigMigrationError("Agent registry contains a non-object Agent")
        agent_id = str(agent.get("agentId") or "").strip()
        if not agent_id:
            raise AgentConfigMigrationError("Every Agent requires an agentId")
        if agent_id in seen_ids:
            raise AgentConfigMigrationError(
                "Agent registry contains duplicate agentId values"
            )
        seen_ids.add(agent_id)
    return input_bytes, payload


def _build_plan(*, data_root: Path) -> _MigrationPlan:
    resolved_root = validate_migration_data_root(data_root)
    registry_path = _registry_path(resolved_root)
    input_bytes, source = _load_registry(registry_path)
    candidate = copy.deepcopy(source)
    source_agents = source["agents"]
    candidate_agents = candidate["agents"]
    changed_count = 0
    agent_prefixed = 0
    session_repair_count = 0
    for source_agent, candidate_agent in zip(
        source_agents,
        candidate_agents,
        strict=True,
    ):
        agent_id = str(source_agent.get("agentId") or "").strip()
        if agent_id.startswith("agent-"):
            agent_prefixed += 1
        if str(source_agent.get("createdBy") or "").strip() == "session_repair":
            session_repair_count += 1
        previous_hash = str(candidate_agent.get("configHash") or "").strip()
        materialize_agent_config_identity(
            candidate_agent,
            increment_if_changed=bool(previous_hash),
            previous_hash=previous_hash,
        )
        if candidate_agent != source_agent:
            changed_count += 1

    if changed_count:
        candidate_bytes = (
            f"{json.dumps(candidate, ensure_ascii=False, indent=2)}\n".encode("utf-8")
        )
    else:
        candidate_bytes = input_bytes
    tool_policies_before = (
        source.get("toolPolicies")
        if isinstance(source.get("toolPolicies"), dict)
        else {}
    )
    memory_policies_before = (
        source.get("memoryPolicies")
        if isinstance(source.get("memoryPolicies"), dict)
        else {}
    )
    tool_policies_after = (
        candidate.get("toolPolicies")
        if isinstance(candidate.get("toolPolicies"), dict)
        else {}
    )
    memory_policies_after = (
        candidate.get("memoryPolicies")
        if isinstance(candidate.get("memoryPolicies"), dict)
        else {}
    )
    manifest: dict[str, Any] = {
        "schemaVersion": 1,
        "operation": "agent_config_authority_migration",
        "dataRoot": str(resolved_root),
        "targetPath": str(registry_path),
        "objectCount": len(source_agents),
        "changedAgentCount": changed_count,
        "unchangedAgentCount": len(source_agents) - changed_count,
        "agentIdPatternCounts": {
            "agentPrefixed": agent_prefixed,
            "other": len(source_agents) - agent_prefixed,
        },
        "anomalies": {
            "sessionRepairAgents": session_repair_count,
        },
        "inputSha256": _bytes_sha256(input_bytes),
        "candidateSha256": _bytes_sha256(candidate_bytes),
        "policyHashesBefore": {
            "toolPolicies": _canonical_sha256(tool_policies_before),
            "memoryPolicies": _canonical_sha256(memory_policies_before),
        },
        "policyHashesAfter": {
            "toolPolicies": _canonical_sha256(tool_policies_after),
            "memoryPolicies": _canonical_sha256(memory_policies_after),
        },
        "targetConfigSchemaVersion": AGENT_CONFIG_SCHEMA_VERSION,
        "defaultPermissionPreset": DEFAULT_PERMISSION_PRESET,
        "writeContract": "backup_then_strict_atomic_replace",
    }
    manifest["manifestHash"] = _canonical_sha256(manifest)
    blocked = session_repair_count > 0
    public_payload = {
        "schemaVersion": 1,
        "status": "blocked" if blocked else "dry_run",
        "applyAllowed": not blocked,
        "blockReasons": (
            ["createdBy=session_repair records require separate quarantine review"]
            if blocked
            else []
        ),
        "manifest": manifest,
    }
    return _MigrationPlan(
        data_root=resolved_root,
        registry_path=registry_path,
        input_bytes=input_bytes,
        candidate_bytes=candidate_bytes,
        public_payload=public_payload,
    )


def plan_agent_config_migration(*, data_root: Path) -> dict[str, Any]:
    """Return a deterministic, read-only migration manifest."""

    return copy.deepcopy(_build_plan(data_root=data_root).public_payload)


def _artifact_root(data_root: Path, manifest_hash: str) -> Path:
    root = (data_root / ARTIFACTS_RELATIVE_PATH / manifest_hash[:24]).resolve(
        strict=False
    )
    if not isolation.is_within(root, data_root):
        raise AgentConfigMigrationError(
            "migration artifact path escaped the explicit data root"
        )
    return root


def _read_json_mapping(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _recover_completed_apply(
    *,
    data_root: Path,
    registry_path: Path,
    approved_manifest_hash: str,
) -> dict[str, Any] | None:
    artifact_root = _artifact_root(data_root, approved_manifest_hash)
    apply_manifest_path = artifact_root / "apply-manifest.json"
    apply_manifest = _read_json_mapping(apply_manifest_path)
    if (
        str(apply_manifest.get("manifestHash") or "") != approved_manifest_hash
        or not apply_manifest.get("outputSha256")
    ):
        return None
    try:
        current_sha = _bytes_sha256(registry_path.read_bytes())
        backup_sha = _bytes_sha256(
            (artifact_root / "backup" / "agents.json").read_bytes()
        )
    except OSError:
        return None
    if (
        current_sha != str(apply_manifest.get("outputSha256") or "")
        or backup_sha != str(apply_manifest.get("backupSha256") or "")
    ):
        return None
    if str(apply_manifest.get("status") or "") != "applied":
        apply_manifest["status"] = "applied"
        apply_manifest["recoveredAt"] = _utc_now_iso()
        _strict_atomic_write(
            apply_manifest_path,
            f"{json.dumps(apply_manifest, ensure_ascii=False, indent=2)}\n".encode(
                "utf-8"
            ),
        )
    return {
        "schemaVersion": 1,
        "status": "already_applied",
        "manifestHash": approved_manifest_hash,
        "artifactRoot": str(artifact_root),
        "targetPath": str(registry_path),
    }


def apply_agent_config_migration(
    *,
    data_root: Path,
    approved_manifest_hash: str,
) -> dict[str, Any]:
    """Apply only the exact previously reviewed plan to an isolated fixture."""

    normalized_hash = str(approved_manifest_hash or "").strip().lower()
    if not normalized_hash:
        raise AgentConfigMigrationError(
            "apply requires the matching dry-run manifest hash"
        )
    plan = _build_plan(data_root=data_root)
    current_hash = str(plan.public_payload["manifest"]["manifestHash"])
    if not secrets.compare_digest(normalized_hash, current_hash):
        recovered = _recover_completed_apply(
            data_root=plan.data_root,
            registry_path=plan.registry_path,
            approved_manifest_hash=normalized_hash,
        )
        if recovered is not None:
            return recovered
        raise AgentConfigMigrationError(
            "apply requires the matching dry-run manifest hash"
        )
    anomaly_count = int(
        plan.public_payload["manifest"]["anomalies"]["sessionRepairAgents"]
    )
    if anomaly_count:
        raise AgentConfigMigrationError(
            "createdBy=session_repair Agents are blocked from config migration"
        )
    if plan.input_bytes == plan.candidate_bytes:
        return {
            "schemaVersion": 1,
            "status": "already_current",
            "manifestHash": current_hash,
            "artifactRoot": "",
            "targetPath": str(plan.registry_path),
        }

    artifact_root = _artifact_root(plan.data_root, current_hash)
    backup_path = artifact_root / "backup" / "agents.json"
    quarantine_path = artifact_root / "quarantine" / "index.json"
    apply_manifest_path = artifact_root / "apply-manifest.json"
    if backup_path.exists():
        if _bytes_sha256(backup_path.read_bytes()) != _bytes_sha256(plan.input_bytes):
            raise AgentConfigMigrationError(
                "existing migration backup does not match the approved input"
            )
    else:
        _strict_atomic_write(backup_path, plan.input_bytes)
    quarantine_payload = {
        "schemaVersion": 1,
        "reason": "no records quarantined by config authority migration",
        "entries": [],
    }
    _strict_atomic_write(
        quarantine_path,
        f"{json.dumps(quarantine_payload, ensure_ascii=False, indent=2)}\n".encode(
            "utf-8"
        ),
    )
    apply_manifest = {
        "schemaVersion": 1,
        "status": "prepared",
        "preparedAt": _utc_now_iso(),
        "manifestHash": current_hash,
        "targetPath": str(plan.registry_path),
        "backupPath": str(backup_path),
        "backupSha256": _bytes_sha256(plan.input_bytes),
        "outputSha256": _bytes_sha256(plan.candidate_bytes),
        "dryRunManifest": plan.public_payload["manifest"],
    }
    _strict_atomic_write(
        apply_manifest_path,
        f"{json.dumps(apply_manifest, ensure_ascii=False, indent=2)}\n".encode(
            "utf-8"
        ),
    )
    if _bytes_sha256(plan.registry_path.read_bytes()) != _bytes_sha256(plan.input_bytes):
        raise AgentConfigMigrationError(
            "Agent registry changed after dry-run planning; no write was applied"
        )
    _strict_atomic_write(plan.registry_path, plan.candidate_bytes)
    output_sha = _bytes_sha256(plan.registry_path.read_bytes())
    if output_sha != _bytes_sha256(plan.candidate_bytes):
        raise AgentConfigMigrationError(
            "Agent registry verification failed after atomic replacement"
        )
    apply_manifest["status"] = "applied"
    apply_manifest["appliedAt"] = _utc_now_iso()
    _strict_atomic_write(
        apply_manifest_path,
        f"{json.dumps(apply_manifest, ensure_ascii=False, indent=2)}\n".encode(
            "utf-8"
        ),
    )
    return {
        "schemaVersion": 1,
        "status": "applied",
        "manifestHash": current_hash,
        "artifactRoot": str(artifact_root),
        "targetPath": str(plan.registry_path),
        "backupSha256": apply_manifest["backupSha256"],
        "outputSha256": output_sha,
    }


def _strict_atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Dry-run or apply Agent config authority migration inside an "
            "explicit sentinel-marked temporary data root."
        )
    )
    parser.add_argument(
        "--data-root",
        required=True,
        type=Path,
        help="Existing child directory of the system temp root.",
    )
    parser.add_argument(
        "--initialize-data-root",
        action="store_true",
        help="Atomically install the migration sentinel before validation.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the exact approved dry-run manifest. Defaults to dry-run.",
    )
    parser.add_argument(
        "--approved-manifest-hash",
        default="",
        help="Exact manifestHash emitted by a preceding dry-run.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.initialize_data_root:
        initialize_migration_data_root(args.data_root)
    if args.apply:
        payload = apply_agent_config_migration(
            data_root=args.data_root,
            approved_manifest_hash=args.approved_manifest_hash,
        )
    else:
        payload = plan_agent_config_migration(data_root=args.data_root)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
