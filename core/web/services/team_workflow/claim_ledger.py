"""Append-only claim ledger service with accepted-evidence support gating.

A claim can only become ``supported`` when every referenced evidence record is
accepted and scope-consistent.  Meeting text can never promote a claim
directly: meeting-sourced claims always start as ``proposed``.  Supersede and
retract are append-only operations that preserve the affected records and
their counter-evidence.  Pure offline JSONL under the team workspace.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.infrastructure import developer_sandbox
from core.research.workflow.contracts import (
    ACCEPTED_REVIEW_STATUS,
    ClaimLedgerEntry,
    ContractValidationError,
    scope_hash_for,
)

SCHEMA_VERSION = 1
DEFAULT_MODE = "formal"
_LOCK = threading.RLock()
_SCOPE_FIELDS = ("program", "theme", "campaign", "question", "branch", "workflow")

PROJECT_ROOT = Path(__file__).resolve().parents[4]


class ClaimLedgerError(RuntimeError):
    """Base error for claim ledger persistence."""


class ClaimLedgerClaimNotFoundError(ClaimLedgerError):
    """Raised when a claim does not exist."""


class ClaimLedgerNotSupportedError(ClaimLedgerError):
    """Raised when a claim lacks accepted, scope-consistent supporting evidence."""


def _project_root() -> Path:
    return Path(PROJECT_ROOT)


def _safe_team_id(team_id: str) -> str:
    return (
        "".join(
            character if character.isalnum() or character in "._-" else "_"
            for character in str(team_id or "")
        )[:96]
        or "team"
    )


def _team_workspace_root(team_id: str) -> Path:
    return developer_sandbox.seeded_sandbox_workspace_path(
        _project_root(),
        "teams",
        _safe_team_id(team_id),
    )


def _kind_path(team_id: str, kind: str) -> Path:
    return _team_workspace_root(team_id) / "research_workflow" / f"{kind}.jsonl"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _stable_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ClaimLedgerError(
                f"Invalid claim ledger JSONL at line {line_number}."
            ) from exc
        if not isinstance(payload, dict):
            raise ClaimLedgerError(
                f"Invalid claim ledger record at line {line_number}."
            )
        records.append(payload)
    return records


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    line = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(existing)
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def _resolve_scope(payload: Mapping[str, Any]) -> dict[str, str]:
    identity: dict[str, str] = {}
    for field in _SCOPE_FIELDS:
        value = str(payload.get(field) or "").strip()
        if not value:
            raise ContractValidationError(
                f"scope requires a non-empty '{field}' field"
            )
        identity[field] = value
    agent_id = str(payload.get("agentId") or "").strip()
    if not agent_id:
        raise ContractValidationError("scope requires a non-empty agentId")
    mode = str(payload.get("mode") or "").strip().lower() or DEFAULT_MODE
    if mode not in {"formal", "dev", "platform"}:
        raise ContractValidationError(f"unsupported scope mode: {mode}")
    scope_hash = scope_hash_for(**identity, agent_id=agent_id, mode=mode)
    return {**identity, "agentId": agent_id, "mode": mode, "scopeHash": scope_hash}


def _latest_by_id(records: list[dict[str, Any]], field: str, record_id: str) -> dict[str, Any] | None:
    matched = [record for record in records if str(record.get(field) or "") == record_id]
    return matched[-1] if matched else None


def _store_path(team_id: str) -> Path:
    return _kind_path(team_id, "claim_ledger")


def _normalize_evidence_refs(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ContractValidationError("evidenceRefs must be a list")
    refs: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ContractValidationError("each evidence ref must be an object")
        refs.append(
            {
                "claimEvidenceId": str(item.get("claimEvidenceId") or "").strip(),
                "scopeHash": str(item.get("scopeHash") or "").strip().lower(),
                "reviewStatus": str(item.get("reviewStatus") or "").strip().lower(),
                "supportLevel": str(item.get("supportLevel") or "").strip().lower(),
                "sourceId": str(item.get("sourceId") or "").strip(),
            }
        )
    return refs


def _claim_seed(payload: dict[str, Any], scope: dict[str, str]) -> str:
    return _stable_hash(
        {
            "claim": str(payload.get("claim") or "").strip(),
            "scopeHash": scope["scopeHash"],
            "createdBy": str(payload.get("createdBy") or "").strip(),
        }
    )


def _claim_definition(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: record.get(key)
        for key in (
            "claimId",
            "claim",
            "program",
            "theme",
            "campaign",
            "question",
            "branch",
            "workflow",
            "agentId",
            "mode",
            "scopeHash",
            "status",
            "source",
            "evidenceRefs",
            "counterEvidenceRefs",
            "supersedesClaimId",
            "retractsClaimId",
            "meetingPromotionAllowed",
            "createdBy",
        )
    }


def propose_claim(team_id: str, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Append one proposed claim.  Meeting text can never carry evidence refs."""
    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    request = dict(payload) if isinstance(payload, Mapping) else {}
    scope = _resolve_scope(request)
    source = str(request.get("source") or "agent").strip().lower()
    claim_text = str(request.get("claim") or "").strip()
    if not claim_text:
        raise ContractValidationError("claim text is required")
    created_by = str(request.get("createdBy") or "").strip()
    if not created_by:
        raise ContractValidationError("createdBy is required")
    evidence_refs = _normalize_evidence_refs(request.get("evidenceRefs") or [])
    if source == "meeting":
        if evidence_refs:
            raise ContractValidationError(
                "meeting text can never promote a claim directly"
            )
    claim_id = (
        str(request.get("claimId") or "").strip()
        or f"claim-{_claim_seed(request, scope)[:20]}"
    )
    record: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "claimId": claim_id,
        "claim": claim_text,
        "program": scope["program"],
        "theme": scope["theme"],
        "campaign": scope["campaign"],
        "question": scope["question"],
        "branch": scope["branch"],
        "workflow": scope["workflow"],
        "agentId": scope["agentId"],
        "mode": scope["mode"],
        "scopeHash": scope["scopeHash"],
        "status": "proposed",
        "source": source,
        "evidenceRefs": evidence_refs,
        "counterEvidenceRefs": [
            str(item or "").strip() for item in list(request.get("counterEvidenceRefs") or []) if str(item or "").strip()
        ],
        "supersedesClaimId": str(request.get("supersedesClaimId") or "").strip(),
        "retractsClaimId": "",
        "meetingPromotionAllowed": False,
        "createdBy": created_by,
        "createdAt": _utc_now(),
    }
    ClaimLedgerEntry.from_dict(record)
    with _LOCK:
        existing = _latest_by_id(_read_jsonl(_store_path(normalized_team_id)), "claimId", claim_id)
        if existing is not None and existing.get("schemaVersion") is not None:
            if _claim_definition(existing) != _claim_definition(record):
                raise ClaimLedgerError(
                    "claim id is already bound to different content"
                )
            return {
                "schemaVersion": SCHEMA_VERSION,
                "teamId": normalized_team_id,
                "status": "reused",
                "claim": existing,
                "storagePath": str(_store_path(normalized_team_id)),
            }
        _append_jsonl(_store_path(normalized_team_id), record)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "status": "created",
        "claim": record,
        "storagePath": str(_store_path(normalized_team_id)),
    }


