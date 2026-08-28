"""Immutable WorkflowDefinition registry with per-run version pinning.

Identity of a workflow definition is the triple
``(workflowId, workflowVersionId, structureHash)``.  The first source of truth
is the versioned JSON snapshots in ``core/research/workflow/definitions/``;
definitions created by newer code register into the process-local runtime
cache at run creation (register-or-resolve).

Checkpoint prepare/get/advance/fork must resolve the graph definition through
this port using the run record's version identity.  Resolution is fail-closed:
an unknown version, a structureHash mismatch, or a node-set mismatch raises
``WorkflowDefinitionRegistryError`` with diagnostics instead of silently
driving an in-flight run with the current graph.

Business code must not open snapshot files directly; this module is the only
reader of the snapshot directory.
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from .definition import definition_structure_hash
from .models import WorkflowDefinition

SNAPSHOT_KIND = "workflow_definition_snapshot"
SNAPSHOT_VERSION = 1
SNAPSHOT_SUFFIX = ".json"
SNAPSHOT_FILENAME_PATTERN = re.compile(r"^(?P<workflowId>[A-Za-z0-9._-]+)@(?P<schemaVersion>[A-Za-z0-9._-]+)$")

DEFAULT_SNAPSHOT_DIR = Path(__file__).resolve().parent / "definitions"


class WorkflowDefinitionRegistryError(RuntimeError):
    """Base error for registry failures (always fail-closed)."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


class UnknownWorkflowDefinitionVersion(WorkflowDefinitionRegistryError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="unknown_workflow_definition_version")


class WorkflowDefinitionHashMismatch(WorkflowDefinitionRegistryError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="workflow_definition_hash_mismatch")


class WorkflowDefinitionSnapshotInvalid(WorkflowDefinitionRegistryError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="workflow_definition_snapshot_invalid")


class WorkflowDefinitionNodeMismatch(WorkflowDefinitionRegistryError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="workflow_definition_node_mismatch")


@dataclass(frozen=True)
class DefinitionIdentity:
    workflowId: str
    workflowVersionId: str
    structureHash: str

    def to_dict(self) -> dict[str, str]:
        return {
            "workflowId": self.workflowId,
            "workflowVersionId": self.workflowVersionId,
            "structureHash": self.structureHash,
        }


@dataclass(frozen=True)
class _RegistryEntry:
    definition: WorkflowDefinition
    source: str  # "snapshot" | "runtime"


_LOCK = threading.RLock()
_REGISTRY: dict[tuple[str, str], _RegistryEntry] = {}
_BOOTSTRAPPED = False


def workflow_version_id_for(structure_hash: str) -> str:
    """Deterministic run-facing version id derived from the structure hash."""
    return f"wv-{structure_hash[:12]}"


def definition_identity(definition: WorkflowDefinition) -> DefinitionIdentity:
    return DefinitionIdentity(
        workflowId=definition.workflowId,
        workflowVersionId=workflow_version_id_for(definition.structureHash),
        structureHash=definition.structureHash,
    )


# --------------------------------------------------------------------------
# Snapshot payload helpers
# --------------------------------------------------------------------------


def definition_snapshot_payload(definition: WorkflowDefinition) -> dict[str, Any]:
    """Canonical snapshot payload for one definition (contentHash = structure hash)."""
    return {
        "snapshotKind": SNAPSHOT_KIND,
        "snapshotVersion": SNAPSHOT_VERSION,
        "workflowId": definition.workflowId,
        "schemaVersion": definition.schemaVersion,
        "workflowVersionId": workflow_version_id_for(definition.structureHash),
        "contentHash": definition_structure_hash(definition),
        "definition": definition.to_dict(),
    }


