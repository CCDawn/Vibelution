"""Durable G12 calibration judgement-record store (operator-entered evidence).

The G12 calibration gate (``g12_calibration_service.calibration_gate_verdict``)
has always been able to *judge* a ``G12CalibrationBundle``; what was missing
was anywhere to persist the decision-#13 pilot evidence, so the executor's
default read was permanently fail-closed ("calibration evidence
unavailable").  This store closes exactly that gap without touching the gate
logic:

- manifests: validated :class:`AuditSampleManifest` documents (gate must be
  ``G12``), deduplicated by ``manifestId`` with hash consistency enforced;
- judgements: validated :class:`G12JudgementRecord` items bound fail-closed
  to a stored manifest through ``G12CalibrationBundle.build`` (scope +
  ``sampleKind`` + one-record-per-question, exactly the frozen contract);
  an identical re-record is an idempotent skip, a *conflicting* judgement
  for an already-judged question is rejected.

Storage follows the team-scoped research-workflow JSONL convention (same
directory and durability helpers as the shadow and activation-audit
stores).  Recording an entry IS the credential: the executor's default
calibration read and the real-batch concurrency elevation both load this
store; with nothing recorded both stay fail-closed.  No bypass switch
exists.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from core.research.competition.calibration_records import (
    G12CalibrationBundle,
    G12JudgementRecord,
)
from core.research.workflow.contracts._validation import ContractValidationError
from core.research.workflow.contracts.audit_sampling import AuditSampleManifest
from core.web.services.team_workflow.research_runtime.audit_sampling_service import (
    AuditSamplingError,
    policy_reference,
)
from core.web.services.team_workflow.research_runtime.g12_calibration_service import (
    ASSESSMENT_STATUS_PENDING,
    G12_GATE,
    calibration_gate_verdict,
    collect_pending_records,
)
from core.web.services.team_workflow.research_runtime.policy_shadow_evaluator import (
    developer_sandbox_project_root,
)

G12_STORE_SCHEMA_VERSION = "1.0.0"
G12_MANIFEST_STORE_FILENAME = "g12_calibration_manifests.jsonl"
G12_JUDGEMENT_STORE_FILENAME = "g12_calibration_judgements.jsonl"
JUDGEMENT_ID_PREFIX = "g12j-"


class G12CalibrationStoreError(ValueError):
    """Typed fail-closed error for G12 judgement-record storage."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _stable_hash(payload: Any) -> str:
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    import hashlib

    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _team_research_workflow_root(team_id: str) -> Path:
    from core.infrastructure import developer_sandbox
    from core.web.services.team_workflow.storage_ids import safe_storage_component

    root = developer_sandbox.seeded_sandbox_workspace_path(
        Path(developer_sandbox_project_root()),
        "teams",
        safe_storage_component(str(team_id or "").strip(), fallback="team"),
    )
    return root / "research_workflow"


def g12_manifest_store_path(team_id: str) -> Path:
    """Dedicated manifest store next to the shadow/chain stores (same pattern)."""

    return _team_research_workflow_root(team_id) / G12_MANIFEST_STORE_FILENAME


def g12_judgement_store_path(team_id: str) -> Path:
    """Dedicated judgement store next to the shadow/chain stores."""

    return _team_research_workflow_root(team_id) / G12_JUDGEMENT_STORE_FILENAME


# ---------------------------------------------------------------------------
# read helpers (tolerant JSONL, same durability conventions)


def _read_store(path: Path) -> list[dict[str, Any]]:
    from core.web.services.team_workflow.storage_durability import read_jsonl_tolerant

    return read_jsonl_tolerant(path) if path.is_file() else []


def _append_store(path: Path, record: Mapping[str, Any]) -> None:
    from core.web.services.team_workflow.storage_durability import append_jsonl_locked

    path.parent.mkdir(parents=True, exist_ok=True)
    append_jsonl_locked(path, dict(record))


def _read_manifests(team_id: str) -> list[dict[str, Any]]:
    return _read_store(g12_manifest_store_path(team_id))


def _read_judgements(team_id: str) -> list[dict[str, Any]]:
    return _read_store(g12_judgement_store_path(team_id))


def _policy_identity_filter(
    policy: Any,
) -> tuple[str, str, str] | None:
    """(policyId, version, contentHash) filter, or ``None`` for "any"."""

    if policy is None:
        return None
    if isinstance(policy, AuditSampleManifest):
        return (
            policy.policyId,
            policy.policyVersion,
            policy.policyContentHash,
        )
    if hasattr(policy, "policyId") and hasattr(policy, "declaredContentHash"):
        return (
            str(policy.policyId),
            str(policy.version),
            str(policy.declaredContentHash),
        )
    if isinstance(policy, Mapping):
        try:
            return policy_reference(policy)
        except AuditSamplingError as exc:
            raise G12CalibrationStoreError(
                f"policy identity is unusable for the G12 store: {exc}",
                code="policy_identity_invalid",
            ) from exc
    raise G12CalibrationStoreError(
        "policy must be an AutoAdvancePolicyV2, an AuditSampleManifest or a "
        "policy payload mapping",
        code="policy_identity_invalid",
    )


