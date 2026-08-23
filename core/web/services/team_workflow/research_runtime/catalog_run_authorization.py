"""Immutable, auditable authorization records for real catalog batches.

Readiness snapshots describe the platform's current state; they are not an
approval artifact.  This module persists an approval that is bound to one
server-derived real-batch scope and one canonical readiness hash.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from core.research.competition.real_control_batch import (
    RealBatchError,
    real_plan,
    validate_real_batch_plan,
)
from core.research.workflow.ledger import CatalogRunAuthorization

from .formal_write_runtime import get_write_store

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SCOPE_KEYS = frozenset({"planId", "gateId", "questionIds"})
_READINESS_HASH_KEYS = (
    "readinessReportSha256",
    "readinessReportHash",
    "catalogReadinessReportSha256",
)
_READINESS_REPORT_KEYS = ("readinessReport", "report")


class CatalogRunAuthorizationError(ValueError):
    """A catalog authorization is missing, corrupt, stale, or out of scope."""


def canonical_sha256(value: Mapping[str, Any] | list[Any] | str) -> str:
    """Return a stable hash for the limited JSON values used as evidence.

    Batch scopes are strings/lists only and reports are persisted JSON objects,
    so sorted compact JSON gives a repeatable representation before hashing.
    """

    if isinstance(value, str):
        payload = value.encode("utf-8")
    else:
        try:
            payload = json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise CatalogRunAuthorizationError("authorization evidence is not JSON") from exc
    return hashlib.sha256(payload).hexdigest()


def require_readiness_report_sha256(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if not _SHA256_RE.fullmatch(normalized):
        raise CatalogRunAuthorizationError(
            "readiness_report_sha256 must be a lowercase SHA-256 digest"
        )
    return normalized


def readiness_report_sha256(evidence: Mapping[str, Any] | list[Any] | str) -> str:
    """Hash a report, or validate a digest that is already server-owned."""

    if isinstance(evidence, str) and _SHA256_RE.fullmatch(evidence.strip().lower()):
        return require_readiness_report_sha256(evidence)
    return canonical_sha256(evidence)


def readiness_report_sha256_from_snapshot(snapshot: Mapping[str, Any]) -> str:
    """Return one verified readiness hash from a server snapshot.

    A top-level digest is useful when a snapshot intentionally omits its full
    report, but it must never override a report that is present.  Otherwise a
    stale digest can make changed readiness content look authorized.
    """

    if not isinstance(snapshot, Mapping):
        raise CatalogRunAuthorizationError("readiness snapshot is invalid")
    supplied_hashes = {
        require_readiness_report_sha256(str(snapshot.get(key) or ""))
        for key in _READINESS_HASH_KEYS
        if str(snapshot.get(key) or "").strip()
    }
    if len(supplied_hashes) > 1:
        raise CatalogRunAuthorizationError("readiness snapshot has conflicting report hashes")
    report_hashes = {
        readiness_report_sha256(report)
        for key in _READINESS_REPORT_KEYS
        if isinstance((report := snapshot.get(key)), (Mapping, list))
    }
    if len(report_hashes) > 1:
        raise CatalogRunAuthorizationError("readiness snapshot has conflicting reports")
    if report_hashes:
        report_hash = next(iter(report_hashes))
        if supplied_hashes and report_hash not in supplied_hashes:
            raise CatalogRunAuthorizationError(
                "readiness report does not match its supplied hash"
            )
        return report_hash
    if supplied_hashes:
        return next(iter(supplied_hashes))
    raise CatalogRunAuthorizationError("readiness snapshot has no report hash")


def expected_batch_scope(plan_id: str) -> dict[str, Any]:
    """Return the only scope that may be authorized for a real plan."""

    try:
        normalized_plan = validate_real_batch_plan(str(plan_id or "").strip())
    except RealBatchError as exc:
        raise CatalogRunAuthorizationError("authorization plan is not a real batch") from exc
    plan = real_plan(normalized_plan)
    return {
        "planId": normalized_plan,
        "gateId": str(plan.gate_id),
        "questionIds": [str(question_id) for question_id in plan.question_ids],
    }


def _validated_batch_scope(plan_id: str, batch_scope: Mapping[str, Any]) -> dict[str, Any]:
    expected = expected_batch_scope(plan_id)
    if not isinstance(batch_scope, Mapping) or set(batch_scope.keys()) != _SCOPE_KEYS:
        raise CatalogRunAuthorizationError("batch_scope must be the exact real-plan scope")
    if not isinstance(batch_scope.get("questionIds"), list):
        raise CatalogRunAuthorizationError("batch_scope questionIds must be an ordered list")
    if dict(batch_scope) != expected:
        raise CatalogRunAuthorizationError("batch_scope does not match the frozen real plan")
    return expected


def batch_scope_sha256(batch_scope: Mapping[str, Any]) -> str:
    return canonical_sha256(batch_scope)


def _record_hash_payload(record: CatalogRunAuthorization) -> dict[str, Any]:
    try:
        scope = json.loads(record.batch_scope_json)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise CatalogRunAuthorizationError("catalog authorization scope is unreadable") from exc
    if not isinstance(scope, Mapping):
        raise CatalogRunAuthorizationError("catalog authorization scope is invalid")
    return {
        "authorizationId": record.authorization_id,
        "teamId": record.team_id,
        "planId": record.plan_id,
        "batchScope": dict(scope),
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
    """Check immutable content and any requested identity boundary."""

    try:
        if team_id is not None and record.team_id != str(team_id).strip():
            return False
        if plan_id is not None and record.plan_id != str(plan_id).strip():
            return False
        report_hash = require_readiness_report_sha256(record.readiness_report_sha256)
        stored_scope_hash = require_readiness_report_sha256(record.scope_hash)
        scope = json.loads(record.batch_scope_json)
        if not isinstance(scope, Mapping):
            return False
        expected_scope = _validated_batch_scope(record.plan_id, scope)
        if batch_scope_sha256(expected_scope) != stored_scope_hash:
            return False
        if scope_hash is not None and stored_scope_hash != require_readiness_report_sha256(scope_hash):
            return False
        if readiness_sha256 is not None and report_hash != require_readiness_report_sha256(
            readiness_sha256
        ):
            return False
        if (
            not record.authorization_id
            or not record.team_id
            or not record.approved_by.strip()
            or record.approved_at_ms <= 0
            or record.created_at_ms <= 0
        ):
            return False
        return record.record_hash == expected_record_hash(record)
    except (CatalogRunAuthorizationError, TypeError, ValueError, json.JSONDecodeError):
        return False


def find_catalog_run_authorization(
    team_id: str,
    *,
    plan_id: str,
    batch_scope: Mapping[str, Any],
    readiness_report_sha256_value: str,
) -> CatalogRunAuthorization | None:
    """Find only an exact, valid approval for the current server facts."""

    normalized_team = str(team_id or "").strip()
    normalized_plan = str(plan_id or "").strip()
    if not normalized_team or not normalized_plan:
        return None
    try:
        scope = _validated_batch_scope(normalized_plan, batch_scope)
        report_hash = require_readiness_report_sha256(readiness_report_sha256_value)
    except CatalogRunAuthorizationError:
        return None
    record = get_write_store().find_catalog_run_authorization(
        team_id=normalized_team,
        plan_id=normalized_plan,
        scope_hash=batch_scope_sha256(scope),
        readiness_report_sha256=report_hash,
    )
    if record is None or not validate_catalog_run_authorization(
        record,
        team_id=normalized_team,
        plan_id=normalized_plan,
        scope_hash=batch_scope_sha256(scope),
        readiness_sha256=report_hash,
    ):
        return None
    return record


def record_catalog_run_authorization(
    team_id: str,
    *,
    plan_id: str,
    batch_scope: Mapping[str, Any],
    approved_by: str,
    readiness_evidence: Mapping[str, Any] | list[Any] | str | None = None,
    readiness_report_sha256_value: str | None = None,
    approved_at_ms: int | None = None,
) -> CatalogRunAuthorization:
    """Persist exactly one approval record for an exact scope/report pair."""

    normalized_team = str(team_id or "").strip()
    normalized_plan = str(plan_id or "").strip()
    approver = str(approved_by or "").strip()
    if not normalized_team or not approver:
        raise CatalogRunAuthorizationError("team_id and approved_by are required")
    scope = _validated_batch_scope(normalized_plan, batch_scope)
    if readiness_evidence is None and readiness_report_sha256_value is None:
        raise CatalogRunAuthorizationError("readiness evidence or hash is required")
    evidence_hash = (
        readiness_report_sha256(readiness_evidence)
        if readiness_evidence is not None
        else None
    )
    supplied_hash = (
        require_readiness_report_sha256(readiness_report_sha256_value)
        if readiness_report_sha256_value is not None
        else None
    )
    if evidence_hash is not None and supplied_hash is not None and evidence_hash != supplied_hash:
        raise CatalogRunAuthorizationError("readiness evidence does not match its supplied hash")
    report_hash = supplied_hash or evidence_hash
    assert report_hash is not None
    scope_hash = batch_scope_sha256(scope)
    now_ms = int(approved_at_ms if approved_at_ms is not None else time.time() * 1000)
    if now_ms <= 0:
        raise CatalogRunAuthorizationError("approved_at_ms must be positive")
    authorization_id = "auth-" + canonical_sha256(
        {
            "teamId": normalized_team,
            "planId": normalized_plan,
            "scopeHash": scope_hash,
            "readinessReportSha256": report_hash,
        }
    )[:32]
    record = CatalogRunAuthorization(
        authorization_id=authorization_id,
        team_id=normalized_team,
        plan_id=normalized_plan,
        batch_scope_json=json.dumps(scope, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        scope_hash=scope_hash,
        approved_by=approver,
        approved_at_ms=now_ms,
        readiness_report_sha256=report_hash,
        record_hash="",
        created_at_ms=now_ms,
    )
    record = replace(record, record_hash=expected_record_hash(record))
    store = get_write_store()

    def mutate(uow: Any) -> CatalogRunAuthorization | None:
        existing = uow.repository.find_catalog_run_authorization(
            team_id=normalized_team,
            plan_id=normalized_plan,
            scope_hash=scope_hash,
            readiness_report_sha256=report_hash,
        )
        if existing is not None:
            return existing
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
    """Return the complete immutable identity required by a real run."""

    try:
        scope = json.loads(record.batch_scope_json)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise CatalogRunAuthorizationError("catalog authorization scope is unreadable") from exc
    if not isinstance(scope, Mapping):
        raise CatalogRunAuthorizationError("catalog authorization scope is invalid")
    return {
        "authorizationId": record.authorization_id,
        "teamId": record.team_id,
        "planId": record.plan_id,
        "batchScope": dict(scope),
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
    "expected_batch_scope",
    "expected_record_hash",
    "find_catalog_run_authorization",
    "readiness_report_sha256",
    "readiness_report_sha256_from_snapshot",
    "record_catalog_run_authorization",
    "require_readiness_report_sha256",
    "validate_catalog_run_authorization",
]