def _accepted_scope_consistent_refs(
    evidence_refs: Sequence[Mapping[str, Any]],
    scope_hash: str,
) -> list[dict[str, Any]]:
    accepted: list[dict[str, Any]] = []
    for ref in evidence_refs:
        if str(ref.get("reviewStatus") or "").lower() != ACCEPTED_REVIEW_STATUS:
            raise ClaimLedgerNotSupportedError(
                "only accepted evidence can support a claim"
            )
        if str(ref.get("scopeHash") or "").lower() != scope_hash:
            raise ClaimLedgerNotSupportedError(
                "evidence scope must match the claim scope"
            )
        accepted.append(dict(ref))
    return accepted


def support_claim(
    team_id: str,
    claim_id: str,
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Support an existing proposed claim with accepted, scope-consistent evidence.

    Counter-evidence among the accepted refs is preserved on the record.
    A claim with no supporting accepted evidence cannot be supported.
    """
    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    normalized_claim_id = str(claim_id or "").strip()
    if not normalized_claim_id:
        raise ClaimLedgerError("Claim id is required.")
    request = dict(payload) if isinstance(payload, Mapping) else {}
    with _LOCK:
        records = _read_jsonl(_store_path(normalized_team_id))
        current = _latest_by_id(records, "claimId", normalized_claim_id)
        if current is None:
            raise ClaimLedgerClaimNotFoundError("Claim not found.")
        evidence_refs = _normalize_evidence_refs(request.get("evidenceRefs") or [])
        if not evidence_refs:
            raise ClaimLedgerNotSupportedError(
                "supporting a claim requires accepted, scope-consistent evidence"
            )
        accepted = _accepted_scope_consistent_refs(
            evidence_refs,
            str(current.get("scopeHash") or ""),
        )
        supporting = [
            ref for ref in accepted if str(ref.get("supportLevel") or "").lower() == "supports"
        ]
        counter = [
            ref for ref in accepted if str(ref.get("supportLevel") or "").lower() != "supports"
        ]
        if not supporting:
            raise ClaimLedgerNotSupportedError(
                "accepted evidence must support the claim; contradictory-only evidence cannot promote it"
            )
        now = _utc_now()
        record = dict(current)
        record["status"] = "supported"
        record["evidenceRefs"] = accepted
        record["counterEvidenceRefs"] = sorted(
            {
                *list(current.get("counterEvidenceRefs") or []),
                *(str(ref.get("claimEvidenceId") or "") for ref in counter),
            }
        )
        record["supportedAt"] = now
        record["supportedBy"] = str(request.get("supportedBy") or "").strip()
        record["meetingPromotionAllowed"] = False
        ClaimLedgerEntry.from_dict(record)
        latest_stored = _latest_by_id(
            _read_jsonl(_store_path(normalized_team_id)),
            "claimId",
            normalized_claim_id,
        )
        if (
            latest_stored is not None
            and str(latest_stored.get("status") or "") == "supported"
            and latest_stored.get("evidenceRefs") == accepted
        ):
            return {
                "schemaVersion": SCHEMA_VERSION,
                "teamId": normalized_team_id,
                "status": "reused",
                "claim": latest_stored,
                "storagePath": str(_store_path(normalized_team_id)),
            }
        _append_jsonl(_store_path(normalized_team_id), record)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "status": "created",
        "claim": record,
        "counterEvidencePreserved": bool(record["counterEvidenceRefs"]),
        "storagePath": str(_store_path(normalized_team_id)),
    }


def supersede_claim(
    team_id: str,
    claim_id: str,
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Append a new claim that supersedes an existing one, preserving the old.

    The old record is never rewritten; a superseded marker is appended to its
    history and the new claim links back via ``supersedesClaimId``.
    """
    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    normalized_claim_id = str(claim_id or "").strip()
    if not normalized_claim_id:
        raise ClaimLedgerError("Claim id is required.")
    request = dict(payload) if isinstance(payload, Mapping) else {}
    with _LOCK:
        records = _read_jsonl(_store_path(normalized_team_id))
        current = _latest_by_id(records, "claimId", normalized_claim_id)
        if current is None:
            raise ClaimLedgerClaimNotFoundError("Claim not found.")
        superseding_payload = {
            **{
                key: current[key]
                for key in (
                    "program",
                    "theme",
                    "campaign",
                    "question",
                    "branch",
                    "workflow",
                    "agentId",
                    "mode",
                )
            },
            "claim": str(request.get("claim") or current.get("claim") or "").strip(),
            "createdBy": str(request.get("createdBy") or "").strip(),
            "source": str(request.get("source") or "agent").strip().lower(),
            "supersedesClaimId": normalized_claim_id,
        }
        created = propose_claim(normalized_team_id, superseding_payload)
        new_claim = created["claim"]
        if str(new_claim.get("supersedesClaimId") or "") != normalized_claim_id:
            raise ClaimLedgerError("superseding claim was not linked back to its parent")
        now = _utc_now()
        superseded_marker = dict(current)
        superseded_marker["status"] = "superseded"
        superseded_marker["supersededByClaimId"] = str(new_claim.get("claimId") or "")
        superseded_marker["supersededAt"] = now
        ClaimLedgerEntry.from_dict(superseded_marker)
        latest_stored = _latest_by_id(
            _read_jsonl(_store_path(normalized_team_id)),
            "claimId",
            normalized_claim_id,
        )
        if latest_stored is None or str(latest_stored.get("status") or "") != "superseded":
            _append_jsonl(_store_path(normalized_team_id), superseded_marker)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "status": "created",
        "supersededClaim": superseded_marker,
        "claim": new_claim,
        "storagePath": str(_store_path(normalized_team_id)),
    }


