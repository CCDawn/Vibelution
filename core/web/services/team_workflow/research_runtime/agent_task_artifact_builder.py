"""Build content-addressed workflow artifacts from canonical Agent task output."""

from __future__ import annotations

from typing import Any

from core.research.workflow.contracts import ArtifactManifest
from core.research.workflow.definition import build_challenge_cup_workflow_definition
from core.research.workflow.models import WorkflowNodeSpec

from .artifact_readback_registry import load_scoped_artifact_payload
from .evidence_relation_artifact import build_evidence_relation_artifact
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
    search_trace = [
        dict(item)
        for item in result.get("searchTrace") or []
        if isinstance(item, dict)
    ]
    counter_perspectives = {"limitation_or_null", "falsification"}
    counter_candidates = [
        dict(item)
        for item in candidate_sources
        if str(item.get("perspective") or item.get("perspectiveId") or "")
        .strip()
        .lower()
        in counter_perspectives
    ]
    return {
        "runId": record["runId"],
        "nodeRunId": node_run["nodeRunId"],
        "taskId": task["taskId"],
        "sessionId": task.get("sessionId") or node_run.get("sessionId") or "",
        "perspectives": explicit_perspectives or queries,
        "queries": queries,
        "candidateSources": candidate_sources,
        "counterEvidenceCandidateSources": counter_candidates,
        "searchTrace": search_trace,
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
    return build_evidence_relation_artifact(result)


def _hypothesis_set_payload(
    record: dict[str, Any],
    node_run: dict[str, Any],
) -> dict[str, Any]:
    """Read the exact deterministic fan-in artifact bound to this NodeRun."""

    bundle = next(
        (
            dict(item)
            for item in record.get("taskBundles") or []
            if str(item.get("parentNodeRunId") or "")
            == str(node_run.get("nodeRunId") or "")
        ),
        None,
    )
    refs = list((bundle or {}).get("aggregationArtifactRefs") or [])
    if (bundle or {}).get("status") != "succeeded" or len(refs) != 1:
        raise ValueError(
            "hypothesis_design requires one completed TaskBundle aggregation artifact"
        )
    from .workflow_artifact_store import list_workflow_artifacts

    artifact = next(
        (
            dict(item)
            for item in list_workflow_artifacts(
                str(record.get("teamId") or ""),
                kind="hypothesis_set",
                workflow_run_id=str(record.get("runId") or ""),
            )
            if str(item.get("recordId") or "") == str(refs[0] or "")
        ),
        None,
    )
    payload = (artifact or {}).get("payload")
    provenance = (
        payload.get("provenance") if isinstance(payload, dict) else None
    )
    if (
        not isinstance(payload, dict)
        or not isinstance(provenance, dict)
        or str(provenance.get("nodeRunId") or "")
        != str(node_run.get("nodeRunId") or "")
    ):
        raise ValueError(
            "hypothesis_design aggregation artifact is missing or belongs to another NodeRun"
        )
    return dict(payload)


def _protocol_design_artifact_payloads(
    record: dict[str, Any],
    node_run: dict[str, Any],
    task: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Read and validate both canonical protocol-design artifact envelopes."""

    team_id = str(record.get("teamId") or "").strip()
    workflow_run_id = str(record.get("runId") or "").strip()
    authority_run_id = str(
        task.get("sourceCollectionRunId") or workflow_run_id
    ).strip()
    if not team_id or not workflow_run_id or not authority_run_id:
        raise ValueError("protocol_design artifact scope is incomplete")

    envelopes: dict[str, dict[str, Any]] = {}
    plan_ids: dict[str, str] = {}
    for kind in ("research_plan", "protocol_draft"):
        envelope = load_scoped_artifact_payload(
            kind,
            team_id=team_id,
            authority_run_id=authority_run_id,
            workflow_run_id=workflow_run_id,
        )
        if not isinstance(envelope, dict):
            raise ValueError(f"protocol_design canonical {kind} readback is missing")
        expected_scope = {
            "kind": kind,
            "teamId": team_id,
            "workflowRunId": workflow_run_id,
            "sourceCollectionRunId": authority_run_id,
        }
        if any(
            str(envelope.get(field) or "").strip() != expected
            for field, expected in expected_scope.items()
        ):
            raise ValueError(f"protocol_design canonical {kind} scope is invalid")
        payload = envelope.get("payload")
        if not isinstance(payload, dict):
            raise ValueError(f"protocol_design canonical {kind} payload is missing")
        plan_id = str(payload.get("planId") or "").strip()
        if not plan_id:
            raise ValueError(f"protocol_design canonical {kind} planId is missing")
        envelopes[kind] = envelope
        plan_ids[kind] = plan_id

    if plan_ids["research_plan"] != plan_ids["protocol_draft"]:
        raise ValueError("protocol_design canonical planId values do not match")

    task_id = str(task.get("taskId") or "").strip()
    session_id = str(task.get("sessionId") or "").strip()
    turn = task.get("turn") if isinstance(task.get("turn"), dict) else {}
    turn_id = str(turn.get("turnId") or "").strip()
    agent_id = str(task.get("agentId") or "").strip()
    node_run_id = str(node_run.get("nodeRunId") or "").strip()
    input_snapshot_hash = str(node_run.get("inputSnapshotHash") or "").strip()
    attempt = node_run.get("attempt")
    if (
        not task_id
        or not session_id
        or not turn_id
        or not agent_id
        or not node_run_id
        or not input_snapshot_hash
        or isinstance(attempt, bool)
        or not isinstance(attempt, int)
        or attempt <= 0
    ):
        raise ValueError("protocol_design canonical producer binding is incomplete")

    expected_producer = {
        "nodeRunId": node_run_id,
        "attempt": attempt,
        "taskId": task_id,
        "sessionId": session_id,
        "turnId": turn_id,
        "agentId": agent_id,
    }
    research_payload = envelopes["research_plan"]["payload"]
    producer = research_payload.get("producer")
    if (
        not isinstance(producer, dict)
        or isinstance(producer.get("attempt"), bool)
        or not isinstance(producer.get("attempt"), int)
        or any(
            producer.get(field) != expected
            for field, expected in expected_producer.items()
        )
    ):
        raise ValueError("protocol_design canonical research_plan producer is invalid")
    if research_payload.get("inputSnapshotHash") != input_snapshot_hash:
        raise ValueError(
            "protocol_design canonical research_plan inputSnapshotHash is invalid"
        )

    protocol_payload = envelopes["protocol_draft"]["payload"]
    expected_protocol_binding = {
        "createdFromTaskId": task_id,
        "createdFromSessionId": session_id,
        "createdFromTurnId": turn_id,
    }
    if any(
        protocol_payload.get(field) != expected
        for field, expected in expected_protocol_binding.items()
    ):
        raise ValueError("protocol_design canonical protocol_draft producer is invalid")

    return envelopes


def _payload_for_kind(
    record: dict[str, Any],
    node_spec: WorkflowNodeSpec,
    node_run: dict[str, Any],
    task: dict[str, Any],
    artifact_kind: str,
    *,
    protocol_artifact_payloads: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if node_spec.nodeId == "protocol_design" and artifact_kind in {
        "research_plan",
        "protocol_draft",
    }:
        payloads = (
            protocol_artifact_payloads
            if protocol_artifact_payloads is not None
            else _protocol_design_artifact_payloads(record, node_run, task)
        )
        return payloads[artifact_kind]

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
    if node_spec.nodeId == "hypothesis_design" and artifact_kind == "hypothesis_set":
        return _hypothesis_set_payload(record, node_run)
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
    protocol_artifact_payloads = (
        _protocol_design_artifact_payloads(record, node_run, task)
        if node_spec.nodeId == "protocol_design"
        else None
    )
    for artifact_kind in node_spec.producesArtifactKinds:
        payload = _payload_for_kind(
            record,
            node_spec,
            node_run,
            task,
            artifact_kind,
            protocol_artifact_payloads=protocol_artifact_payloads,
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