def parse_snapshot_payload(payload: Mapping[str, Any]) -> WorkflowDefinition:
    """Parse and verify one snapshot payload; any drift/tamper fails closed."""
    if not isinstance(payload, Mapping):
        raise WorkflowDefinitionSnapshotInvalid("snapshot payload must be a JSON object")
    if str(payload.get("snapshotKind") or "") != SNAPSHOT_KIND:
        raise WorkflowDefinitionSnapshotInvalid(
            f"snapshot payload has unexpected snapshotKind: {payload.get('snapshotKind')!r}"
        )
    try:
        definition = WorkflowDefinition.from_dict(payload["definition"])
    except (KeyError, TypeError, ValueError) as exc:
        raise WorkflowDefinitionSnapshotInvalid(
            f"snapshot definition is unreadable: {exc}"
        ) from exc
    try:
        recomputed = definition_structure_hash(definition)
    except (TypeError, ValueError) as exc:
        raise WorkflowDefinitionSnapshotInvalid(
            f"snapshot definition cannot be hashed: {exc}"
        ) from exc
    stored_hash = str(payload.get("contentHash") or "")
    if not stored_hash:
        raise WorkflowDefinitionSnapshotInvalid("snapshot payload has no contentHash")
    if stored_hash != recomputed:
        raise WorkflowDefinitionHashMismatch(
            "snapshot contentHash mismatch: "
            f"stored={stored_hash} recomputed={recomputed}"
        )
    if definition.structureHash and definition.structureHash != recomputed:
        raise WorkflowDefinitionHashMismatch(
            "snapshot definition.structureHash mismatch: "
            f"stored={definition.structureHash} recomputed={recomputed}"
        )
    expected_version_id = workflow_version_id_for(recomputed)
    payload_version_id = str(payload.get("workflowVersionId") or "")
    if payload_version_id and payload_version_id != expected_version_id:
        raise WorkflowDefinitionHashMismatch(
            "snapshot workflowVersionId does not match contentHash: "
            f"payload={payload_version_id} expected={expected_version_id}"
        )
    return WorkflowDefinition(
        workflowId=definition.workflowId,
        schemaVersion=definition.schemaVersion,
        label=definition.label,
        stages=definition.stages,
        nodes=definition.nodes,
        edges=definition.edges,
        structureHash=recomputed,
    )


# --------------------------------------------------------------------------
# Registration
# --------------------------------------------------------------------------


def register_definition(
    definition: WorkflowDefinition,
    *,
    source: str = "runtime",
) -> DefinitionIdentity:
    """Register one definition; identical re-registration is a no-op."""
    if not definition.structureHash:
        raise WorkflowDefinitionSnapshotInvalid(
            "cannot register a definition without a computed structureHash"
        )
    identity = definition_identity(definition)
    key = (identity.workflowId, identity.workflowVersionId)
    with _LOCK:
        existing = _REGISTRY.get(key)
        if existing is not None:
            if existing.definition.structureHash != identity.structureHash:
                raise WorkflowDefinitionHashMismatch(
                    "workflowVersionId hash collision: "
                    f"workflowId={identity.workflowId} "
                    f"workflowVersionId={identity.workflowVersionId} "
                    f"registered={existing.definition.structureHash} "
                    f"incoming={identity.structureHash}"
                )
            return identity
        _REGISTRY[key] = _RegistryEntry(definition=definition, source=source)
    return identity


def register_definition_snapshot(
    payload: Mapping[str, Any],
    *,
    source: str = "snapshot",
) -> DefinitionIdentity:
    """Ops re-entry point: register one verified snapshot payload.

    Used by bootstrap loading and available for operators to rebuild registry
    state for older versions (e.g. pre-2.1.0 in-flight runs).
    """
    definition = parse_snapshot_payload(payload)
    return register_definition(definition, source=source)


def register_or_resolve(definition: WorkflowDefinition) -> DefinitionIdentity:
    """Run-creation entry: resolve the current definition, registering if new."""
    return register_definition(definition, source="runtime")


def registered_identities(workflow_id: str = "") -> tuple[DefinitionIdentity, ...]:
    _ensure_bootstrapped()
    with _LOCK:
        entries = sorted(_REGISTRY.items(), key=lambda item: (item[0][0], item[0][1]))
    return [
        definition_identity(entry.definition)
        for key, entry in entries
        if not workflow_id or key[0] == workflow_id
    ]


def registered_definitions() -> tuple[WorkflowDefinition, ...]:
    _ensure_bootstrapped()
    with _LOCK:
        entries = sorted(_REGISTRY.items(), key=lambda item: (item[0][0], item[0][1]))
    return [entry.definition for _, entry in entries]


def reset_registry_for_tests() -> None:
    """Clear the process-local registry (test isolation only)."""
    global _BOOTSTRAPPED
    with _LOCK:
        _REGISTRY.clear()
        _BOOTSTRAPPED = False


# --------------------------------------------------------------------------
# Resolution (the registry port used by checkpoint/run lifecycle)
# --------------------------------------------------------------------------


