"""Immutable question-level registry for every real model invocation receipt."""

from __future__ import annotations

import hashlib
import json
import os
from copy import deepcopy
from pathlib import Path
from threading import RLock
from typing import Any, Mapping, Sequence
from uuid import uuid4

from core.research.workflow.contracts.model_invocation_receipt import (
    ModelInvocationReceipt,
    ModelInvocationStatus,
)
from core.web.services.team_workflow.research_projects import resolve_team_program_root

STORE_SCHEMA_VERSION = 1
STORE_KIND = "challenge_question_model_invocation_receipts"
REQUIRED_OUTCOME_KINDS = frozenset(
    {"candidate", "review", "revision", "plan", "final_output"}
)
ALLOWED_OUTCOME_KINDS = REQUIRED_OUTCOME_KINDS | frozenset({"source_evidence"})
_LOCK = RLock()


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _path_component(value: Any, *, field_name: str) -> str:
    """Map an audit identifier to an irreversible, single path component."""

    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field_name} is required")
    # Never place caller-controlled identifiers in a filesystem path.  The
    # digest is also safe for values such as '.', '..', '/' and '\\'.
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _path(team_id: str, question_id: str, workflow_run_id: str) -> Path:
    normalized_question = str(question_id or "").strip().upper()
    normalized_run = str(workflow_run_id or "").strip()
    safe_question = _path_component(normalized_question, field_name="questionId")
    safe_run = _path_component(normalized_run, field_name="workflowRunId")
    return (
        resolve_team_program_root(team_id)
        / "challenge_program"
        / "model_invocation_receipts"
        / safe_question
        / f"{safe_run}.json"
    )


