"""Automation policy shadow evaluator (R1.4).

The shadow execution core beside real decision points: given an
``AutoAdvancePolicyV2`` (``executionMode == "shadow"``) and the duck-typed
context observed at a real chain decision point (digest state, candidate
scores, sibling progress...), evaluate what the system policy *would* decide
if it were active — and record one human-comparison evaluation record.  It
never emits a command, never mutates chain state, and never advances anything:
the records are the calibration evidence stream (would-vs-actual agreement)
for the G12 gate, not an automation path.

Naming guard: this is the *automation policy shadow* (the policy document's
``executionMode=shadow`` semantics from ``automation_policy``).  It has
nothing to do with the ``off/shadow/on`` session-scope modes of
``hypothesis_session_scope_mode``.

Behavior guard: when no shadow policy is configured
(``VIBELUTION_AUTO_ADVANCE_POLICY_PATH`` unset or unloadable) every hook is a
no-op — the execution path stays byte-identical to the non-shadow chain.

wouldDecide rules per capability switch (documented against the zero-click
plan semantics):

- ``autoCloseMeetingRound`` -> ``auto_close`` at ``meeting_close``: the round
  closes itself only when the full confirmation chain passed — digest draft
  present and content-hash verified, closure approved, every closure decision
  resolvable, and a human confirmation actor present.
- ``autoSelectCandidates`` -> ``auto_select`` at ``candidate_selection``:
  finalists are picked automatically only when candidates exist, every
  candidate carries a numeric score, all scores clear the threshold, and the
  count stays within the finalist limit.
- ``autoStartEvidenceRepair`` -> ``auto_repair`` at ``evidence_repair``: a
  repair pass starts only on a detected evidence gap and only while the
  bounded revision budget (``policy.maxRevisionRounds``, decision #3) has
  remaining rounds.
- ``autoConvergeQuestion`` -> ``auto_converge`` at ``converge_question``:
  mirrors the authoritative ``chain_state`` convergence gates — latest round
  closed, meta review accepted, no new evidence requests, no pending handoffs.
- ``autoAdvanceBatchGate`` -> ``auto_gate`` at ``batch_gate``: the gate
  advances only when every stage gate passed and the budget is not exhausted.

A disabled capability switch, or any failed gate, yields ``hold`` (the policy
would do nothing and the human stays in the loop).
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.infrastructure import developer_sandbox
from core.research.workflow.contracts.automation_policy import AutoAdvancePolicyV2
from core.research.workflow.contracts.policy_shadow import (
    POLICY_SHADOW_ACTION_FOR_POINT,
    POLICY_SHADOW_CAPABILITY_FOR_POINT,
    POLICY_SHADOW_SCHEMA_VERSION,
    PolicyShadowDecision,
    PolicyShadowEvaluationRecord,
    derive_shadow_agreement,
)

SHADOW_POLICY_ENV = "VIBELUTION_AUTO_ADVANCE_POLICY_PATH"
SHADOW_EVALUATION_STORE_FILENAME = "policy_shadow_evaluations.jsonl"

# Default selection threshold/limit inputs when the decision-point context
# does not carry explicit ones (bounded draft/screen flow defaults).
DEFAULT_CANDIDATE_MIN_SCORE = 0.0
DEFAULT_FINALIST_LIMIT = 5

_LOCK = threading.Lock()
_POLICY_CACHE: dict[str, tuple[float, int, AutoAdvancePolicyV2 | None]] = {}


class PolicyShadowEvaluationError(ValueError):
    """Typed fail-closed error for shadow evaluation requests."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _gate(gate_id: str, passed: bool, **detail: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {"gateId": gate_id, "passed": bool(passed)}
    entry.update({key: value for key, value in detail.items() if value is not None})
    return entry


def _context_int(context: Mapping[str, Any], key: str, default: int = 0) -> int:
    try:
        value = context.get(key)
        if isinstance(value, bool):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _context_bool(context: Mapping[str, Any], key: str, default: bool = False) -> bool:
    value = context.get(key, default)
    return value is True


# ---------------------------------------------------------------------------
# gate evaluation per decision point (pure)


def _evaluate_meeting_close_gates(context: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        _gate(
            "closureApproved",
            _context_bool(context, "closureApproved"),
            meetingRoundId=str(context.get("meetingRoundId") or "") or None,
        ),
        _gate(
            "digestConfirmed",
            _context_bool(context, "digestConfirmed"),
            meetingType=str(context.get("meetingType") or "") or None,
        ),
        _gate(
            "decisionsResolved",
            _context_bool(context, "decisionsResolved"),
            unresolvedDecisionCount=_context_int(context, "unresolvedDecisionCount")
            or None,
        ),
        _gate(
            "humanConfirmationPresent",
            bool(str(context.get("closedBy") or "").strip()),
        ),
    ]


