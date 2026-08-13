"""Canonical Smoke evidence and release for the human Smoke gate."""

from __future__ import annotations

import json
from typing import Any

from core.research.workflow.ledger import RunRecord, WorkflowLedgerStore

from .artifact_readback_registry import (
    build_canonical_ref,
    load_scoped_artifact_payload,
)
from .human_acceptance_artifact import (
    KnowledgeAcceptanceArtifactError,
    PreparedHumanAcceptanceArtifact,
)
from .human_gate_artifacts import canonical_sha256
from .workflow_artifact_store import put_workflow_artifact


def prepare_smoke_release_artifact(
    *,
    store: WorkflowLedgerStore,
    run: RunRecord,
    task_id: str = "",
    target_node_id: str = "",
    resolved_by: str = "",
) -> PreparedHumanAcceptanceArtifact | None:
    """Run missing Smoke observation, verify it, then write one release."""

    handoff = store.read(
        lambda repo: _find_smoke_handoff(
            repo,
            run_id=run.run_id,
            task_id=str(task_id or "").strip(),
            target_node_id=str(target_node_id or "").strip(),
        )
    )
    if handoff is None:
        return None
    handoff_id, node_run_id = handoff
    snapshot = _json_object(run.input_snapshot_json)
    authority_run_id = str(snapshot.get("sourceCollectionRunId") or "").strip()
    if not authority_run_id:
        raise KnowledgeAcceptanceArtifactError(
            "smoke_release_not_materialized: sourceCollectionRunId missing"
        )

    frozen_envelope = load_scoped_artifact_payload(
        "frozen_protocol",
        team_id=run.team_id,
        authority_run_id=authority_run_id,
        workflow_run_id=run.run_id,
    )
    frozen = _artifact_body(frozen_envelope)
    plan_id = str(frozen.get("planId") or frozen.get("protocolId") or "").strip()
    if str(frozen.get("status") or "").lower() != "frozen" or not plan_id:
        raise KnowledgeAcceptanceArtifactError("frozen_protocol_not_materialized")

    evidence_envelope = _load_smoke_evidence(run, authority_run_id)
    if evidence_envelope is None:
        _execute_smoke_observation(
            store=store,
            run=run,
            plan_id=plan_id,
            handoff_id=handoff_id,
        )
        evidence_envelope = _load_smoke_evidence(run, authority_run_id)
    evidence = _artifact_body(evidence_envelope)
    _require_passed_smoke(evidence, plan_id=plan_id)

    smoke_run_id = str(evidence.get("smokeRunId") or "").strip()
    release_payload = {
        "teamId": run.team_id,
        "workflowRunId": run.run_id,
        "sourceCollectionRunId": authority_run_id,
        "planId": plan_id,
        "smokeRunId": smoke_run_id,
        "status": "released",
        "decision": "accept",
        "resolvedBy": str(resolved_by or "").strip(),
        "smokeEvidenceHash": canonical_sha256(evidence_envelope),
        "frozenProtocolHash": canonical_sha256(frozen_envelope),
    }
    put_workflow_artifact(
        run.team_id,
        kind="smoke_release",
        workflow_run_id=run.run_id,
        source_collection_run_id=authority_run_id,
        artifact_identity=f"human-gate:{handoff_id}",
        payload=release_payload,
    )
    release_envelope = {
        "teamId": run.team_id,
        "kind": "smoke_release",
        "workflowRunId": run.run_id,
        "sourceCollectionRunId": authority_run_id,
        "payload": release_payload,
    }
    content_hash = canonical_sha256(release_envelope)
    receipt_identity = canonical_sha256(
        {
            "runId": run.run_id,
            "handoffId": handoff_id,
            "artifactHash": content_hash,
        }
    )
    domain_revision = canonical_sha256(
        {
            "kind": "smoke_release",
            "teamId": run.team_id,
            "authorityRunId": authority_run_id,
            "contentHash": content_hash,
            "schemaVersion": "1.0.0",
        }
    )[:32]
    return PreparedHumanAcceptanceArtifact(
        receipt_id=f"ar-sr-{receipt_identity[:24]}",
        handoff_id=handoff_id,
        node_run_id=node_run_id,
        artifact_kind="smoke_release",
        canonical_ref=build_canonical_ref(
            kind="smoke_release",
            team_id=run.team_id,
            authority_run_id=authority_run_id,
            content_hash=content_hash,
        ),
        artifact_version="1.0.0",
        sha256=content_hash,
        domain_revision=domain_revision,
    )