def _load(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    if not path.is_file():
        raise ValueError("model invocation receipt store path is not a file")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("model invocation receipt store is unreadable or corrupt") from exc
    if not isinstance(payload, dict):
        raise ValueError("model invocation receipt store must be a JSON object")
    return payload


def _write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Keep the atomic sibling name short.  The receipt path already contains
    # two SHA-256 segments, so repeating the target basename plus a full UUID
    # can exceed the legacy Windows MAX_PATH boundary even when the final file
    # itself is valid.
    temporary = path.with_name(f".tmp-{uuid4().hex[:12]}")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _outcome_kinds(receipt: ModelInvocationReceipt) -> tuple[str, ...]:
    raw = receipt.metadata.get("outcomeKinds")
    values = tuple(
        dict.fromkeys(
            str(item or "").strip().lower()
            for item in list(raw or [])
            if str(item or "").strip()
        )
    )
    if not values or any(item not in ALLOWED_OUTCOME_KINDS for item in values):
        raise ValueError("model invocation receipt outcomeKinds are invalid")
    return values


def _require_lower_sha256(value: Any, *, field_name: str) -> str:
    normalized = str(value or "").strip()
    if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
        raise ValueError(f"{field_name} must be a lowercase sha256 hex digest")
    return normalized


def _validate_receipt(
    value: Mapping[str, Any],
    *,
    question_id: str,
    workflow_run_id: str,
) -> ModelInvocationReceipt:
    if not isinstance(value, Mapping):
        raise ValueError("model invocation receipt must be an object")
    receipt = ModelInvocationReceipt.from_dict(value)
    if receipt.status not in {
        ModelInvocationStatus.SUCCEEDED,
        ModelInvocationStatus.RETRIED,
    }:
        raise ValueError("only successful model invocation receipts may be registered")
    scope = dict(receipt.scope or {})
    locator = dict(receipt.evidence_locator or {})
    normalized_question = str(question_id or "").strip().upper()
    normalized_run = str(workflow_run_id or "").strip()
    if str(scope.get("questionId") or "").strip().upper() != normalized_question:
        raise ValueError("model invocation receipt question scope mismatch")
    if receipt.run_id != normalized_run:
        raise ValueError("model invocation receipt run mismatch")
    if str(scope.get("workflowRunId") or "").strip() != normalized_run:
        raise ValueError("model invocation receipt workflow run scope mismatch")
    for scope_key, locator_key in (
        ("sessionId", "sessionId"),
        ("taskId", "taskId"),
        ("turnId", "turnId"),
        ("formalNodeId", "formalNodeId"),
        ("formalNodeRunId", "formalNodeRunId"),
        ("modelPolicySha256", "modelPolicySha256"),
    ):
        if not str(scope.get(scope_key) or "").strip() or (
            str(scope.get(scope_key) or "").strip()
            != str(locator.get(locator_key) or "").strip()
        ):
            raise ValueError(f"model invocation receipt {scope_key} locator mismatch")
    node_run_id = str(receipt.node_run_id or "").strip()
    if (
        not node_run_id
        or node_run_id != str(scope.get("formalNodeRunId") or "").strip()
        or node_run_id != str(locator.get("formalNodeRunId") or "").strip()
    ):
        raise ValueError("model invocation receipt nodeRunId scope mismatch")
    _require_lower_sha256(scope.get("modelPolicySha256"), field_name="modelPolicySha256")
    for locator_key in (
        "kind",
        "outputRef",
        "invocationId",
    ):
        if not str(locator.get(locator_key) or "").strip():
            raise ValueError(f"model invocation receipt evidenceLocator.{locator_key} is required")
    _require_lower_sha256(locator.get("outputSha256"), field_name="evidenceLocator.outputSha256")
    try:
        locator_attempt = int(locator.get("attempt"))
    except (TypeError, ValueError) as exc:
        raise ValueError("evidenceLocator.attempt must be an integer") from exc
    if isinstance(locator.get("attempt"), bool) or locator_attempt != int(receipt.attempt):
        raise ValueError("model invocation receipt attempt locator mismatch")
    _outcome_kinds(receipt)
    return receipt


def _validate_store_payload(
    payload: Mapping[str, Any] | None,
    *,
    team_id: str,
    question_id: str,
    workflow_run_id: str,
) -> list[dict[str, Any]]:
    """Validate an existing store before it can participate in a write."""

    if payload is None:
        return []
    if (
        payload.get("schemaVersion") != STORE_SCHEMA_VERSION
        or payload.get("storeKind") != STORE_KIND
        or str(payload.get("teamId") or "") != team_id
        or str(payload.get("questionId") or "").strip().upper() != question_id
        or str(payload.get("workflowRunId") or "") != workflow_run_id
    ):
        raise ValueError("model invocation receipt store header is invalid")
    raw_receipts = payload.get("receipts")
    if not isinstance(raw_receipts, list):
        raise ValueError("model invocation receipt store receipts must be a list")
    values: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_receipts:
        if not isinstance(raw, Mapping):
            raise ValueError("model invocation receipt store contains a non-object receipt")
        receipt = _validate_receipt(
            raw,
            question_id=question_id,
            workflow_run_id=workflow_run_id,
        )
        if receipt.receipt_id in seen:
            raise ValueError("model invocation receipt store contains duplicate receiptId")
        seen.add(receipt.receipt_id)
        values.append(dict(raw))
    return values


def register_question_model_invocation_receipts(
    team_id: str,
    *,
    question_id: str,
    workflow_run_id: str,
    receipts: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Append receipts idempotently; a conflicting receipt id fails closed."""

    normalized_team = str(team_id or "").strip()
    normalized_question = str(question_id or "").strip().upper()
    normalized_run = str(workflow_run_id or "").strip()
    if not normalized_team:
        raise ValueError("teamId is required")
    validated = []
    for value in receipts:
        if not isinstance(value, Mapping):
            raise ValueError("model invocation receipt must be an object")
        validated.append(
            _validate_receipt(
                value,
                question_id=normalized_question,
                workflow_run_id=normalized_run,
            )
        )
    path = _path(normalized_team, normalized_question, normalized_run)
    with _LOCK:
        stored = _load(path)
        existing_values = _validate_store_payload(
            stored,
            team_id=normalized_team,
            question_id=normalized_question,
            workflow_run_id=normalized_run,
        )
        existing = {
            str(item.get("receiptId") or "").strip(): item for item in existing_values
        }
        changed = False
        for receipt in validated:
            payload = receipt.to_dict()
            previous = existing.get(receipt.receipt_id)
            if previous is not None:
                if previous != payload:
                    raise ValueError("model invocation receipt replay conflict")
                continue
            existing[receipt.receipt_id] = payload
            existing_values.append(payload)
            changed = True
        if changed or stored is None:
            _write(
                path,
                {
                    "schemaVersion": STORE_SCHEMA_VERSION,
                    "storeKind": STORE_KIND,
                    "teamId": normalized_team,
                    "questionId": normalized_question,
                    "workflowRunId": normalized_run,
                    "receipts": existing_values,
                },
            )
    return question_model_invocation_receipt_refs(
        normalized_team,
        question_id=normalized_question,
        workflow_run_id=normalized_run,
    )


def question_model_invocation_receipt_refs(
    team_id: str,
    *,
    question_id: str,
    workflow_run_id: str,
) -> list[dict[str, Any]]:
    """Return hash-verifiable locators, refusing an unreadable/tampered store."""

    normalized_question = str(question_id or "").strip().upper()
    normalized_run = str(workflow_run_id or "").strip()
    try:
        payload = _load(_path(team_id, normalized_question, normalized_run))
        existing_values = _validate_store_payload(
            payload,
            team_id=str(team_id or "").strip(),
            question_id=normalized_question,
            workflow_run_id=normalized_run,
        )
    except (OSError, TypeError, ValueError):
        return []
    if not existing_values:
        return []
    refs: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        for raw in existing_values:
            receipt = _validate_receipt(
                raw,
                question_id=normalized_question,
                workflow_run_id=normalized_run,
            )
            if receipt.receipt_id in seen:
                return []
            seen.add(receipt.receipt_id)
            locator = deepcopy(dict(receipt.evidence_locator))
            refs.append(
                {
                    "receiptId": receipt.receipt_id,
                    "receiptSha256": _canonical_sha256(receipt.to_dict()),
                    "nodeRunId": receipt.node_run_id,
                    "sessionId": str(receipt.scope.get("sessionId") or ""),
                    "turnId": str(receipt.scope.get("turnId") or ""),
                    "outcomeKinds": list(_outcome_kinds(receipt)),
                    "evidenceLocator": locator,
                    "evidenceLocatorSha256": _canonical_sha256(locator),
                }
            )
    except (TypeError, ValueError, KeyError):
        return []
    return refs


def model_invocation_receipt_coverage(
    refs: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    covered = {
        str(kind or "").strip().lower()
        for ref in refs
        if isinstance(ref, Mapping)
        for kind in list(ref.get("outcomeKinds") or [])
        if str(kind or "").strip()
    }
    observed = sorted(covered & REQUIRED_OUTCOME_KINDS)
    missing = sorted(REQUIRED_OUTCOME_KINDS - covered)
    return {
        "status": "observed" if observed else "missing",
        "observedKinds": observed,
        "coveredKinds": observed,
        "missingKinds": missing,
        "receiptCount": len(list(refs)),
    }


def model_invocation_receipt_evidence_entries(
    team_id: str,
    *,
    question_id: str,
    workflow_run_id: str,
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for ref in question_model_invocation_receipt_refs(
        team_id,
        question_id=question_id,
        workflow_run_id=workflow_run_id,
    ):
        entries.append(
            {
                "path": f"model-invocations/{ref['receiptId']}.json",
                "kind": "model_invocation_receipt",
                "sha256": ref["receiptSha256"],
                "scope": {
                    "questionId": str(question_id or "").strip().upper(),
                    "runId": str(workflow_run_id or "").strip(),
                    "nodeRunId": ref["nodeRunId"],
                    "outcomeKinds": list(ref["outcomeKinds"]),
                    "evidenceLocator": deepcopy(ref["evidenceLocator"]),
                    "evidenceLocatorSha256": ref["evidenceLocatorSha256"],
                },
            }
        )
    return entries


__all__ = [
    "ALLOWED_OUTCOME_KINDS",
    "REQUIRED_OUTCOME_KINDS",
    "model_invocation_receipt_coverage",
    "model_invocation_receipt_evidence_entries",
    "question_model_invocation_receipt_refs",
    "register_question_model_invocation_receipts",
]
