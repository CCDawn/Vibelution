"""Build content-addressed workflow artifacts from canonical Agent task output."""

from __future__ import annotations

import copy
from typing import Any

from core.research.workflow.contracts import ArtifactManifest
from core.research.workflow.definition_registry import resolve_definition_for_run_record
from core.research.workflow.models import WorkflowNodeSpec

from .artifact_readback_registry import load_scoped_artifact_payload
from .evidence_relation_artifact import build_evidence_relation_artifact
from .human_gate_artifacts import canonical_sha256
from .source_extraction_evidence_cards import (
    build_source_extraction_evidence_cards,
)
from ..source_collection.search_execution import (
    project_source_collection_search_trace,
)


def _unique_text(values: list[object]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _stage_one_completion_payloads(
    record: dict[str, Any],
    *,
    node_id: str,
    produced_kinds: tuple[str, ...],
) -> dict[str, dict[str, Any]]:
    snapshot = (
        record.get("inputSnapshot")
        if isinstance(record.get("inputSnapshot"), dict)
        else {}
    )
    policy = (
        snapshot.get("stageOneCompletionPolicy")
        if isinstance(snapshot.get("stageOneCompletionPolicy"), dict)
        else None
    )
    if policy is None or str(policy.get("closureNodeId") or "") != node_id:
        return {}
    raw_required = policy.get("requiredArtifactKinds")
    if not isinstance(raw_required, list) or not raw_required:
        raise ValueError("stage-one completion policy artifact kinds are missing")
    required = [str(item).strip() for item in raw_required]
    if any(not item for item in required) or len(required) != len(set(required)):
        raise ValueError("stage-one completion policy artifact kinds are invalid")
    team_id = str(record.get("teamId") or "").strip()
    workflow_run_id = str(record.get("runId") or "").strip()
    authority_run_id = str(
        snapshot.get("sourceCollectionRunId") or workflow_run_id
    ).strip()
    if not team_id or not workflow_run_id or not authority_run_id:
        raise ValueError("stage-one completion artifact scope is incomplete")
    extras: dict[str, dict[str, Any]] = {}
    for kind in required:
        if kind in produced_kinds:
            continue
        envelope = load_scoped_artifact_payload(
            kind,
            team_id=team_id,
            authority_run_id=authority_run_id,
            workflow_run_id=workflow_run_id,
        )
        payload = envelope.get("payload") if isinstance(envelope, dict) else None
        if not isinstance(payload, dict) or not payload:
            raise ValueError(
                f"stage-one canonical artifact is missing or unreadable: {kind}"
            )
        extras[kind] = dict(payload)
    return extras


def _source_artifact_ids(record: dict[str, Any], node_id: str) -> list[str]:
    definition = resolve_definition_for_run_record(
        record,
        expected_node_ids=[node_id],
    )
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
        or (
            task.get("writeback", {}).get("materializedSources")
            if isinstance(task.get("writeback"), dict)
            else {}
        )
        or {}
    )
    lineage = [
        dict(item)
        for item in materialized.get("lineage") or []
        if isinstance(item, dict)
    ]
    lineage_by_fingerprint = {
        str(item.get("fingerprint") or "").strip(): item
        for item in lineage
        if str(item.get("fingerprint") or "").strip()
    }
    lineage_by_lead_id = {
        str(item.get("leadId") or "").strip(): item
        for item in lineage
        if str(item.get("leadId") or "").strip()
    }
    candidate_sources: list[dict[str, Any]] = []
    for lead in leads:
        lead_fingerprint = str(lead.get("fingerprint") or "").strip()
        lead_id = str(lead.get("leadId") or "").strip()
        lineage_entry = (
            lineage_by_fingerprint.get(lead_fingerprint)
            if lead_fingerprint
            else None
        ) or (lineage_by_lead_id.get(lead_id) if lead_id else None)
        if not lineage_entry:
            continue
        source_record = (
            dict(lineage_entry.get("record"))
            if isinstance(lineage_entry.get("record"), dict)
            else {}
        )
        candidate = (
            dict(lineage_entry.get("candidate"))
            if isinstance(lineage_entry.get("candidate"), dict)
            else {}
        )
        candidate_id = str(candidate.get("candidateId") or "").strip()
        record_id = str(source_record.get("recordId") or "").strip()
        if not candidate_id and not record_id:
            continue
        candidate_sources.append(
            {
                **lead,
                "sourceId": str(
                    candidate_id or record_id
                ),
                "candidateId": candidate_id,
                "recordId": record_id,
                "sourceRef": str(
                    source_record.get("sourceRef") or lead.get("locator") or ""
                ),
            }
        )
    source_collection_run_id = str(
        task.get("sourceCollectionRunId")
        or record.get("sourceCollectionRunId")
        or ""
    ).strip()
    search_trace = project_source_collection_search_trace(
        str(record.get("teamId") or ""),
        source_collection_run_id,
        assignment_id=str(task.get("assignmentId") or "").strip(),
        assignment_ids=[
            str(item or "").strip()
            for item in task.get("assignmentIds") or []
            if str(item or "").strip()
        ],
    )
    queries = _unique_text(
        [item.get("query") for item in leads]
        + [item.get("query") for item in search_trace]
    )
    explicit_perspectives = _unique_text(
        [item.get("perspective") or item.get("perspectiveId") for item in leads]
        + [item.get("perspective") for item in search_trace]
    )
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
    from core.web.services.team_workflow.source_collection.extraction_retrieved_at_backfill import (
        backfill_persisted_extraction_task_retrieved_at,
    )

    # Read-point Challenge v2 ``retrieved_at`` backfill — the same single
    # authoritative implementation the writeback boundary and the claim
    # materializer read point run.  A persisted extraction task that predates
    # that backfill would otherwise fail the card builder's fail-closed
    # timestamp contract here at artifact-build time.  The backfill mutates
    # ``task["result"]`` in place, so it runs on a detached copy: this builder
    # is a read point and never touches the caller's canonical task object.
    task_view = dict(task)
    task_view["result"] = copy.deepcopy(task.get("result") or {})
    result = dict(
        backfill_persisted_extraction_task_retrieved_at(task_view).get("result")
        or {}
    )
    return {
        **result,
        "evidenceCards": build_source_extraction_evidence_cards(result),
    }


