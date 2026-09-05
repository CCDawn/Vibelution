"""Authoritative Challenge Cup phase-one approval and phase-two gate.

The 125-question result set becoming complete is a machine-observed content
fact.  It is intentionally separate from the operator's whole-package
approval and the Team Knowledge applied receipt.
"""

from __future__ import annotations

import hashlib
import json
import threading
import uuid
from collections.abc import Iterable
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.research.competition.resources import load_science_question_catalog
from core.web.services.team_workflow.research_projects import resolve_team_program_root

PHASE_ONE_REQUIRED_QUESTION_COUNT = 125
PHASE_BOUNDARY_SCHEMA_VERSION = 1
PHASE_TWO_DEEP_EXPERIMENT_QUESTION_IDS = frozenset({"SCI-091", "SCI-096"})
_STORE_LOCK = threading.RLock()


class ChallengePhaseBoundaryError(ValueError):
    """Raised when a phase-boundary command violates the domain contract."""


class PhaseTwoLockedError(ChallengePhaseBoundaryError):
    """Raised when a phase-two write is attempted before publication closes."""


def _text(value: Any) -> str:
    return str(value or "").strip()


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def build_phase_one_manifest(question_run_summary: dict[str, Any] | None) -> dict[str, Any]:
    """Build the immutable identity of the current 125-question package."""

    summary = question_run_summary if isinstance(question_run_summary, dict) else {}
    completed_ids = sorted(
        {
            _text(item)
            for item in summary.get("completedQuestionIds") or []
            if _text(item)
        }
    )
    result_by_question: dict[str, dict[str, str]] = {}
    for raw in summary.get("completedQuestionResults") or []:
        if not isinstance(raw, dict):
            continue
        question_id = _text(raw.get("questionId"))
        if not question_id or question_id not in completed_ids:
            continue
        result_by_question[question_id] = {
            "questionId": question_id,
            "runId": _text(raw.get("runId")),
            "outputSha256": _text(raw.get("outputSha256")),
            "artifactPath": _text(raw.get("artifactPath")),
        }
    package_items = [
        result_by_question.get(
            question_id,
            {
                "questionId": question_id,
                "runId": "",
                "outputSha256": "",
                "artifactPath": "",
            },
        )
        for question_id in completed_ids
    ]
    content_sha256 = _canonical_sha256(
        [
            {
                "questionId": item["questionId"],
                "outputSha256": item["outputSha256"],
            }
            for item in package_items
        ]
    )
    catalog = load_science_question_catalog()
    expected_ids = {
        _text(item.get("id"))
        for item in catalog.get("questions") or []
        if isinstance(item, dict) and _text(item.get("id"))
    }
    content_ready = (
        len(expected_ids) == PHASE_ONE_REQUIRED_QUESTION_COUNT
        and set(completed_ids) == expected_ids
        and len(result_by_question) == PHASE_ONE_REQUIRED_QUESTION_COUNT
        and all(
            _text(item.get("runId"))
            and _text(item.get("outputSha256"))
            and _text(item.get("artifactPath"))
            for item in package_items
        )
    )
    manifest_body = {
        "schemaVersion": PHASE_BOUNDARY_SCHEMA_VERSION,
        "kind": "challenge_phase_one_result_package",
        "requiredQuestionCount": PHASE_ONE_REQUIRED_QUESTION_COUNT,
        "questionCount": len(completed_ids),
        "questionIds": completed_ids,
        "resultRefs": package_items,
        "contentSha256": content_sha256,
        "contentReady": content_ready,
    }
    return {**manifest_body, "manifestSha256": _canonical_sha256(manifest_body)}


def _matching_record(
    records: Iterable[dict[str, Any]],
    *,
    status: str,
    manifest_sha256: str,
    content_sha256: str,
) -> dict[str, Any] | None:
    for record in reversed(list(records)):
        if not isinstance(record, dict):
            continue
        if (
            _text(record.get("status")) == status
            and _text(record.get("manifestSha256")) == manifest_sha256
            and _text(record.get("contentSha256")) == content_sha256
        ):
            return deepcopy(record)
    return None


