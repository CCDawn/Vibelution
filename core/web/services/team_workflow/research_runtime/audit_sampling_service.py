"""Deterministic audit sampling service for the Challenge Cup (R4.4).

Given a question pool (with risk/domain metadata), a human-review policy
snapshot and a seed, this writer derives reproducible audit sample manifests:

- G12 calibration pilot (decision #13): the full pilot pool, every question
  ``g12_calibration``;
- G125 sequential batches (decision #13): fixed-size batches (default 5)
  drawn without replacement from the remaining pool the caller passes;
- drift sentinels (decision #5): exactly three low-risk questions drawn from
  the second half of the G125 ordering, never from the first half and never
  from medium/high risk classes;
- risk-triggered / anomaly full-review manifests: full-review carriers for
  flagged questions (decision #6: risk-triggered, never class-wide).

Draw rule (no RNG state, no wall clock): every candidate gets a priority
digest ``sha256(f"{derived_seed}:{questionId}")`` where ``derived_seed`` is
the canonical hash of (seed, purpose, gate, batchIndex); candidates are
ordered by ``(digest, questionId)`` and dealt round-robin across strata
(risk_class, catalog_domain) until the requested count is reached.  The same
seed over the same pool therefore reproduces byte-identical manifests.

This module never executes workflow work, never approves anything and never
touches the ledger: it only derives immutable contracts for the audit chain.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from core.research.workflow.contracts._canonical import sha256_hex
from core.research.workflow.contracts._validation import ContractValidationError
from core.research.workflow.contracts.audit_sampling import (
    DRIFT_SENTINEL_COUNT,
    DRIFT_SENTINEL_GATE,
    GATES,
    RUN_PHASE_VALUES,
    AuditSampleManifest,
    DriftSentinelSelection,
    SampleKind,
    SentinelExclusion,
    audit_sample_manifest_hash,
    drift_sentinel_selection_hash,
    parse_sample_kind,
)

SAMPLING_RULE_VERSION = "cc-audit-sampling-r4.4-v1"
SENTINEL_SELECTION_RULE_VERSION = "cc-audit-sentinel-r4.4-v1"

DEFAULT_G125_BATCH_SIZE = 5

# Decision #13 / auto_advance_policy v2 ``allowedRiskClasses``: only this
# class is eligible for drift-sentinel duty and calibrated auto-advance.
LOW_RISK_CLASS = "low_risk_standard"

G125_GATE = "G125"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class AuditSamplingError(ValueError):
    """The sampling input is malformed or the request cannot be fulfilled."""


@dataclass(frozen=True, slots=True)
class PoolQuestion:
    """One normalized question-pool entry with audit metadata."""

    questionId: str
    riskClass: str
    catalogDomain: str
    runPhase: str = ""


def normalize_pool(pool: Sequence[Mapping[str, Any]]) -> tuple[PoolQuestion, ...]:
    """Fail-closed normalization of a raw question pool."""

    if not isinstance(pool, Sequence) or isinstance(pool, (str, bytes)) or not pool:
        raise AuditSamplingError("question pool must be a non-empty list of objects")
    entries: list[PoolQuestion] = []
    seen: set[str] = set()
    for raw in pool:
        if not isinstance(raw, Mapping):
            raise AuditSamplingError("question pool entries must be JSON objects")
        question_id = str(raw.get("questionId") or "").strip()
        risk_class = str(raw.get("riskClass") or "").strip()
        domain = str(raw.get("catalogDomain") or "").strip()
        run_phase = str(raw.get("runPhase") or "").strip()
        if not question_id or not risk_class or not domain:
            raise AuditSamplingError(
                "question pool entries require questionId, riskClass and catalogDomain"
            )
        if question_id in seen:
            raise AuditSamplingError(f"duplicate questionId in pool: {question_id}")
        if run_phase and run_phase not in RUN_PHASE_VALUES:
            raise AuditSamplingError(
                "runPhase must be one of: " + ", ".join(sorted(RUN_PHASE_VALUES))
            )
        seen.add(question_id)
        entries.append(
            PoolQuestion(
                questionId=question_id,
                riskClass=risk_class,
                catalogDomain=domain,
                runPhase=run_phase,
            )
        )
    return tuple(entries)


def policy_reference(policy: Mapping[str, Any]) -> tuple[str, str, str]:
    """Extract the fail-closed (policyId, version, contentHash) binding."""

    if not isinstance(policy, Mapping):
        raise AuditSamplingError("policy snapshot must be a JSON object")
    policy_id = str(policy.get("policyId") or "").strip()
    version = str(policy.get("version") or "").strip()
    raw_hash = policy.get("contentHash")
    if raw_hash is None:
        raw_hash = policy.get("declaredContentHash")
    if raw_hash is None and isinstance(policy.get("approval"), Mapping):
        raw_hash = policy["approval"].get("contentHash")
    content_hash = str(raw_hash or "").strip().lower()
    if not policy_id or not version:
        raise AuditSamplingError("policy snapshot requires policyId and version")
    if not _SHA256_RE.fullmatch(content_hash):
        raise AuditSamplingError(
            "policy contentHash must be a sha256 hex digest (uppercase input is normalized)"
        )
    return policy_id, version, content_hash


def assert_policy_binding(
    manifest: AuditSampleManifest, policy: Mapping[str, Any]
) -> None:
    """Reject a manifest that was not generated under this policy snapshot."""

    policy_id, version, content_hash = policy_reference(policy)
    if (
        manifest.policyId != policy_id
        or manifest.policyVersion != version
        or manifest.policyContentHash != content_hash
    ):
        raise AuditSamplingError(
            "audit manifest policy binding does not match the current policy "
            f"snapshot ({manifest.policyId}/{manifest.policyVersion}/"
            f"{manifest.policyContentHash})"
        )


def second_half_question_ids(pool: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    """Return the second half of the gate ordering (sorted by questionId)."""

    entries = normalize_pool(pool)
    ordered = sorted(entries, key=lambda entry: entry.questionId)
    start = len(ordered) // 2
    return tuple(entry.questionId for entry in ordered[start:])


def draw_g125_batch(
    *,
    pool: Sequence[Mapping[str, Any]],
    seed: str,
    batch_index: int,
    batch_size: int = DEFAULT_G125_BATCH_SIZE,
) -> tuple[str, ...]:
    """Draw one sequential G125 batch from the remaining pool, deterministically."""

    entries = normalize_pool(pool)
    if not entries:
        raise AuditSamplingError("remaining question pool is empty")
    if not isinstance(batch_index, int) or isinstance(batch_index, bool) or batch_index < 1:
        raise AuditSamplingError("batch_index must be an integer >= 1")
    if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size < 1:
        raise AuditSamplingError("batch_size must be an integer >= 1")
    derived = _derive_seed(
        seed=seed, purpose="g125_sequential", gate=G125_GATE, batch_index=batch_index
    )
    return tuple(
        sorted(
            _stratified_draw(
                entries, count=min(batch_size, len(entries)), derived_seed=derived
            )
        )
    )


def generate_g12_calibration_manifest(
    *,
    pool: Sequence[Mapping[str, Any]],
    policy: Mapping[str, Any],
    seed: str,
    generated_at: str,
    manifest_id: str | None = None,
) -> AuditSampleManifest:
    """Build the G12 calibration pilot manifest: review the whole pilot pool."""

    entries = normalize_pool(pool)
    assignments = {
        entry.questionId: SampleKind.G12_CALIBRATION for entry in entries
    }
    return build_audit_sample_manifest(
        gate="G12",
        batch_index=1,
        policy=policy,
        seed=seed,
        generated_at=generated_at,
        assignments=assignments,
        strata=_strata_for(entries),
        manifest_id=manifest_id,
    )


def generate_g125_batch_manifest(
    *,
    pool: Sequence[Mapping[str, Any]],
    policy: Mapping[str, Any],
    seed: str,
    batch_index: int,
    batch_size: int = DEFAULT_G125_BATCH_SIZE,
    generated_at: str,
    risk_triggered_question_ids: Iterable[str] = (),
    anomaly_question_ids: Iterable[str] = (),
    sentinel_selection: DriftSentinelSelection | None = None,
    manifest_id: str | None = None,
) -> AuditSampleManifest:
    """Build one sequential G125 batch manifest, optionally carrying sentinels.

    ``pool`` is the REMAINING pool for this batch (earlier batches' questions
    are removed by the caller), which keeps every batch reproducible without
    hidden state.  ``sentinel_selection`` must have been drawn with
    ``exclude_question_ids`` covering this batch so sentinels never collide
    with sequential picks.
    """

    entries = normalize_pool(pool)
    if not entries:
        raise AuditSamplingError("remaining question pool is empty")
    if not isinstance(batch_index, int) or isinstance(batch_index, bool) or batch_index < 1:
        raise AuditSamplingError("batch_index must be an integer >= 1")
    if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size < 1:
        raise AuditSamplingError("batch_size must be an integer >= 1")
    derived = _derive_seed(
        seed=seed, purpose="g125_sequential", gate=G125_GATE, batch_index=batch_index
    )
    drawn = _stratified_draw(entries, count=min(batch_size, len(entries)), derived_seed=derived)
    assignments: dict[str, SampleKind] = {
        question_id: SampleKind.G125_SEQUENTIAL for question_id in drawn
    }
    assignments = _apply_full_review_overrides(
        assignments,
        risk_triggered_question_ids=risk_triggered_question_ids,
        anomaly_question_ids=anomaly_question_ids,
    )
    if sentinel_selection is not None:
        assignments = _merge_sentinel_selection(assignments, sentinel_selection)
    sampled_entries = [entry for entry in entries if entry.questionId in assignments]
    return build_audit_sample_manifest(
        gate=G125_GATE,
        batch_index=batch_index,
        policy=policy,
        seed=seed,
        generated_at=generated_at,
        assignments=assignments,
        strata=_strata_for(sampled_entries),
        manifest_id=manifest_id,
    )


def generate_full_review_manifest(
    *,
    gate: str,
    pool: Sequence[Mapping[str, Any]],
    sample_kind: SampleKind | str,
    policy: Mapping[str, Any],
    seed: str,
    generated_at: str,
    question_ids: Iterable[str] | None = None,
    manifest_id: str | None = None,
) -> AuditSampleManifest:
    """Build a full-review manifest for risk-triggered or anomaly questions.

    ``pool`` carries the metadata of the flagged questions; ``question_ids``
    defaults to the whole pool.  Only ``risk_triggered_full_review`` and
    ``anomaly_full_review`` are legal here (decision #6: risk-triggered,
    never class-wide).
    """

    kind = parse_sample_kind(sample_kind)
    if kind not in (SampleKind.RISK_TRIGGERED_FULL_REVIEW, SampleKind.ANOMALY_FULL_REVIEW):
        raise AuditSamplingError(
            "full-review manifests only support risk_triggered_full_review "
            "or anomaly_full_review"
        )
    entries = normalize_pool(pool)
    wanted = (
        [str(item or "").strip() for item in question_ids]
        if question_ids is not None
        else [entry.questionId for entry in entries]
    )
    if not wanted:
        raise AuditSamplingError("full-review manifests require at least one question")
    by_id = {entry.questionId: entry for entry in entries}
    unknown = [question_id for question_id in wanted if question_id not in by_id]
    if unknown:
        raise AuditSamplingError(
            "full-review questions must come from the given pool: " + ", ".join(unknown)
        )
    assignments = {question_id: kind for question_id in wanted}
    return build_audit_sample_manifest(
        gate=gate,
        batch_index=1,
        policy=policy,
        seed=seed,
        generated_at=generated_at,
        assignments=assignments,
        strata=_strata_for([by_id[question_id] for question_id in wanted]),
        manifest_id=manifest_id,
    )


def select_drift_sentinels(
    *,
    pool: Sequence[Mapping[str, Any]],
    policy: Mapping[str, Any],
    seed: str,
    generated_at: str,
    exclude_question_ids: Iterable[str] = (),
    manifest_id: str = "",
    selection_id: str | None = None,
) -> DriftSentinelSelection:
    """Deterministically pick the three rolling drift sentinels (decision #5).

    Candidates are the low-risk questions of the second half of the G125
    ordering.  First-half questions, non-low-risk questions and
    ``exclude_question_ids`` (e.g. questions already drawn in the current
    batch) are recorded as pre-draw exclusions with reasons; the draw pool
    must still hold at least three candidates or the selection fails
    closed.
    """

    normalize_pool(pool)  # fail closed on malformed pools even when unused below
    policy_reference(policy)
    if not str(seed or "").strip():
        raise AuditSamplingError("drift sentinel selection requires a seed")
    if not str(generated_at or "").strip():
        raise AuditSamplingError("drift sentinel selection requires generated_at")
    entries = sorted(
        normalize_pool(pool), key=lambda entry: entry.questionId
    )
    second_half_start = len(entries) // 2
    excluded = {
        str(item or "").strip() for item in exclude_question_ids if str(item or "").strip()
    }
    candidate_pool: list[str] = []
    pre_draw: list[SentinelExclusion] = []
    for index, entry in enumerate(entries):
        if index < second_half_start:
            pre_draw.append(
                SentinelExclusion(
                    questionId=entry.questionId, reason="outside_second_half"
                )
            )
        elif entry.riskClass != LOW_RISK_CLASS:
            pre_draw.append(
                SentinelExclusion(questionId=entry.questionId, reason="not_low_risk")
            )
        elif entry.questionId in excluded:
            pre_draw.append(
                SentinelExclusion(questionId=entry.questionId, reason="already_sampled")
            )
        else:
            candidate_pool.append(entry.questionId)
    if len(candidate_pool) < DRIFT_SENTINEL_COUNT:
        raise AuditSamplingError(
            "drift sentinel candidate pool (second-half low-risk questions) "
            f"holds {len(candidate_pool)} candidates, need {DRIFT_SENTINEL_COUNT}"
        )
    derived = _derive_seed(
        seed=seed, purpose="drift_sentinel", gate=DRIFT_SENTINEL_GATE, batch_index=0
    )
    prioritized = sorted(
        candidate_pool,
        key=lambda question_id: (_priority(derived, question_id), question_id),
    )
    selected = tuple(sorted(prioritized[:DRIFT_SENTINEL_COUNT]))
    exclusions = {
        question_id: "not_drawn"
        for question_id in candidate_pool
        if question_id not in set(selected)
    }
    payload = {
        "selectionId": str(selection_id or "").strip()
        or _derived_selection_id(seed=seed, candidate_pool=candidate_pool),
        "manifestId": str(manifest_id or "").strip(),
        "gate": DRIFT_SENTINEL_GATE,
        "seed": str(seed).strip(),
        "candidatePool": candidate_pool,
        "secondHalfStartIndex": second_half_start,
        "selectedQuestionIds": list(selected),
        "exclusions": exclusions,
        "preDrawExclusions": [exclusion.to_dict() for exclusion in pre_draw],
        "selectionRuleVersion": SENTINEL_SELECTION_RULE_VERSION,
        "selectedAt": str(generated_at).strip(),
    }
    try:
        return DriftSentinelSelection.from_dict(payload)
    except ContractValidationError as exc:
        raise AuditSamplingError(str(exc)) from exc


def bind_sentinel_selection_to_manifest(
    selection: DriftSentinelSelection, *, manifest_id: str
) -> DriftSentinelSelection:
    """Link an unbound sentinel selection to its manifest and re-sign it."""

    bound_manifest_id = str(manifest_id or "").strip()
    if not bound_manifest_id:
        raise AuditSamplingError("bind requires a non-empty manifest id")
    bound = replace(selection, manifestId=bound_manifest_id)
    return replace(bound, selectionHash=drift_sentinel_selection_hash(bound))


def build_audit_sample_manifest(
    *,
    gate: str,
    batch_index: int,
    policy: Mapping[str, Any],
    seed: str,
    generated_at: str,
    assignments: Mapping[str, SampleKind | str],
    strata: Mapping[str, Any] | None = None,
    manifest_id: str | None = None,
) -> AuditSampleManifest:
    """Shared deterministic writer behind every generator (fail-closed)."""

    if str(gate or "").strip() not in GATES:
        raise AuditSamplingError(
            "gate must be one of: " + ", ".join(sorted(GATES))
        )
    if not isinstance(batch_index, int) or isinstance(batch_index, bool) or batch_index < 1:
        raise AuditSamplingError("batch_index must be an integer >= 1")
    if not str(seed or "").strip():
        raise AuditSamplingError("sampling seed is required")
    if not str(generated_at or "").strip():
        raise AuditSamplingError("generated_at is required")
    if not assignments:
        raise AuditSamplingError("audit manifests require at least one sampled question")
    if strata is None:
        raise AuditSamplingError("audit manifests require a strata snapshot")
    normalized_assignments = {
        str(question_id or "").strip(): parse_sample_kind(kind)
        for question_id, kind in assignments.items()
    }
    question_ids = sorted(normalized_assignments)
    normalized_strata = {
        str(axis or "").strip(): sorted(str(value or "").strip() for value in values)
        for axis, values in strata.items()
    }
    policy_id, policy_version, content_hash = policy_reference(policy)
    resolved_manifest_id = str(manifest_id or "").strip() or _derived_manifest_id(
        gate=gate,
        batch_index=batch_index,
        policy_id=policy_id,
        policy_version=policy_version,
        policy_content_hash=content_hash,
        seed=seed,
        question_ids=question_ids,
    )
    payload = {
        "manifestId": resolved_manifest_id,
        "gate": str(gate).strip(),
        "batchIndex": batch_index,
        "policyId": policy_id,
        "policyVersion": policy_version,
        "policyContentHash": content_hash,
        "seed": str(seed).strip(),
        "samplingRuleVersion": SAMPLING_RULE_VERSION,
        "generatedAt": str(generated_at).strip(),
        "questionIds": question_ids,
        "sampleAssignments": [
            {
                "questionId": question_id,
                "sampleKind": normalized_assignments[question_id].value,
            }
            for question_id in question_ids
        ],
        "strata": normalized_strata,
    }
    try:
        manifest = AuditSampleManifest.from_dict(payload)
    except ContractValidationError as exc:
        raise AuditSamplingError(str(exc)) from exc
    return replace(manifest, manifestHash=audit_sample_manifest_hash(manifest))


def sampling_matrix(
    *,
    pool: Sequence[Mapping[str, Any]],
    sampled_question_ids: Iterable[str],
) -> dict[str, Any]:
    """Build the deterministic strata sampling matrix for one audit sample.

    Rows are (riskClass, catalogDomain) strata sorted by name, each with the
    pool size, sampled size and per-sampleKind counts; totals close the
    matrix so reviewers can see coverage at one glance.
    """

    entries = normalize_pool(pool)
    sampled_ids = [str(item or "").strip() for item in sampled_question_ids]
    sampled_set = set(sampled_ids)
    unknown = sorted(
        question_id for question_id in sampled_set if question_id not in {
            entry.questionId for entry in entries
        }
    )
    if unknown:
        raise AuditSamplingError(
            "sampled questions must come from the pool: " + ", ".join(unknown)
        )
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    for entry in entries:
        row = rows.setdefault(
            (entry.riskClass, entry.catalogDomain),
            {"poolCount": 0, "sampledCount": 0},
        )
        row["poolCount"] += 1
        if entry.questionId in sampled_set:
            row["sampledCount"] += 1
    return {
        "strataRows": [
            {
                "riskClass": risk_class,
                "catalogDomain": domain,
                "poolCount": row["poolCount"],
                "sampledCount": row["sampledCount"],
            }
            for (risk_class, domain), row in sorted(rows.items())
        ],
        "totals": {"pool": len(entries), "sampled": len(sampled_set)},
    }


def _derive_seed(*, seed: str, purpose: str, gate: str, batch_index: int) -> str:
    return sha256_hex(
        {
            "batchIndex": batch_index,
            "gate": gate,
            "purpose": purpose,
            "seed": str(seed).strip(),
        }
    )


def _priority(derived_seed: str, question_id: str) -> str:
    return hashlib.sha256(f"{derived_seed}:{question_id}".encode("utf-8")).hexdigest()


def _stratified_draw(
    entries: tuple[PoolQuestion, ...], *, count: int, derived_seed: str
) -> tuple[str, ...]:
    """Deal round-robin across strata from digest-prioritized member lists."""

    if count < 1:
        raise AuditSamplingError("sample count must be >= 1")
    if count > len(entries):
        raise AuditSamplingError(
            f"requested sample count {count} exceeds candidate pool {len(entries)}"
        )
    strata: dict[tuple[str, str], list[PoolQuestion]] = {}
    for entry in entries:
        strata.setdefault((entry.riskClass, entry.catalogDomain), []).append(entry)
    queues = [
        sorted(
            strata[key],
            key=lambda entry: (_priority(derived_seed, entry.questionId), entry.questionId),
        )
        for key in sorted(strata)
    ]
    picked: list[str] = []
    level = 0
    while len(picked) < count:
        progressed = False
        for queue in queues:
            if level < len(queue):
                picked.append(queue[level].questionId)
                progressed = True
                if len(picked) == count:
                    break
        if not progressed:  # pragma: no cover - defensive
            raise AuditSamplingError("stratified draw exhausted its candidate pool")
        level += 1
    return tuple(picked)


def _strata_for(entries: Iterable[PoolQuestion]) -> dict[str, list[str]]:
    materialized = list(entries)
    strata: dict[str, list[str]] = {
        "risk_class": sorted({entry.riskClass for entry in materialized}),
        "catalog_domain": sorted({entry.catalogDomain for entry in materialized}),
    }
    phases = sorted({entry.runPhase for entry in materialized if entry.runPhase})
    if phases:
        strata["run_phase"] = phases
    return strata


def _apply_full_review_overrides(
    assignments: dict[str, SampleKind],
    *,
    risk_triggered_question_ids: Iterable[str],
    anomaly_question_ids: Iterable[str],
) -> dict[str, SampleKind]:
    risk_ids = [str(item or "").strip() for item in risk_triggered_question_ids]
    anomaly_ids = [str(item or "").strip() for item in anomaly_question_ids]
    unknown = [
        question_id
        for question_id in (*risk_ids, *anomaly_ids)
        if question_id not in assignments
    ]
    if unknown:
        raise AuditSamplingError(
            "full-review targets must be part of this batch: " + ", ".join(sorted(unknown))
        )
    updated = dict(assignments)
    for question_id in risk_ids:
        updated[question_id] = SampleKind.RISK_TRIGGERED_FULL_REVIEW
    for question_id in anomaly_ids:
        updated[question_id] = SampleKind.ANOMALY_FULL_REVIEW
    return updated


def _merge_sentinel_selection(
    assignments: dict[str, SampleKind],
    selection: DriftSentinelSelection,
) -> dict[str, SampleKind]:
    updated = dict(assignments)
    for question_id in selection.selectedQuestionIds:
        if question_id in updated:
            raise AuditSamplingError(
                "drift sentinel question is already sampled in this batch; "
                f"re-select with exclude_question_ids: {question_id}"
            )
        updated[question_id] = SampleKind.DRIFT_SENTINEL
    sentinel_count = sum(
        1 for kind in updated.values() if kind is SampleKind.DRIFT_SENTINEL
    )
    if sentinel_count != DRIFT_SENTINEL_COUNT:
        raise AuditSamplingError(
            f"batch manifests carrying sentinels must carry exactly "
            f"{DRIFT_SENTINEL_COUNT}, got {sentinel_count}"
        )
    return updated


def _derived_manifest_id(
    *,
    gate: str,
    batch_index: int,
    policy_id: str,
    policy_version: str,
    policy_content_hash: str,
    seed: str,
    question_ids: list[str],
) -> str:
    digest = sha256_hex(
        {
            "batchIndex": batch_index,
            "gate": str(gate).strip(),
            "policyContentHash": policy_content_hash,
            "policyId": policy_id,
            "policyVersion": policy_version,
            "questionIds": question_ids,
            "seed": str(seed).strip(),
        }
    )
    return "manifest-" + digest[:24]


def _derived_selection_id(*, seed: str, candidate_pool: list[str]) -> str:
    digest = sha256_hex(
        {
            "candidatePool": candidate_pool,
            "purpose": "drift_sentinel",
            "seed": str(seed).strip(),
        }
    )
    return "sentinel-" + digest[:24]


__all__ = [
    "DEFAULT_G125_BATCH_SIZE",
    "G125_GATE",
    "LOW_RISK_CLASS",
    "SAMPLING_RULE_VERSION",
    "AuditSamplingError",
    "PoolQuestion",
    "SENTINEL_SELECTION_RULE_VERSION",
    "assert_policy_binding",
    "bind_sentinel_selection_to_manifest",
    "build_audit_sample_manifest",
    "draw_g125_batch",
    "generate_full_review_manifest",
    "generate_g125_batch_manifest",
    "generate_g12_calibration_manifest",
    "normalize_pool",
    "policy_reference",
    "sampling_matrix",
    "second_half_question_ids",
    "select_drift_sentinels",
]
