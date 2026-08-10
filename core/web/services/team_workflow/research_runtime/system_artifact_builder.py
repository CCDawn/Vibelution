"""Build content-addressed ArtifactManifest records from System observations."""

from __future__ import annotations

from typing import Any

from core.research.workflow.contracts import ArtifactManifest

from .human_gate_artifacts import canonical_sha256
from .node_execution_support import iso, utc_now


def build_system_artifact(
    *,
    record: dict[str, Any],
    node_run: dict[str, Any],
    artifact_kind: str,
    payload: dict[str, Any],
    source_artifact_ids: list[str],
    adapter_name: str,
) -> ArtifactManifest:
    content_hash = canonical_sha256(payload)
    return ArtifactManifest.from_dict(
        {
            "artifactId": f"{artifact_kind}:{content_hash[:16]}",
            "contentHash": content_hash,
            "schemaVersion": "1.0.0",
            "producerNodeRunId": node_run["nodeRunId"],
            "producerAttempt": int(node_run["attempt"]),
            "inputSnapshotHash": node_run["inputSnapshotHash"],
            "configHash": canonical_sha256(
                {
                    "workflowVersionId": record["workflowVersionId"],
                    "nodeId": node_run["nodeId"],
                }
            ),
            "environmentSnapshotHash": canonical_sha256(
                {
                    "environmentSnapshotRef": (
                        record.get("inputSnapshot") or {}
                    ).get("environmentSnapshotRef")
                }
            ),
            "toolVersionHash": canonical_sha256(
                {
                    "adapter": adapter_name,
                    "workflowVersionId": record["workflowVersionId"],
                }
            ),
            "sourceArtifactIds": list(source_artifact_ids),
            "cacheDisposition": "produced",
            "createdAt": iso(utc_now()),
        }
    )
