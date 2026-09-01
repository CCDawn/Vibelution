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
    parse_canonical_ref,
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
        if task_kind == "gate:smoke_gate":
            from .smoke_release_artifact import prepare_smoke_release_artifact

            return prepare_smoke_release_artifact(
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
    elif (
        request.command is WorkflowCommandKind.RETRY_NODE
        and request.node_id == "smoke_gate"
    ) or request.command is WorkflowCommandKind.RECONCILE_RUN:
        from .protocol_freeze_artifact import prepare_protocol_freeze_artifact

        return prepare_protocol_freeze_artifact(
            store=store,
            run=run,
            target_node_id="smoke_gate",
            resolved_by=str(request.requested_by.actor_id or "").strip(),
        )
    elif (
        request.command is WorkflowCommandKind.RETRY_NODE
        and request.node_id == "controlled_run"
    ):
        from .smoke_release_artifact import prepare_smoke_release_artifact

        return prepare_smoke_release_artifact(
            store=store,
            run=run,
            target_node_id="controlled_run",
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


def load_accepted_knowledge_package_from_receipt(
    store: WorkflowLedgerStore,
    *,
    team_id: str,
    run_id: str,
) -> dict[str, Any] | None:
    """Read the accepted Knowledge Package via the bound handoff receipt only.

    Ledger receipts are the handoff selector. Candidate inventory without a
    bound receipt must not unlock experiment bootstrap, and a later inventory
    item must not replace the accepted content hash.
    """

    normalized_team = str(team_id or "").strip()
    normalized_run = str(run_id or "").strip()
    if not normalized_team or not normalized_run:
        return None
    try:
        bound = store.read(
            lambda repo: _bound_knowledge_package_receipt(
                repo,
                run_id=normalized_run,
            )
        )
    except KnowledgeAcceptanceArtifactError:
        return None
    if bound is None:
        return None
    canonical_ref, content_hash = bound
    parsed = parse_canonical_ref(canonical_ref)
    if parsed is None or parsed.get("kind") != "knowledge_package":
        return None
    if str(parsed.get("teamId") or "") != normalized_team:
        return None
    pinned_hash = str(parsed.get("contentHash") or "").strip()
    ledger_hash = str(content_hash or "").strip()
    if not pinned_hash or pinned_hash != ledger_hash or len(pinned_hash) < 16:
        return None
    payload = load_scoped_artifact_payload(
        "knowledge_package",
        team_id=normalized_team,
        authority_run_id=str(parsed.get("authorityRunId") or ""),
        workflow_run_id=normalized_run,
        content_hash=pinned_hash,
    )
    if not is_accepted_knowledge_package(payload):
        return None
    if canonical_sha256(payload) != pinned_hash:
        return None
    return payload


def load_accepted_knowledge_packages_from_invocations(
    store: WorkflowLedgerStore,
    *,
    team_id: str,
    parent_run_id: str,
) -> list[dict[str, Any]]:
    """Load every accepted sideflow package absorbed by one parent run.

    The invocation row supplies lineage and the parent event proves delivery.
    The canonical ref then pins the Team Knowledge authority and content hash;
    no child receipt is copied into the parent run.
    """

    normalized_team = str(team_id or "").strip()
    normalized_parent = str(parent_run_id or "").strip()
    if not normalized_team or not normalized_parent:
        return []
    try:
        invocations, delivery_payloads = store.read(
            lambda repo: (
                repo.list_knowledge_invocations_for_parent(normalized_parent),
                repo.list_knowledge_delivery_event_payloads(normalized_parent),
            )
        )
    except Exception:
        return []

    delivered: set[tuple[str, str]] = set()
    for raw_payload in delivery_payloads or []:
        try:
            event_payload = json.loads(str(raw_payload or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if not isinstance(event_payload, dict):
            continue
        invocation_id = str(event_payload.get("invocationId") or "").strip()
        package_hash = str(
            event_payload.get("packageContentHash") or ""
        ).strip().lower()
        if invocation_id and len(package_hash) == 64:
            delivered.add((invocation_id, package_hash))

    packages: list[dict[str, Any]] = []
    for invocation in invocations or []:
        invocation_id = str(invocation.invocation_id or "").strip()
        package_hash = str(invocation.package_content_hash or "").strip().lower()
        if (
            str(invocation.parent_run_id or "") != normalized_parent
            or str(invocation.status or "") != "completed"
            or str(invocation.handoff_state or "") != "accepted"
            or (invocation_id, package_hash) not in delivered
        ):
            continue
        canonical_ref = _canonical_ref_from_json(
            str(invocation.knowledge_package_ref or "")
        )
        parsed = parse_canonical_ref(canonical_ref)
        if (
            parsed is None
            or parsed.get("kind") != "knowledge_package"
            or str(parsed.get("teamId") or "") != normalized_team
            or str(parsed.get("contentHash") or "").strip().lower()
            != package_hash
        ):
            continue
        producer_run_id = str(invocation.knowledge_child_run_id or "").strip()
        payload = load_scoped_artifact_payload(
            "knowledge_package",
            team_id=normalized_team,
            authority_run_id=str(parsed.get("authorityRunId") or ""),
            workflow_run_id=producer_run_id,
            content_hash=package_hash,
        )
        if (
            not is_accepted_knowledge_package(payload)
            or canonical_sha256(payload) != package_hash
        ):
            continue
        packages.append(
            {
                "invocationId": invocation_id,
                "producerRunId": producer_run_id,
                "knowledgePackageRef": canonical_ref,
                "packageContentHash": package_hash,
                "package": dict(payload or {}),
            }
        )
    return sorted(
        packages,
        key=lambda item: (
            str(item.get("packageContentHash") or ""),
            str(item.get("invocationId") or ""),
        ),
    )


def _canonical_ref_from_json(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        decoded = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return text
    if isinstance(decoded, dict):
        return str(decoded.get("canonicalRef") or "").strip()
    return text


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


def _bound_knowledge_package_receipt(
    repo: Any,
    *,
    run_id: str,
) -> tuple[str, str] | None:
    handoff = _find_knowledge_handoff(
        repo,
        run_id=run_id,
        task_id="",
        target_node_id="hypothesis_design",
    )
    if handoff is None:
        return None
    handoff_id, _node_run_id = handoff
    for row in repo.list_handoff_artifact_refs_for_run(run_id):
        if str(row[0]) != handoff_id or str(row[2]) != "knowledge_package":
            continue
        canonical_ref = ""
        try:
            payload = json.loads(row[3] or "{}")
        except (TypeError, json.JSONDecodeError):
            payload = {}
        if isinstance(payload, dict):
            canonical_ref = str(payload.get("canonicalRef") or "").strip()
        content_hash = str(row[5] or "").strip()
        if not canonical_ref or not content_hash:
            continue
        parsed = parse_canonical_ref(canonical_ref)
        if parsed is None or parsed.get("kind") != "knowledge_package":
            return None
        if str(parsed.get("contentHash") or "").strip() != content_hash:
            return None
        return canonical_ref, content_hash
    return None


def is_accepted_knowledge_package(payload: dict[str, Any] | None) -> bool:
    return _is_accepted_package(payload)


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