# ---------------------------------------------------------------------------
# write paths (recording IS the credential)


def record_g12_calibration_manifest(
    team_id: str,
    manifest_payload: Mapping[str, Any],
    *,
    recorded_by: str,
) -> dict[str, Any]:
    """Validate + persist one G12 sample manifest (idempotent by manifestId)."""

    operator = str(recorded_by or "").strip()
    if not operator:
        raise G12CalibrationStoreError(
            "recorded_by must be a non-empty operator identity",
            code="recorded_by_missing",
        )
    try:
        manifest = AuditSampleManifest.from_dict(dict(manifest_payload))
    except ContractValidationError as exc:
        raise G12CalibrationStoreError(
            f"manifest is invalid: {exc}", code="manifest_invalid"
        ) from exc
    if manifest.gate != G12_GATE:
        raise G12CalibrationStoreError(
            f"gate must be {G12_GATE}; got {manifest.gate!r}",
            code="manifest_gate_invalid",
        )
    existing = _read_manifests(str(team_id))
    for item in existing:
        if str(item.get("manifestId") or "") == manifest.manifestId:
            stored_hash = str(item.get("manifestHash") or "")
            if stored_hash and stored_hash != manifest.manifestHash:
                raise G12CalibrationStoreError(
                    "manifestId is already stored with a different manifestHash",
                    code="manifest_hash_conflict",
                )
            return {
                "status": "reused",
                "manifestId": manifest.manifestId,
                "manifestHash": manifest.manifestHash,
                "totalRequired": len(manifest.questionIds),
            }
    _append_store(
        g12_manifest_store_path(str(team_id)),
        {
            "schemaVersion": G12_STORE_SCHEMA_VERSION,
            "manifestId": manifest.manifestId,
            "manifestHash": manifest.manifestHash,
            "manifest": manifest.to_dict(),
            "recordedBy": operator,
            "recordedAt": _utc_now(),
        },
    )
    return {
        "status": "recorded",
        "manifestId": manifest.manifestId,
        "manifestHash": manifest.manifestHash,
        "totalRequired": len(manifest.questionIds),
    }


def _judgement_id(manifest_hash: str, judgement: G12JudgementRecord) -> str:
    return JUDGEMENT_ID_PREFIX + _stable_hash(
        {"manifestHash": manifest_hash, "judgement": judgement.to_dict()}
    )[:16]