def _load_smoke_evidence(
    run: RunRecord,
    authority_run_id: str,
) -> dict[str, Any] | None:
    return load_scoped_artifact_payload(
        "smoke_evidence",
        team_id=run.team_id,
        authority_run_id=authority_run_id,
        workflow_run_id=run.run_id,
    )


def _execute_smoke_observation(
    *,
    store: WorkflowLedgerStore,
    run: RunRecord,
    plan_id: str,
    handoff_id: str,
) -> None:
    from .real_domain_ports import RealDomainPorts

    try:
        RealDomainPorts(store).execute_run_smoke(
            run_id=run.run_id,
            plan_id=plan_id,
            team_id=run.team_id,
            action_id=f"human-smoke:{handoff_id}",
        )
    except KnowledgeAcceptanceArtifactError:
        raise
    except Exception as exc:
        raise KnowledgeAcceptanceArtifactError(
            f"smoke_execution_failed: {type(exc).__name__}: {exc}"
        ) from exc


def _find_smoke_handoff(
    repo: Any,
    *,
    run_id: str,
    task_id: str,
    target_node_id: str,
) -> tuple[str, str] | None:
    if task_id:
        task = repo.get_human_task(task_id)
        if task is None or str(task[1]) != run_id:
            return None
        if str(task[4]) != "gate:smoke_gate":
            return None
        handoff_id = str(task[3] or "")
        if not handoff_id:
            raise KnowledgeAcceptanceArtifactError("smoke_handoff_missing")
        handoff = repo.get_handoff(handoff_id)
        if not _is_smoke_handoff(repo, handoff, run_id=run_id):
            raise KnowledgeAcceptanceArtifactError("smoke_handoff_invalid")
        return handoff_id, str(task[2])
    if target_node_id != "controlled_run":
        return None
    for handoff in reversed(repo.list_handoffs_for_node(run_id, target_node_id)):
        if str(handoff[8]) != "accepted":
            continue
        if not _is_smoke_handoff(repo, handoff, run_id=run_id):
            continue
        if _handoff_has_release(repo, run_id=run_id, handoff_id=str(handoff[0])):
            return None
        return str(handoff[0]), str(handoff[3])
    return None


def _is_smoke_handoff(repo: Any, handoff: Any, *, run_id: str) -> bool:
    if handoff is None or str(handoff[1]) != run_id or str(handoff[4]) != "controlled_run":
        return False
    attempt = repo.get_attempt(str(handoff[3] or ""))
    return attempt is not None and attempt.run_id == run_id and attempt.node_id == "smoke_gate"


def _handoff_has_release(repo: Any, *, run_id: str, handoff_id: str) -> bool:
    return any(
        str(item[0]) == handoff_id and str(item[2]) == "smoke_release"
        for item in repo.list_handoff_artifact_refs_for_run(run_id)
    )


def _artifact_body(envelope: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(envelope, dict):
        return {}
    payload = envelope.get("payload")
    if isinstance(payload, dict) and payload:
        return dict(payload)
    return dict(envelope) if envelope else {}


def _require_passed_smoke(evidence: dict[str, Any], *, plan_id: str) -> None:
    if not evidence:
        raise KnowledgeAcceptanceArtifactError("smoke_evidence_not_materialized")
    if str(evidence.get("status") or "").strip().lower() != "passed":
        raise KnowledgeAcceptanceArtifactError("smoke_evidence_not_passed")
    if str(evidence.get("planId") or "").strip() != plan_id:
        raise KnowledgeAcceptanceArtifactError("smoke_evidence_plan_mismatch")
    if not str(evidence.get("smokeRunId") or "").strip():
        raise KnowledgeAcceptanceArtifactError("smoke_evidence_identity_missing")


def _json_object(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}
