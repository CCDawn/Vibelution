"""Prepare and persist the canonical artifact carried by a human handoff."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from core.research.workflow.contracts import CommandRequest, WorkflowCommandKind
from core.research.workflow.ledger import RunRecord, WorkflowLedgerStore

from .artifact_readback_registry import (
    build_canonical_ref,
    load_scoped_artifact_payload,
)
from .human_gate_artifacts import canonical_sha256


class KnowledgeAcceptanceArtifactError(RuntimeError):
    """The accepted knowledge gate cannot produce its required artifact."""


@dataclass(frozen=True, slots=True)
class PreparedHumanAcceptanceArtifact:
    receipt_id: str
    handoff_id: str
    node_run_id: str
    artifact_kind: str
    canonical_ref: str
    artifact_version: str
    sha256: str
    domain_revision: str


def prepare_command_human_acceptance_artifact(
    *,
    store: WorkflowLedgerStore,
    run: RunRecord,
    request: CommandRequest,
) -> PreparedHumanAcceptanceArtifact | None:
    """Select the canonical artifact needed by a human-gate command."""
    task_id = ""
    target_node_id = ""
    if (
        request.command is WorkflowCommandKind.RESOLVE_HUMAN_TASK
        and str(request.payload.get("decision") or "") == "accept"
    ):
        task_id = str(request.payload.get("taskId") or "")
        task_kind = store.read(
            lambda repo: _human_task_kind(repo, run_id=run.run_id, task_id=task_id)
        )
        if task_kind == "gate:protocol_freeze":
            from .protocol_freeze_artifact import prepare_protocol_freeze_artifact

            return prepare_protocol_freeze_artifact(
                store=store,
                run=run,
                task_id=task_id,
                resolved_by=str(request.requested_by.actor_id or "").strip(),
            )
    elif (
        request.command is WorkflowCommandKind.RETRY_NODE
        and request.node_id == "hypothesis_design"
    ):
        target_node_id = "hypothesis_design"
    elif request.command is WorkflowCommandKind.RECONCILE_RUN:
        from .protocol_freeze_artifact import prepare_protocol_freeze_artifact

        return prepare_protocol_freeze_artifact(
            store=store,
            run=run,
            target_node_id="smoke_gate",
            resolved_by=str(request.requested_by.actor_id or "").strip(),
        )
    else:
        return None
    return prepare_knowledge_handoff_artifact(
        store=store,
        run=run,
        task_id=task_id,
        target_node_id=target_node_id,
    )


def prepare_knowledge_handoff_artifact(
    *,
    store: WorkflowLedgerStore,
    run: RunRecord,
    task_id: str,
    target_node_id: str = "",
) -> PreparedHumanAcceptanceArtifact | None:
    """Read and verify the Team Knowledge package before a Ledger mutation.

    ``task_id`` is used by the normal human-accept path. ``target_node_id`` is
    used only by retry recovery for historical accepted handoffs that predate
    receipt binding.
    """

    handoff = store.read(
        lambda repo: _find_knowledge_handoff(
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
            "knowledge_package_not_materialized: sourceCollectionRunId missing"
        )
    payload = load_scoped_artifact_payload(
        "knowledge_package",
        team_id=run.team_id,
        authority_run_id=authority_run_id,
        workflow_run_id=run.run_id,
    )
    if not _is_accepted_package(payload):
        raise KnowledgeAcceptanceArtifactError("knowledge_package_not_materialized")
    content_hash = canonical_sha256(payload)
    receipt_identity = canonical_sha256(
        {"runId": run.run_id, "artifactHash": content_hash}
    )
    domain_revision = canonical_sha256(
        {
            "kind": "knowledge_package",
            "teamId": run.team_id,
            "authorityRunId": authority_run_id,
            "contentHash": content_hash,
            "schemaVersion": "1.0.0",
        }
    )[:32]
    return PreparedHumanAcceptanceArtifact(
        receipt_id=f"ar-kp-{receipt_identity[:24]}",
        handoff_id=handoff_id,
        node_run_id=node_run_id,
        artifact_kind="knowledge_package",
        canonical_ref=build_canonical_ref(
            kind="knowledge_package",
            team_id=run.team_id,
            authority_run_id=authority_run_id,
            content_hash=content_hash,
        ),
        artifact_version="1.0.0",
        sha256=content_hash,
        domain_revision=domain_revision,
    )


def persist_prepared_human_acceptance_artifact(
    uow: Any,
    *,
    run: RunRecord,
    prepared: PreparedHumanAcceptanceArtifact | None,
    now_ms: int,
) -> tuple[str, ...]:
    """Insert one idempotent receipt and bind it to the outgoing handoff."""

    if prepared is None:
        return ()
    existing = uow.repository.get_artifact_receipt(prepared.receipt_id)
    if existing is None:
        uow.repository.insert_artifact_receipt(
            receipt_id=prepared.receipt_id,
            run_id=run.run_id,
            node_run_id=prepared.node_run_id,
            team_id=run.team_id,
            artifact_kind=prepared.artifact_kind,
            canonical_ref_json=json.dumps(
                {"canonicalRef": prepared.canonical_ref},
                ensure_ascii=False,
            ),
            artifact_version=prepared.artifact_version,
            sha256=prepared.sha256,
            domain_revision=prepared.domain_revision,
            materialized=1,
            verified_at_ms=now_ms,
        )
    elif (
        str(existing[1]) != run.run_id
        or str(existing[2]) != prepared.node_run_id
        or str(existing[4]) != prepared.artifact_kind
        or str(existing[7]) != prepared.sha256
    ):
        raise KnowledgeAcceptanceArtifactError(
            "knowledge_package_receipt_identity_conflict"
        )
    bound = uow.repository.execute(
        "SELECT 1 FROM handoff_receipts WHERE handoff_id = ? AND receipt_id = ?",
        (prepared.handoff_id, prepared.receipt_id),
    ).fetchone()
    if bound is None:
        ordinal_row = uow.repository.execute(
            "SELECT COALESCE(MAX(ordinal), -1) + 1 FROM handoff_receipts "
            "WHERE handoff_id = ?",
            (prepared.handoff_id,),
        ).fetchone()
        uow.repository.insert_handoff_receipt(
            prepared.handoff_id,
            prepared.receipt_id,
            int(ordinal_row[0] if ordinal_row else 0),
        )
    return (prepared.receipt_id,)


def _find_knowledge_handoff(
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
        if str(task[4]) != "gate:knowledge_handoff":
            return None
        if not str(task[3] or ""):
            raise KnowledgeAcceptanceArtifactError(
                "knowledge_package_handoff_missing"
            )
        handoff = repo.get_handoff(str(task[3]))
        if handoff is None or str(handoff[2]) != "knowledge_handoff->hypothesis_design":
            raise KnowledgeAcceptanceArtifactError(
                "knowledge_package_handoff_invalid"
            )
        return str(handoff[0]), str(task[2])
    if target_node_id != "hypothesis_design":
        return None
    for handoff in reversed(repo.list_handoffs_for_node(run_id, target_node_id)):
        if (
            str(handoff[2]) == "knowledge_handoff->hypothesis_design"
            and str(handoff[8]) == "accepted"
        ):
            return str(handoff[0]), str(handoff[3])
    return None


def _human_task_kind(repo: Any, *, run_id: str, task_id: str) -> str:
    if not task_id:
        return ""
    task = repo.get_human_task(task_id)
    if task is None or str(task[1]) != run_id:
        return ""
    return str(task[4] or "")


def _json_object(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _is_accepted_package(payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict) or payload.get("accepted") is not True:
        return False
    items = payload.get("knowledgeItems")
    return bool(
        isinstance(items, list)
        and items
        and all(
            isinstance(item, dict)
            and str(item.get("knowledgeItemId") or "").strip()
            and len(str(item.get("contentHash") or "").strip()) == 64
            for item in items
        )
    )
