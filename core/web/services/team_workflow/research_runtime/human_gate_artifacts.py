"""Build verifiable ArtifactManifest records for a resolved human gate."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from core.research.workflow.contracts import ArtifactManifest
from core.research.workflow.models import WorkflowNodeSpec


def canonical_sha256(value: object) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def build_human_gate_artifacts(
    *,
    record: dict[str, Any],
    node_spec: WorkflowNodeSpec,
    node_run: dict[str, Any],
    task: dict[str, Any],
    source_artifact_ids: list[str],
    decision: str,
    resolved_by: str,
    created_at: str,
    gate_context: dict[str, Any] | None = None,
) -> tuple[list[ArtifactManifest], dict[str, dict[str, Any]]]:
    payload_base = {
        "runId": record["runId"],
        "nodeId": node_spec.nodeId,
        "nodeRunId": node_run["nodeRunId"],
        "taskId": task["taskId"],
        "decision": decision,
        "resolvedBy": resolved_by,
        "sourceArtifactIds": source_artifact_ids,
        **(gate_context or {}),
    }
    config_hash = canonical_sha256(
        {
            "workflowVersionId": record["workflowVersionId"],
            "nodeId": node_spec.nodeId,
            "roleKey": node_spec.primaryRoleKey,
        }
    )
    environment_hash = canonical_sha256(
        {
            "environmentSnapshotRef": (
                record.get("inputSnapshot") or {}
            ).get("environmentSnapshotRef"),
        }
    )
    tool_hash = canonical_sha256(
        {
            "adapter": "human_task_resolution",
            "workflowVersionId": record["workflowVersionId"],
        }
    )
    manifests: list[ArtifactManifest] = []
    payloads: dict[str, dict[str, Any]] = {}
    for artifact_kind in node_spec.producesArtifactKinds:
        payload = {**payload_base, "artifactKind": artifact_kind}
        content_hash = canonical_sha256(payload)
        artifact_id = f"{artifact_kind}:{content_hash[:16]}"
        manifest = ArtifactManifest.from_dict(
            {
                "artifactId": artifact_id,
                "contentHash": content_hash,
                "schemaVersion": "1.0.0",
                "producerNodeRunId": node_run["nodeRunId"],
                "producerAttempt": int(node_run["attempt"]),
                "inputSnapshotHash": node_run["inputSnapshotHash"],
                "configHash": config_hash,
                "environmentSnapshotHash": environment_hash,
                "toolVersionHash": tool_hash,
                "sourceArtifactIds": source_artifact_ids,
                "cacheDisposition": "produced",
                "createdAt": created_at,
            }
        )
        manifests.append(manifest)
        payloads[artifact_id] = payload
    return manifests, payloads
