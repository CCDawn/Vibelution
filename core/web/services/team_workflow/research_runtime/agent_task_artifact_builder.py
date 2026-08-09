"""Build content-addressed workflow artifacts from canonical Agent task output."""

from __future__ import annotations

from typing import Any

from core.research.workflow.contracts import ArtifactManifest
from core.research.workflow.definition import build_challenge_cup_workflow_definition
from core.research.workflow.models import WorkflowNodeSpec

from .human_gate_artifacts import canonical_sha256
from .source_extraction_evidence_cards import (
    build_source_extraction_evidence_cards,
)


def _unique_text(values: list[object]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _source_artifact_ids(record: dict[str, Any], node_id: str) -> list[str]:
    definition = build_challenge_cup_workflow_definition()
    required_kinds = {
        kind
        for edge in definition.edges
        if edge.toNodeId == node_id
        for kind in edge.requiredArtifactKinds
    }
    refs: list[str] = []
    for manifest in record.get("artifactManifests") or []:
        artifact_id = str(manifest.get("artifactId") or "")
        if artifact_id.split(":", 1)[0] in required_kinds:
            refs.append(artifact_id)
    return _unique_text(refs)


def _source_finding_payload(
    record: dict[str, Any],
    node_run: dict[str, Any],
    task: dict[str, Any],
) -> dict[str, Any]:
    result = dict(task.get("result") or {})
    leads = [dict(item) for item in result.get("candidateLeads") or [] if isinstance(item, dict)]
    materialized = dict(
        task.get("materializedSources")
        or result.get("materializedSources")
        or {}
    )
    records = [dict(item) for item in materialized.get("createdRecords") or [] if isinstance(item, dict)]
    candidates = [dict(item) for item in materialized.get("importedCandidates") or [] if isinstance(item, dict)]
    candidate_sources: list[dict[str, Any]] = []
    for index, lead in enumerate(leads):
        source_record = records[index] if index < len(records) else {}
        candidate = candidates[index] if index < len(candidates) else {}
        candidate_sources.append(
            {
                **lead,
                "sourceId": str(
                    candidate.get("candidateId")
                    or source_record.get("recordId")
                    or lead.get("locator")
                    or ""
                ),
                "candidateId": str(candidate.get("candidateId") or ""),
                "recordId": str(source_record.get("recordId") or ""),
                "sourceRef": str(
                    source_record.get("sourceRef") or lead.get("locator") or ""
                ),
            }
        )
    queries = _unique_text([item.get("query") for item in leads])
    explicit_perspectives = _unique_text(
        [item.get("perspective") or item.get("perspectiveId") for item in leads]
    )
    return {
        "runId": record["runId"],
        "nodeRunId": node_run["nodeRunId"],
        "taskId": task["taskId"],
        "sessionId": task.get("sessionId") or node_run.get("sessionId") or "",
        "perspectives": explicit_perspectives or queries,
        "queries": queries,
        "candidateSources": candidate_sources,
        "materializedSources": materialized,
        "evidenceRefs": list(task.get("evidenceRefs") or []),
        "summary": str(task.get("summary") or ""),
    }


def _source_extraction_payload(task: dict[str, Any]) -> dict[str, Any]:
    result = dict(task.get("result") or {})
    return {
        **result,
        "evidenceCards": build_source_extraction_evidence_cards(result),
    }


def _evidence_relations_payload(task: dict[str, Any]) -> dict[str, Any]:
    result = dict(task.get("result") or {})
    graph = dict(result.get("candidateGraph") or {})
    return {
        **result,
        **graph,
        "evidenceGaps": list(
            result.get("evidenceGaps") or graph.get("evidenceGaps") or []
        ),
        "counterEvidenceRefs": list(
            result.get("counterEvidenceRefs")
            or graph.get("counterEvidenceRefs")
            or []
        ),
    }


def _payload_for_kind(
    record: dict[str, Any],
    node_spec: WorkflowNodeSpec,
    node_run: dict[str, Any],
    task: dict[str, Any],
    artifact_kind: str,
) -> dict[str, Any]:
    result = dict(task.get("result") or {})
    explicit_payloads = result.get("artifactPayloads")
    if isinstance(explicit_payloads, dict) and isinstance(
        explicit_payloads.get(artifact_kind), dict
    ):
        return dict(explicit_payloads[artifact_kind])
    if node_spec.nodeId == "source_finding":
        return _source_finding_payload(record, node_run, task)
    if node_spec.nodeId == "source_extraction":
        return _source_extraction_payload(task)
    if node_spec.nodeId == "evidence_relations":
        return _evidence_relations_payload(task)
    return {
        **result,
        "runId": result.get("runId") or record["runId"],
        "nodeRunId": result.get("nodeRunId") or node_run["nodeRunId"],
        "taskId": task["taskId"],
        "sessionId": task.get("sessionId") or node_run.get("sessionId") or "",
        "resultRefs": list(task.get("resultRefs") or []),
    }


def build_agent_task_artifacts(
    *,
    record: dict[str, Any],
    node_spec: WorkflowNodeSpec,
    node_run: dict[str, Any],
    task: dict[str, Any],
    created_at: str,
) -> tuple[list[ArtifactManifest], dict[str, dict[str, Any]]]:
    """Translate a terminal canonical task into immutable workflow artifacts."""
    source_artifact_ids = _source_artifact_ids(record, node_spec.nodeId)
    config_hash = canonical_sha256(
        {
            "workflowVersionId": record["workflowVersionId"],
            "nodeId": node_spec.nodeId,
            "agentId": node_run.get("agentId") or "",
            "modelRef": node_run.get("modelRef") or "",
        }
    )
    environment_hash = canonical_sha256(
        {
            "environmentSnapshotRef": (record.get("inputSnapshot") or {}).get(
                "environmentSnapshotRef"
            )
        }
    )
    tool_hash = canonical_sha256(
        {
            "adapter": "external_agent_task_reconciliation",
            "adapterVersion": 2,
            "workflowVersionId": record["workflowVersionId"],
        }
    )
    manifests: list[ArtifactManifest] = []
    payloads: dict[str, dict[str, Any]] = {}
    for artifact_kind in node_spec.producesArtifactKinds:
        payload = _payload_for_kind(
            record,
            node_spec,
            node_run,
            task,
            artifact_kind,
        )
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