def record_g12_judgements(
    team_id: str,
    payload: Mapping[str, Any],
    *,
    recorded_by: str,
) -> dict[str, Any]:
    """Bind + persist operator judgements for one stored G12 manifest.

    Fail-closed binding: every judgement (stored + new) must satisfy the
    frozen ``G12CalibrationBundle`` rules against the stored manifest.
    Identical re-records (same content) are idempotent skips; a *different*
    judgement for an already-judged question is rejected, never overwritten.
    """

    operator = str(recorded_by or "").strip()
    if not operator:
        raise G12CalibrationStoreError(
            "recorded_by must be a non-empty operator identity",
            code="recorded_by_missing",
        )
    if not isinstance(payload, Mapping):
        raise G12CalibrationStoreError(
            "payload must be a JSON object", code="payload_invalid"
        )
    manifest_id = str(payload.get("manifestId") or "").strip()
    raw_judgements = payload.get("judgements")
    if not manifest_id:
        raise G12CalibrationStoreError(
            "manifestId must be a non-empty string", code="manifest_id_missing"
        )
    if not isinstance(raw_judgements, list) or not raw_judgements:
        raise G12CalibrationStoreError(
            "judgements must be a non-empty list", code="judgements_invalid"
        )
    stored = next(
        (
            item
            for item in _read_manifests(str(team_id))
            if str(item.get("manifestId") or "") == manifest_id
        ),
        None,
    )
    if stored is None:
        raise G12CalibrationStoreError(
            f"manifest {manifest_id!r} is not stored; record the manifest first",
            code="manifest_not_found",
        )
    try:
        manifest = AuditSampleManifest.from_dict(dict(stored.get("manifest") or {}))
    except ContractValidationError as exc:
        raise G12CalibrationStoreError(
            f"stored manifest is invalid: {exc}", code="manifest_invalid"
        ) from exc
    manifest_hash = str(stored.get("manifestHash") or "")
    existing_wrappers = [
        item
        for item in _read_judgements(str(team_id))
        if str(item.get("manifestId") or "") == manifest_id
    ]
    existing_by_question: dict[str, dict[str, Any]] = {
        str(item.get("judgement", {}).get("questionId") or ""): item
        for item in existing_wrappers
        if isinstance(item.get("judgement"), Mapping)
    }
    new_wrappers: list[dict[str, Any]] = []
    skipped_duplicates = 0
    for raw in raw_judgements:
        if not isinstance(raw, Mapping):
            raise G12CalibrationStoreError(
                "each judgement must be a JSON object", code="judgements_invalid"
            )
        try:
            judgement = G12JudgementRecord.from_dict(dict(raw))
        except Exception as exc:  # noqa: BLE001 - fail-closed record parse
            raise G12CalibrationStoreError(
                f"judgement is invalid: {exc}", code="judgement_invalid"
            ) from exc
        record_id = _judgement_id(manifest_hash, judgement)
        if any(
            str(item.get("recordId") or "") == record_id
            for item in existing_wrappers
        ):
            skipped_duplicates += 1
            continue
        prior = existing_by_question.get(judgement.questionId)
        if prior is not None:
            raise G12CalibrationStoreError(
                "question "
                f"{judgement.questionId!r} already carries a different "
                "judgement for this manifest; judgements are never "
                "overwritten",
                code="judgement_conflict",
            )
        existing_by_question[judgement.questionId] = {
            "recordId": record_id,
            "judgement": judgement.to_dict(),
        }
        new_wrappers.append(
            {
                "schemaVersion": G12_STORE_SCHEMA_VERSION,
                "recordId": record_id,
                "manifestId": manifest.manifestId,
                "manifestHash": manifest_hash,
                "judgement": judgement.to_dict(),
                "recordedBy": operator,
                "recordedAt": _utc_now(),
            }
        )
    # Fail-closed bind of the FULL collection (stored + new) before any write.
    bundle = _bundle_for(manifest, list(existing_by_question.values()))
    for wrapper in new_wrappers:
        _append_store(g12_judgement_store_path(str(team_id)), wrapper)
    pending = collect_pending_records(manifest, bundle.records)
    return {
        "status": "recorded" if new_wrappers else "reused",
        "manifestId": manifest.manifestId,
        "manifestHash": manifest_hash,
        "recordedCount": len(new_wrappers),
        "skippedDuplicateCount": skipped_duplicates,
        "totalRecorded": pending["totalRecorded"],
        "totalRequired": pending["totalRequired"],
        "bundleStatus": pending["status"],
        "pending": pending["pending"],
    }


def _bundle_for(
    manifest: AuditSampleManifest,
    wrappers: Sequence[Mapping[str, Any]],
) -> G12CalibrationBundle:
    records: list[G12JudgementRecord] = []
    for wrapper in wrappers:
        judgement = wrapper.get("judgement")
        if not isinstance(judgement, Mapping):
            raise G12CalibrationStoreError(
                "stored judgement entry is malformed", code="store_corrupt"
            )
        try:
            records.append(G12JudgementRecord.from_dict(dict(judgement)))
        except Exception as exc:  # noqa: BLE001 - fail-closed store reparse
            raise G12CalibrationStoreError(
                f"stored judgement is invalid: {exc}", code="store_corrupt"
            ) from exc
    try:
        return G12CalibrationBundle.build(manifest=manifest, records=records)
    except Exception as exc:  # noqa: BLE001 - fail-closed binding
        raise G12CalibrationStoreError(
            f"judgement collection is invalid against the manifest: {exc}",
            code="bundle_invalid",
        ) from exc


# ---------------------------------------------------------------------------
# read paths (executor ladder rung 3 + real-batch concurrency elevation)