def _evaluate_candidate_selection_gates(
    context: Mapping[str, Any],
) -> list[dict[str, Any]]:
    candidates = [
        item for item in list(context.get("candidates") or []) if isinstance(item, Mapping)
    ]
    candidate_ids = [str(item.get("candidateId") or "").strip() for item in candidates]
    candidate_ids = [item for item in candidate_ids if item]
    scores: list[float] = []
    scores_available = bool(candidates)
    for item in candidates:
        raw = item.get("score")
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            scores_available = False
            continue
        scores.append(float(raw))
    threshold = context.get("minScore")
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        threshold = DEFAULT_CANDIDATE_MIN_SCORE
    finalist_limit = context.get("finalistLimit")
    if isinstance(finalist_limit, bool) or not isinstance(finalist_limit, (int, float)):
        finalist_limit = DEFAULT_FINALIST_LIMIT
    return [
        _gate("candidatesAvailable", bool(candidate_ids), candidateCount=len(candidate_ids)),
        _gate("scoresAvailable", scores_available),
        _gate(
            "scoresAboveThreshold",
            scores_available and all(score >= float(threshold) for score in scores),
            minScore=float(threshold),
            lowestScore=min(scores) if scores else None,
        ),
        _gate(
            "withinFinalistLimit",
            bool(candidate_ids) and len(candidate_ids) <= int(finalist_limit),
            finalistLimit=int(finalist_limit),
        ),
    ]


def _evaluate_evidence_repair_gates(
    policy: AutoAdvancePolicyV2, context: Mapping[str, Any]
) -> list[dict[str, Any]]:
    gap_count = _context_int(context, "gapCount")
    rounds_used = _context_int(context, "revisionRoundsUsed")
    return [
        _gate("evidenceGapDetected", gap_count > 0, gapCount=gap_count),
        _gate(
            "revisionBudgetRemaining",
            rounds_used < policy.maxRevisionRounds,
            revisionRoundsUsed=rounds_used,
            maxRevisionRounds=policy.maxRevisionRounds,
        ),
    ]


def _evaluate_converge_question_gates(
    context: Mapping[str, Any],
) -> list[dict[str, Any]]:
    new_requests = _context_int(context, "newEvidenceRequestCount")
    pending_handoffs = _context_int(context, "pendingHandoffCount")
    return [
        _gate(
            "latestRoundClosed",
            _context_bool(context, "latestRoundClosed"),
            roundId=str(context.get("roundId") or "") or None,
        ),
        _gate("metaReviewAccepted", _context_bool(context, "metaReviewAccepted")),
        _gate("noNewEvidenceRequests", new_requests == 0, newEvidenceRequestCount=new_requests),
        _gate("noPendingHandoffs", pending_handoffs == 0, pendingHandoffCount=pending_handoffs),
    ]


def _evaluate_batch_gate_gates(context: Mapping[str, Any]) -> list[dict[str, Any]]:
    stage_gates_raw = context.get("stageGates")
    if isinstance(stage_gates_raw, Mapping):
        stage_gates = {str(key): value is True for key, value in stage_gates_raw.items()}
        stage_gates_passed = bool(stage_gates) and all(stage_gates.values())
    else:
        stage_gates = {}
        stage_gates_passed = stage_gates_raw is True
    budget_exhausted = _context_bool(context, "budgetExhausted")
    return [
        _gate("stageGatesPassed", stage_gates_passed, stageGates=stage_gates or None),
        _gate("budgetRemaining", not budget_exhausted),
    ]


def _evaluate_gates(
    policy: AutoAdvancePolicyV2, decision_point: str, context: Mapping[str, Any]
) -> list[dict[str, Any]]:
    if decision_point == "meeting_close":
        return _evaluate_meeting_close_gates(context)
    if decision_point == "candidate_selection":
        return _evaluate_candidate_selection_gates(context)
    if decision_point == "evidence_repair":
        return _evaluate_evidence_repair_gates(policy, context)
    if decision_point == "converge_question":
        return _evaluate_converge_question_gates(context)
    if decision_point == "batch_gate":
        return _evaluate_batch_gate_gates(context)
    raise PolicyShadowEvaluationError(
        f"unsupported policy shadow decision point: {decision_point!r}",
        code="unsupported_decision_point",
    )


