"""Post-run Challenge Cup delivery orchestration.

When a research run closes (``result_package`` succeeded → run ``succeeded``)
the formal delivery chain runs as a decoupled post-run step rather than a
graph node: evidence index → submission projection check → preview/formal
export → PDF size limit. The run itself stays ``succeeded``; delivery outcomes
land in the Ledger as ``delivery_orchestration_*`` events plus one immutable
``delivery_orchestration_result`` workflow artifact, so operators can diagnose
the chain from the run timeline without the run ever flapping to failed.

Preview closure is the success bar (any progress may ship a preview pack).
Formal export stays fail-closed: gate states that are not explicitly provided
through the run input snapshot ``deliveryRequest`` default to refused, so a
DEV run diagnoses the missing gates instead of impersonating a final pack.
"""

from __future__ import annotations

import json
from typing import Any

from core.research.competition.delivery import (
    build_evidence_index,
    check_pdf_limit,
    export_results,
    validate_submission_projection,
)
from core.research.workflow.ledger import EventRecord, OutboxRecord, RunRecord
from core.research.workflow.transitions import RunStatus

from .artifact_readback_registry import build_canonical_ref
from .human_gate_artifacts import canonical_sha256
from .ids import new_id
from .workflow_artifact_store import put_workflow_artifact

DELIVERY_OUTBOX_KIND = "delivery_orchestration"
DELIVERY_ARTIFACT_KIND = "delivery_orchestration_result"
DELIVERY_EVENT_COMPLETED = "delivery_orchestration_completed"
DELIVERY_EVENT_BLOCKED = "delivery_orchestration_blocked"
DELIVERY_EVENT_FAILED = "delivery_orchestration_failed"

_TRIGGER_NODE_ID = "result_package"


