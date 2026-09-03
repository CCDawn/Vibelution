"""Automation policy active executor (post-R1.4: gated real execution).

The final piece of the hypothesis-first automation chain: an
``AutoAdvancePolicyV2`` that is **approved + active** can now actually act at
the same real decision points where the R1.4 shadow evaluator records its
would-have-decided evidence.  The executor only ever *presses existing
buttons* — ``approve_meeting_digest``, ``record_hypothesis_selection`` and
``record_human_adjudication`` — under the system actor, with every
fail-closed gate of those paths untouched.  It is not a second
implementation of any decision: each capability dispatches to the exact
idempotent function a human confirmation would call.

Safety ladder (evaluated per attempt; ANY failed rung => record-only):

0. ``VIBELUTION_AUTO_ADVANCE_DISABLED`` truthy -> nothing executes
   (kill switch, highest priority, audited);
1. policy load: the resolved policy document (operator config.toml
   ``[research_workflow].auto_advance_policy_path`` first, then
   ``VIBELUTION_AUTO_ADVANCE_POLICY_PATH``, then the default
   ``auto-advance-policy.active.json`` in the operator config home) must
   load + hash-verify through the frozen loader at ``stage="activation"``;
2. activation credential: ``executionMode == "active"`` AND
   ``status == "approved"`` AND a non-empty ``approval.approvedBy`` —
   enforced twice (fail-closed at contract validation, re-checked here);
3. calibration gate: the decision-#13 statistical evidence
   (kappa / false-auto-approve upper bound / stratum coverage) must satisfy
   the policy's declared ``calibrationGate`` via
   ``g12_calibration_service.calibration_gate_verdict``; missing or
   underpowered evidence is fail-closed;
4. ``drainMode == "none"`` (requested/draining/drained never execute);
5. the capability switch for this decision point must be ``True``;
6. decision-point re-verification: meeting digests are re-validated
   (markers preserved + evidence-request keywords non-empty) before
   approval; convergence re-checks the chain's own gates and always passes
   through the existing claim-belief hard gate (fail-closed semantics are
   borrowed, never relaxed: a blocked gate records ``skipped``, nothing
   more).

Audit: every attempt that gets past the "no policy configured" fast path
appends one durable record to ``policy_activation_audit.jsonl`` (same
directory conventions as the shadow store) carrying the policy identity,
the per-rung verdicts, the actor and the outcome.  Shadow recording is
completely unchanged; the two stores are separate files.

Behavior guard: with no policy document configured (config.toml key unset,
env unset, and no default file in the operator config home) every hook is
a no-op before any I/O — the executing chain stays byte-identical to the
non-policy flow.  All hooks swallow their own failures into
diagnostics (quiet scene events); they never break a host flow.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.infrastructure import developer_sandbox
from core.research.workflow.contracts.automation_policy import (
    ACTIVE_REQUIRES_APPROVAL_RECORD,
    ACTIVE_REQUIRES_APPROVED_STATUS,
    AutoAdvancePolicyV2,
)
from core.research.workflow.contracts.policy_shadow import (
    POLICY_SHADOW_CAPABILITY_FOR_POINT,
)

POLICY_ACTIVATION_AUDIT_SCHEMA_VERSION = "1.0.0"
AUTO_ADVANCE_DISABLED_ENV = "VIBELUTION_AUTO_ADVANCE_DISABLED"
ACTIVATION_AUDIT_STORE_FILENAME = "policy_activation_audit.jsonl"
SYSTEM_ACTOR_PREFIX = "system:auto-advance:"

# Decision points with a real executor body in this module; the remaining
# capability switches (autoStartEvidenceRepair, autoAdvanceBatchGate) are
# audited as ``not_implemented`` whenever their decision point is attempted,
# never silently ignored.
EXECUTABLE_DECISION_POINTS = frozenset(
    {"meeting_close", "candidate_selection", "converge_question"}
)
NOT_IMPLEMENTED_DECISION_POINTS = frozenset(
    {"evidence_repair", "batch_gate"}
)

_KILL_SWITCH_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})

_LOCK = threading.Lock()
_DOCUMENT_CACHE: dict[
    str, tuple[float, int, tuple[AutoAdvancePolicyV2 | None, dict[str, Any] | None]]
] = {}
_REENTRANCY = threading.local()


class AutoAdvanceExecutionError(ValueError):
    """Typed fail-closed error for automation policy execution attempts."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


