"""Canonical frozen-protocol artifact for the protocol human gate."""

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


def prepare_protocol_freeze_artifact(
    *,
    store: WorkflowLedgerStore,
    run: RunRecord,
    task_id: str = "",
    target_node_id: str = "",
    resolved_by: str = "",
) -> PreparedHumanAcceptanceArtifact | None:
    """Materialize one immutable frozen protocol from approved source artifacts.

    The normal path is the protocol-freeze human decision. ``target_node_id``
    is used only by reconcile recovery for historical accepted handoffs whose
    Ledger receipt was never bound.
    """

    handoff = store.read(
        lambda repo: _find_protocol_freeze_handoff(
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
            "frozen_protocol_not_materialized: sourceCollectionRunId missing"
        )
    draft_envelope = load_scoped_artifact_payload(
        "protocol_draft",
        team_id=run.team_id,
        authority_run_id=authority_run_id,
        workflow_run_id=run.run_id,
    )
    review_envelope = load_scoped_artifact_payload(
        "protocol_review_report",
        team_id=run.team_id,
        authority_run_id=authority_run_id,
        workflow_run_id=run.run_id,
    )
    draft = _artifact_body(draft_envelope)
    review = _artifact_body(review_envelope)
    if not draft:
        raise KnowledgeAcceptanceArtifactError("protocol_draft_not_materialized")
    protocol_id = str(draft.get("protocolId") or draft.get("planId") or "").strip()
    plan_id = str(draft.get("planId") or protocol_id).strip()
    if not protocol_id or not plan_id:
        raise KnowledgeAcceptanceArtifactError("protocol_identity_missing")
    _require_approved_protocol_review(review, protocol_id=protocol_id)

    draft_hash = canonical_sha256(draft_envelope)
    review_hash = canonical_sha256(review_envelope)
    frozen_payload = {
        "teamId": run.team_id,
        "workflowRunId": run.run_id,
        "sourceCollectionRunId": authority_run_id,
        "protocolId": protocol_id,
        "planId": plan_id,
        "status": "frozen",
        "decision": "accept",
        "resolvedBy": str(resolved_by or "").strip(),
        "protocolDraftHash": draft_hash,
        "protocolReviewHash": review_hash,
        "protocol": draft,
        "review": {
            "protocolId": protocol_id,
            "status": "approved",
            "blocking_issue_count": 0,
            "open_waivers": 0,
            "checks": list(review.get("checks") or []),
        },
    }
    put_workflow_artifact(
        run.team_id,
        kind="frozen_protocol",
        workflow_run_id=run.run_id,
        source_collection_run_id=authority_run_id,
        artifact_identity=f"human-gate:{handoff_id}",
        payload=frozen_payload,
    )
    frozen_envelope = {
        "teamId": run.team_id,
        "kind": "frozen_protocol",
        "workflowRunId": run.run_id,
        "sourceCollectionRunId": authority_run_id,
        "payload": frozen_payload,
    }
    content_hash = canonical_sha256(frozen_envelope)
    receipt_identity = canonical_sha256(
        {
            "runId": run.run_id,
            "handoffId": handoff_id,
            "artifactHash": content_hash,
        }
    )
    domain_revision = canonical_sha256(
        {
            "kind": "frozen_protocol",
            "teamId": run.team_id,
            "authorityRunId": authority_run_id,
            "contentHash": content_hash,
            "schemaVersion": "1.0.0",
        }
    )[:32]
    return PreparedHumanAcceptanceArtifact(
        receipt_id=f"ar-fp-{receipt_identity[:24]}",
        handoff_id=handoff_id,
        node_run_id=node_run_id,
        artifact_kind="frozen_protocol",
        canonical_ref=build_canonical_ref(
            kind="frozen_protocol",
            team_id=run.team_id,
            authority_run_id=authority_run_id,
            content_hash=content_hash,
        ),
        artifact_version="1.0.0",
        sha256=content_hash,
        domain_revision=domain_revision,
    )


def _find_protocol_freeze_handoff(
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
        if str(task[4]) != "gate:protocol_freeze":
            return None
        handoff_id = str(task[3] or "")
        if not handoff_id:
            raise KnowledgeAcceptanceArtifactError("protocol_freeze_handoff_missing")
        handoff = repo.get_handoff(handoff_id)
        if not _is_protocol_freeze_handoff(repo, handoff, run_id=run_id):
            raise KnowledgeAcceptanceArtifactError("protocol_freeze_handoff_invalid")
        return handoff_id, str(task[2])
    if target_node_id != "smoke_gate":
        return None
    for handoff in reversed(repo.list_handoffs_for_node(run_id, target_node_id)):
        if str(handoff[8]) != "accepted":
            continue
        if not _is_protocol_freeze_handoff(repo, handoff, run_id=run_id):
            continue
        if repo.list_handoff_receipts(str(handoff[0])):
            return None
        return str(handoff[0]), str(handoff[3])
    return None


def _is_protocol_freeze_handoff(repo: Any, handoff: Any, *, run_id: str) -> bool:
    if handoff is None or str(handoff[1]) != run_id or str(handoff[4]) != "smoke_gate":
        return False
    attempt = repo.get_attempt(str(handoff[3] or ""))
    return attempt is not None and attempt.run_id == run_id and attempt.node_id == "protocol_freeze"


def _artifact_body(envelope: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(envelope, dict):
        return {}
    payload = envelope.get("payload")
    if isinstance(payload, dict) and payload:
        return dict(payload)
    return dict(envelope) if envelope else {}


def _require_approved_protocol_review(
    review: dict[str, Any],
    *,
    protocol_id: str,
) -> None:
    if not review:
        raise KnowledgeAcceptanceArtifactError("protocol_review_not_materialized")
    review_protocol_id = str(review.get("protocolId") or "").strip()
    if review_protocol_id != protocol_id:
        raise KnowledgeAcceptanceArtifactError("protocol_review_identity_mismatch")
    if str(review.get("status") or "").strip().lower() != "approved":
        raise KnowledgeAcceptanceArtifactError("protocol_review_not_approved")
    if int(review.get("blocking_issue_count") or 0) != 0:
        raise KnowledgeAcceptanceArtifactError("protocol_review_has_blocking_issues")
    if int(review.get("open_waivers") or 0) != 0:
        raise KnowledgeAcceptanceArtifactError("protocol_review_has_open_waivers")


def _json_object(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}