def project_challenge_phase_boundary(
    *,
    manifest: dict[str, Any],
    approvals: Iterable[dict[str, Any]] = (),
    knowledge_receipts: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    manifest_sha256 = _text(manifest.get("manifestSha256"))
    content_sha256 = _text(manifest.get("contentSha256"))
    content_ready = manifest.get("contentReady") is True
    approval = _matching_record(
        approvals,
        status="approved",
        manifest_sha256=manifest_sha256,
        content_sha256=content_sha256,
    )
    receipt = _matching_record(
        knowledge_receipts,
        status="applied",
        manifest_sha256=manifest_sha256,
        content_sha256=content_sha256,
    )
    approved = content_ready and approval is not None
    knowledge_published = approved and receipt is not None
    publication_status = (
        "applied" if knowledge_published else "pending" if approved else "not_requested"
    )
    return {
        "schemaVersion": PHASE_BOUNDARY_SCHEMA_VERSION,
        "manifest": deepcopy(manifest),
        "phase1ContentReady": content_ready,
        "phase1Approved": approved,
        "phase1KnowledgePublished": knowledge_published,
        "phase1Complete": approved,
        "phase2Activated": approved and knowledge_published,
        "approval": approval,
        "knowledgeReceipt": receipt,
        "knowledgePublication": {
            "status": publication_status,
            "target": "challenge_cup_team_knowledge",
            "requestedAt": _text((approval or {}).get("knowledgePublicationRequestedAt")),
            "appliedAt": _text((receipt or {}).get("appliedAt")),
        },
    }


def require_phase_two_activation_from_projection(projection: dict[str, Any]) -> None:
    if projection.get("phase2Activated") is True:
        return
    if projection.get("phase1ContentReady") is not True:
        reason = "phase_one_content_incomplete"
    elif projection.get("phase1Approved") is not True:
        reason = "phase_one_approval_required"
    else:
        reason = "phase_one_knowledge_receipt_required"
    raise PhaseTwoLockedError(f"phase_two_locked: {reason}")


def request_targets_challenge_phase_two(payload: dict[str, Any] | None) -> bool:
    """Identify explicit Direction-B/deep-experiment write requests.

    Generic experiment planning is also used inside the phase-one research
    loop, so ``stageType=experiment`` alone is not a phase-two signal.
    """

    request = payload if isinstance(payload, dict) else {}
    for key in ("programPhase", "challengeProgramPhase", "executionPhase"):
        try:
            if int(request.get(key) or 0) == 2:
                return True
        except (TypeError, ValueError):
            continue
    question_id = _text(
        request.get("challengeQuestionId") or request.get("questionId")
    ).upper()
    return question_id in PHASE_TWO_DEEP_EXPERIMENT_QUESTION_IDS and (
        request.get("deepExperiment") is True
        or _text(request.get("programDirection")).upper() == "B"
    )


def research_project_targets_challenge_phase_two(
    project: dict[str, Any] | None,
) -> bool:
    """Use the canonical project binding, not client-declared phase labels."""

    record = project if isinstance(project, dict) else {}
    question_id = _text(record.get("challengeQuestionId")).upper()
    return question_id in PHASE_TWO_DEEP_EXPERIMENT_QUESTION_IDS


def _store_path(team_id: str) -> Path:
    return resolve_team_program_root(team_id) / "challenge_program" / "phase_boundary.json"


def _empty_store(team_id: str) -> dict[str, Any]:
    return {
        "schemaVersion": PHASE_BOUNDARY_SCHEMA_VERSION,
        "teamId": team_id,
        "approvals": [],
        "knowledgeReceipts": [],
        "updatedAt": "",
    }


def _load_store(team_id: str) -> dict[str, Any]:
    path = _store_path(team_id)
    if not path.exists():
        return _empty_store(team_id)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ChallengePhaseBoundaryError("phase_boundary_store_invalid") from exc
    if not isinstance(value, dict):
        raise ChallengePhaseBoundaryError("phase_boundary_store_invalid")
    value.setdefault("approvals", [])
    value.setdefault("knowledgeReceipts", [])
    return value


def _write_store(team_id: str, store: dict[str, Any]) -> None:
    path = _store_path(team_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(store, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def get_challenge_phase_boundary_status(
    team_id: str,
    *,
    question_run_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if question_run_summary is None:
        from core.web.services.team_workflow.challenge_question_runs import (
            challenge_question_run_summary,
        )

        question_run_summary = challenge_question_run_summary(team_id)
    manifest = build_phase_one_manifest(question_run_summary)
    with _STORE_LOCK:
        store = _load_store(team_id)
    projection = project_challenge_phase_boundary(
        manifest=manifest,
        approvals=store.get("approvals") or [],
        knowledge_receipts=store.get("knowledgeReceipts") or [],
    )
    return {"teamId": team_id, **projection, "updatedAt": _text(store.get("updatedAt"))}


def approve_current_phase_one_manifest(
    team_id: str,
    *,
    operator_id: str,
    operator_display_name: str = "",
    note: str = "",
    question_run_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    status = get_challenge_phase_boundary_status(
        team_id,
        question_run_summary=question_run_summary,
    )
    if status["phase1ContentReady"] is not True:
        raise ChallengePhaseBoundaryError("phase_one_content_incomplete")
    manifest = status["manifest"]
    now = _utc_now_iso()
    approval = {
        "approvalId": f"phase-one-approval-{uuid.uuid4().hex}",
        "status": "approved",
        "manifestSha256": manifest["manifestSha256"],
        "contentSha256": manifest["contentSha256"],
        "approvedBy": _text(operator_id),
        "approvedByDisplayName": _text(operator_display_name),
        "note": _text(note)[:1000],
        "approvedAt": now,
        "knowledgePublicationRequestedAt": now,
    }
    if not approval["approvedBy"]:
        raise ChallengePhaseBoundaryError("operator_identity_required")
    with _STORE_LOCK:
        store = _load_store(team_id)
        existing = _matching_record(
            store.get("approvals") or [],
            status="approved",
            manifest_sha256=manifest["manifestSha256"],
            content_sha256=manifest["contentSha256"],
        )
        if existing is None:
            store.setdefault("approvals", []).append(approval)
        store["updatedAt"] = now
        _write_store(team_id, store)
    return get_challenge_phase_boundary_status(
        team_id,
        question_run_summary=question_run_summary,
    )


def record_phase_one_knowledge_applied_receipt(
    team_id: str,
    receipt: dict[str, Any],
    *,
    question_run_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Record a trusted Team Knowledge applied receipt from the service layer."""

    status = get_challenge_phase_boundary_status(
        team_id,
        question_run_summary=question_run_summary,
    )
    if status["phase1Approved"] is not True:
        raise ChallengePhaseBoundaryError("phase_one_approval_required")
    manifest = status["manifest"]
    normalized = {
        "receiptId": _text(receipt.get("receiptId")),
        "proposalId": _text(receipt.get("proposalId")),
        "knowledgeBaseId": _text(receipt.get("knowledgeBaseId")),
        "knowledgeItemIds": [
            _text(item)
            for item in receipt.get("knowledgeItemIds") or []
            if _text(item)
        ],
        "batchId": _text(receipt.get("batchId")),
        "status": _text(receipt.get("status")),
        "manifestSha256": _text(receipt.get("manifestSha256")),
        "contentSha256": _text(receipt.get("contentSha256")),
        "appliedAt": _text(receipt.get("appliedAt")) or _utc_now_iso(),
    }
    if (
        normalized["status"] != "applied"
        or not normalized["receiptId"]
        or not normalized["knowledgeBaseId"]
        or not normalized["knowledgeItemIds"]
        or not normalized["batchId"]
    ):
        raise ChallengePhaseBoundaryError("knowledge_applied_receipt_required")
    if (
        normalized["manifestSha256"] != manifest["manifestSha256"]
        or normalized["contentSha256"] != manifest["contentSha256"]
    ):
        raise ChallengePhaseBoundaryError("knowledge_receipt_hash_mismatch")
    with _STORE_LOCK:
        store = _load_store(team_id)
        existing = _matching_record(
            store.get("knowledgeReceipts") or [],
            status="applied",
            manifest_sha256=manifest["manifestSha256"],
            content_sha256=manifest["contentSha256"],
        )
        if existing is None:
            store.setdefault("knowledgeReceipts", []).append(normalized)
        store["updatedAt"] = normalized["appliedAt"]
        _write_store(team_id, store)
    return get_challenge_phase_boundary_status(
        team_id,
        question_run_summary=question_run_summary,
    )


def require_phase_two_activation(team_id: str) -> dict[str, Any]:
    projection = get_challenge_phase_boundary_status(team_id)
    require_phase_two_activation_from_projection(projection)
    return projection