class _PointSkip(Exception):
    """Internal: a decision-point precondition failed (record-only path)."""

    def __init__(self, code: str, detail: dict[str, Any] | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.detail = dict(detail or {})


# ---------------------------------------------------------------------------
# small helpers


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _stable_hash(payload: Any) -> str:
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def kill_switch_enabled() -> bool:
    """True when ``VIBELUTION_AUTO_ADVANCE_DISABLED`` carries a truthy value."""

    return os.environ.get(AUTO_ADVANCE_DISABLED_ENV, "").strip().lower() in (
        _KILL_SWITCH_TRUE_VALUES
    )


def system_actor_for(policy: AutoAdvancePolicyV2) -> str:
    """The stable system actor id used for every executor-driven command."""

    return f"{SYSTEM_ACTOR_PREFIX}{policy.policyId}"


def _record_scene_event(
    event_code: str,
    *,
    outcome: str,
    fields: dict[str, Any] | None = None,
    level: str = "info",
) -> None:
    try:
        from core.web.services.runtime_scene_service import (
            record_runtime_scene_event_quietly,
        )

        record_runtime_scene_event_quietly(
            "team_workflow_orchestration",
            "automation_policy_executor",
            event_code,
            level=level,
            outcome=outcome,
            fields=fields or {},
        )
    except Exception:  # noqa: BLE001 - observability is best-effort by contract
        return


# ---------------------------------------------------------------------------
# policy source (stage="activation", hash-verified, cached)


def _load_document_cached() -> tuple[AutoAdvancePolicyV2 | None, dict[str, Any] | None]:
    """Load the configured policy at activation stage, or ``(None, None)``.

    Fail-closed about the document (hash verify + activation-stage
    validation: an active document must carry status=approved AND a
    non-empty approval.approvedBy), fail-silent for the chain.  The document
    path resolves config-first (``[research_workflow]
    .auto_advance_policy_path`` in the operator config.toml — env
    propagation into backend processes is unreliable), then
    ``VIBELUTION_AUTO_ADVANCE_POLICY_PATH``, then the default
    ``auto-advance-policy.active.json`` in the operator config home; a
    missing file behaves exactly like "no policy configured".  Results are
    cached per (path, mtime, size) exactly like the shadow loader.
    """

    from config.paths import resolve_auto_advance_policy_path

    from core.web.services.team_workflow.research_runtime.automation_policy_service import (
        load_auto_advance_policy_v2_document,
    )

    try:
        resolved = resolve_auto_advance_policy_path()
        stat = resolved.stat()
    except OSError:
        return None, None
    cache_key = str(resolved)
    with _LOCK:
        cached = _DOCUMENT_CACHE.get(cache_key)
        if cached and cached[0] == stat.st_mtime and cached[1] == stat.st_size:
            return cached[2]
    policy: AutoAdvancePolicyV2 | None
    payload: dict[str, Any] | None
    try:
        policy, payload = load_auto_advance_policy_v2_document(
            resolved, stage="activation"
        )
    except Exception:  # noqa: BLE001 - unusable configuration disables execution
        policy, payload = None, None
        _record_scene_event(
            "auto_advance_policy_source_invalid",
            outcome="policy_load_failed",
            fields={"path": str(resolved), "env": _shadow_policy_env()},
            level="warning",
        )
    with _LOCK:
        _DOCUMENT_CACHE[cache_key] = (stat.st_mtime, stat.st_size, (policy, payload))
    return policy, payload


def _shadow_policy_env() -> str:
    from core.web.services.team_workflow.research_runtime.policy_shadow_evaluator import (
        SHADOW_POLICY_ENV,
    )

    return SHADOW_POLICY_ENV


def load_active_policy_from_environment() -> AutoAdvancePolicyV2 | None:
    """Public loader: the configured activation-stage policy, or ``None``."""

    policy, _ = _load_document_cached()
    return policy


def default_calibration_gate_verdict(
    policy: AutoAdvancePolicyV2, *, team_id: str = ""
) -> dict[str, Any]:
    """The ladder's default calibration evidence read (read-only).

    Delegates to :func:`g12_calibration_service.calibration_gate_verdict`.
    When operator-entered G12 evidence exists for this team
    (``g12_calibration_store`` manifests + judgement records bound to this
    policy identity) the persisted bundle is judged by the unchanged gate
    logic; with nothing recorded the answer stays fail-closed
    ("calibration evidence unavailable") and the executor only records.
    Callers with real decision-#13 evidence may still inject their verdict
    explicitly.  There is deliberately no bypass switch.
    """

    from core.web.services.team_workflow.research_runtime.g12_calibration_service import (
        calibration_gate_verdict,
    )
    from core.web.services.team_workflow.research_runtime.g12_calibration_store import (
        load_g12_calibration_bundle,
    )

    bundle = (
        load_g12_calibration_bundle(str(team_id or "").strip(), policy=policy)
        if str(team_id or "").strip()
        else None
    )
    return calibration_gate_verdict(policy, bundle)


# ---------------------------------------------------------------------------
# safety ladder (pure)


def evaluate_activation_ladder(
    policy: AutoAdvancePolicyV2,
    payload: Mapping[str, Any] | None,
    *,
    calibration_verdict: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate every ladder rung for one attempt (pure, no I/O).

    Returns ``{"allowed": bool, "rungs": [...], "firstFailure": code|None}``.
    Run order encodes priority: the kill switch is evaluated first; every
    other rung is still reported so the audit shows the full picture.
    """

    verdict = dict(calibration_verdict or {})
    rungs: list[dict[str, Any]] = []

    def _rung(gate_id: str, passed: bool, **detail: Any) -> None:
        entry: dict[str, Any] = {"gateId": gate_id, "passed": bool(passed)}
        entry.update({key: value for key, value in detail.items() if value is not None})
        rungs.append(entry)

    # Rung 0 (highest priority): global kill switch.
    kill = kill_switch_enabled()
    _rung("killSwitch", not kill, env=AUTO_ADVANCE_DISABLED_ENV if kill else None)
    # Rung 1: the caller guarantees a loaded policy (see attempt_capability);
    # recorded for a complete audit trail.
    _rung("policyLoaded", policy is not None)
    # Rung 2: activation credential (contract-validated + re-checked).
    approval = payload.get("approval") if isinstance(payload, Mapping) else None
    approvers = approval.get("approvedBy") if isinstance(approval, Mapping) else None
    approver_list = [
        str(item).strip()
        for item in (approvers if isinstance(approvers, list) else [])
        if str(item).strip()
    ]
    credential_ok = (
        policy.executionMode == "active"
        and policy.status == "approved"
        and bool(approver_list)
    )
    _rung(
        "activationCredential",
        credential_ok,
        executionMode=policy.executionMode,
        policyStatus=policy.status,
        approvedBy=approver_list or None,
        expectedCodes=[
            ACTIVE_REQUIRES_APPROVED_STATUS,
            ACTIVE_REQUIRES_APPROVAL_RECORD,
        ],
    )
    # Rung 3: statistical calibration gate (decision #13).
    calibration_passed = verdict.get("passed") is True
    _rung(
        "calibrationGate",
        calibration_passed,
        reasonCode=str(verdict.get("reasonCode") or "") or None,
        status=str(verdict.get("status") or "") or None,
        reasons=list(verdict.get("reasons") or []) or None,
    )
    # Rung 4: drain semantics.
    drain = policy.drainMode
    _rung("drainMode", drain == "none", drainMode=drain)
    allowed = all(entry["passed"] for entry in rungs)
    first_failure = next(
        (entry["gateId"] for entry in rungs if not entry["passed"]), None
    )
    return {
        "allowed": allowed,
        "rungs": rungs,
        "firstFailure": first_failure,
    }


# ---------------------------------------------------------------------------
# audit store (dedicated JSONL beside the shadow store)


def policy_activation_audit_store_path(team_id: str) -> Path:
    """Dedicated JSONL store next to the shadow/chain stores (same pattern)."""

    from core.web.services.team_workflow.research_runtime.policy_shadow_evaluator import (
        developer_sandbox_project_root,
    )
    from core.web.services.team_workflow.storage_ids import safe_storage_component

    root = developer_sandbox.seeded_sandbox_workspace_path(
        Path(developer_sandbox_project_root()),
        "teams",
        safe_storage_component(str(team_id or "").strip(), fallback="team"),
    )
    return root / "research_workflow" / ACTIVATION_AUDIT_STORE_FILENAME


def list_activation_audits(team_id: str) -> dict[str, Any]:
    """Read helper over the audit store (tests and future UI surfaces)."""

    from core.web.services.team_workflow.storage_durability import read_jsonl_tolerant

    path = policy_activation_audit_store_path(team_id)
    records = read_jsonl_tolerant(path) if path.is_file() else []
    return {
        "schemaVersion": POLICY_ACTIVATION_AUDIT_SCHEMA_VERSION,
        "teamId": team_id,
        "audits": records,
        "count": len(records),
    }


def _build_audit_record(
    *,
    team_id: str,
    question_id: str,
    decision_point: str,
    capability: str,
    policy: AutoAdvancePolicyV2,
    ladder: Mapping[str, Any],
    decision: str,
    reason_code: str,
    ref: Mapping[str, Any] | None,
    detail: Mapping[str, Any] | None,
    actor: str,
) -> dict[str, Any]:
    ref = dict(ref or {})
    identity = {
        "policyId": policy.policyId,
        "policyVersion": policy.version,
        "policyContentHash": policy.declaredContentHash,
        "decisionPoint": decision_point,
        "capability": capability,
        "teamId": team_id,
        "questionId": question_id,
        "ref": ref,
        "decision": decision,
        "reasonCode": reason_code,
    }
    record = {
        "schemaVersion": POLICY_ACTIVATION_AUDIT_SCHEMA_VERSION,
        "auditId": "hfaudit-" + _stable_hash(identity)[:16],
        "teamId": team_id,
        "questionId": str(question_id or "").strip().upper(),
        "decisionPoint": decision_point,
        "capability": capability,
        "policyId": policy.policyId,
        "policyVersion": policy.version,
        "policyContentHash": policy.declaredContentHash,
        "policyExecutionMode": policy.executionMode,
        "policyStatus": policy.status,
        "ladder": [dict(item) for item in ladder.get("rungs", [])],
        "capabilityEnabled": policy.capabilities.get(capability) is True,
        "decision": decision,
        "reasonCode": reason_code,
        "ref": ref,
        "detail": dict(detail or {}),
        "actor": actor,
        "executedAt": _utc_now(),
    }
    return record


def _append_audit_record(record: Mapping[str, Any]) -> None:
    """Append one audit record; identical auditIds are written only once."""

    from core.web.services.team_workflow.storage_durability import (
        append_jsonl_locked,
        read_jsonl_tolerant,
    )

    path = policy_activation_audit_store_path(str(record.get("teamId") or ""))
    path.parent.mkdir(parents=True, exist_ok=True)
    audit_id = str(record.get("auditId") or "")
    if audit_id:
        existing = read_jsonl_tolerant(path) if path.is_file() else []
        if any(str(item.get("auditId") or "") == audit_id for item in existing):
            return
    append_jsonl_locked(path, dict(record))


# ---------------------------------------------------------------------------
# decision-point executors (each presses one existing idempotent button)


def _meeting_round(team_id: str, meeting_round_id: str) -> dict[str, Any]:
    from core.web.services.team_workflow import meeting_rounds

    return meeting_rounds.get_meeting_round(team_id, meeting_round_id)["meetingRound"]


def _revalidate_digest(
    meeting_round: Mapping[str, Any],
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Re-run the digest's own fail-closed checks before pressing approve.

    Markers preserved (``_assert_markers_preserved``) plus every evidence
    request re-validated with non-empty keywords
    (``meeting_runtime.validate_evidence_request_draft``).  Raises whatever
    the validators raise; returns (draft, validation_errors) otherwise.
    """

    from core.web.services.team_workflow import meeting_rounds

    draft = (
        dict(meeting_round.get("digestDraft"))
        if isinstance(meeting_round.get("digestDraft"), Mapping)
        else {}
    )
    if not draft:
        raise _PointSkip("digest_draft_missing")
    content_hash = str(draft.get("contentHash") or "").strip()
    if not content_hash:
        raise _PointSkip("digest_content_hash_missing")
    source_messages = meeting_rounds.meeting_source_messages(meeting_round)
    # Markers preserved: every disagreement/risk/action item from the source
    # messages must still be present in the digest (fail-closed, borrowed).
    meeting_rounds._assert_markers_preserved(
        draft, meeting_rounds.extract_discussion_markers(source_messages)
    )
    # EV keywords non-empty: revalidate each untrusted draft request with the
    # exact validator the human approval path uses (require_keywords=True).
    from core.web.services.team_workflow import meeting_runtime

    source_refs = [
        str(item).strip()
        for item in list(draft.get("sourceMessageRefs") or [])
        if str(item).strip()
    ]
    raw_requests = [
        item
        for item in list(draft.get("evidenceRequests") or [])
        if isinstance(item, Mapping)
    ]
    validation_errors: list[dict[str, str]] = [
        dict(item)
        for item in list(draft.get("validationErrors") or [])
        if isinstance(item, Mapping)
    ]
    valid = 0
    for raw in raw_requests:
        normalized, errors = meeting_runtime.validate_evidence_request_draft(
            raw, meeting_round, source_refs=source_refs
        )
        validation_errors.extend(errors)
        if normalized is None:
            continue
        if not [str(k).strip() for k in normalized.get("searchEnvelope", {}).get("keywords", []) if str(k).strip()]:
            validation_errors.append(
                {"code": "search_keywords_missing", "message": "keywords must be non-empty"}
            )
            continue
        valid += 1
    attempted = bool(raw_requests) or bool(draft.get("validationErrors"))
    if attempted and not valid:
        raise _PointSkip(
            "digest_revalidation_failed", {"validationErrors": validation_errors}
        )
    return draft, validation_errors


def _execute_meeting_close(
    team_id: str,
    *,
    meeting_round_id: str,
    policy: AutoAdvancePolicyV2,
) -> dict[str, Any]:
    """Auto-close one ``awaiting_approval`` meeting digest (existing path)."""

    from core.web.services.team_workflow.research_runtime import hypothesis_first_chain as chain

    meeting_round = _meeting_round(team_id, meeting_round_id)
    if str(meeting_round.get("status") or "") != "awaiting_approval":
        raise _PointSkip(
            "meeting_not_awaiting_approval",
            {"status": str(meeting_round.get("status") or "")},
        )
    try:
        draft, validation_errors = _revalidate_digest(meeting_round)
    except _PointSkip:
        raise
    except Exception as exc:  # noqa: BLE001 - validator failures are record-only
        # Any fail-closed validator (markers preserved, EV keywords, draft
        # shape) failing means the human button must not be pressed.
        raise _PointSkip(
            "digest_revalidation_failed",
            {"errorType": type(exc).__name__, "error": str(exc)[:300]},
        ) from exc
    result = chain.approve_meeting_digest(
        team_id,
        meeting_round_id,
        closed_by=system_actor_for(policy),
        expected_digest_content_hash=str(draft.get("contentHash") or "").strip(),
    )
    closed = (
        result.get("meetingRound") if isinstance(result.get("meetingRound"), Mapping) else {}
    )
    return {
        "meetingRoundId": meeting_round_id,
        "resultStatus": str(result.get("status") or ""),
        "meetingRoundStatus": str(closed.get("status") or ""),
        "validationErrorCount": len(validation_errors),
    }


def _execute_candidate_selection(
    team_id: str,
    *,
    question_id: str,
    candidate_ids: list[str],
    selection_scope: Mapping[str, Any] | None,
    workflow_run_id: str,
    policy: AutoAdvancePolicyV2,
) -> dict[str, Any]:
    """Auto-record one bounded selection through the existing record path.

    Deterministic, auditable cost bound (autoSelectCandidates): the ids
    arrive in the generation digest's ``proposedCandidates`` order (the
    chain hook preserves it), so the rule is dedupe-keep-order then cap at
    the policy's ``candidateSelection.maxSelected`` (floor 2 keeps the
    review comparable-pair gate meaningful).  There is no scoring signal at
    this surface, so proposal order IS the rule; the rule, its source, the
    cap and whether truncation happened are all written into the audit
    detail below.
    """

    from core.research.workflow.contracts.automation_policy import (
        CANDIDATE_SELECTION_DEFAULT_MAX,
        CANDIDATE_SELECTION_MIN_MAX,
        CANDIDATE_SELECTION_RULE_DIGEST_ORDER,
    )
    from core.web.services.team_workflow import hypothesis_selection

    normalized_question = str(question_id or "").strip().upper()
    ordered: list[str] = []
    for item in candidate_ids:
        candidate_id = str(item or "").strip()
        if candidate_id and candidate_id not in ordered:
            ordered.append(candidate_id)
    if not normalized_question:
        raise _PointSkip("question_id_missing")
    raw_max = (policy.candidateSelection or {}).get("maxSelected")
    max_selected = (
        raw_max
        if isinstance(raw_max, int)
        and not isinstance(raw_max, bool)
        and raw_max >= CANDIDATE_SELECTION_MIN_MAX
        else CANDIDATE_SELECTION_DEFAULT_MAX
    )
    selected = ordered[:max_selected]
    if len(selected) < 2:
        raise _PointSkip(
            "candidate_set_too_small",
            {
                "candidateIds": ordered,
                "reason": (
                    "record_selection requires at least two candidates "
                    "(review needs a comparable pair)"
                ),
            },
        )
    payload = {
        **dict(selection_scope or {}),
        "questionId": normalized_question,
        "workflowRunId": str(workflow_run_id or "").strip(),
        "selectedCandidateIds": selected,
        "decidedBy": system_actor_for(policy),
    }
    result = hypothesis_selection.record_hypothesis_selection(
        team_id, payload, background=True
    )
    selection = (
        result.get("selection") if isinstance(result.get("selection"), Mapping) else {}
    )
    return {
        "status": str(result.get("status") or ""),
        "selectionId": str(selection.get("selectionId") or ""),
        "candidateIds": selected,
        "selectionRule": CANDIDATE_SELECTION_RULE_DIGEST_ORDER,
        "selectionSource": (
            "generation digest proposedCandidates order as passed by the "
            "chain selection tick"
        ),
        "maxSelected": max_selected,
        "totalCandidates": len(ordered),
        "truncated": len(ordered) > max_selected,
    }


def _execute_converge_question(
    team_id: str,
    *,
    question_id: str,
    hypothesis_round_id: str,
    policy: AutoAdvancePolicyV2,
) -> dict[str, Any]:
    """Auto-converge via the existing human-adjudication authority path.

    The call goes through ``record_human_adjudication``, which internally
    re-runs the claim-belief hard gate for accepted decisions (fail-closed,
    semantics untouched).  A blocked gate is a recorded skip, never a
    bypass.
    """

    from core.web.services.team_workflow.research_runtime import hypothesis_first_chain as chain

    normalized_question = str(question_id or "").strip().upper()
    if not normalized_question:
        raise _PointSkip("question_id_missing")
    rounds = chain._question_hypothesis_rounds(team_id, normalized_question)
    if not rounds:
        raise _PointSkip("no_hypothesis_round")
    latest = rounds[-1]
    round_id = str(hypothesis_round_id or "").strip() or str(
        latest.get("roundId") or ""
    ).strip()
    if not round_id or str(latest.get("roundId") or "") != round_id:
        raise _PointSkip("round_not_current", {"roundId": round_id or None})
    if str(latest.get("status") or "") != "closed":
        raise _PointSkip(
            "latest_round_not_closed", {"status": str(latest.get("status") or "")}
        )
    meta_review = (
        latest.get("metaReview")
        if isinstance(latest.get("metaReview"), Mapping)
        else {}
    )
    if meta_review.get("accepted") is not True:
        raise _PointSkip("meta_review_not_accepted")
    if chain._pending_handoff_count(team_id, normalized_question) != 0:
        raise _PointSkip("pending_handoffs")
    idempotency_key = (
        f"auto-advance:{policy.policyId}:"
        f"{policy.declaredContentHash[:12]}:{round_id}"
    )
    rationale = (
        f"auto-advance: policy {policy.policyId} v{policy.version} converged "
        "the question after every hard gate passed (calibrated, audited)"
    )
    try:
        result = chain.record_human_adjudication(
            team_id,
            question_id=normalized_question,
            hypothesis_round_id=round_id,
            decision="accepted",
            rationale=rationale,
            idempotency_key=idempotency_key,
            decided_by=system_actor_for(policy),
        )
    except chain.ClaimBeliefGateBlockedError as exc:
        raise _PointSkip(
            "claim_belief_gate_blocked",
            {
                "candidateId": exc.candidate_id,
                "blockers": list(exc.blockers),
                "gateReason": str(getattr(exc, "reason", "") or ""),
            },
        ) from exc
    adjudication = (
        result.get("adjudication")
        if isinstance(result.get("adjudication"), Mapping)
        else {}
    )
    return {
        "status": str(result.get("status") or ""),
        "adjudicationId": str(adjudication.get("adjudicationId") or ""),
        "hypothesisRoundId": round_id,
        "idempotencyKey": idempotency_key,
    }


# ---------------------------------------------------------------------------
# dispatch entry


def _capability_for(decision_point: str) -> str:
    return POLICY_SHADOW_CAPABILITY_FOR_POINT.get(str(decision_point or "").strip(), "")


def attempt_capability(
    *,
    decision_point: str,
    team_id: str,
    question_id: str = "",
    policy: AutoAdvancePolicyV2 | None = None,
    payload: Mapping[str, Any] | None = None,
    calibration_verdict: Mapping[str, Any] | None = None,
    meeting_round_id: str = "",
    candidate_ids: list[str] | None = None,
    selection_scope: Mapping[str, Any] | None = None,
    workflow_run_id: str = "",
    hypothesis_round_id: str = "",
) -> dict[str, Any] | None:
    """Attempt one gated real execution at a real decision point.

    Returns the audit record dict, or ``None`` when the fast path applies
    (no policy configured / unloadable / unknown point / reentrant call) —
    in those cases nothing executes and no audit is written.
    """

    point = str(decision_point or "").strip()
    capability = _capability_for(point)
    if point not in POLICY_SHADOW_CAPABILITY_FOR_POINT or not capability:
        _record_scene_event(
            "auto_advance_attempt_rejected",
            outcome="unsupported_decision_point",
            fields={"decisionPoint": point},
            level="warning",
        )
        return None
    loaded_policy, loaded_payload = _load_document_cached()
    active_policy = policy if policy is not None else loaded_policy
    active_payload = payload if payload is not None else loaded_payload
    if active_policy is None:
        # No usable configuration: stay byte-identical to the non-policy
        # chain (diagnostics only — the shadow loader already warned).
        return None

    normalized_team_id = str(team_id or "").strip()
    normalized_question = str(question_id or "").strip().upper()
    ref = {
        key: value
        for key, value in {
            "meetingRoundId": str(meeting_round_id or "").strip() or None,
            "hypothesisRoundId": str(hypothesis_round_id or "").strip() or None,
            "candidateIds": sorted(
                {str(item or "").strip() for item in candidate_ids or [] if str(item or "").strip()}
            )
            or None,
        }.items()
        if value is not None
    }

    verdict = calibration_verdict
    if verdict is None:
        verdict = default_calibration_gate_verdict(
            active_policy, team_id=normalized_team_id
        )
    ladder = evaluate_activation_ladder(
        active_policy, active_payload, calibration_verdict=verdict
    )
    actor = system_actor_for(active_policy)

    def _audit(decision: str, reason_code: str, detail: dict[str, Any] | None = None) -> dict[str, Any]:
        record = _build_audit_record(
            team_id=normalized_team_id,
            question_id=normalized_question,
            decision_point=point,
            capability=capability,
            policy=active_policy,
            ladder=ladder,
            decision=decision,
            reason_code=reason_code,
            ref=ref,
            detail=detail,
            actor=actor,
        )
        try:
            _append_audit_record(record)
        except Exception as exc:  # noqa: BLE001 - audit must never break the host
            _record_scene_event(
                "auto_advance_audit_write_failed",
                outcome="audit_write_failed",
                fields={"error": str(exc)},
                level="warning",
            )
        _record_scene_event(
            "auto_advance_attempt_recorded",
            outcome=decision,
            fields={
                "decisionPoint": point,
                "capability": capability,
                "decision": decision,
                "reasonCode": reason_code,
            },
        )
        return record

    if not ladder["allowed"]:
        return _audit("skipped", f"ladder_{ladder['firstFailure']}")
    if active_policy.capabilities.get(capability) is not True:
        return _audit("skipped", "capability_disabled")

    if point in NOT_IMPLEMENTED_DECISION_POINTS:
        # Capability is ON but no executor body exists (yet): never silent.
        return _audit(
            "not_implemented",
            "capability_not_implemented",
            {
                "note": (
                    "the capability switch is enabled but this decision point "
                    "has no executor body; the human stays in the loop"
                )
            },
        )
    if point not in EXECUTABLE_DECISION_POINTS:  # pragma: no cover - both sets cover the contract enum
        return _audit("skipped", "unsupported_decision_point")

    in_flight = getattr(_REENTRANCY, "capabilities", None)
    if in_flight is None:
        in_flight = set()
        _REENTRANCY.capabilities = in_flight
    if capability in in_flight:
        return _audit("skipped", "reentrant_attempt")
    in_flight.add(capability)
    try:
        try:
            if point == "meeting_close":
                detail = _execute_meeting_close(
                    normalized_team_id,
                    meeting_round_id=str(meeting_round_id or "").strip(),
                    policy=active_policy,
                )
            elif point == "candidate_selection":
                detail = _execute_candidate_selection(
                    normalized_team_id,
                    question_id=normalized_question,
                    candidate_ids=list(candidate_ids or []),
                    selection_scope=selection_scope,
                    workflow_run_id=workflow_run_id,
                    policy=active_policy,
                )
            else:  # converge_question
                detail = _execute_converge_question(
                    normalized_team_id,
                    question_id=normalized_question,
                    hypothesis_round_id=str(hypothesis_round_id or "").strip(),
                    policy=active_policy,
                )
        except _PointSkip as skip:
            return _audit("skipped", skip.code, skip.detail or None)
        except Exception as exc:  # noqa: BLE001 - classify, audit, never raise
            from core.web.services.team_workflow.research_runtime.hypothesis_first_chain import (
                StaleDigestError,
            )

            if isinstance(exc, StaleDigestError):
                return _audit(
                    "skipped",
                    "stale_digest",
                    {"expected": exc.expected, "actual": exc.actual},
                )
            return _audit(
                "failed",
                "execution_error",
                {"errorType": type(exc).__name__, "error": str(exc)[:500]},
            )
        return _audit("executed", "executed", detail)
    finally:
        in_flight.discard(capability)


def attempt_capability_quietly(**kwargs: Any) -> dict[str, Any] | None:
    """Chain-facing wrapper: never raises, degrades to a quiet scene event."""

    try:
        return attempt_capability(**kwargs)
    except Exception as exc:  # noqa: BLE001 - hooks must never break the chain
        _record_scene_event(
            "auto_advance_attempt_failed",
            outcome="attempt_failed",
            fields={
                "decisionPoint": str(kwargs.get("decision_point") or ""),
                "error": str(exc)[:500],
            },
            level="warning",
        )
        return None


__all__ = [
    "ACTIVATION_AUDIT_STORE_FILENAME",
    "AUTO_ADVANCE_DISABLED_ENV",
    "AutoAdvanceExecutionError",
    "EXECUTABLE_DECISION_POINTS",
    "NOT_IMPLEMENTED_DECISION_POINTS",
    "POLICY_ACTIVATION_AUDIT_SCHEMA_VERSION",
    "SYSTEM_ACTOR_PREFIX",
    "attempt_capability",
    "attempt_capability_quietly",
    "default_calibration_gate_verdict",
    "evaluate_activation_ladder",
    "kill_switch_enabled",
    "list_activation_audits",
    "load_active_policy_from_environment",
    "policy_activation_audit_store_path",
    "system_actor_for",
]