def _evidence_relations_payload(task: dict[str, Any]) -> dict[str, Any]:
    result = dict(task.get("result") or {})
    return build_evidence_relation_artifact(result)


def load_canonical_problem_understanding_payload(
    *,
    record: dict[str, Any],
    node_run: dict[str, Any],
) -> dict[str, Any]:
    """Read the immutable problem-understanding artifact for this NodeRun.

    ``problem_understanding`` is written by the governed task writeback path.
    A terminal task result, summary, score, or receipt is not an authority for
    this artifact and must never be synthesized here.
    """

    team_id = str(record.get("teamId") or "").strip()
    workflow_run_id = str(record.get("runId") or "").strip()
    node_run_id = str(node_run.get("nodeRunId") or "").strip()
    if not team_id or not workflow_run_id or not node_run_id:
        raise ValueError(
            "problem_understanding canonical readback requires teamId, runId and nodeRunId"
        )

    from .workflow_artifact_store import list_workflow_artifacts

    scoped = list_workflow_artifacts(
        team_id,
        kind="problem_understanding",
        workflow_run_id=workflow_run_id,
    )
    matches = [
        item
        for item in scoped
        if str(item.get("recordId") or "").strip() == node_run_id
    ]
    if len(matches) != 1:
        raise ValueError(
            "problem_understanding canonical artifact is missing for current NodeRun"
        )
    artifact = matches[0]
    authority_run_id = str(artifact.get("sourceCollectionRunId") or "").strip()
    payload = artifact.get("payload")
    if (
        str(artifact.get("kind") or "").strip() != "problem_understanding"
        or str(artifact.get("workflowRunId") or "").strip() != workflow_run_id
        or not authority_run_id
        or not isinstance(payload, dict)
        or not payload
    ):
        raise ValueError(
            "problem_understanding canonical artifact scope or payload is invalid"
        )

    envelope = {
        "teamId": team_id,
        "kind": "problem_understanding",
        "workflowRunId": workflow_run_id,
        "sourceCollectionRunId": authority_run_id,
        "payload": payload,
    }
    content_hash = canonical_sha256(envelope)
    canonical = load_scoped_artifact_payload(
        "problem_understanding",
        team_id=team_id,
        authority_run_id=authority_run_id,
        workflow_run_id=workflow_run_id,
        content_hash=content_hash,
    )
    if not isinstance(canonical, dict):
        raise TypeError(
            "problem_understanding canonical readback is unavailable or hash-mismatched"
        )
    if any(
        str(canonical.get(field) or "").strip() != expected
        for field, expected in (
            ("teamId", team_id),
            ("kind", "problem_understanding"),
            ("workflowRunId", workflow_run_id),
            ("sourceCollectionRunId", authority_run_id),
        )
    ):
        raise ValueError("problem_understanding canonical readback scope is invalid")
    canonical_payload = canonical.get("payload")
    if (
        not isinstance(canonical_payload, dict)
        or canonical_sha256(canonical_payload) != canonical_sha256(payload)
    ):
        raise ValueError(
            "problem_understanding canonical readback payload is invalid"
        )
    return dict(canonical_payload)


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
    from .workflow_artifact_store import (
        list_workflow_artifacts,
        merge_hypothesis_set_authority_payload,
    )

    scoped_rows = [
        dict(item)
        for item in list_workflow_artifacts(
            str(record.get("teamId") or ""),
            kind="hypothesis_set",
            workflow_run_id=str(record.get("runId") or ""),
        )
    ]
    artifact = next(
        (
            item
            for item in scoped_rows
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
    # Same single readback merge as the registry: the closeout manifest payload
    # for this NodeRun must carry the embedded closeout gate/receipts even when
    # the embedding rows derive from the aggregation record id.
    return merge_hypothesis_set_authority_payload(
        payload,
        scoped_rows,
        artifact,
    )


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

    if node_spec.nodeId == "problem_understanding" and artifact_kind == (
        "problem_understanding"
    ):
        return load_canonical_problem_understanding_payload(
            record=record,
            node_run=node_run,
        )

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
    produced_kinds = tuple(node_spec.producesArtifactKinds)
    stage_one_payloads = _stage_one_completion_payloads(
        record,
        node_id=node_spec.nodeId,
        produced_kinds=produced_kinds,
    )
    artifact_kinds = (*produced_kinds, *stage_one_payloads)
    for artifact_kind in artifact_kinds:
        payload = stage_one_payloads.get(artifact_kind)
        if payload is None:
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