def resolve_definition(
    *,
    workflow_id: str,
    workflow_version_id: str,
    structure_hash: str = "",
    run_id: str = "",
    expected_node_ids: Iterable[str] = (),
) -> WorkflowDefinition:
    """Resolve the pinned definition for one run identity; fail closed.

    Raises with diagnostics (run id, expected version, registered versions)
    when the version is unknown, the structure hash does not match, or the
    run's expected nodes are not part of the pinned definition.
    """
    _ensure_bootstrapped()
    normalized_workflow_id = str(workflow_id or "").strip()
    normalized_version_id = str(workflow_version_id or "").strip()
    normalized_hash = str(structure_hash or "").strip()
    with _LOCK:
        entry = _REGISTRY.get((normalized_workflow_id, normalized_version_id))
        known = tuple(
            definition_identity(item.definition)
            for (wf_id, _), item in sorted(_REGISTRY.items())
            if wf_id == normalized_workflow_id
        )
    if entry is None:
        raise UnknownWorkflowDefinitionVersion(
            "workflow definition version is not registered; refusing to "
            "compile the current graph for this run: "
            f"runId={run_id or '<unknown>'} "
            f"workflowId={normalized_workflow_id} "
            f"workflowVersionId={normalized_version_id} "
            f"structureHash={normalized_hash or '<absent>'}; "
            f"registeredVersions={[i.workflowVersionId for i in known]}"
        )
    pinned = entry.definition
    if normalized_hash and normalized_hash != pinned.structureHash:
        raise WorkflowDefinitionHashMismatch(
            "run structureHash does not match the pinned definition: "
            f"runId={run_id or '<unknown>'} "
            f"workflowId={normalized_workflow_id} "
            f"workflowVersionId={normalized_version_id} "
            f"expectedStructureHash={normalized_hash} "
            f"registeredStructureHash={pinned.structureHash}; "
            f"registeredVersions={[i.workflowVersionId for i in known]}"
        )
    node_ids = {node.nodeId for node in pinned.nodes}
    missing = sorted({str(n) for n in expected_node_ids if n} - node_ids)
    if missing:
        raise WorkflowDefinitionNodeMismatch(
            "run references nodes missing from the pinned definition: "
            f"runId={run_id or '<unknown>'} "
            f"workflowVersionId={normalized_version_id} "
            f"missingNodes={missing}"
        )
    return pinned


def resolve_definition_for_run_record(
    run_record: Mapping[str, Any],
    *,
    expected_node_ids: Iterable[str] | None = None,
) -> WorkflowDefinition:
    """Resolve the definition pinned in a run record's version identity.

    ``expected_node_ids`` defaults to the run's completed + current node ids,
    giving the node-set check real teeth against topology drift.
    """
    if expected_node_ids is None:
        expected: list[str] = [
            *(str(n) for n in (run_record.get("completedNodeIds") or [])),
            *(str(n) for n in (run_record.get("runtimeCurrentNodeIds") or [])),
        ]
        expected_node_ids = expected
    return resolve_definition(
        workflow_id=str(run_record.get("workflowId") or ""),
        workflow_version_id=str(run_record.get("workflowVersionId") or ""),
        structure_hash=str(run_record.get("structureHash") or ""),
        run_id=str(run_record.get("runId") or ""),
        expected_node_ids=expected_node_ids,
    )


# --------------------------------------------------------------------------
# Snapshot bootstrap (this module is the only snapshot reader)
# --------------------------------------------------------------------------


def snapshot_dir() -> Path:
    return DEFAULT_SNAPSHOT_DIR


def bootstrap_definitions_from_dir(directory: Path) -> tuple[DefinitionIdentity, ...]:
    """Register every snapshot file in one directory; any bad file fails closed."""
    identities: list[DefinitionIdentity] = []
    for path in sorted(Path(directory).glob(f"*{SNAPSHOT_SUFFIX}")):
        match = SNAPSHOT_FILENAME_PATTERN.match(path.stem)
        if match is None:
            raise WorkflowDefinitionSnapshotInvalid(
                f"snapshot filename does not match <workflowId>@<schemaVersion>{SNAPSHOT_SUFFIX}: "
                f"file={path.name}"
            )
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise WorkflowDefinitionSnapshotInvalid(
                f"snapshot file is unreadable: file={path.name} error={exc}"
            ) from exc
        identity = register_definition_snapshot(payload)
        payload_workflow_id = str(payload.get("workflowId") or "")
        if payload_workflow_id and payload_workflow_id != match.group("workflowId"):
            raise WorkflowDefinitionSnapshotInvalid(
                f"snapshot workflowId does not match filename: file={path.name} "
                f"workflowId={payload_workflow_id}"
            )
        identities.append(identity)
    return tuple(identities)


def bootstrap_builtin_definitions() -> tuple[DefinitionIdentity, ...]:
    return bootstrap_definitions_from_dir(snapshot_dir())


def _ensure_bootstrapped() -> None:
    global _BOOTSTRAPPED
    with _LOCK:
        if _BOOTSTRAPPED:
            return
        _BOOTSTRAPPED = True
    bootstrap_builtin_definitions()