class DeliveryOrchestrationError(RuntimeError):
    """Permanent delivery-chain input/integrity failure (never retried)."""

    def __init__(self, code: str, detail: str, *, step: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail
        self.step = step


def delivery_idempotency_key(run_id: str) -> str:
    return f"delivery:{str(run_id or '').strip()}"


def enqueue_delivery_orchestration(uow: Any, *, run: RunRecord, now_ms: int) -> bool:
    """Insert the post-run delivery outbox action inside the closing writer tx.

    Idempotent by ``delivery:{run_id}``: re-closing an already terminal run or
    replaying a repair path never duplicates the orchestration.
    """
    key = delivery_idempotency_key(run.run_id)
    if not key or key == "delivery:":
        return False
    existing = uow.repository.execute(
        "SELECT action_id FROM outbox_actions WHERE idempotency_key = ?",
        (key,),
    ).fetchone()
    if existing is not None:
        return False
    uow.repository.insert_outbox(
        OutboxRecord(
            action_id=new_id("act"),
            run_id=run.run_id,
            command_id=None,
            node_run_id=None,
            action_kind=DELIVERY_OUTBOX_KIND,
            idempotency_key=key,
            payload_json=json.dumps(
                {
                    "schemaVersion": 1,
                    "runId": run.run_id,
                    "teamId": run.team_id,
                    "triggerNodeId": _TRIGGER_NODE_ID,
                },
                ensure_ascii=False,
            ),
            status="pending",
            attempt_count=0,
            available_at_ms=now_ms,
            lease_owner=None,
            lease_expires_at_ms=None,
            last_problem_json=None,
            created_at_ms=now_ms,
            updated_at_ms=now_ms,
        )
    )
    return True


def _input_snapshot(run: RunRecord) -> dict[str, Any]:
    try:
        loaded = json.loads(run.input_snapshot_json or "{}")
    except (TypeError, ValueError):
        return {}
    return dict(loaded) if isinstance(loaded, dict) else {}


def _delivery_request(snapshot: dict[str, Any]) -> dict[str, Any]:
    request = snapshot.get("deliveryRequest")
    return dict(request) if isinstance(request, dict) else {}


def _gate_value(request: dict[str, Any], key: str) -> str:
    """Operator-attested gate result; missing stays fail-closed (not PASS)."""
    return str(request.get(key) or "").strip()


def _receipt_evidence_entries(store: Any, run_id: str) -> list[dict[str, Any]]:
    rows = store.read(lambda repo: repo.list_artifact_receipts_for_run(run_id))
    entries: list[dict[str, Any]] = []
    for row in rows or ():
        receipt_id = str(row[0] or "").strip()
        node_run_id = str(row[2] or "").strip()
        artifact_kind = str(row[4] or "").strip()
        sha256 = str(row[7] or "").strip()
        canonical_ref = ""
        try:
            ref_payload = json.loads(str(row[5] or "{}"))
        except (TypeError, ValueError):
            ref_payload = {}
        if isinstance(ref_payload, dict):
            canonical_ref = str(ref_payload.get("canonicalRef") or "").strip()
        if not receipt_id or not artifact_kind:
            continue
        entries.append(
            {
                "path": f"workflow/{artifact_kind}/{receipt_id}",
                "kind": artifact_kind,
                "sha256": sha256,
                "scope": {
                    "runId": run_id,
                    "nodeRunId": node_run_id,
                    "canonicalRef": canonical_ref,
                },
            }
        )
    return entries


def _request_evidence_entries(request: dict[str, Any]) -> list[dict[str, Any]]:
    raw = request.get("extraEvidence")
    if raw is None:
        return []
    if not isinstance(raw, list) or any(not isinstance(item, dict) for item in raw):
        raise DeliveryOrchestrationError(
            "invalid_delivery_request",
            "deliveryRequest.extraEvidence must be a list of objects",
            step="evidence_index",
        )
    return [dict(item) for item in raw]


def _program_delivery_state(team_id: str) -> tuple[dict[str, Any], str | None]:
    """Approved-question count + submission page state; fail-closed on read errors."""
    try:
        from core.web.services.team_workflow.challenge_program import (
            build_competition_program_projection,
        )
        from core.web.services.team_workflow.challenge_question_runs import (
            challenge_question_run_summary,
        )

        summary = challenge_question_run_summary(team_id)
        projection = build_competition_program_projection(question_run_summary=summary)
        result_set = projection.get("fullCatalogResultSet")
        approved = int((result_set or {}).get("approvedQuestionCount") or 0)
        requirement = projection.get("directionSubmissionRequirement")
        requirement = dict(requirement) if isinstance(requirement, dict) else {}
        return (
            {
                "approvedQuestionCount": approved,
                "captured": requirement.get("captured") is True,
                "officialPageObservedState": str(
                    requirement.get("officialPageObservedState") or ""
                ),
            },
            None,
        )
    except Exception as exc:  # noqa: BLE001 - program-state reads must fail closed, never crash delivery
        # Fail-closed: unknown program state must never count toward formal.
        return (
            {
                "approvedQuestionCount": 0,
                "captured": False,
                "officialPageObservedState": "",
            },
            f"program_projection_unavailable:{type(exc).__name__}:{exc}",
        )


def _pdf_size_bytes(request: dict[str, Any], preview_pack: dict[str, Any]) -> tuple[int, str]:
    if "deliveryPdfSizeBytes" in request:
        try:
            return int(request.get("deliveryPdfSizeBytes")), "delivery_request"
        except (TypeError, ValueError) as exc:
            raise DeliveryOrchestrationError(
                "invalid_delivery_request",
                f"deliveryRequest.deliveryPdfSizeBytes is not an integer: {exc}",
                step="pdf_limit",
            ) from exc
    packed = json.dumps(preview_pack, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return len(packed), "preview_pack_json"


def run_delivery_orchestration(
    store: Any,
    *,
    run_id: str,
    now_ms: int,
) -> dict[str, Any]:
    """Execute the delivery chain outside the writer transaction.

    Returns the terminal outcome (``succeeded``/``blocked``) with the persisted
    artifact ref. Raises ``DeliveryOrchestrationError`` for permanent input or
    integrity failures; any other exception is transient and may be retried.
    """
    _ = now_ms  # timestamps come from the delivery library (UTC second marks)
    run = store.get_run(run_id)
    if run is None:
        raise DeliveryOrchestrationError(
            "run_missing", f"run {run_id} no longer exists", step="load_run"
        )
    team_id = str(run.team_id or "").strip()
    if not team_id:
        raise DeliveryOrchestrationError(
            "missing_team_scope", "run has no team scope", step="load_run"
        )
    snapshot = _input_snapshot(run)
    request = _delivery_request(snapshot)
    authority_run_id = str(snapshot.get("sourceCollectionRunId") or run.run_id).strip()

    entries = _receipt_evidence_entries(store, run.run_id)
    entries.extend(_request_evidence_entries(request))
    try:
        evidence_index = build_evidence_index(entries)
    except ValueError as exc:
        raise DeliveryOrchestrationError(
            "evidence_path_unsafe", str(exc), step="evidence_index"
        ) from exc

    program_state, diagnostic = _program_delivery_state(team_id)
    diagnostics = [diagnostic] if diagnostic else []

    export_payload = {
        "approvedQuestionCount": program_state["approvedQuestionCount"],
        "r0": _gate_value(request, "r0"),
        "r1": _gate_value(request, "r1"),
        "r2": _gate_value(request, "r2"),
        "r3": _gate_value(request, "r3"),
        "pendingClaimCount": int(request.get("pendingClaimCount") or 0),
        "submissionProjectionFrozen": request.get("submissionProjectionFrozen") is True,
        "evidenceIndex": list(evidence_index.get("entries") or []),
    }
    projection_report = validate_submission_projection(
        {
            "submissionProjectionFrozen": export_payload["submissionProjectionFrozen"],
            "captured": program_state["captured"],
            "officialPageObservedState": program_state["officialPageObservedState"],
        }
    )
    preview_pack = export_results(export_payload, mode="preview")
    formal_pack = export_results(export_payload, mode="formal")

    size_bytes, size_source = _pdf_size_bytes(request, preview_pack)
    try:
        pdf_report = check_pdf_limit(size_bytes)
    except ValueError as exc:
        raise DeliveryOrchestrationError(
            "invalid_delivery_request", str(exc), step="pdf_limit"
        ) from exc
    pdf_report = {**pdf_report, "sizeSource": size_source}

    status = "succeeded" if pdf_report["withinLimit"] else "blocked"
    code = "" if status == "succeeded" else "pdf_limit_exceeded"
    detail = (
        ""
        if status == "succeeded"
        else (
            f"delivery content is {pdf_report['sizeBytes']} bytes, "
            f"over the {pdf_report['limitBytes']}-byte limit"
        )
    )

    artifact_payload = {
        "schemaVersion": 1,
        "teamId": team_id,
        "workflowRunId": run.run_id,
        "sourceCollectionRunId": authority_run_id,
        "deliveryStatus": status,
        "trigger": {
            "nodeId": _TRIGGER_NODE_ID,
            "completionKind": str(run.completion_kind or ""),
            "terminalReason": str(run.terminal_reason or ""),
        },
        "request": {
            "r0": export_payload["r0"],
            "r1": export_payload["r1"],
            "r2": export_payload["r2"],
            "r3": export_payload["r3"],
            "pendingClaimCount": export_payload["pendingClaimCount"],
            "submissionProjectionFrozen": export_payload["submissionProjectionFrozen"],
        },
        "steps": {
            "evidenceIndex": evidence_index,
            "submissionProjection": projection_report,
            "previewPack": preview_pack,
            "formalPack": formal_pack,
            "pdfLimit": pdf_report,
        },
        "formalBlockers": list(formal_pack.get("blockers") or []),
        "diagnostics": diagnostics,
    }
    put_workflow_artifact(
        team_id,
        kind=DELIVERY_ARTIFACT_KIND,
        workflow_run_id=run.run_id,
        source_collection_run_id=authority_run_id,
        payload=artifact_payload,
    )
    envelope = {
        "teamId": team_id,
        "kind": DELIVERY_ARTIFACT_KIND,
        "workflowRunId": run.run_id,
        "sourceCollectionRunId": authority_run_id,
        "payload": artifact_payload,
    }
    content_hash = canonical_sha256(envelope)
    artifact_ref = build_canonical_ref(
        kind=DELIVERY_ARTIFACT_KIND,
        team_id=team_id,
        authority_run_id=authority_run_id,
        content_hash=content_hash,
    )
    return {
        "status": status,
        "code": code,
        "detail": detail,
        "run": run,
        "artifactRef": artifact_ref,
        "artifactContentHash": content_hash,
        "approvedQuestionCount": program_state["approvedQuestionCount"],
        "evidenceEntryCount": int(evidence_index.get("entryCount") or 0),
        "formalBlockers": list(formal_pack.get("blockers") or []),
        "previewPackStatus": str(preview_pack.get("status") or ""),
        "submissionProjection": projection_report,
        "pdfCheck": pdf_report,
        "diagnostics": diagnostics,
    }


def delivery_event_payload(outcome: dict[str, Any]) -> dict[str, Any]:
    """Compact, diagnosable timeline payload for a terminal delivery event."""
    status = str(outcome.get("status") or "")
    code = str(outcome.get("code") or "")
    detail = str(outcome.get("detail") or "")
    reason = {
        "succeeded": "交付链已闭环：preview 包已导出",
        "blocked": f"交付链受阻：{detail or code}",
        "failed": f"交付链失败：{detail or code}",
    }.get(status, "交付链状态已更新")
    return {
        "nodeId": _TRIGGER_NODE_ID,
        "deliveryStatus": status,
        "code": code,
        "detail": detail,
        "reason": reason,
        "failedStep": str(outcome.get("failedStep") or ""),
        "approvedQuestionCount": int(outcome.get("approvedQuestionCount") or 0),
        "evidenceEntryCount": int(outcome.get("evidenceEntryCount") or 0),
        "previewPackStatus": str(outcome.get("previewPackStatus") or ""),
        "formalBlockers": [str(item) for item in outcome.get("formalBlockers") or []],
        "pdfCheck": dict(outcome.get("pdfCheck") or {}),
        "submissionProjection": dict(outcome.get("submissionProjection") or {}),
        "artifactKind": DELIVERY_ARTIFACT_KIND,
        "artifactRef": str(outcome.get("artifactRef") or ""),
        "diagnostics": [str(item) for item in outcome.get("diagnostics") or []],
    }


def delivery_event_type(status: str) -> str:
    return {
        "succeeded": DELIVERY_EVENT_COMPLETED,
        "blocked": DELIVERY_EVENT_BLOCKED,
        "failed": DELIVERY_EVENT_FAILED,
    }.get(status, DELIVERY_EVENT_FAILED)


def build_delivery_event(
    *,
    run: RunRecord,
    sequence: int,
    outcome: dict[str, Any],
    actor_id: str,
    correlation_id: str,
    now_ms: int,
) -> EventRecord:
    return EventRecord(
        run_id=run.run_id,
        sequence=sequence,
        event_id=new_id("evt"),
        run_version=run.run_version,
        event_type=delivery_event_type(str(outcome.get("status") or "")),
        actor_json=json.dumps(
            {"actorType": "system", "actorId": actor_id},
            ensure_ascii=False,
        ),
        correlation_id=correlation_id,
        causation_id=None,
        payload_json=json.dumps(delivery_event_payload(outcome), ensure_ascii=False),
        occurred_at_ms=now_ms,
    )


def run_status_allows_delivery(status: str) -> bool:
    return str(status or "") == RunStatus.SUCCEEDED.value
