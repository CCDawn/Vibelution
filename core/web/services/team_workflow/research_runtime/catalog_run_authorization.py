"""Auditable authorization records for real catalog batches.

The authorization is deliberately separate from the DEV control snapshot.  A
snapshot answers what the platform currently reports; this module records who
approved a concrete batch scope, when they approved it, and the exact readiness
evidence hash they relied on.  Future readiness reports can use the same API
without changing the Ledger schema or accepting a boolean confirmation as
evidence.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Mapping
from typing import Any

from core.research.workflow.ledger import CatalogRunAuthorization

from .formal_write_runtime import get_write_store

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class CatalogRunAuthorizationError(ValueError):
    """The approval evidence is malformed, stale, or unavailable."""


def canonical_sha256(value: Mapping[str, Any] | list[Any] | str) -> str:
    """Hash JSON evidence with one stable representation."""

    if isinstance(value, str):
        raw = value.encode("utf-8")
    else:
        raw = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _require_sha256(value: str, *, label: str) -> str:
    normalized = str(value or "").strip().lower()
    if not _SHA256_RE.fullmatch(normalized):
        raise CatalogRunAuthorizationError(
            f"{label} must be a lowercase sha256 hex digest."
        )
    return normalized


def readiness_report_sha256(
    evidence: Mapping[str, Any] | list[Any] | str,
) -> str:
    """Return the canonical hash of a readiness report/evidence object."""

    if isinstance(evidence, str) and _SHA256_RE.fullmatch(evidence.strip().lower()):
        return evidence.strip().lower()
    return canonical_sha256(evidence)


def require_readiness_report_sha256(value: str) -> str:
    """Validate a caller-provided digest rather than hashing the text again."""

    return _require_sha256(value, label="readiness_report_sha256")


def batch_scope_sha256(batch_scope: Mapping[str, Any] | list[Any]) -> str:
    return canonical_sha256(batch_scope)


def _record_hash_payload(record: CatalogRunAuthorization) -> dict[str, Any]:
    try:
        scope = json.loads(record.batch_scope_json)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise CatalogRunAuthorizationError("catalog authorization scope is invalid") from exc
    return {
        "authorizationId": record.authorization_id,
        "teamId": record.team_id,
        "planId": record.plan_id,
        "batchScope": scope,
        "scopeHash": record.scope_hash,
        "approvedBy": record.approved_by,
        "approvedAtMs": record.approved_at_ms,
        "readinessReportSha256": record.readiness_report_sha256,
        "createdAtMs": record.created_at_ms,
    }


def expected_record_hash(record: CatalogRunAuthorization) -> str:
    return canonical_sha256(_record_hash_payload(record))


def validate_catalog_run_authorization(
    record: CatalogRunAuthorization,
    *,
    team_id: str | None = None,
    plan_id: str | None = None,
    scope_hash: str | None = None,
    readiness_sha256: str | None = None,
) -> bool:
    """Validate immutable content and optional lookup scope before use."""

    if team_id is not None and record.team_id != str(team_id):
        return False
    if plan_id is not None and record.plan_id != str(plan_id):
        return False
    try:
        report_hash = _require_sha256(
            record.readiness_report_sha256, label="readiness_report_sha256"
        )
        expected_scope_hash = _require_sha256(record.scope_hash, label="scope_hash")
        scope = json.loads(record.batch_scope_json)
    except (CatalogRunAuthorizationError, TypeError, ValueError, json.JSONDecodeError):
        return False
    if not isinstance(scope, (dict, list)):
        return False
    if batch_scope_sha256(scope) != expected_scope_hash:
        return False
    if scope_hash is not None and expected_scope_hash != str(scope_hash):
        return False
    if readiness_sha256 is not None and report_hash != str(readiness_sha256):
        return False
    if not record.authorization_id or not record.team_id or not record.plan_id:
        return False
    if not record.approved_by.strip() or record.approved_at_ms <= 0 or record.created_at_ms <= 0:
        return False
    return record.record_hash == expected_record_hash(record)


def find_catalog_run_authorization(
    team_id: str,
    *,
    plan_id: str,
    batch_scope: Mapping[str, Any] | list[Any],
    readiness_report_sha256_value: str | None = None,
    readiness_report_hash: str | None = None,
) -> CatalogRunAuthorization | None:
    """Find and validate the exact approval for a current scope/evidence hash."""

    normalized_team = str(team_id or "").strip()
    normalized_plan = str(plan_id or "").strip()
    if not normalized_team or not normalized_plan:
        return None
    scope_hash = batch_scope_sha256(batch_scope)
    raw_report_hash = readiness_report_sha256_value or readiness_report_hash
    if not raw_report_hash:
        return None
    if (
        readiness_report_sha256_value is not None
        and readiness_report_hash is not None
        and readiness_report_sha256_value != readiness_report_hash
    ):
        return None
    report_hash = _require_sha256(raw_report_hash, label="readiness_report_sha256")
    store = get_write_store()
    record = store.find_catalog_run_authorization(
        team_id=normalized_team,
        plan_id=normalized_plan,
        scope_hash=scope_hash,
        readiness_report_sha256=report_hash,
    )
    if record is None or not validate_catalog_run_authorization(
        record,
        team_id=normalized_team,
        plan_id=normalized_plan,
        scope_hash=scope_hash,
        readiness_sha256=report_hash,
    ):
        return None
    return record


def record_catalog_run_authorization(
    team_id: str,
    *,
    plan_id: str,
    batch_scope: Mapping[str, Any] | list[Any],
    approved_by: str,
    readiness_evidence: Mapping[str, Any] | list[Any] | str | None = None,
    readiness_report_sha256_value: str | None = None,
    readiness_report_hash: str | None = None,
    approved_at_ms: int | None = None,
    authorization_id: str | None = None,
) -> CatalogRunAuthorization:
    """Persist one approval, idempotently, for an exact scope/evidence pair.

    Callers that already have a trusted report hash may pass it directly.  If
    raw readiness evidence is supplied, its hash is computed here; supplying
    both is allowed only when they agree.  No platform marker or ``confirmed``
    boolean is read by this generic API.
    """

    normalized_team = str(team_id or "").strip()
    normalized_plan = str(plan_id or "").strip()
    approver = str(approved_by or "").strip()
    if not normalized_team or not normalized_plan:
        raise CatalogRunAuthorizationError("team_id and plan_id are required")
    if not approver:
        raise CatalogRunAuthorizationError("approved_by is required")
    if not isinstance(batch_scope, (Mapping, list)):
        raise CatalogRunAuthorizationError("batch_scope must be JSON object/array")
    if (
        readiness_report_sha256_value is not None
        and readiness_report_hash is not None
        and readiness_report_sha256_value != readiness_report_hash
    ):
        raise CatalogRunAuthorizationError(
            "readiness_report_sha256 and readiness_report_hash do not agree"
        )
    explicit_report_hash = readiness_report_sha256_value or readiness_report_hash
    if readiness_evidence is None and explicit_report_hash is None:
        raise CatalogRunAuthorizationError("readiness evidence/hash is required")
    evidence_hash = (
        readiness_report_sha256(readiness_evidence)
        if readiness_evidence is not None
        else None
    )
    supplied_hash = (
        _require_sha256(
            explicit_report_hash,
            label="readiness_report_sha256",
        )
        if explicit_report_hash is not None
        else None
    )
    if evidence_hash and supplied_hash and evidence_hash != supplied_hash:
        raise CatalogRunAuthorizationError(
            "readiness evidence does not match readiness_report_sha256"
        )
    report_hash = supplied_hash or evidence_hash
    assert report_hash is not None
    scope_hash = batch_scope_sha256(batch_scope)
    store = get_write_store()
    existing = store.find_catalog_run_authorization(
        team_id=normalized_team,
        plan_id=normalized_plan,
        scope_hash=scope_hash,
        readiness_report_sha256=report_hash,
    )
    if existing is not None:
        if not validate_catalog_run_authorization(
            existing,
            team_id=normalized_team,
            plan_id=normalized_plan,
            scope_hash=scope_hash,
            readiness_sha256=report_hash,
        ):
            raise CatalogRunAuthorizationError("existing catalog authorization is corrupt")
        return existing

    now_ms = int(approved_at_ms if approved_at_ms is not None else time.time() * 1000)
    if now_ms <= 0:
        raise CatalogRunAuthorizationError("approved_at_ms must be positive")
    auth_id = str(authorization_id or "").strip() or (
        "auth-" + canonical_sha256(
            {
                "teamId": normalized_team,
                "planId": normalized_plan,
                "scopeHash": scope_hash,
                "readinessReportSha256": report_hash,
            }
        )[:32]
    )
    scope_json = json.dumps(
        batch_scope,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    record = CatalogRunAuthorization(
        authorization_id=auth_id,
        team_id=normalized_team,
        plan_id=normalized_plan,
        batch_scope_json=scope_json,
        scope_hash=scope_hash,
        approved_by=approver,
        approved_at_ms=now_ms,
        readiness_report_sha256=report_hash,
        record_hash="",
        created_at_ms=now_ms,
    )
    record = CatalogRunAuthorization(
        **{**record.__dict__, "record_hash": expected_record_hash(record)}
    )

    def mutate(uow):
        uow.repository.insert_catalog_run_authorization(record)
        return uow.repository.find_catalog_run_authorization(
            team_id=normalized_team,
            plan_id=normalized_plan,
            scope_hash=scope_hash,
            readiness_report_sha256=report_hash,
        )

    persisted = store.submit(mutate, force_flush=True).result(timeout=15)
    if persisted is None or not validate_catalog_run_authorization(
        persisted,
        team_id=normalized_team,
        plan_id=normalized_plan,
        scope_hash=scope_hash,
        readiness_sha256=report_hash,
    ):
        raise CatalogRunAuthorizationError("catalog authorization was not persisted")
    return persisted


def authorization_to_dict(record: CatalogRunAuthorization) -> dict[str, Any]:
    return {
        "authorizationId": record.authorization_id,
        "teamId": record.team_id,
        "planId": record.plan_id,
        "batchScope": json.loads(record.batch_scope_json),
        "scopeHash": record.scope_hash,
        "approvedBy": record.approved_by,
        "approvedAtMs": record.approved_at_ms,
        "readinessReportSha256": record.readiness_report_sha256,
        "recordHash": record.record_hash,
        "createdAtMs": record.created_at_ms,
    }


__all__ = [
    "CatalogRunAuthorizationError",
    "authorization_to_dict",
    "batch_scope_sha256",
    "canonical_sha256",
    "expected_record_hash",
    "find_catalog_run_authorization",
    "readiness_report_sha256",
    "record_catalog_run_authorization",
    "require_readiness_report_sha256",
    "validate_catalog_run_authorization",
]
