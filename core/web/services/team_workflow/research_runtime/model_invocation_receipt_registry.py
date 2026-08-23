"""Immutable question-level registry for every real model invocation receipt."""

from __future__ import annotations

import hashlib
import json
import os
from copy import deepcopy
from pathlib import Path
from threading import RLock
from typing import Any, Mapping, Sequence
from urllib.parse import quote
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


def _path(team_id: str, question_id: str, workflow_run_id: str) -> Path:
    safe_question = quote(str(question_id or "").strip().upper(), safe="")
    safe_run = quote(str(workflow_run_id or "").strip(), safe="")
    if not safe_question or not safe_run:
        raise ValueError("questionId and workflowRunId are required")
    return (
        resolve_team_program_root(team_id)
        / "challenge_program"
        / "model_invocation_receipts"
        / safe_question
        / f"{safe_run}.json"
    )


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
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
    if not values or any(item not in REQUIRED_OUTCOME_KINDS for item in values):
        raise ValueError("model invocation receipt outcomeKinds are invalid")
    return values


def _validate_receipt(
    value: Mapping[str, Any],
    *,
    question_id: str,
    workflow_run_id: str,
) -> ModelInvocationReceipt:
    receipt = ModelInvocationReceipt.from_dict(value)
    if receipt.status not in {
        ModelInvocationStatus.SUCCEEDED,
        ModelInvocationStatus.RETRIED,
    }:
        raise ValueError("only successful model invocation receipts may be registered")
    scope = dict(receipt.scope or {})
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
    ):
        if not str(scope.get(scope_key) or "").strip() or (
            str(scope.get(scope_key) or "").strip()
            != str(receipt.evidence_locator.get(locator_key) or "").strip()
        ):
            raise ValueError(f"model invocation receipt {scope_key} locator mismatch")
    _outcome_kinds(receipt)
    return receipt


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
    validated = [
        _validate_receipt(
            value,
            question_id=normalized_question,
            workflow_run_id=normalized_run,
        )
        for value in receipts
        if isinstance(value, Mapping)
    ]
    path = _path(normalized_team, normalized_question, normalized_run)
    with _LOCK:
        stored = _load(path)
        existing_values = [
            item for item in list(stored.get("receipts") or []) if isinstance(item, dict)
        ]
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
        if changed or not stored:
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
    payload = _load(_path(team_id, normalized_question, normalized_run))
    if not payload:
        return []
    if (
        payload.get("schemaVersion") != STORE_SCHEMA_VERSION
        or payload.get("storeKind") != STORE_KIND
        or str(payload.get("teamId") or "") != str(team_id or "").strip()
        or str(payload.get("questionId") or "").upper() != normalized_question
        or str(payload.get("workflowRunId") or "") != normalized_run
    ):
        return []
    refs: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        for raw in list(payload.get("receipts") or []):
            if not isinstance(raw, Mapping):
                return []
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
    missing = sorted(REQUIRED_OUTCOME_KINDS - covered)
    return {
        "status": "passed" if not missing else "failed",
        "coveredKinds": sorted(covered & REQUIRED_OUTCOME_KINDS),
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
    "REQUIRED_OUTCOME_KINDS",
    "model_invocation_receipt_coverage",
    "model_invocation_receipt_evidence_entries",
    "question_model_invocation_receipt_refs",
    "register_question_model_invocation_receipts",
]