def _would_decide_payload(
    decision_point: str, context: Mapping[str, Any], evidence: list[dict[str, Any]]
) -> dict[str, Any]:
    payload: dict[str, Any] = {"decisionPoint": decision_point}
    if decision_point == "candidate_selection":
        payload["candidateIds"] = [
            str(item.get("candidateId") or "").strip()
            for item in list(context.get("candidates") or [])
            if isinstance(item, Mapping) and str(item.get("candidateId") or "").strip()
        ]
    elif decision_point == "evidence_repair":
        payload["gapCount"] = _context_int(context, "gapCount")
    elif decision_point == "converge_question":
        payload["roundId"] = str(context.get("roundId") or "").strip()
    elif decision_point == "meeting_close":
        payload["meetingRoundId"] = str(context.get("meetingRoundId") or "").strip()
    for entry in evidence:
        if entry.get("gateId") == "capabilityEnabled":
            continue
        for key in (
            "unresolvedDecisionCount",
            "gapCount",
            "newEvidenceRequestCount",
            "pendingHandoffCount",
        ):
            if key in entry:
                payload[key] = entry[key]
    return payload


# ---------------------------------------------------------------------------
# public evaluation surface (pure)


def evaluate_policy_shadow_decision(
    policy: Any,
    decision_point: str,
    context: Mapping[str, Any] | None = None,
    *,
    evaluated_at: str | None = None,
) -> PolicyShadowDecision:
    """Evaluate one decision point against a shadow policy (pure function).

    Fail-closed: only an ``AutoAdvancePolicyV2`` with
    ``executionMode == "shadow"`` may be evaluated — an active policy is
    rejected with ``active_execution_mode_forbidden`` because shadow records
    are a preview instrument, never an execution path.
    """

    if not isinstance(policy, AutoAdvancePolicyV2):
        raise PolicyShadowEvaluationError(
            "policy shadow evaluation requires an AutoAdvancePolicyV2 document",
            code="unsupported_policy",
        )
    if policy.executionMode != "shadow":
        raise PolicyShadowEvaluationError(
            "policy shadow evaluation refuses executionMode="
            f"{policy.executionMode!r}; only shadow policies may be evaluated",
            code="active_execution_mode_forbidden",
        )
    point = str(decision_point or "").strip()
    if point not in POLICY_SHADOW_CAPABILITY_FOR_POINT:
        raise PolicyShadowEvaluationError(
            f"unsupported policy shadow decision point: {point!r}",
            code="unsupported_decision_point",
        )
    context = dict(context or {})
    capability = POLICY_SHADOW_CAPABILITY_FOR_POINT[point]
    capability_enabled = policy.capabilities.get(capability) is True
    evidence = [
        _gate(
            "capabilityEnabled",
            capability_enabled,
            capability=capability,
        )
    ]
    evidence.extend(_evaluate_gates(policy, point, context))
    action = POLICY_SHADOW_ACTION_FOR_POINT[point]
    would = (
        action
        if capability_enabled and all(entry["passed"] for entry in evidence[1:])
        else "hold"
    )
    return PolicyShadowDecision(
        schemaVersion=POLICY_SHADOW_SCHEMA_VERSION,
        capability=capability,
        decisionPoint=point,
        wouldDecide=would,
        wouldDecidePayload=_would_decide_payload(point, context, evidence),
        evidence=evidence,
        evaluatedAt=evaluated_at or _utc_now(),
    )