def retract_claim(
    team_id: str,
    claim_id: str,
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Append a retraction marker, preserving the claim's evidence and counter-evidence."""
    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    normalized_claim_id = str(claim_id or "").strip()
    if not normalized_claim_id:
        raise ClaimLedgerError("Claim id is required.")
    request = dict(payload) if isinstance(payload, Mapping) else {}
    with _LOCK:
        records = _read_jsonl(_store_path(normalized_team_id))
        current = _latest_by_id(records, "claimId", normalized_claim_id)
        if current is None:
            raise ClaimLedgerClaimNotFoundError("Claim not found.")
        if str(current.get("status") or "") == "retracted":
            return {
                "schemaVersion": SCHEMA_VERSION,
                "teamId": normalized_team_id,
                "status": "reused",
                "claim": current,
                "storagePath": str(_store_path(normalized_team_id)),
            }
        now = _utc_now()
        retracted = dict(current)
        retracted["status"] = "retracted"
        retracted["retractedAt"] = now
        retracted["retractedBy"] = str(request.get("retractedBy") or "").strip()
        retracted["retractionReason"] = str(request.get("retractionReason") or "").strip()
        ClaimLedgerEntry.from_dict(retracted)
        _append_jsonl(_store_path(normalized_team_id), retracted)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "status": "created",
        "claim": retracted,
        "counterEvidencePreserved": bool(retracted.get("counterEvidenceRefs")),
        "storagePath": str(_store_path(normalized_team_id)),
    }


def get_claim(team_id: str, claim_id: str) -> dict[str, Any]:
    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    normalized_claim_id = str(claim_id or "").strip()
    with _LOCK:
        records = _read_jsonl(_store_path(normalized_team_id))
        record = _latest_by_id(records, "claimId", normalized_claim_id)
    if record is None:
        raise ClaimLedgerClaimNotFoundError("Claim not found.")
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "claim": record,
        "storagePath": str(_store_path(normalized_team_id)),
    }


def list_claims(team_id: str) -> dict[str, Any]:
    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    with _LOCK:
        records = _read_jsonl(_store_path(normalized_team_id))
    latest: dict[str, dict[str, Any]] = {}
    for record in records:
        latest[str(record.get("claimId") or "")] = record
    rows = sorted(latest.values(), key=lambda item: str(item.get("createdAt") or ""))
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "claimCount": len(rows),
        "claims": rows,
        "storagePath": str(_store_path(normalized_team_id)),
    }