def load_g12_calibration_bundle(
    team_id: str,
    *,
    policy: Any = None,
) -> G12CalibrationBundle | None:
    """Latest judged G12 bundle for the (optional) policy identity, or None.

    Manifest selection is deterministic: manifests are filtered by the exact
    ``(policyId, version, contentHash)`` binding when a policy is given, then
    the newest manifest that actually carries judgement records wins; with no
    judged manifest the newest stored manifest is returned (its bundle reads
    ``pending``).  ``None`` only when nothing is stored at all — the
    fail-closed "calibration evidence unavailable" case.
    """

    identity = _policy_identity_filter(policy)
    manifests = _read_manifests(str(team_id))
    if identity is not None:
        manifests = [
            item
            for item in manifests
            if (
                str(item.get("manifest", {}).get("policyId") or ""),
                str(item.get("manifest", {}).get("policyVersion") or ""),
                str(item.get("manifest", {}).get("policyContentHash") or ""),
            )
            == identity
        ]
    if not manifests:
        return None

    def _order(item: Mapping[str, Any]) -> tuple[str, str]:
        return (
            str(item.get("recordedAt") or ""),
            str(item.get("manifestId") or ""),
        )

    manifests.sort(key=_order)
    matching_ids = {str(item.get("manifestId") or "") for item in manifests}
    judgements = [
        item
        for item in _read_judgements(str(team_id))
        if str(item.get("manifestId") or "") in matching_ids
    ]
    judged_by_manifest: dict[str, list[dict[str, Any]]] = {}
    for item in judgements:
        judged_by_manifest.setdefault(str(item.get("manifestId") or ""), []).append(
            item
        )
    for item in reversed(manifests):
        manifest_id = str(item.get("manifestId") or "")
        wrappers = judged_by_manifest.get(manifest_id) or []
        if wrappers:
            return _manifest_item_to_bundle(item, wrappers)
    return _manifest_item_to_bundle(manifests[-1], [])


def _manifest_item_to_bundle(
    item: Mapping[str, Any],
    wrappers: Sequence[Mapping[str, Any]],
) -> G12CalibrationBundle:
    try:
        manifest = AuditSampleManifest.from_dict(dict(item.get("manifest") or {}))
    except ContractValidationError as exc:
        raise G12CalibrationStoreError(
            f"stored manifest is invalid: {exc}", code="store_corrupt"
        ) from exc
    return _bundle_for(manifest, wrappers)


def g12_calibration_gate_verdict_for_team(
    team_id: str,
    *,
    policy: Any = None,
) -> dict[str, Any]:
    """The store-backed default calibration read (read-only, fail-closed).

    ``policy`` omitted means the frozen default thresholds are applied to the
    newest stored evidence (used by the real-batch concurrency elevation,
    which is not bound to one automation policy).  The returned mapping is
    exactly ``g12_calibration_service.calibration_gate_verdict`` output; no
    stored evidence yields the fail-closed unavailable verdict.
    """

    from core.web.services.team_workflow.research_runtime.g12_calibration_service import (
        _policy_identity,
    )

    bundle = load_g12_calibration_bundle(str(team_id), policy=policy)
    if bundle is not None:
        if policy is None:
            policy = {
                "policyId": bundle.policyId,
                "version": bundle.policyVersion,
                "contentHash": bundle.policyContentHash,
            }
        # calibration_gate_verdict re-derives and re-checks the policy
        # identity (G12CalibrationServiceError on an unusable mapping) and
        # applies the declared thresholds with the unchanged gate logic.
        return calibration_gate_verdict(policy, bundle)
    if policy is not None:
        # Nothing stored: the unchanged fail-closed answer for this policy.
        return calibration_gate_verdict(policy, None)
    # No evidence AND no usable policy identity: the same fail-closed
    # verdict shape, without inventing an identity.
    return {
        "passed": False,
        "policyId": "",
        "policyVersion": "",
        "policyContentHash": "",
        "status": "unavailable",
        "reasonCode": "calibration_evidence_unavailable",
        "reasons": [
            "no G12 calibration bundle is available; the statistical "
            "gate cannot be green without decision-#13 pilot evidence"
        ],
        "declaredThresholds": {},
        "evidence": {},
    }


def g12_calibration_gate_status(
    team_id: str,
    *,
    policy: Any = None,
) -> dict[str, Any]:
    """Read helper for routes/diagnostics: bundle projection + gate verdict."""

    bundle = load_g12_calibration_bundle(str(team_id), policy=policy)
    projection = bundle.to_dict() if bundle is not None else None
    verdict = g12_calibration_gate_verdict_for_team(str(team_id), policy=policy)
    return {
        "schemaVersion": G12_STORE_SCHEMA_VERSION,
        "teamId": str(team_id or "").strip(),
        "bundle": projection,
        "verdict": verdict,
        "evidenceStatus": str(verdict.get("status") or ASSESSMENT_STATUS_PENDING),
        "gatePassed": verdict.get("passed") is True,
    }


__all__ = [
    "G12_JUDGEMENT_STORE_FILENAME",
    "G12_MANIFEST_STORE_FILENAME",
    "G12_STORE_SCHEMA_VERSION",
    "G12CalibrationStoreError",
    "g12_calibration_gate_status",
    "g12_calibration_gate_verdict_for_team",
    "g12_judgement_store_path",
    "g12_manifest_store_path",
    "load_g12_calibration_bundle",
    "record_g12_calibration_manifest",
    "record_g12_judgements",
]