def build_policy_shadow_evaluation_record(
    decision: PolicyShadowDecision,
    *,
    policy: AutoAdvancePolicyV2,
    team_id: str,
    question_id: str,
    actual_outcome: Mapping[str, Any],
    scope: Mapping[str, Any] | None = None,
    record_id: str | None = None,
) -> PolicyShadowEvaluationRecord:
    """Pair one shadow decision with the real human outcome (fail-closed).

    The agreement class is derived, never free-form: the record constructor
    rejects any stored agreement that contradicts
    ``(wouldDecide, outcomeClass)`` and refuses records about a non-shadow
    policy.
    """

    from core.web.services.team_workflow.storage_ids import safe_storage_component

    outcome = dict(actual_outcome or {})
    outcome_class = str(outcome.get("outcomeClass") or "").strip()
    if not outcome_class:
        outcome["outcomeClass"] = "none"
        outcome_class = "none"
    expected_agreement = derive_shadow_agreement(decision.wouldDecide, outcome_class)
    if not str(outcome.get("agreement") or "").strip():
        outcome["agreement"] = expected_agreement
    normalized_team_id = safe_storage_component(
        str(team_id or "").strip(), fallback="team"
    )
    identity = {
        "teamId": normalized_team_id,
        "questionId": str(question_id or "").strip().upper(),
        "decisionPoint": decision.decisionPoint,
        "wouldDecide": decision.wouldDecide,
        "evaluatedAt": decision.evaluatedAt,
        "outcome": outcome.get("outcome"),
        "policyId": policy.policyId,
        "policyVersion": policy.version,
    }
    if record_id:
        final_record_id = str(record_id).strip()
    else:
        from core.web.services.team_workflow.research_runtime.hypothesis_first_chain import (
            _stable_hash,
        )

        final_record_id = "pshadow-" + _stable_hash(identity)[:16]
    return PolicyShadowEvaluationRecord(
        schemaVersion=POLICY_SHADOW_SCHEMA_VERSION,
        recordId=final_record_id,
        teamId=normalized_team_id,
        questionId=str(question_id or "").strip().upper(),
        scope=dict(scope or {}),
        decisionPoint=decision.decisionPoint,
        capability=decision.capability,
        wouldDecide=decision.wouldDecide,
        wouldDecidePayload=dict(decision.wouldDecidePayload),
        evidence=[dict(item) for item in decision.evidence],
        actualOutcome=outcome,
        agreement=expected_agreement,
        evaluatedAt=decision.evaluatedAt,
        policyId=policy.policyId,
        policyVersion=policy.version,
        policyContentHash=policy.declaredContentHash,
        policyExecutionMode=policy.executionMode,
    )


# ---------------------------------------------------------------------------
# policy source + record store (chain-facing, best-effort by design)


def load_shadow_policy_from_environment() -> AutoAdvancePolicyV2 | None:
    """Load the configured shadow policy, or ``None`` when none is usable.

    The path comes from ``VIBELUTION_AUTO_ADVANCE_POLICY_PATH``.  Loading is
    fail-closed about the document itself (hash verify + preview validation
    through ``load_auto_advance_policy_v2``), but fail-silent for the chain:
    an unusable configuration disables shadow recording instead of breaking
    any decision point.  Results are cached per (path, mtime, size).
    """

    from core.web.services.team_workflow.research_runtime.automation_policy_service import (
        load_auto_advance_policy_v2,
    )

    raw_path = os.environ.get(SHADOW_POLICY_ENV, "").strip()
    if not raw_path:
        return None
    try:
        resolved = Path(raw_path)
        stat = resolved.stat()
    except OSError:
        _record_scene_event(
            "policy_shadow_policy_source_unreadable",
            outcome="policy_load_failed",
            fields={"env": SHADOW_POLICY_ENV},
            level="warning",
        )
        return None
    cache_key = str(resolved)
    with _LOCK:
        cached = _POLICY_CACHE.get(cache_key)
        if cached and cached[0] == stat.st_mtime and cached[1] == stat.st_size:
            return cached[2]
    policy: AutoAdvancePolicyV2 | None
    try:
        policy = load_auto_advance_policy_v2(resolved)
    except Exception:
        policy = None
        _record_scene_event(
            "policy_shadow_policy_source_invalid",
            outcome="policy_load_failed",
            fields={"env": SHADOW_POLICY_ENV},
            level="warning",
        )
    with _LOCK:
        _POLICY_CACHE[cache_key] = (stat.st_mtime, stat.st_size, policy)
    return policy


def policy_shadow_store_path(team_id: str) -> Path:
    """Dedicated JSONL store next to the chain ledger (same storage pattern).

    A separate file — not a new ``workflow_artifact_store`` kind and not a
    recordKind inside ``hypothesis_first_chain.jsonl`` — keeps the advisory
    shadow stream out of every chain read, reset, and readiness path, so the
    executing chain stays byte-identical whether or not shadowing is on.
    """

    from core.web.services.team_workflow.storage_ids import safe_storage_component

    root = developer_sandbox.seeded_sandbox_workspace_path(
        Path(developer_sandbox_project_root()),
        "teams",
        safe_storage_component(str(team_id or "").strip(), fallback="team"),
    )
    return root / "research_workflow" / SHADOW_EVALUATION_STORE_FILENAME


def developer_sandbox_project_root() -> str:
    """Project root for storage resolution (matches the chain's default)."""

    from core.web.services.team_workflow.research_runtime.hypothesis_first_chain import (
        _project_root,
    )

    return str(_project_root())


def append_policy_shadow_evaluation_record(record: PolicyShadowEvaluationRecord) -> None:
    """Append one validated record to the dedicated shadow JSONL store."""

    from core.web.services.team_workflow.storage_durability import append_jsonl_locked

    path = policy_shadow_store_path(record.teamId)
    path.parent.mkdir(parents=True, exist_ok=True)
    append_jsonl_locked(path, record.to_dict())


def list_policy_shadow_evaluations(
    team_id: str, *, question_id: str = ""
) -> dict[str, Any]:
    """Read helper over the shadow store (tests and future UI surfaces)."""

    from core.web.services.team_workflow.storage_durability import read_jsonl_tolerant

    path = policy_shadow_store_path(team_id)
    records = read_jsonl_tolerant(path) if path.is_file() else []
    normalized_question = str(question_id or "").strip().upper()
    if normalized_question:
        records = [
            record
            for record in records
            if str(record.get("questionId") or "").upper() == normalized_question
        ]
    return {
        "schemaVersion": POLICY_SHADOW_SCHEMA_VERSION,
        "teamId": team_id,
        "questionId": normalized_question,
        "evaluations": records,
        "count": len(records),
    }


def record_policy_shadow_decision(
    *,
    team_id: str,
    question_id: str,
    policy: AutoAdvancePolicyV2,
    decision_point: str,
    context: Mapping[str, Any],
    actual_outcome: Mapping[str, Any],
    scope: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Evaluate one decision point and persist the human-comparison record.

    Returns the record dict, or ``None`` when nothing qualified.  Raises on
    fail-closed violations (active policy, unknown point) — callers that sit
    inside execution paths should use
    :func:`record_policy_shadow_decision_safely`.
    """

    decision = evaluate_policy_shadow_decision(policy, decision_point, context)
    record = build_policy_shadow_evaluation_record(
        decision,
        policy=policy,
        team_id=team_id,
        question_id=question_id,
        actual_outcome=actual_outcome,
        scope=scope,
    )
    append_policy_shadow_evaluation_record(record)
    return record.to_dict()


def record_policy_shadow_decision_safely(
    *,
    team_id: str,
    question_id: str,
    decision_point: str,
    context: Mapping[str, Any],
    actual_outcome: Mapping[str, Any],
    scope: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Chain-facing hook: shadow-evaluate one decision point, never raise.

    No configured policy -> no-op without any I/O.  Any failure degrades to a
    quiet scene event (diagnostics never break the chain — same discipline as
    the chain's own observability events).
    """

    try:
        policy = load_shadow_policy_from_environment()
        if policy is None:
            return None
        record = record_policy_shadow_decision(
            team_id=team_id,
            question_id=question_id,
            policy=policy,
            decision_point=decision_point,
            context=context,
            actual_outcome=actual_outcome,
            scope=scope,
        )
        if record is not None:
            _record_scene_event(
                "policy_shadow_evaluation_recorded",
                outcome="recorded",
                fields={
                    "decisionPoint": record.get("decisionPoint"),
                    "wouldDecide": record.get("wouldDecide"),
                    "agreement": record.get("agreement"),
                },
            )
        return record
    except Exception as exc:  # noqa: BLE001 - shadow recording must never break the chain
        _record_scene_event(
            "policy_shadow_evaluation_failed",
            outcome="shadow_record_failed",
            fields={"decisionPoint": str(decision_point or ""), "error": str(exc)},
            level="warning",
        )
        return None


def _record_scene_event(
    event_code: str,
    *,
    outcome: str,
    fields: dict[str, Any] | None = None,
    level: str = "info",
) -> None:
    """Best-effort observability event; diagnostics never break the chain."""

    try:
        from core.web.services.runtime_scene_service import (
            record_runtime_scene_event_quietly,
        )

        record_runtime_scene_event_quietly(
            "team_workflow_orchestration",
            "policy_shadow_evaluator",
            event_code,
            level=level,
            outcome=outcome,
            fields=fields or {},
        )
    except Exception:  # noqa: BLE001 - observability is best-effort by contract
        return


def shadow_decision_to_json(decision: PolicyShadowDecision) -> str:
    """Canonical JSON rendering for logs/tests."""

    return json.dumps(decision.to_dict(), ensure_ascii=False, sort_keys=True)


__all__ = [
    "DEFAULT_CANDIDATE_MIN_SCORE",
    "DEFAULT_FINALIST_LIMIT",
    "SHADOW_EVALUATION_STORE_FILENAME",
    "SHADOW_POLICY_ENV",
    "PolicyShadowEvaluationError",
    "append_policy_shadow_evaluation_record",
    "build_policy_shadow_evaluation_record",
    "developer_sandbox_project_root",
    "evaluate_policy_shadow_decision",
    "list_policy_shadow_evaluations",
    "load_shadow_policy_from_environment",
    "policy_shadow_store_path",
    "record_policy_shadow_decision",
    "record_policy_shadow_decision_safely",
    "shadow_decision_to_json",
]
