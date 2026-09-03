"""Hypothesis-first orchestration chain (HF-4).

Owns the append-only chain ledger that wires the hypothesis-first event chain:

- selection -> first hypothesis-review meeting auto-open (round 1), with the
  room ``roundId`` <-> ``meetingRoundId`` two-way binding produced by
  ``meeting_runtime.open_hypothesis_review_meeting``;
- meeting closure -> ``request_new_evidence`` decisions carrying a valid
  ``searchEnvelope`` create stage-1 collection through the existing
  ``research_knowledge_collection_facade`` and dispatch its existing background
  search runner (idempotent per child run; the facade itself stays idempotent
  by scopeHash and no graph recursion happens here);
- child collection handoff -> parent run ``hypothesis_design`` readiness
  re-check (always outside any writer transaction) plus the next review
  meeting auto-open with a continuous lineage chain;
- ``chain_state`` read model consumed by the readiness evaluators for the
  ``hypothesis_first_meeting_open`` / ``knowledge_gap_pending`` /
  ``hypothesis_round_unconverged`` / ``template_baseline_missing`` blockers.

The chain ledger is a JSONL store next to the other ``research_workflow``
stores.  It never writes to the workflow ledger directly; parent runs are only
nudged through the command service with deterministic idempotency keys, so
replays after an interruption never duplicate attempts, meetings, or
collection requests.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from core.infrastructure import developer_sandbox
from core.research.workflow.contracts import ContractValidationError, scope_hash_for
from core.research.workflow.definition import CHALLENGE_CUP_WORKFLOW_ID

SCHEMA_VERSION = 1
HARD_ROUND_LIMIT = 3
COLLECTION_REQUEST_KIND = "collection_request"
REVIEW_ROUND_LINK_KIND = "review_round_link"
CANDIDATE_KIND = "hypothesis_candidate"
EXPLORATORY_DRAFT_KIND = "hypothesis_exploratory_draft"
EXPLORATORY_DRAFT_AUTHORITY = "exploratory_draft"
FORMAL_GROUNDED_CANDIDATE_AUTHORITY = "formal_grounded_candidate"
GENERATION_ATTEMPT_KIND = "generation_attempt"
REVIEW_DISPATCH_ATTEMPT_KIND = "review_dispatch_attempt"
HUMAN_ADJUDICATION_KIND = "human_adjudication"
QUESTION_RESET_AUDIT_KIND = "question_reset_audit"
SELECTION_COMMAND_OUTCOME_KIND = "selection_command_outcome"
REQUEST_EVIDENCE_DECISION = "request_new_evidence"
# Retrieval-circuit gap consumption: a live ``evidence_gap_unavailable``
# marker for the same goal stops new collection runs and lets the review
# converge with an explicit gap manifest instead of re-requesting forever.
EVIDENCE_GAP_STATUS = "evidence_gap_unavailable"
GAP_CONVERGENCE_KIND = "hypothesis_gap_convergence"
HYPOTHESIS_REVIEW_MEETING_TYPE = "hypothesis_review"
CANDIDATE_GENERATION_MEETING_TYPE = "hypothesis_candidate_generation"
# Server-owned scope mode that fences formal review: only this marker makes
# the hypothesis review executor run in FORMAL mode (provider-bound receipts).
HYPOTHESIS_REVIEW_FORMAL_MODE = "formal"
HYPOTHESIS_DESIGN_NODE_ID = "hypothesis_design"
_HYPOTHESIS_FIRST_WORKFLOW = "hypothesis_first"
_DEFAULT_BRANCH = "main"
_OPERATOR_AGENT_ID = "operator"
_SCOPE_FIELDS = ("program", "theme", "campaign", "question", "branch", "workflow")
_TERMINAL_RUN_STATUSES = frozenset({"succeeded", "failed", "cancelled", "archived"})
_ACTIVE_ATTEMPT_STATUSES = frozenset(
    {"starting", "dispatching", "running", "waiting_human"}
)
_ACTIVE_MEETING_STATUSES = frozenset({"open", "summarizing", "awaiting_approval"})
_ACTIVE_COLLECTION_STATUSES = frozenset(
    {"pending", "queued", "starting", "dispatching", "running", "collecting"}
)

# Bounded self-healing for failed collection child runs: when a child run
# reaches the ``failed`` terminal status, the chain schedules at most
# ``SOURCE_COLLECTION_AUTO_RETRY_MAX_ATTEMPTS`` automatic recover attempts
# (the same in-process implementation the recover endpoint uses) with
# exponential backoff, so a transient failure heals without a human.  Only
# ``failed`` is auto-retried: ``needs_continue`` stays fatal per the frozen
# retry taxonomy P0 contract (never auto-reconciled) and ``cancelled`` is a
# verdict.  Once the budget is spent the request keeps its failed recovery
# state (the human recover path is untouched) and one anomaly-inbox
# escalation item is emitted with the frozen ``collection_auto_retry_exhausted``
# taxonomy code (kind/severity derived by ``build_anomaly_inbox``).
SOURCE_COLLECTION_AUTO_RETRY_MAX_ATTEMPTS = 2
SOURCE_COLLECTION_AUTO_RETRY_INITIAL_DELAY_SECONDS = 30.0
SOURCE_COLLECTION_AUTO_RETRY_BACKOFF_FACTOR = 2.0
SOURCE_COLLECTION_AUTO_RETRY_MAX_DELAY_SECONDS = 120.0
COLLECTION_AUTO_RETRY_TAXONOMY_CODE = "collection_auto_retry_exhausted"

# Review-digest auto-approval (auto-advance, step zero): how long a
# hypothesis-review digest may sit in ``awaiting_approval`` before the
# maintenance sweep approves it.  Deliberately an independent pair from the
# anomaly-inbox digest TTL (that one raises a "waiting too long" alarm while
# this one acts on the wait), so the two thresholds never move together.
AUTO_APPROVE_REVIEW_DIGEST_CLOSED_BY = "system:auto-approve:review-digest"
# Operator decision (2026-09): the automatic approval wait shrinks from 10
# minutes to 3 so a stalled chain reaches its next review round sooner.
DEFAULT_AUTO_APPROVE_DIGEST_TTL_MS = 180_000
AUTO_APPROVE_DIGEST_TTL_MIN_MS = 60_000
_AUTO_APPROVE_DIGEST_TTL_OVERRIDE_ENV = "VIBELUTION_AUTO_APPROVE_DIGEST_TTL_MS"

# Zombie-handoff retry (auto-advance, before adjudication): how long a
# ``handoff_pending`` collection request whose run already completed must
# wait since its last retry attempt before the sweep re-runs the idempotent
# handoff.  Deliberately an independent threshold from the digest TTL above.
DEFAULT_AUTO_RETRY_HANDOFF_GRACE_MS = 60_000
AUTO_RETRY_HANDOFF_GRACE_MIN_MS = 10_000
_AUTO_RETRY_HANDOFF_GRACE_OVERRIDE_ENV = "VIBELUTION_AUTO_RETRY_HANDOFF_GRACE_MS"

# Missing-HypothesisRound auto-regeneration (auto-advance, after the digest
# approval): how long the newest review round must have been fully closed
# before the sweep accepts "no round landed" as a permanent miss instead of
# racing the synchronous fan-in generation a still-settling close is running.
# Deliberately an independent threshold from the digest TTL above.
DEFAULT_AUTO_REGEN_ROUND_GRACE_MS = 120_000
_AUTO_REGEN_ROUND_GRACE_OVERRIDE_ENV = "VIBELUTION_AUTO_REGEN_ROUND_GRACE_MS"

# Knowledge-handoff auto-accept (auto-advance, after formal-run creation):
# operator decision (2026-09) — the knowledge ingestion governance chain
# (source review accepted -> knowledge review approved -> official sync) is
# itself the human decision, so the residual ``knowledge_handoff`` click on
# the formal run is accepted automatically once that chain passed.  Every
# other human gate (protocol_freeze / smoke_gate / candidate_promotion) keeps
# its real human decision semantics and is never touched here.
KNOWLEDGE_HANDOFF_NODE_ID = "knowledge_handoff"
KNOWLEDGE_HANDOFF_TASK_KIND = f"gate:{KNOWLEDGE_HANDOFF_NODE_ID}"
KNOWLEDGE_PACKAGE_DRAFT_KIND = "knowledge_package_draft"
AUTO_KNOWLEDGE_HANDOFF_ACTOR_ID = "system:auto-advance:knowledge-handoff"
AUTO_KNOWLEDGE_HANDOFF_REASON = (
    "auto-advance: knowledge ingestion review chain passed (source review "
    "accepted + knowledge review approved); knowledge handoff accepted per "
    "operator automation policy"
)

# In-flight marker, one regeneration per (teamId, questionId) per process.
# The maintenance tick is serial, but one regeneration can spend the whole
# review-LLM budget (minutes) while the sweep interval is 30s, so any
# re-entrant or concurrent host must not double-trigger the same question.
_ROUND_REGEN_INFLIGHT: dict[tuple[str, str], object] = {}

PROJECT_ROOT = Path(__file__).resolve().parents[5]
_LOCK = threading.RLock()
_RECOVERY_LOCKS: dict[str, threading.Lock] = {}


def _record_scene_event(
    event_code: str,
    *,
    outcome: str,
    fields: dict[str, Any] | None = None,
    level: str = "info",
) -> None:
    """Best-effort observability event; diagnostics never break the chain."""
    from core.web.services.runtime_scene_service import (
        record_runtime_scene_event_quietly,
    )

    record_runtime_scene_event_quietly(
        "team_workflow_orchestration",
        "hypothesis_first_chain",
        event_code,
        level=level,
        outcome=outcome,
        fields=fields or {},
    )


# ---------------------------------------------------------------------------
# automation policy shadow evaluation (R1.4, advisory-only)


def _policy_shadow_scope(meeting_round: Mapping[str, Any]) -> dict[str, str]:
    """Best-effort scope snapshot for shadow records; never raises."""
    try:
        return _scope_envelope_for_meeting(meeting_round)
    except Exception:  # noqa: BLE001 - advisory record only
        return {}


def _pending_handoff_count(team_id: str, question_id: str) -> int:
    """Mirror the ``chain_state`` pending-handoff input (same records read)."""
    normalized = str(question_id or "").strip().upper()
    return sum(
        1
        for record in _collection_requests(_records(team_id))
        if str(record.get("questionId") or "").upper() == normalized
        and str(record.get("status") or "") != "handed_off"
    )


def _record_policy_shadow_decisions(
    team_id: str,
    meeting_round: Mapping[str, Any],
    build_evaluations: Callable[[], list[tuple[str, dict[str, Any], dict[str, Any]]]],
) -> None:
    """Record automation-policy shadow evaluations beside real decision points.

    R1.4 shadow core: evaluates what a configured shadow automation policy
    (``VIBELUTION_AUTO_ADVANCE_POLICY_PATH``) *would* decide if it were active
    at these decision points and appends human-comparison records to the
    dedicated shadow store.  Purely advisory — no execution branch reads these
    records, no command is emitted, and with no policy configured this is a
    no-op before any context I/O, so the executing chain stays byte-identical.
    """
    try:
        from core.web.services.team_workflow.research_runtime import (
            policy_shadow_evaluator,
        )

        policy = policy_shadow_evaluator.load_shadow_policy_from_environment()
        if policy is None:
            return
        scope = _policy_shadow_scope(meeting_round)
        question_id = str(meeting_round.get("question") or "").strip()
        recorded = 0
        for decision_point, context, actual_outcome in build_evaluations():
            policy_shadow_evaluator.record_policy_shadow_decision(
                team_id=team_id,
                question_id=question_id,
                policy=policy,
                decision_point=decision_point,
                context=context,
                actual_outcome=actual_outcome,
                scope=scope,
            )
            recorded += 1
        if recorded:
            _record_scene_event(
                "policy_shadow_evaluations_recorded",
                outcome="recorded",
                fields={"decisionPointCount": recorded},
            )
    except Exception as exc:  # noqa: BLE001 - shadow recording must never break the chain
        _record_scene_event(
            "policy_shadow_evaluation_failed",
            outcome="shadow_record_failed",
            fields={"error": str(exc)},
            level="warning",
        )


# ---------------------------------------------------------------------------
# automation policy active execution hooks (gated, audited, quiet)
#
# The executor only ever presses the chain's own idempotent buttons after its
# full safety ladder (kill switch, activation credential, calibration gate,
# drain mode, capability switch) passes; with no active policy configured
# every hook below is a no-op before any I/O, so these calls stay
# behavior-identical to the pre-executor chain.


def _auto_advance_selection_tick(
    team_id: str,
    meeting_round: Mapping[str, Any],
    candidates: list[dict[str, Any]],
) -> None:
    """Try autoSelectCandidates right after generation candidates register."""

    from core.web.services.team_workflow.research_runtime import (
        automation_policy_executor,
    )

    question_id = str(meeting_round.get("question") or "").strip()
    candidate_ids = [
        str(item.get("hypothesisId") or item.get("candidateId") or "").strip()
        for item in candidates
        if isinstance(item, Mapping)
    ]
    automation_policy_executor.attempt_capability_quietly(
        decision_point="candidate_selection",
        team_id=team_id,
        question_id=question_id,
        candidate_ids=candidate_ids,
        selection_scope=_question_scope_envelope(team_id, question_id),
    )


def _auto_advance_converge_tick(team_id: str, question_id: str) -> None:
    """Try autoConvergeQuestion after a review closure settles."""

    from core.web.services.team_workflow.research_runtime import (
        automation_policy_executor,
    )

    automation_policy_executor.attempt_capability_quietly(
        decision_point="converge_question",
        team_id=team_id,
        question_id=str(question_id or "").strip(),
    )


def _auto_advance_meeting_close_tick(team_id: str, meeting_round_id: str) -> None:
    """Try autoCloseMeetingRound after a summary draft lands (awaiting_approval)."""

    from core.web.services.team_workflow.research_runtime import (
        automation_policy_executor,
    )

    automation_policy_executor.attempt_capability_quietly(
        decision_point="meeting_close",
        team_id=team_id,
        meeting_round_id=str(meeting_round_id or "").strip(),
    )


class HypothesisFirstChainError(RuntimeError):
    """Base error for hypothesis-first chain orchestration."""


class StageOneCandidateScreeningError(HypothesisFirstChainError):
    """Formal R1 screening cannot produce two mechanism-distinct finalists."""

    code = "diversity_collapse"

    def __init__(self, message: str = "diversity_collapse", *, artifact_ref: str = ""):
        self.artifact_ref = str(artifact_ref or "")
        super().__init__(message)


class HypothesisFirstChainNotFoundError(HypothesisFirstChainError):
    """Raised when a chain record (collection request / link) does not exist."""


class StaleDigestError(HypothesisFirstChainError):
    """Raised when approve-digest receives a stale digest content hash."""

    def __init__(self, message: str, *, expected: str = "", actual: str = ""):
        super().__init__(message)
        self.code = "stale_digest"
        self.expected = expected
        self.actual = actual


class StateVersionConflictError(HypothesisFirstChainError):
    """Raised when a V2 command was issued against an obsolete snapshot."""

    code = "state_version_conflict"
    status_code = 409

    def __init__(self, *, expected: str, actual: str, snapshot_path: str = "") -> None:
        super().__init__(
            "流程状态已更新，请刷新当前题目后重新确认。"
        )
        self.expected = expected
        self.actual = actual
        self.snapshot_path = snapshot_path


class IdempotencyConflictError(HypothesisFirstChainError):
    """Raised when one V2 selection key is reused for different input."""

    code = "idempotency_conflict"
    status_code = 409

    def __init__(
        self,
        *,
        action_id: str,
        idempotency_key: str,
        expected_input_digest: str,
        actual_input_digest: str,
    ) -> None:
        super().__init__(
            "idempotencyKey 已绑定到不同的选择输入，不能复用。"
        )
        self.action_id = action_id
        self.idempotency_key = idempotency_key
        self.expected_input_digest = expected_input_digest
        self.actual_input_digest = actual_input_digest
        self.expected = expected_input_digest
        self.actual = actual_input_digest


class FormalCommandRejectedError(HypothesisFirstChainError):
    """A formal runtime command was rejected with a stable client-facing reason.

    Preserves the structured error contract already exposed by the formal
    runtime command route (``code`` plus optional readiness ``blockers``) so
    UI surfaces can render an actionable rejection instead of a flattened
    message string.
    """

    def __init__(
        self,
        message: str,
        *,
        code: str,
        status_code: int = 422,
        blockers: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.blockers = [dict(item) for item in blockers or []]


class StageOneContextBlockedError(FormalCommandRejectedError):
    """A stage-one R1 launch was rejected because its grounded context is blocked.

    Opening the meeting with a FORMAL authority and an empty evidence
    whitelist would strand every speaker turn on the REFS rules, so the
    launch fails before any meeting opens.  The blocker names the exact
    blocked context code (for example ``knowledge_package_has_no_evidence_claims``)
    so the UI can explain what is still missing.
    """

    def __init__(self, context: Mapping[str, Any]) -> None:
        blocked_code = str(context.get("code") or "stage_one_context_blocked")
        message = _STAGE_ONE_BLOCKED_MESSAGES.get(
            blocked_code, "第一阶段接地生成上下文未就绪"
        )
        super().__init__(
            message,
            code="stage_one_context_blocked",
            status_code=409,
            blockers=[
                {
                    "code": blocked_code,
                    "message": message,
                }
            ],
        )
        self.blockedContextCode = blocked_code


_STAGE_ONE_BLOCKED_MESSAGES = {
    "workflow_run_not_found": "第一阶段运行不存在或已不可读，无法开启接地生成",
    "workflow_snapshot_invalid": "第一阶段运行的冻结输入不可读，无法开启接地生成",
    "stage_one_policy_invalid": "第一阶段完成策略不是当前跟踪版本，无法开启接地生成",
    "workflow_scope_mismatch": "运行不属于当前团队或赛题，无法开启接地生成",
    "knowledge_package_has_no_evidence_claims": (
        "知识包没有可引用的证据主张；请先补齐并批准证据后再开启接地生成"
    ),
}


class ClaimBeliefGateBlockedError(FormalCommandRejectedError):
    """A formal selection authority was blocked by the claim belief hard gate.

    R2.2 fail-closed semantics: a hypothesis whose core claims are
    ``contradicted``/``disputed`` — or whose claim data is missing or
    unreadable, so the five-state belief table cannot be evaluated — must
    never be advanced onto the formal path.  The structured ``blockers`` carry
    ``claimId`` and ``beliefState`` so the operator can repair the claim
    ledger (supersede/retract, evidence re-review) and retry the same
    decision; nothing is silently waived.
    """

    def __init__(
        self,
        message: str,
        *,
        stage: str,
        question_id: str,
        candidate_id: str = "",
        blockers: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(
            message,
            code="claim_belief_gate_blocked",
            status_code=422,
            blockers=blockers,
        )
        self.stage = stage
        self.question_id = question_id
        self.candidate_id = candidate_id


def _formal_command_rejection(exc: Exception) -> HypothesisFirstChainError:
    """Convert a formal command-service rejection into a structured error.

    The V2 chain envelope must not flatten typed runtime rejections into a
    bare message: readiness blockers and stable error codes are part of the
    HTTP error contract shared with the formal runtime command route.
    """
    from core.research.workflow.contracts import ReadinessBlocker
    from core.research.workflow.ledger import (
        CommandNotAllowedError as LedgerCommandNotAllowedError,
        IdempotencyConflictError as LedgerIdempotencyConflictError,
        RunVersionConflictError as LedgerRunVersionConflictError,
    )

    from .command_service import (
        CommandForbiddenError,
        NodeNotReadyError,
        WorkflowCommandError,
    )
    from .service import ResearchWorkflowError

    if isinstance(exc, ResearchWorkflowError):
        # Run-creation contract rejections (catalog_run_authorization_required,
        # catalog_run_authorization_replay_mismatch, idempotency_conflict, ...)
        # keep their stable code on the HTTP error contract instead of a 500.
        return FormalCommandRejectedError(
            str(exc) or str(getattr(exc, "code", "") or "run_creation_rejected"),
            code=str(getattr(exc, "code", "") or "run_creation_rejected"),
            status_code=409 if getattr(exc, "code", "") == "idempotency_conflict" else 422,
        )
    if isinstance(exc, NodeNotReadyError):
        readiness = getattr(exc, "readiness", None)
        blockers: list[dict[str, Any]] = []
        for blocker in getattr(readiness, "blockers", ()) or ():
            if isinstance(blocker, ReadinessBlocker):
                blockers.append(blocker.to_dict())
            elif isinstance(blocker, Mapping):
                blockers.append(dict(blocker))
            else:
                blockers.append({"detail": str(blocker)})
        return FormalCommandRejectedError(
            str(exc) or "node_not_ready",
            code="node_not_ready",
            status_code=412,
            blockers=blockers,
        )
    if isinstance(exc, LedgerIdempotencyConflictError):
        return FormalCommandRejectedError(
            str(exc) or "idempotency_conflict",
            code="idempotency_conflict",
            status_code=409,
        )
    if isinstance(exc, LedgerRunVersionConflictError):
        return FormalCommandRejectedError(
            str(exc),
            code="run_version_conflict",
            status_code=409,
        )
    if isinstance(exc, CommandForbiddenError):
        return FormalCommandRejectedError(
            str(exc) or "command_forbidden",
            code="command_forbidden",
            status_code=403,
        )
    if isinstance(exc, LedgerCommandNotAllowedError):
        return FormalCommandRejectedError(
            str(exc) or "command_not_allowed",
            code="command_not_allowed",
            status_code=409,
        )
    if isinstance(exc, WorkflowCommandError):
        return FormalCommandRejectedError(
            str(exc) or "command_rejected",
            code="command_rejected",
        )
    return HypothesisFirstChainError(str(exc))


# ---------------------------------------------------------------------------
# storage primitives (same discipline as hypothesis_selection)


def _project_root() -> Path:
    return Path(PROJECT_ROOT)


def _safe_team_id(team_id: str) -> str:
    from core.web.services.team_workflow.storage_ids import safe_storage_component

    return safe_storage_component(team_id, fallback="team")


def _question_requested_evidence(
    team_id: str,
    question_id: str,
    *,
    meeting_round_ids: set[str] | None = None,
) -> bool:
    """True when this question's persisted review decisions asked for evidence.

    A ``request_new_evidence`` decision (valid or not) proves the discussion
    wanted collection, so the collection-ready waiver must not apply.  Scope
    by question through the decision's meeting round: decision records carry
    no question field, and a team-wide scan would let one question's request
    block every other question's waiver (fatal for the 125-question batch).
    """
    from core.web.services.team_workflow import meeting_rounds

    normalized_question = str(question_id or "").strip().upper()
    if not normalized_question:
        return False
    scoped_meeting_ids = (
        {
            str(meeting_round_id or "").strip()
            for meeting_round_id in meeting_round_ids
            if str(meeting_round_id or "").strip()
        }
        if meeting_round_ids is not None
        else None
    )
    try:
        question_by_meeting = {
            str(meeting.get("meetingRoundId") or ""): str(
                meeting.get("question") or ""
            ).upper()
            for meeting in meeting_rounds.list_meeting_rounds(team_id)["meetings"]
        }
    except Exception:
        # Unreadable meetings fail closed: cannot prove the request belongs to
        # another question, so do not waive.
        return True
    root = developer_sandbox.seeded_sandbox_workspace_path(
        _project_root(),
        "teams",
        _safe_team_id(team_id),
    )
    decisions_path = root / "research_workflow" / "decision_records.jsonl"
    if not decisions_path.exists():
        return False
    try:
        records = _read_jsonl(decisions_path)
    except OSError:
        # Unreadable decision store fails closed, matching the unreadable
        # meetings branch above: an existing evidence request cannot be
        # disproven, so the waiver must not apply.
        return True
    return any(
        str(record.get("decision") or "") == "request_new_evidence"
        and (
            scoped_meeting_ids is None
            or str(record.get("meetingRoundId") or "") in scoped_meeting_ids
        )
        and question_by_meeting.get(
            str(record.get("meetingRoundId") or ""), normalized_question
        )
        == normalized_question
        for record in records
    )


def _storage_path(team_id: str) -> Path:
    root = developer_sandbox.seeded_sandbox_workspace_path(
        _project_root(),
        "teams",
        _safe_team_id(team_id),
    )
    return root / "research_workflow" / "hypothesis_first_chain.jsonl"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _stable_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def selection_version_for(
    *,
    question_id: str,
    selected_candidate_ids: Any,
    previous_selection_id: str = "",
    reset_id: str = "origin",
    scope_hash: str = "",
    workflow_run_id: str = "",
) -> str:
    """Return the order-independent identity of one submitted selection.

    Candidate ordering is presentation detail: the selection version is bound
    to the normalized candidate set, question, previous selection and reset
    boundary.  The durable scope is supplied by the caller, so the same
    helper can be used by command execution, review links and the read model.
    """

    normalized_candidates = sorted(
        _normalized_str_list(selected_candidate_ids)
    )
    return "hf2-selection:" + _stable_hash(
        {
            "questionId": str(question_id or "").strip().upper(),
            "selectedCandidateIds": normalized_candidates,
            "previousSelectionId": str(previous_selection_id or "").strip(),
            "resetId": str(reset_id or "origin").strip() or "origin",
            "scopeHash": str(scope_hash or "").strip(),
            "workflowRunId": str(workflow_run_id or "").strip(),
        }
    )[:24]


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    from core.web.services.team_workflow.storage_durability import read_jsonl_tolerant

    return read_jsonl_tolerant(path)


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    from core.web.services.team_workflow.storage_durability import append_jsonl_locked

    append_jsonl_locked(path, record)


def _latest_by_id(
    records: list[dict[str, Any]], field: str, record_id: str
) -> dict[str, Any] | None:
    matched = [record for record in records if str(record.get(field) or "") == record_id]
    return matched[-1] if matched else None


def _normalized_str_list(value: Any) -> list[str]:
    return [str(item or "").strip() for item in list(value or []) if str(item or "").strip()]


def _rewrite_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    """Replace one JSONL ledger atomically after a scoped reset has been checked."""
    from .atomic_fs import atomic_write_text

    payload = "".join(
        json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        for record in records
    )
    atomic_write_text(path, payload)


def _latest_records(records: list[dict[str, Any]], field: str) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for record in records:
        record_id = str(record.get(field) or "").strip()
        if record_id:
            latest[record_id] = record
    return latest


def _question_reset_snapshot(team_id: str, question_id: str) -> dict[str, Any]:
    """Read the exact question-owned artifacts before a guarded reset.

    The question is the ownership boundary. Meeting digests, decisions and
    hypothesis rounds do not always carry ``questionId`` themselves, so they
    are reached only through this question's meeting ids.  This prevents one
    question's cleanup from sweeping unrelated team research.
    """
    from core.web.services.team_workflow import (
        hypothesis_rounds,
        hypothesis_selection,
        meeting_rounds,
    )

    normalized_question_id = str(question_id or "").strip().upper()
    chain_records = _read_jsonl(_storage_path(team_id))
    selection_records = hypothesis_selection._read_jsonl(hypothesis_selection._storage_path(team_id))
    meeting_records = meeting_rounds._read_jsonl(meeting_rounds._rounds_path(team_id))
    digest_records = meeting_rounds._read_jsonl(meeting_rounds._digests_path(team_id))
    decision_records = meeting_rounds._read_jsonl(meeting_rounds._decisions_path(team_id))
    hypothesis_round_records = hypothesis_rounds._read_jsonl(
        hypothesis_rounds._storage_path(team_id)
    )

    meeting_latest = _latest_records(meeting_records, "meetingRoundId")
    chain_links = [
        record
        for record in chain_records
        if str(record.get("recordKind") or "") == REVIEW_ROUND_LINK_KIND
        and str(record.get("questionId") or "").strip().upper() == normalized_question_id
    ]
    linked_meeting_ids = {
        str(record.get("meetingRoundId") or "").strip()
        for record in chain_links
        if str(record.get("meetingRoundId") or "").strip()
    }
    target_meeting_ids = {
        meeting_id
        for meeting_id, meeting in meeting_latest.items()
        if str(meeting.get("question") or "").strip().upper() == normalized_question_id
    } | linked_meeting_ids
    target_meetings = {
        meeting_id: meeting_latest[meeting_id]
        for meeting_id in target_meeting_ids
        if meeting_id in meeting_latest
    }
    target_selection_ids = {
        str(record.get("selectionId") or "").strip()
        for record in selection_records
        if str(record.get("questionId") or "").strip().upper() == normalized_question_id
        and str(record.get("selectionId") or "").strip()
    }
    target_rounds = {
        round_id: record
        for round_id, record in _latest_records(hypothesis_round_records, "roundId").items()
        if str(record.get("question") or "").strip().upper() == normalized_question_id
        or any(
            isinstance(ref, Mapping)
            and str(ref.get("kind") or "") == "meeting_round"
            and str(ref.get("id") or "").strip() in target_meeting_ids
            for ref in list(record.get("meetingRefs") or [])
        )
    }

    target_chain_records = [
        record
        for record in chain_records
        if str(record.get("recordKind") or "") != QUESTION_RESET_AUDIT_KIND
        and str(record.get("questionId") or "").strip().upper() == normalized_question_id
    ]
    candidate_ids = {
        str(record.get("candidateId") or "").strip()
        for record in target_chain_records
        if str(record.get("recordKind") or "") == CANDIDATE_KIND
        and str(record.get("candidateId") or "").strip()
    }
    target_collection_requests = [
        record
        for record in _collection_requests(chain_records)
        if str(record.get("questionId") or "").strip().upper() == normalized_question_id
    ]
    request_ids = {
        str(record.get("requestId") or "").strip()
        for record in target_collection_requests
        if str(record.get("requestId") or "").strip()
    }
    collection_run_ids = {
        str(record.get("collectionRunId") or "").strip()
        for record in target_collection_requests
        if str(record.get("collectionRunId") or "").strip()
    }
    impact = {
        "candidateCount": len(candidate_ids),
        "selectionCount": len(target_selection_ids),
        "meetingCount": len(target_meetings),
        "hypothesisRoundCount": len(target_rounds),
        "collectionRequestCount": len(request_ids),
        "collectionRunCount": 0,
    }
    active_meetings = [
        meeting_id
        for meeting_id, meeting in target_meetings.items()
        if str(meeting.get("status") or "").strip().lower() in _ACTIVE_MEETING_STATUSES
    ]
    active_requests = [
        request_id
        for request_id, request in _latest_records(
            [
                record
                for record in target_chain_records
                if str(record.get("recordKind") or "") == COLLECTION_REQUEST_KIND
            ],
            "requestId",
        ).items()
        # A legacy pending request with no child run cannot represent work that
        # can still mutate data. Keep the guard for every linked active request,
        # while allowing that unlinked residue to be reset.
        if str(request.get("status") or "").strip().lower() in _ACTIVE_COLLECTION_STATUSES
        and str(request.get("collectionRunId") or "").strip()
    ]
    return {
        "questionId": normalized_question_id,
        "chainRecords": chain_records,
        "selectionRecords": selection_records,
        "meetingRecords": meeting_records,
        "digestRecords": digest_records,
        "decisionRecords": decision_records,
        "hypothesisRoundRecords": hypothesis_round_records,
        "targetMeetingIds": target_meeting_ids,
        "targetRoundIds": set(target_rounds),
        "collectionRunIds": collection_run_ids,
        "impact": impact,
        "activeMeetingIds": active_meetings,
        "activeRequestIds": active_requests,
    }


def preview_question_reset(team_id: str, question_id: str) -> dict[str, Any]:
    """Return a non-mutating, question-scoped reset preview for the confirm UI."""
    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    snapshot = _question_reset_snapshot(normalized_team_id, question_id)
    from core.web.services.team_workflow.source_collection import (
        runs as source_collection_runs,
    )

    active_meetings = list(snapshot["activeMeetingIds"])
    active_requests = list(snapshot["activeRequestIds"])
    collection_preview = source_collection_runs.preview_source_collection_runs_reset(
        normalized_team_id,
        set(snapshot["collectionRunIds"]),
    )
    snapshot["impact"]["collectionRunCount"] = int(collection_preview.get("runCount") or 0)
    if active_meetings:
        blocking_reason = "本题仍有进行中的讨论，请先结束或停止讨论后再重置。"
    elif active_requests:
        blocking_reason = "本题的资料搜集仍在进行，请等待结束或先停止任务。"
    elif not collection_preview.get("canReset"):
        blocking_reason = str(collection_preview.get("blockingReason") or "本题资料运行暂不能重置。")
    else:
        blocking_reason = ""
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "questionId": snapshot["questionId"],
        "canReset": not blocking_reason,
        "blockingReason": blocking_reason,
        "impact": snapshot["impact"],
    }


def reset_question_chain(
    team_id: str,
    question_id: str,
    *,
    confirmation_question_id: str,
) -> dict[str, Any]:
    """Delete only one question's completed hypothesis-first working artifacts.

    The title/question archive and all other questions are intentionally outside
    this operation.  A successful reset leaves a compact audit event, then
    directs the product back to candidate generation.
    """
    from core.web.services.team_service import assert_team_exists
    from core.web.services.team_workflow import (
        hypothesis_rounds,
        hypothesis_selection,
        meeting_rounds,
    )
    from core.web.services.team_workflow.source_collection import (
        runs as source_collection_runs,
    )

    normalized_team_id = assert_team_exists(team_id)
    normalized_question_id = str(question_id or "").strip().upper()
    if not normalized_question_id:
        raise HypothesisFirstChainError("Question id is required.")
    if str(confirmation_question_id or "").strip().upper() != normalized_question_id:
        raise HypothesisFirstChainError("请输入当前题号后再确认重置。")

    with _LOCK, hypothesis_selection._LOCK, meeting_rounds._LOCK, hypothesis_rounds._LOCK:
        snapshot = _question_reset_snapshot(normalized_team_id, normalized_question_id)
        if snapshot["activeMeetingIds"]:
            raise HypothesisFirstChainError("本题仍有进行中的讨论，请先结束或停止讨论后再重置。")
        if snapshot["activeRequestIds"]:
            raise HypothesisFirstChainError("本题的资料搜集仍在进行，请等待结束或先停止任务。")

        source_preview = source_collection_runs.preview_source_collection_runs_reset(
            normalized_team_id,
            set(snapshot["collectionRunIds"]),
        )
        if not source_preview.get("canReset"):
            raise HypothesisFirstChainError(
                str(source_preview.get("blockingReason") or "本题资料运行暂不能重置。")
            )
        snapshot["impact"]["collectionRunCount"] = int(source_preview.get("runCount") or 0)
        target_meeting_ids = set(snapshot["targetMeetingIds"])
        target_round_ids = set(snapshot["targetRoundIds"])
        chain_records = [
            record
            for record in snapshot["chainRecords"]
            if not (
                str(record.get("recordKind") or "") != QUESTION_RESET_AUDIT_KIND
                and str(record.get("questionId") or "").strip().upper() == normalized_question_id
            )
        ]
        audit_record = {
            "schemaVersion": SCHEMA_VERSION,
            "recordKind": QUESTION_RESET_AUDIT_KIND,
            "resetId": f"hf-reset-{_stable_hash({'teamId': normalized_team_id, 'questionId': normalized_question_id, 'at': _utc_now()})[:16]}",
            "questionId": normalized_question_id,
            "resetAt": _utc_now(),
            "removed": dict(snapshot["impact"]),
        }
        chain_records.append(audit_record)
        selection_records = [
            record
            for record in snapshot["selectionRecords"]
            if str(record.get("questionId") or "").strip().upper() != normalized_question_id
        ]
        meeting_records = [
            record
            for record in snapshot["meetingRecords"]
            if str(record.get("meetingRoundId") or "").strip() not in target_meeting_ids
        ]
        digest_records = [
            record
            for record in snapshot["digestRecords"]
            if str(record.get("meetingRoundId") or "").strip() not in target_meeting_ids
        ]
        decision_records = [
            record
            for record in snapshot["decisionRecords"]
            if str(record.get("meetingRoundId") or "").strip() not in target_meeting_ids
        ]
        hypothesis_round_records = [
            record
            for record in snapshot["hypothesisRoundRecords"]
            if str(record.get("roundId") or "").strip() not in target_round_ids
        ]
        writes = (
            (_storage_path(normalized_team_id), chain_records),
            (hypothesis_selection._storage_path(normalized_team_id), selection_records),
            (meeting_rounds._rounds_path(normalized_team_id), meeting_records),
            (meeting_rounds._digests_path(normalized_team_id), digest_records),
            (meeting_rounds._decisions_path(normalized_team_id), decision_records),
            (hypothesis_rounds._storage_path(normalized_team_id), hypothesis_round_records),
        )
        originals = {
            path: path.read_text(encoding="utf-8") if path.exists() else ""
            for path, _records_to_write in writes
        }
        try:
            for path, records_to_write in writes:
                _rewrite_jsonl(path, records_to_write)
            # Source runs are the final destructive step.  A ledger write
            # failure must leave the collection data untouched; a late source
            # guard must restore these ledgers before it is surfaced.
            source_collection_runs.reset_source_collection_runs_for_question(
                normalized_team_id,
                set(snapshot["collectionRunIds"]),
            )
        except Exception as exc:
            for path, original in originals.items():
                try:
                    from .atomic_fs import atomic_write_text

                    atomic_write_text(path, original)
                except OSError:
                    pass
            if isinstance(exc, OSError):
                raise HypothesisFirstChainError("本题运行重置失败，原数据已尝试恢复。") from exc
            raise

    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "questionId": normalized_question_id,
        "removed": dict(snapshot["impact"]),
        "nextAction": {"targetNodeId": "hf_generation", "label": "生成候选假说"},
    }


# ---------------------------------------------------------------------------
# chain ledger reads


def _records(team_id: str) -> list[dict[str, Any]]:
    with _LOCK:
        return _read_jsonl(_storage_path(team_id))


@contextmanager
def hypothesis_first_scope_lock(team_id: str, question_id: str):
    """Serialize one question command across all V2 command workers.

    The V2 state is a coarse cross-surface CAS.  The JSONL services already
    serialize their individual appends across processes, but that is not wide
    enough for the command's read/re-authorize/side-effect sequence: two
    backend workers could both validate the same state version before either
    owning mutation became visible.  The separate scope lock closes that
    window for every V2 command, including the delivery retry whose expensive
    orchestration must happen after the claim and before the terminal event.

    This intentionally uses a lock file distinct from the chain JSONL lock.
    Command handlers may append to that JSONL while this scope is held, and a
    nested acquisition of the same OS file lock is not portable on Windows.
    Late workflow/runtime completions still carry their own meeting/request
    identity and are validated by the owning service.
    """

    from core.web.services.team_workflow import (
        hypothesis_rounds,
        hypothesis_selection,
        meeting_rounds,
    )
    from core.web.services.team_workflow.storage_durability import (
        inter_process_lock,
    )

    # Keep this separate from ``hypothesis_first_chain.jsonl.lock``: command
    # handlers append through ``append_jsonl_locked`` while the scope is held.
    scope_key = _stable_hash({"questionId": str(question_id or "").strip().upper()})[:24]
    scope_lock = _storage_path(team_id).with_name(
        f"hypothesis_first_v2_scope_{scope_key}"
    )
    with (
        inter_process_lock(scope_lock, timeout_s=120.0),
        _LOCK,
        hypothesis_selection._LOCK,
        meeting_rounds._LOCK,
        hypothesis_rounds._LOCK,
    ):
        yield


def assert_expected_state_version(
    team_id: str,
    question_id: str,
    expected_state_version: str,
    *,
    workflow_run_id: str = "",
) -> dict[str, Any]:
    """Re-read V2 inside the caller's scope lock and enforce coarse CAS."""

    expected = str(expected_state_version or "").strip()
    if not expected:
        raise ContractValidationError("expectedStateVersion is required")
    from .hypothesis_first_state_v2 import project_hypothesis_first_state_v2

    normalized_workflow_run_id = str(workflow_run_id or "").strip()
    snapshot = project_hypothesis_first_state_v2(
        team_id,
        question_id,
        workflow_run_id=normalized_workflow_run_id,
    )
    actual = str(snapshot.get("stateVersion") or "").strip()
    if not actual or actual != expected:
        raise StateVersionConflictError(
            expected=expected,
            actual=actual,
            snapshot_path=(
                "/teams/"
                + str(team_id)
                + "/workflow-orchestration/hypothesis-first/chain/state-v2?questionId="
                + str(question_id)
                + (
                    "&runId=" + normalized_workflow_run_id
                    if normalized_workflow_run_id
                    else ""
                )
            ),
        )
    return snapshot


def _command_question_id(
    team_id: str,
    command: str,
    payload: Mapping[str, Any],
    question_id: str = "",
) -> str:
    """Resolve the question fence without trusting client labels."""

    explicit = str(question_id or payload.get("questionId") or "").strip().upper()
    if explicit:
        return explicit
    from core.web.services.team_workflow import meeting_rounds

    meeting_id = str(payload.get("meetingRoundId") or "").strip()
    if meeting_id:
        meeting = meeting_rounds.get_meeting_round(team_id, meeting_id)["meetingRound"]
        resolved = str(meeting.get("question") or "").strip().upper()
        if resolved:
            return resolved
    request_id = str(payload.get("requestId") or "").strip()
    if request_id:
        request = _latest_by_id(
            _collection_requests(_records(team_id)), "requestId", request_id
        )
        resolved = str((request or {}).get("questionId") or "").strip().upper()
        if resolved:
            return resolved
    selection_id = str(payload.get("selectionId") or "").strip()
    if selection_id:
        from core.web.services.team_workflow import hypothesis_selection

        selection = hypothesis_selection.get_hypothesis_selection(team_id, selection_id)[
            "selection"
        ]
        resolved = str(selection.get("questionId") or "").strip().upper()
        if resolved:
            return resolved
    raise ContractValidationError(
        f"{command} requires a questionId or a question-scoped identity"
    )


def _find_allowed_command(
    snapshot: Mapping[str, Any],
    *,
    action_id: str,
    command: str,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Re-authorize a command against the freshly projected action list."""

    for action in list(snapshot.get("allowedActions") or []):
        if not isinstance(action, Mapping) or action.get("kind") != "command":
            continue
        if str(action.get("actionId") or "") != action_id:
            continue
        if str(action.get("command") or "") != command:
            continue
        if dict(action.get("payload") or {}) != dict(payload):
            continue
        if action.get("enabled") is not True:
            break
        return dict(action)
    raise HypothesisFirstChainError(
        f"command is no longer allowed for the current hypothesis-first state: {command}"
    )


def _current_reset_id(
    team_id: str,
    question_id: str,
    *,
    records: list[dict[str, Any]] | None = None,
) -> str:
    """Read the current reset fence without broadening the question scope."""

    normalized_question_id = str(question_id or "").strip().upper()
    source = records if records is not None else _records(team_id)
    reset_id = "origin"
    for record in source:
        if (
            str(record.get("recordKind") or "") == QUESTION_RESET_AUDIT_KIND
            and str(record.get("questionId") or "").strip().upper()
            == normalized_question_id
        ):
            reset_id = str(record.get("resetId") or "origin").strip() or "origin"
    return reset_id


def _selection_command_input_digest(
    *,
    action_id: str,
    question_id: str,
    payload: Mapping[str, Any],
    candidate_ids: Any,
    workflow_run_id: str = "",
) -> str:
    """Hash semantic selection input while ignoring presentation ordering."""

    return _stable_hash(
        {
            "actionId": str(action_id or "").strip(),
            "command": "record_selection",
            "questionId": str(question_id or "").strip().upper(),
            "workflowRunId": str(workflow_run_id or "").strip(),
            "payload": dict(payload),
            "candidateIds": sorted(_normalized_str_list(candidate_ids)),
        }
    )


def _selection_command_action_id(action_id: str, command: str) -> str:
    """Resolve the only command whose replay must precede V2 CAS."""

    if command:
        return command
    normalized_action_id = str(action_id or "").strip()
    if normalized_action_id == "record-selection" or normalized_action_id.startswith(
        "record-selection:"
    ):
        return "record_selection"
    # The rejected-adjudication recovery offer re-enters record_selection under
    # a different actionId prefix.  The V2 wire request carries no ``command``
    # field (StrictWireModel), so without this mapping the pre-CAS selection
    # fence is skipped and the execution block reads unbound selection locals.
    if normalized_action_id == "reselect-after-rejection" or (
        normalized_action_id.startswith("reselect-after-rejection:")
    ):
        return "record_selection"
    return ""


def _screen_stage_one_selection_candidates(
    *,
    team_id: str,
    question_id: str,
    workflow_run_id: str,
    selected_candidate_ids: list[str],
    scope: Mapping[str, Any],
    screened_by: str,
) -> dict[str, Any]:
    """Apply R1 screening only when the selected set is formally grounded."""

    normalized_run_id = str(workflow_run_id or "").strip()
    if not normalized_run_id:
        return {"candidateIds": list(selected_candidate_ids), "artifactRef": ""}
    records = list_hypothesis_candidates(
        team_id,
        question_id=question_id,
        workflow_run_id=normalized_run_id,
    )["candidates"]
    by_id = {
        str(item.get("candidateId") or "").strip(): dict(item)
        for item in records
        if isinstance(item, Mapping) and str(item.get("candidateId") or "").strip()
    }
    selected = [by_id[item] for item in selected_candidate_ids if item in by_id]
    formal = [
        item
        for item in selected
        if str(item.get("candidateAuthority") or "").strip().lower()
        == FORMAL_GROUNDED_CANDIDATE_AUTHORITY
    ]
    if not formal:
        return {"candidateIds": list(selected_candidate_ids), "artifactRef": ""}
    if len(selected) != len(selected_candidate_ids) or len(formal) != len(selected):
        raise StageOneCandidateScreeningError(
            "diversity_collapse: stage-one selection mixes missing or non-formal candidates"
        )
    from .candidate_screening import (
        build_screening_drafts_from_candidates,
        screen_candidate_drafts,
    )
    from .candidate_screening_artifact_writer import (
        record_candidate_screening_artifact,
    )

    drafts = build_screening_drafts_from_candidates(formal)
    created_at = max(
        (str(item.get("createdAt") or "").strip() for item in formal),
        default="",
    ) or "1970-01-01T00:00:00Z"
    screening_id = "candidate-screening-" + _stable_hash(
        {
            "teamId": team_id,
            "workflowRunId": normalized_run_id,
            "questionId": question_id,
            "candidateIds": sorted(selected_candidate_ids),
        }
    )[:20]
    artifact = screen_candidate_drafts(
        screening_id=screening_id,
        question_id=question_id,
        program=str(scope.get("program") or ""),
        theme=str(scope.get("theme") or ""),
        campaign=str(scope.get("campaign") or ""),
        question=str(scope.get("question") or question_id),
        branch=str(scope.get("branch") or ""),
        workflow=str(scope.get("workflow") or ""),
        agent_id=str(scope.get("agentId") or ""),
        mode=str(scope.get("mode") or ""),
        drafts=drafts,
        screened_by=screened_by,
        created_at=created_at,
    )
    persisted = record_candidate_screening_artifact(
        team_id=team_id,
        workflow_run_id=normalized_run_id,
        artifact=artifact,
    )
    finalist_ids = list(artifact.pairwiseCandidateIds)
    mechanisms = {
        artifact.candidate_by_id(candidate_id).axisProfile.mechanism
        for candidate_id in finalist_ids
        if artifact.candidate_by_id(candidate_id) is not None
    }
    if len(finalist_ids) < 2 or len(mechanisms) < 2:
        raise StageOneCandidateScreeningError(
            "diversity_collapse: fewer than two mechanism-distinct finalists survived",
            artifact_ref=persisted["canonicalRef"],
        )
    return {
        "candidateIds": finalist_ids,
        "artifactRef": persisted["canonicalRef"],
    }


def _selection_command_outcome(
    team_id: str,
    *,
    question_id: str,
    action_id: str,
    idempotency_key: str,
    reset_id: str,
    workflow_run_id: str = "",
    records: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Find a durable selection outcome in the existing chain ledger."""

    normalized_team_id = str(team_id or "").strip()
    normalized_question_id = str(question_id or "").strip().upper()
    normalized_reset_id = str(reset_id or "origin").strip() or "origin"
    normalized_workflow_run_id = str(workflow_run_id or "").strip()
    source = records if records is not None else _records(team_id)
    for record in reversed(source):
        if str(record.get("recordKind") or "") != SELECTION_COMMAND_OUTCOME_KIND:
            continue
        if str(record.get("teamId") or "").strip() != normalized_team_id:
            continue
        if str(record.get("questionId") or "").strip().upper() != normalized_question_id:
            continue
        if str(record.get("actionId") or "").strip() != str(action_id or "").strip():
            continue
        if str(record.get("idempotencyKey") or "").strip() != str(idempotency_key or "").strip():
            continue
        stored_reset_id = str(record.get("resetId") or "").strip()
        if stored_reset_id != normalized_reset_id:
            continue
        if (
            normalized_workflow_run_id
            and str(record.get("workflowRunId") or "").strip()
            != normalized_workflow_run_id
        ):
            continue
        return record
    return None


def _selection_command_outcome_for_version(
    team_id: str,
    *,
    question_id: str,
    action_id: str,
    selection_version: str,
    reset_id: str,
    workflow_run_id: str = "",
    records: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Find an earlier command outcome for the same selection version."""

    normalized_team_id = str(team_id or "").strip()
    normalized_question_id = str(question_id or "").strip().upper()
    normalized_action_id = str(action_id or "").strip()
    normalized_version = str(selection_version or "").strip()
    normalized_reset_id = str(reset_id or "origin").strip() or "origin"
    normalized_workflow_run_id = str(workflow_run_id or "").strip()
    source = records if records is not None else _records(team_id)
    for record in reversed(source):
        if str(record.get("recordKind") or "") != SELECTION_COMMAND_OUTCOME_KIND:
            continue
        if str(record.get("teamId") or "").strip() != normalized_team_id:
            continue
        if str(record.get("questionId") or "").strip().upper() != normalized_question_id:
            continue
        if str(record.get("actionId") or "").strip() != normalized_action_id:
            continue
        if str(record.get("selectionVersion") or "").strip() != normalized_version:
            continue
        stored_reset_id = str(record.get("resetId") or "").strip()
        if stored_reset_id != normalized_reset_id:
            continue
        if (
            normalized_workflow_run_id
            and str(record.get("workflowRunId") or "").strip()
            != normalized_workflow_run_id
        ):
            continue
        return record
    return None


def _selection_command_result(result: Any) -> dict[str, Any]:
    """Keep the durable replay payload small but retain all navigation ids."""

    selection = result.get("selection") if isinstance(result, Mapping) else {}
    selection = dict(selection) if isinstance(selection, Mapping) else {}
    review = result.get("reviewMeeting") if isinstance(result, Mapping) else {}
    review = dict(review) if isinstance(review, Mapping) else {}
    meeting = review.get("meetingRound")
    meeting = dict(meeting) if isinstance(meeting, Mapping) else {}
    review_meetings = review.get("reviewMeetings")
    review_meetings = review_meetings if isinstance(review_meetings, list) else []
    if not meeting:
        first_review = review_meetings[0] if review_meetings else {}
        first_review = first_review if isinstance(first_review, Mapping) else {}
        meeting = (
            dict(first_review.get("meetingRound"))
            if isinstance(first_review.get("meetingRound"), Mapping)
            else {}
        )
    meeting_round_id = str(
        meeting.get("meetingRoundId")
        or review.get("meetingRoundId")
        or ""
    ).strip()
    room_id = str(
        review.get("roomId")
        or meeting.get("linkedChatRoomId")
        or ""
    ).strip()
    chat_room_round_ids = _normalized_str_list(
        review.get("chatRoomRoundIds") or meeting.get("chatRoomRoundIds")
    )
    round_id = str(review.get("roundId") or "").strip()
    if not round_id and chat_room_round_ids:
        round_id = chat_room_round_ids[-1]
    return {
        "selectionId": str(selection.get("selectionId") or "").strip(),
        "selectedCandidateIds": _normalized_str_list(
            selection.get("selectedCandidateIds")
        ),
        "meetingRoundId": meeting_round_id,
        "roomId": room_id,
        "roundId": round_id,
        "chatRoomRoundIds": chat_room_round_ids,
        "selection": selection,
        "reviewMeeting": review,
    }


def _selection_command_replay(
    outcome: Mapping[str, Any],
    *,
    team_id: str,
    question_id: str,
    action_id: str,
    idempotency_key: str,
    expected_state_version: str,
    workflow_run_id: str = "",
) -> dict[str, Any]:
    """Build a replay envelope without re-entering any owning mutation."""

    return {
        "schemaVersion": 2,
        "teamId": team_id,
        "questionId": question_id,
        "workflowRunId": str(workflow_run_id or "").strip(),
        "command": "record_selection",
        "actionId": action_id,
        "idempotencyKey": idempotency_key,
        "acceptedStateVersion": str(
            outcome.get("acceptedStateVersion") or expected_state_version
        ),
        "status": "reused",
        "result": dict(outcome.get("result") or {}),
    }


def _active_review_binding_groups(
    team_id: str,
    *,
    question_id: str,
    selection_version: str,
    workflow_run_id: str = "",
    records: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return active candidate-review groups for one selection version."""

    from core.web.services.team_workflow import hypothesis_selection, meeting_rounds

    normalized_question_id = str(question_id or "").strip().upper()
    normalized_version = str(selection_version or "").strip()
    normalized_workflow_run_id = str(workflow_run_id or "").strip()
    if not normalized_version:
        return []
    source = records if records is not None else _records(team_id)
    try:
        selection_payload = hypothesis_selection.list_hypothesis_selections(
            team_id,
            question_id=normalized_question_id,
            workflow_run_id=normalized_workflow_run_id,
        )
        selection_records = [
            dict(record)
            for record in list(selection_payload.get("selections") or [])
            if isinstance(record, Mapping)
        ]
    except Exception:  # noqa: BLE001 - unreadable legacy selection is not authority
        selection_records = []
    selection_by_id: dict[str, dict[str, Any]] = {}
    for record in selection_records:
        selection_id = str(record.get("selectionId") or "").strip()
        if selection_id:
            selection_by_id[selection_id] = record
    meetings = meeting_rounds.list_meeting_rounds(team_id).get("meetings") or []
    meeting_by_id = {
        str(item.get("meetingRoundId") or "").strip(): dict(item)
        for item in meetings
        if isinstance(item, Mapping) and str(item.get("meetingRoundId") or "").strip()
    }
    groups: dict[tuple[str, str, int], dict[str, Any]] = {}
    for link in _review_round_links(source):
        if str(link.get("questionId") or "").strip().upper() != normalized_question_id:
            continue
        selection_id = str(link.get("selectionId") or "").strip()
        linked_selection = selection_by_id.get(selection_id) or {}
        version = str(link.get("selectionVersion") or "").strip()
        if not version and linked_selection:
            version = selection_version_for(
                question_id=normalized_question_id,
                selected_candidate_ids=linked_selection.get("selectedCandidateIds"),
                previous_selection_id=str(
                    linked_selection.get("previousSelectionId") or ""
                ),
                scope_hash=str(linked_selection.get("scopeHash") or ""),
                reset_id=_current_reset_id(
                    team_id,
                    normalized_question_id,
                    records=source,
                ),
                workflow_run_id=str(
                    linked_selection.get("workflowRunId") or ""
                ).strip(),
            )
        if version != normalized_version:
            continue
        meeting_id = str(link.get("meetingRoundId") or "").strip()
        meeting = meeting_by_id.get(meeting_id)
        if (
            normalized_workflow_run_id
            and meeting is not None
            and _meeting_workflow_run_id(meeting) != normalized_workflow_run_id
        ):
            continue
        if not meeting or str(meeting.get("status") or "").strip().lower() not in _ACTIVE_MEETING_STATUSES:
            continue
        round_index = int(link.get("roundIndex") or 1)
        key = (version, selection_id, round_index)
        group = groups.setdefault(
            key,
            {
                "selectionVersion": version,
                "selectionId": selection_id,
                "roundIndex": round_index,
                "links": [],
                "meetings": {},
            },
        )
        group["links"].append(dict(link))
        group["meetings"][meeting_id] = meeting
    return list(groups.values())


def _review_binding_replay_result(
    team_id: str,
    group: Mapping[str, Any],
) -> dict[str, Any]:
    """Project an already-open binding into the selection service shape."""

    links = sorted(
        [dict(item) for item in list(group.get("links") or []) if isinstance(item, Mapping)],
        key=lambda item: (
            int(item.get("candidateOrder") or 0),
            str(item.get("meetingRoundId") or ""),
        ),
    )
    meetings = {
        str(key): dict(value)
        for key, value in dict(group.get("meetings") or {}).items()
        if isinstance(value, Mapping)
    }
    review_meetings: list[dict[str, Any]] = []
    for link in links:
        meeting = meetings.get(str(link.get("meetingRoundId") or ""), {})
        rounds = _normalized_str_list(meeting.get("chatRoomRoundIds"))
        review_meetings.append(
            {
                "schemaVersion": SCHEMA_VERSION,
                "teamId": team_id,
                "status": "reused",
                "meetingRound": meeting,
                "roomId": str(meeting.get("linkedChatRoomId") or ""),
                "roundId": rounds[-1] if rounds else "",
                "chatRoomRoundIds": rounds,
                "link": link,
            }
        )
    primary = review_meetings[0] if review_meetings else {}
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": team_id,
        "status": "reused",
        "meetingRound": primary.get("meetingRound") or {},
        "roomId": str(primary.get("roomId") or ""),
        "roundId": str(primary.get("roundId") or ""),
        "chatRoomRoundIds": list(primary.get("chatRoomRoundIds") or []),
        "link": primary.get("link") or {},
        "reviewMeetings": review_meetings,
        "candidateCount": len(review_meetings),
    }


def retry_review_dispatch(
    team_id: str,
    selection_id: str,
    candidate_ids: list[str],
) -> dict[str, Any]:
    """Re-open only the failed candidate review meetings for one selection."""

    from core.web.services.team_workflow import hypothesis_selection

    normalized_selection_id = str(selection_id or "").strip()
    requested = [str(item or "").strip() for item in candidate_ids if str(item or "").strip()]
    if not normalized_selection_id or not requested:
        raise ContractValidationError("selectionId and candidateIds are required")
    selection = hypothesis_selection.get_hypothesis_selection(
        team_id, normalized_selection_id
    )["selection"]
    selected = [
        str(item or "").strip()
        for item in list(selection.get("selectedCandidateIds") or [])
        if str(item or "").strip() in requested
    ]
    if not selected:
        raise HypothesisFirstChainError(
            "retry_review_dispatch candidates are not part of the current selection"
        )
    current_links = [
        item
        for item in _review_round_links(_records(team_id))
        if str(item.get("selectionId") or "") == normalized_selection_id
    ]
    round_index = max((int(item.get("roundIndex") or 0) for item in current_links), default=1)
    retry_selection = {**selection, "selectedCandidateIds": selected}
    return open_review_meeting_for_selection(
        team_id,
        retry_selection,
        round_index=round_index,
        background=True,
    )


# ---------------------------------------------------------------------------
# claim belief hard gate (R2.2, fail-closed)
#
# The formal selection/convergence authorities of this chain consume the
# five-state belief table (`ClaimBeliefTable` via
# `claim_belief_service.evaluate_claim_belief`) as a hard gate: only a
# candidate-specific core claim must carry accepted support plus accepted
# counter/boundary coverage.  Legacy fact-only projections retain their old
# five-state semantics; formal candidate bindings are identified by
# ``reasoningRole=hypothesis`` and are evaluated strictly.

CLAIM_BELIEF_GATE_BLOCKING_STATES = frozenset({"contradicted", "disputed"})


def _claim_evidence_records(team_id: str) -> list[dict[str, Any]]:
    """Authoritative claim-evidence records for one team (evidence store)."""
    from core.research.evidence import ClaimEvidenceStore

    return [
        dict(record)
        for record in ClaimEvidenceStore(_project_root()).list(team_id)
        if isinstance(record, Mapping)
    ]


def _question_claim_rows_for_gate(team_id: str, question_id: str) -> list[dict[str, Any]]:
    """Latest-per-claim ledger rows scoped to one question (read-only)."""
    from core.web.services.team_workflow import claim_ledger as claim_ledger_service

    listing = claim_ledger_service.list_claims(team_id)
    normalized_question = str(question_id or "").strip().upper()
    return [
        dict(item)
        for item in list(listing.get("claims") or [])
        if isinstance(item, Mapping)
        and str(item.get("question") or "").strip().upper() == normalized_question
    ]


def _formal_grounded_candidate_ids_for_gate(
    team_id: str, question_id: str
) -> set[str]:
    """Formal R1 candidates that must never fall back to legacy fact rows."""

    normalized_question = str(question_id or "").strip().upper()
    return {
        str(record.get("candidateId") or "").strip()
        for record in _records(team_id)
        if str(record.get("recordKind") or "") == CANDIDATE_KIND
        and str(record.get("questionId") or "").strip().upper() == normalized_question
        and str(record.get("candidateAuthority") or "").strip()
        == FORMAL_GROUNDED_CANDIDATE_AUTHORITY
        and str(record.get("candidateId") or "").strip()
    }


def _blocked_gate_verdict(
    candidate_id: str, reason: str, *, claims: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    return {
        "candidateId": candidate_id,
        "status": "blocked",
        "reason": reason,
        "claims": list(claims or []),
        "blockedClaims": list(claims or []),
    }


def evaluate_claim_belief_gate(
    team_id: str,
    question_id: str,
    candidate_ids: Any,
) -> dict[str, dict[str, Any]]:
    """Evaluate the claim belief hard gate for the given candidates.

    Fail-closed by construction: every unreadable store, unparsable ledger
    entry, missing claim row and `contradicted`/`disputed` belief state
    becomes a structured ``blocked`` verdict instead of an exception or a
    silent allow.  The belief states themselves come exclusively from
    `evaluate_claim_belief` — this gate never re-derives them.
    """
    normalized_question = str(question_id or "").strip().upper()
    if isinstance(candidate_ids, str):
        requested = [candidate_ids]
    else:
        requested = [str(item or "").strip() for item in list(candidate_ids or [])]
    requested = [item for item in requested if item]
    verdicts: dict[str, dict[str, Any]] = {}
    if not requested:
        return verdicts

    from core.research.workflow.contracts import ClaimLedgerEntry

    from .claim_belief_service import evaluate_claim_belief

    try:
        claim_rows = _question_claim_rows_for_gate(team_id, normalized_question)
    except Exception:  # noqa: BLE001 - fail closed on unreadable ledger
        for candidate_id in requested:
            verdicts[candidate_id] = _blocked_gate_verdict(
                candidate_id, "claim_ledger_unavailable"
            )
        return verdicts
    try:
        evidence_records = _claim_evidence_records(team_id)
    except Exception:  # noqa: BLE001 - fail closed on unreadable evidence store
        for candidate_id in requested:
            verdicts[candidate_id] = _blocked_gate_verdict(
                candidate_id, "claim_evidence_store_unavailable"
            )
        return verdicts
    try:
        formal_grounded_candidate_ids = _formal_grounded_candidate_ids_for_gate(
            team_id, normalized_question
        )
    except Exception:  # noqa: BLE001 - evidence/ledger gates still fail closed
        formal_grounded_candidate_ids = set()

    entries_by_id: dict[str, Any] = {}
    invalid_claim_ids: set[str] = set()
    for row in claim_rows:
        claim_id = str(row.get("claimId") or "").strip()
        if not claim_id:
            continue
        try:
            entries_by_id[claim_id] = ClaimLedgerEntry.from_dict(dict(row))
        except Exception:  # noqa: BLE001 - invalid rows cannot support a gate allow
            invalid_claim_ids.add(claim_id)

    claims_by_candidate: dict[str, set[str]] = {
        candidate_id: set() for candidate_id in requested
    }
    strict_claims_by_candidate: dict[str, set[str]] = {
        candidate_id: set() for candidate_id in requested
    }
    for record in evidence_records:
        candidate_id = str(record.get("candidateId") or "").strip()
        claim_id = str(record.get("claimId") or "").strip()
        if candidate_id in claims_by_candidate and claim_id:
            claims_by_candidate[candidate_id].add(claim_id)
            if str(record.get("reasoningRole") or "").strip().lower() == "hypothesis":
                strict_claims_by_candidate[candidate_id].add(claim_id)

    for candidate_id in requested:
        strict_claim_ids = strict_claims_by_candidate.get(candidate_id) or set()
        strict_candidate_binding = bool(strict_claim_ids)
        strict_candidate_required = (
            candidate_id in formal_grounded_candidate_ids
            or strict_candidate_binding
        )
        if strict_candidate_required and not strict_candidate_binding:
            verdicts[candidate_id] = _blocked_gate_verdict(
                candidate_id, "candidate_claim_binding_missing"
            )
            continue
        claim_ids = sorted(
            strict_claim_ids
            if strict_candidate_binding
            else claims_by_candidate.get(candidate_id) or set()
        )
        if not claim_ids:
            # No claim data at all for this candidate: an unevidenced core
            # claim must not enter the formal path (fail-closed).
            verdicts[candidate_id] = _blocked_gate_verdict(
                candidate_id, "claim_data_missing"
            )
            continue
        missing = [
            item
            for item in claim_ids
            if item not in entries_by_id and item not in invalid_claim_ids
        ]
        invalid = [item for item in claim_ids if item in invalid_claim_ids]
        if missing:
            # Bridged claim ids absent from this question's scoped ledger rows
            # mean no evaluable claim data for this question (fail-closed).
            verdicts[candidate_id] = _blocked_gate_verdict(
                candidate_id, "claim_data_missing"
            )
            continue
        if invalid:
            claims_preview = [
                {
                    "claimId": item,
                    "beliefState": "unknown",
                    "problem": "ledger_entry_invalid",
                }
                for item in sorted(set(invalid))
            ]
            verdicts[candidate_id] = _blocked_gate_verdict(
                candidate_id,
                "claim_ledger_entry_unreadable",
                claims=claims_preview,
            )
            continue
        try:
            table = evaluate_claim_belief(
                [entries_by_id[claim_id] for claim_id in claim_ids],
                evidence_records,
            )
        except Exception:  # noqa: BLE001 - fail closed on evaluation failure
            verdicts[candidate_id] = _blocked_gate_verdict(
                candidate_id, "claim_belief_evaluation_failed"
            )
            continue
        states = {entry.claimId: entry for entry in table.entries}
        claim_summaries: list[dict[str, Any]] = []
        blocked_claims: list[dict[str, Any]] = []
        evidence_gaps: list[dict[str, str]] = []
        for claim_id in claim_ids:
            entry = states.get(claim_id)
            if entry is None:
                blocked_claims.append(
                    {
                        "claimId": claim_id,
                        "beliefState": "unknown",
                        "problem": "belief_entry_missing",
                    }
                )
                continue
            claim_summaries.append(
                {
                    "claimId": claim_id,
                    "beliefState": entry.beliefState,
                    "acceptedSupportCount": entry.acceptedSupportCount,
                    "acceptedCounterCount": entry.acceptedCounterCount,
                    "supportingEvidenceIds": list(entry.supportingEvidenceIds),
                    "counterEvidenceIds": list(entry.counterEvidenceIds),
                }
            )
            if entry.beliefState in CLAIM_BELIEF_GATE_BLOCKING_STATES:
                blocked_claims.append(
                    {
                        "claimId": claim_id,
                        "beliefState": entry.beliefState,
                        "acceptedSupportCount": entry.acceptedSupportCount,
                        "acceptedCounterCount": entry.acceptedCounterCount,
                        "counterEvidenceIds": list(entry.counterEvidenceIds),
                    }
                )
            if strict_candidate_binding:
                if entry.acceptedSupportCount < 1:
                    evidence_gaps.append(
                        {"claimId": claim_id, "gap": "accepted_support_missing"}
                    )
                # Counter review is conditional, not a blanket requirement: a
                # claim+candidate with no contradicts/counter_evidence record
                # at all has nothing to review (vacuously satisfied), so an
                # evidence-clean candidate is never blocked by a review of a
                # record that does not exist.  Only when such a record exists
                # (pending or accepted) must its accepted version be on file,
                # so refuting material still cannot slip through unreviewed.
                counter_records = [
                    record
                    for record in evidence_records
                    if str(record.get("candidateId") or "").strip() == candidate_id
                    and str(record.get("claimId") or "").strip() == claim_id
                    and (
                        str(record.get("supportLevel") or "").strip().lower()
                        == "contradicts"
                        or str(record.get("evidenceKind") or "").strip().lower()
                        == "counter_evidence"
                    )
                ]
                if counter_records and not any(
                    str(record.get("reviewStatus") or "").strip().lower()
                    == "accepted"
                    for record in counter_records
                ):
                    evidence_gaps.append(
                        {
                            "claimId": claim_id,
                            "gap": "accepted_counter_or_boundary_missing",
                        }
                    )
        if evidence_gaps:
            verdicts[candidate_id] = {
                "candidateId": candidate_id,
                "status": "blocked",
                "reason": "candidate_evidence_gap",
                "claims": claim_summaries,
                "blockedClaims": blocked_claims,
                "evidenceGaps": evidence_gaps,
            }
            continue
        if blocked_claims:
            verdicts[candidate_id] = _blocked_gate_verdict(
                candidate_id, "claim_belief_state_blocked", claims=blocked_claims
            )
        else:
            verdicts[candidate_id] = {
                "candidateId": candidate_id,
                "status": "allowed",
                "reason": "",
                "claims": claim_summaries,
                "blockedClaims": [],
            }
    return verdicts


def _gate_blocker_payload(verdict: dict[str, Any]) -> dict[str, Any]:
    """One route-renderable blocker entry for a blocked gate verdict."""
    return {
        "code": "claim_belief_gate_blocked",
        "candidateId": verdict.get("candidateId") or "",
        "reason": str(verdict.get("reason") or ""),
        "claims": list(verdict.get("blockedClaims") or []),
        "evidenceGaps": list(verdict.get("evidenceGaps") or []),
    }


def _assert_claim_belief_gate_allows(
    team_id: str,
    question_id: str,
    candidate_id: str,
    *,
    stage: str,
) -> dict[str, Any]:
    """Raise `ClaimBeliefGateBlockedError` when the candidate fails the gate."""
    normalized_candidate = str(candidate_id or "").strip()
    verdict = evaluate_claim_belief_gate(team_id, question_id, [normalized_candidate]).get(
        normalized_candidate
    ) or _blocked_gate_verdict(normalized_candidate, "claim_belief_evaluation_failed")
    if verdict.get("status") == "allowed":
        return verdict
    blocked_claims = [
        str(item.get("claimId") or "")
        for item in list(verdict.get("blockedClaims") or [])
        if isinstance(item, Mapping)
    ]
    reason = str(verdict.get("reason") or "")
    if reason == "claim_belief_state_blocked":
        message = (
            f"Claim belief gate blocked this decision: the core claims "
            f"({', '.join(blocked_claims) or 'unknown'}) of candidate "
            f"{normalized_candidate or 'unknown'} have been refuted or are disputed, "
            f"and must not advance to the formal path. Please supersede/retract the claim or repair the "
            f"evidence review before retrying."
        )
    else:
        message = (
            f"Claim belief gate blocked this decision: the candidate "
            f"{normalized_candidate or 'unknown'}'s claim data cannot be evaluated ({reason}), "
            f"fail-closed and not allowed to advance to the formal path."
        )
    _record_scene_event(
        "claim_belief_gate_blocked",
        outcome="blocked",
        level="warning",
        fields={
            "stage": stage,
            "questionId": str(question_id or "").strip().upper(),
            "candidateId": normalized_candidate,
            "gateReason": reason,
            "blockedClaimIds": blocked_claims,
        },
    )
    raise ClaimBeliefGateBlockedError(
        message,
        stage=stage,
        question_id=str(question_id or "").strip().upper(),
        candidate_id=normalized_candidate,
        blockers=[_gate_blocker_payload(verdict)],
    )


def _apply_human_acceptance_for_recommended_candidate(
    team_id: str,
    question_id: str,
    candidate_id: str,
    *,
    hypothesis_round_id: str,
    accepted_by: str,
) -> dict[str, Any]:
    """Exercise the human acceptance authority over pending support evidence.

    Chain evidence collection never runs an evidence review round
    (``materialize_chain_collection_evidence`` registers its bridged evidence
    ``pending`` by design), so without an acceptance write the claim belief
    gate's ``acceptedSupportCount >= 1`` requirement could never be met and an
    accepted human adjudication — the designed acceptance authority — would be
    deadlocked.  Before the gate pre-check of an ``accepted`` adjudication,
    the recommended candidate's pending supporting evidence is promoted by
    appending audited accepted twin records (the evidence store is append-only
    with content-hash ids, so history is preserved, never rewritten):

    - the pending ``supports`` records the candidate's core claim rows
      actually cite (the records the belief table counts), and
    - the candidate-dimension records bound to those core claim rows
      (``reasoningRole`` fact or hypothesis — live stores carry both for the
      same claim after historical repairs).

    Pure source-fact records on their own fact claim rows that the core claims
    do not cite are never touched, ``contradicts``/boundary records are never
    auto-accepted, and the gate's ``contradicted``/``disputed`` blocking
    states stay fully in force.
    """
    normalized_candidate = str(candidate_id or "").strip()
    normalized_question = str(question_id or "").strip().upper()
    if not normalized_candidate:
        return {
            "status": "skipped",
            "reason": "recommended_candidate_missing",
            "acceptedTwinCount": 0,
        }
    claim_rows_by_id = {
        str(row.get("claimId") or "").strip(): dict(row)
        for row in _question_claim_rows_for_gate(team_id, normalized_question)
        if isinstance(row, Mapping) and str(row.get("claimId") or "").strip()
    }
    evidence_records = [
        dict(record)
        for record in _claim_evidence_records(team_id)
        if isinstance(record, Mapping)
    ]
    core_claim_ids = {
        str(record.get("claimId") or "").strip()
        for record in evidence_records
        if str(record.get("candidateId") or "").strip() == normalized_candidate
        and str(record.get("claimId") or "").strip() in claim_rows_by_id
    }
    if not core_claim_ids:
        return {
            "status": "skipped",
            "reason": "core_claim_rows_missing",
            "candidateId": normalized_candidate,
            "acceptedTwinCount": 0,
        }
    cited_evidence_ids = {
        str(ref.get("claimEvidenceId") or "").strip()
        for claim_id in core_claim_ids
        for ref in list(claim_rows_by_id[claim_id].get("evidenceRefs") or [])
        if isinstance(ref, Mapping) and str(ref.get("claimEvidenceId") or "").strip()
    }
    # Belief readers resolve a cited record's scope against the claim's
    # scopeHash, and the store records carry none of their own: without the
    # claim scope on the twin, an accepted twin would stay neutral and the
    # acceptance would never count.  Refs are scope-consistent by ledger
    # contract, so the core claim's scopeHash is the twin's scope either way.
    scope_hash_by_claim = {
        claim_id: str(claim_rows_by_id[claim_id].get("scopeHash") or "")
        .strip()
        .lower()
        for claim_id in core_claim_ids
    }
    surface: list[dict[str, Any]] = []
    seen_evidence_ids: set[str] = set()
    for record in evidence_records:
        evidence_id = str(record.get("claimEvidenceId") or "").strip()
        if not evidence_id or evidence_id in seen_evidence_ids:
            continue
        claim_id = str(record.get("claimId") or "").strip()
        candidate_bound = (
            str(record.get("candidateId") or "").strip() == normalized_candidate
            and claim_id in core_claim_ids
        )
        if not (candidate_bound or evidence_id in cited_evidence_ids):
            continue
        if str(record.get("reviewStatus") or "").strip().lower() != "pending":
            continue
        if str(record.get("supportLevel") or "").strip().lower() not in {
            "supports",
            "",
        }:
            continue
        if candidate_bound:
            scope_hash = scope_hash_by_claim.get(claim_id, "")
        else:
            scope_hash = next(
                (
                    scope_hash_by_claim[core_id]
                    for core_id in core_claim_ids
                    if any(
                        isinstance(ref, Mapping)
                        and str(ref.get("claimEvidenceId") or "").strip()
                        == evidence_id
                        for ref in list(
                            claim_rows_by_id[core_id].get("evidenceRefs") or []
                        )
                    )
                ),
                "",
            )
        entry = dict(record)
        if scope_hash:
            entry["scopeHash"] = scope_hash
        surface.append(entry)
        seen_evidence_ids.add(evidence_id)
    if not surface:
        return {
            "status": "no_pending_support_evidence",
            "candidateId": normalized_candidate,
            "coreClaimIds": sorted(core_claim_ids),
            "acceptedTwinCount": 0,
        }
    from core.research.evidence import ClaimEvidenceStore

    twins = ClaimEvidenceStore(_project_root()).append_accepted_review_twins(
        team_id,
        surface,
        accepted_by=accepted_by,
        accepted_at_ms=int(datetime.now(timezone.utc).timestamp() * 1000),
        acceptance_round_id=str(hypothesis_round_id or "").strip(),
        acceptance_source="human_adjudication",
    )
    return {
        "status": "applied",
        "candidateId": normalized_candidate,
        "coreClaimIds": sorted(core_claim_ids),
        "sourceCount": len(surface),
        "acceptedTwinCount": len(twins),
    }


def _adjudication_workflow_run_id(
    team_id: str,
    round_record: Mapping[str, Any],
    *,
    workflow_run_id: str,
) -> str:
    """Resolve the run scope for adjudication-time binding materialization.

    The budget-exhaustion auto-advance reuses ``record_human_adjudication``
    without a ``workflow_run_id`` (chain rounds pre-date run-scoped
    adjudications), so fall back to the round's own meeting refs — the same
    meetings the adjudication already validated.  Empty is a valid answer:
    the materialization then keys run scope off the source evidence records
    instead of a run identity, and a caller that cannot resolve one simply
    skips the run-scoped tag.
    """

    normalized = str(workflow_run_id or "").strip()
    if normalized:
        return normalized
    meeting_ids = {
        str(ref.get("id") or "").strip()
        for ref in list(round_record.get("meetingRefs") or [])
        if isinstance(ref, Mapping)
        and str(ref.get("kind") or "") == "meeting_round"
        and str(ref.get("id") or "").strip()
    }
    if not meeting_ids:
        return ""
    from core.web.services.team_workflow import meeting_rounds

    for meeting in meeting_rounds.list_meeting_rounds(team_id)["meetings"]:
        if str(meeting.get("meetingRoundId") or "").strip() not in meeting_ids:
            continue
        resolved = _meeting_workflow_run_id(meeting)
        if resolved:
            return resolved
    return ""


def _materialize_recommended_candidate_claim_bindings(
    team_id: str,
    question_id: str,
    candidate_id: str,
    *,
    workflow_run_id: str,
) -> dict[str, Any]:
    """Materialize the recommended candidate's strict claim bindings (probe-first).

    Time-invariance fix for the chain-level acceptance authority: the strict
    claim belief gate requires hypothesis-role claim binding records, but the
    only writer (:func:`materialize_candidate_claim_bindings_from_existing_evidence`)
    ran on the formal side — after the formal run exists — while chain-level
    adjudication happens strictly before it.  An accepted adjudication could
    therefore never satisfy the gate (``candidate_claim_binding_missing``),
    deadlocking the convergence the human (or budget-exhaustion policy) had
    just granted.  Before the gate runs, this binds the recommended
    candidate's already-collected lineage evidence under ``reasoningRole =
    hypothesis`` so the unchanged strict gate can finally read it:

    - probe-first and idempotent: if any hypothesis-role record is already
      bound to the candidate, nothing is written (replays and a human
      adjudication after an auto-advanced one stay write-free);
    - reuse first: when the candidate's core-claim ledger row already exists
      (the chain collection bridge proposed it with its cited evidence refs),
      re-proposing it ref-less would collide with the ledger's content
      binding, so the existing row's claim id is kept and the hypothesis-role
      records are registered against it directly;
    - fresh rows go through the formal materializer unchanged;
    - no evidence to bind (no candidate record, no lineage refs, no matching
      source records) materializes nothing and the gate keeps its original
      fail-closed verdict — bindings are never fabricated and the gate
      semantics are never relaxed.
    """

    normalized_candidate = str(candidate_id or "").strip()
    if not normalized_candidate:
        return {"status": "skipped", "reason": "recommended_candidate_missing"}
    evidence_records = _claim_evidence_records(team_id)
    existing_strict_ids = {
        str(record.get("claimEvidenceId") or "").strip()
        for record in evidence_records
        if str(record.get("candidateId") or "").strip() == normalized_candidate
        and str(record.get("reasoningRole") or "").strip().lower() == "hypothesis"
        and str(record.get("claimEvidenceId") or "").strip()
    }
    if existing_strict_ids:
        return {
            "status": "skipped",
            "reason": "strict_binding_present",
            "candidateId": normalized_candidate,
            "strictBindingCount": len(existing_strict_ids),
        }
    candidate_record = next(
        (
            dict(record)
            for record in reversed(_records(team_id))
            if str(record.get("recordKind") or "") == CANDIDATE_KIND
            and str(record.get("candidateId") or "").strip() == normalized_candidate
            and str(record.get("questionId") or "").strip().upper()
            == str(question_id or "").strip().upper()
        ),
        None,
    )
    statement = str((candidate_record or {}).get("statement") or "").strip()
    lineage_refs = {
        str(item or "").strip()
        for item in list((candidate_record or {}).get("lineageRefs") or [])
        if str(item or "").strip()
    }
    if not candidate_record or not statement or not lineage_refs:
        return {
            "status": "skipped",
            "reason": "candidate_lineage_missing",
            "candidateId": normalized_candidate,
        }
    matching_sources = [
        dict(record)
        for record in evidence_records
        if str(record.get("reasoningRole") or "").strip().lower() != "hypothesis"
        and str(record.get("reviewStatus") or "").strip().lower()
        not in {"rejected", "stale"}
        and (
            str(record.get("sourceId") or "").strip() in lineage_refs
            or str(record.get("claimEvidenceId") or "").strip() in lineage_refs
        )
    ]
    if not matching_sources:
        return {
            "status": "skipped",
            "reason": "no_matching_lineage_evidence",
            "candidateId": normalized_candidate,
        }
    normalized_run = str(workflow_run_id or "").strip()
    question_scope = _question_scope_envelope(team_id, question_id)

    from core.research.evidence import ClaimEvidenceStore

    from .agent_claim_evidence_materializer import (
        _ledger_claim_id,
        materialize_candidate_claim_bindings_from_existing_evidence,
    )

    expected_claim_id = _ledger_claim_id(
        question_scope=question_scope,
        claim_text=statement,
        candidate_id=normalized_candidate,
    )
    ledger_row = next(
        (
            row
            for row in _question_claim_rows_for_gate(team_id, question_id)
            if str(row.get("claimId") or "").strip() == expected_claim_id
        ),
        None,
    )
    if ledger_row is None and any(
        not str(source.get("sourceCollectionRunId") or "").strip()
        or (not normalized_run and not str(source.get("workflowRunId") or "").strip())
        for source in matching_sources
    ):
        # The formal materializer stamps every binding with direct reads of
        # the source's ``sourceCollectionRunId`` plus the run scope of either
        # the resolved run or the source record itself; with either missing it
        # cannot tag provenance, so skip instead of crashing — the gate keeps
        # its original fail-closed verdict.
        return {
            "status": "skipped",
            "reason": "provenance_unresolvable",
            "candidateId": normalized_candidate,
        }
    if ledger_row is None:
        materialized = materialize_candidate_claim_bindings_from_existing_evidence(
            project_root=_project_root(),
            team_id=team_id,
            workflow_run_id=normalized_run,
            question_scope=question_scope,
            candidates=[candidate_record],
        )
        return {
            "status": "applied",
            "reason": "formal_materializer",
            "candidateId": normalized_candidate,
            "claimId": expected_claim_id,
            "materializedCount": len(materialized),
        }
    store = ClaimEvidenceStore(_project_root())
    bound_claim_id = str(ledger_row.get("claimId") or "").strip()
    before_ids = set(existing_strict_ids)
    for source in matching_sources:
        payload: dict[str, Any] = {
            "claimId": bound_claim_id,
            "candidateId": normalized_candidate,
            "sourceId": str(source.get("sourceId") or ""),
            "sourceRevision": str(source.get("sourceRevision") or ""),
            "locator": dict(source.get("locator") or {}),
            "quote": str(source.get("quote") or ""),
            "evidenceKind": str(source.get("evidenceKind") or ""),
            "reasoningRole": "hypothesis",
            "supportLevel": str(source.get("supportLevel") or ""),
            "extractionMethod": str(source.get("extractionMethod") or ""),
            "extractorAgentId": str(source.get("extractorAgentId") or ""),
            "modelRef": str(source.get("modelRef") or ""),
            "sourceCollectionRunId": str(
                source.get("sourceCollectionRunId") or ""
            ),
        }
        run_tag = normalized_run or str(source.get("workflowRunId") or "")
        if run_tag:
            payload["workflowRunId"] = run_tag
        bound = store.register(team_id, payload)
        bound_id = str(bound.get("claimEvidenceId") or "").strip()
        if bound_id and bound_id not in before_ids:
            before_ids.add(bound_id)
    return {
        "status": "applied",
        "reason": "chain_collection_row_reused",
        "candidateId": normalized_candidate,
        "claimId": bound_claim_id,
        "materializedCount": len(before_ids - existing_strict_ids),
    }


def record_human_adjudication(
    team_id: str,
    *,
    question_id: str,
    hypothesis_round_id: str,
    decision: str,
    rationale: str,
    idempotency_key: str,
    workflow_run_id: str = "",
    decided_by: str = "",
) -> dict[str, Any]:
    """Append the missing human authority for an exhausted convergence gate.

    ``decided_by`` defaults to the operator agent id; the automation-policy
    executor passes its system actor (``system:auto-advance:<policyId>``)
    so an auto-recorded adjudication stays attributable in the ledger.
    """

    from core.web.services.team_workflow import hypothesis_rounds

    normalized_question_id = str(question_id or "").strip().upper()
    normalized_round_id = str(hypothesis_round_id or "").strip()
    normalized_decision = str(decision or "").strip().lower()
    normalized_rationale = str(rationale or "").strip()
    normalized_workflow_run_id = str(workflow_run_id or "").strip()
    normalized_decided_by = str(decided_by or "").strip() or _OPERATOR_AGENT_ID
    if normalized_decision not in {"accepted", "rejected"}:
        raise ContractValidationError(
            "human_adjudication decision must be accepted or rejected"
        )
    if not normalized_rationale:
        raise ContractValidationError("human_adjudication rationale is required")
    round_record = hypothesis_rounds.get_hypothesis_round(
        team_id, normalized_round_id
    )["round"]
    if str(round_record.get("status") or "").strip().lower() != "closed":
        raise HypothesisFirstChainError(
            "human adjudication requires a closed hypothesis round"
        )
    round_meeting_ids = [
        str(ref.get("id") or "").strip()
        for ref in list(round_record.get("meetingRefs") or [])
        if isinstance(ref, Mapping)
        and str(ref.get("kind") or "") == "meeting_round"
        and str(ref.get("id") or "").strip()
    ]
    question_rounds = _question_hypothesis_rounds(team_id, normalized_question_id)
    if normalized_workflow_run_id:
        run_meeting_ids = {
            str(meeting.get("meetingRoundId") or "").strip()
            for meeting in _question_meetings(
                team_id,
                normalized_question_id,
                workflow_run_id=normalized_workflow_run_id,
            )
            if str(meeting.get("meetingRoundId") or "").strip()
        }
        if not round_meeting_ids or not set(round_meeting_ids).issubset(
            run_meeting_ids
        ):
            raise HypothesisFirstChainError(
                "human adjudication round does not belong to the workflow run"
            )
        question_rounds = [
            item
            for item in question_rounds
            if any(
                isinstance(ref, Mapping)
                and str(ref.get("kind") or "") == "meeting_round"
                and str(ref.get("id") or "").strip() in run_meeting_ids
                for ref in list(item.get("meetingRefs") or [])
            )
        ]
    if not question_rounds or str(question_rounds[-1].get("roundId") or "") != normalized_round_id:
        raise HypothesisFirstChainError(
            "human adjudication must target the current hypothesis round"
        )
    identity = str(idempotency_key or "").strip()
    with _LOCK:
        records = _read_jsonl(_storage_path(team_id))
        existing = next(
            (
                item
                for item in reversed(records)
                if item.get("recordKind") == HUMAN_ADJUDICATION_KIND
                and str(item.get("idempotencyKey") or "") == identity
            ),
            None,
        )
        if existing is not None:
            if (
                str(existing.get("hypothesisRoundId") or "") != normalized_round_id
                or str(existing.get("decision") or "") != normalized_decision
                or str(existing.get("rationale") or "") != normalized_rationale
                or str(existing.get("workflowRunId") or "")
                != normalized_workflow_run_id
            ):
                raise HypothesisFirstChainError(
                    "human adjudication idempotency key is bound to different input"
                )
            return {"status": "reused", "adjudication": existing}
        if normalized_decision == "accepted":
            # Formal selection hard gate (fail-closed): an accepted human
            # adjudication is a convergence authority for the formal path, so
            # the round's recommended candidate must pass the claim belief
            # gate before the authority is appended.  Replays above are not
            # re-gated; rejecting (elimination) is never gated.  The human
            # acceptance authority is exercised first: the recommended
            # candidate's pending supporting evidence gets audited accepted
            # twins (the chain never runs an evidence review round).  Then the
            # candidate's strict hypothesis-role claim bindings are
            # materialized from its already-collected lineage evidence
            # (probe-first, idempotent) — the only writer ran on the formal
            # side, which always happens after this adjudication, so without
            # this the strict gate could never pass at chain level.  The
            # unchanged gate still blocks contradicted/disputed claims, and a
            # candidate with no bindable evidence keeps its original
            # fail-closed verdict.
            meta_review = (
                round_record.get("metaReview")
                if isinstance(round_record.get("metaReview"), Mapping)
                else {}
            )
            recommended_candidate_id = str(
                meta_review.get("recommendationCandidateId") or ""
            ).strip()
            try:
                acceptance = _apply_human_acceptance_for_recommended_candidate(
                    team_id,
                    normalized_question_id,
                    recommended_candidate_id,
                    hypothesis_round_id=normalized_round_id,
                    accepted_by=normalized_decided_by,
                )
            except Exception as exc:  # noqa: BLE001 - the gate stays fail-closed
                _record_scene_event(
                    "human_adjudication_acceptance_failed",
                    outcome="failed",
                    level="warning",
                    fields={
                        "questionId": normalized_question_id,
                        "candidateId": recommended_candidate_id,
                        "hypothesisRoundId": normalized_round_id,
                        "acceptedBy": normalized_decided_by,
                        "error": str(exc)[:200],
                    },
                )
            else:
                _record_scene_event(
                    "human_adjudication_acceptance_applied",
                    outcome=(
                        "applied" if acceptance.get("acceptedTwinCount") else "skipped"
                    ),
                    fields={
                        "questionId": normalized_question_id,
                        "candidateId": recommended_candidate_id,
                        "hypothesisRoundId": normalized_round_id,
                        "acceptedBy": normalized_decided_by,
                        "acceptanceStatus": str(acceptance.get("status") or ""),
                        "acceptedTwinCount": int(
                            acceptance.get("acceptedTwinCount") or 0
                        ),
                        "sourceCount": int(acceptance.get("sourceCount") or 0),
                        "coreClaimIds": list(acceptance.get("coreClaimIds") or []),
                    },
                )
            try:
                binding_materialization = (
                    _materialize_recommended_candidate_claim_bindings(
                        team_id,
                        normalized_question_id,
                        recommended_candidate_id,
                        workflow_run_id=_adjudication_workflow_run_id(
                            team_id,
                            round_record,
                            workflow_run_id=normalized_workflow_run_id,
                        ),
                    )
                )
            except Exception as exc:  # noqa: BLE001 - the gate stays fail-closed
                _record_scene_event(
                    "human_adjudication_binding_materialization_failed",
                    outcome="failed",
                    level="warning",
                    fields={
                        "questionId": normalized_question_id,
                        "candidateId": recommended_candidate_id,
                        "hypothesisRoundId": normalized_round_id,
                        "error": str(exc)[:200],
                    },
                )
            else:
                _record_scene_event(
                    "human_adjudication_binding_materialized",
                    outcome=str(binding_materialization.get("status") or ""),
                    fields={
                        "questionId": normalized_question_id,
                        "candidateId": recommended_candidate_id,
                        "hypothesisRoundId": normalized_round_id,
                        "materializationStatus": str(
                            binding_materialization.get("status") or ""
                        ),
                        "materializationReason": str(
                            binding_materialization.get("reason") or ""
                        ),
                        "claimId": str(binding_materialization.get("claimId") or ""),
                        "materializedCount": int(
                            binding_materialization.get("materializedCount") or 0
                        ),
                    },
                )
            _assert_claim_belief_gate_allows(
                team_id,
                normalized_question_id,
                recommended_candidate_id,
                stage="human_adjudication",
            )
        now = _utc_now()
        record = {
            "schemaVersion": SCHEMA_VERSION,
            "recordKind": HUMAN_ADJUDICATION_KIND,
            "adjudicationId": f"hf-adjudication-{_stable_hash({'key': identity})[:16]}",
            "idempotencyKey": identity,
            "questionId": normalized_question_id,
            "hypothesisRoundId": normalized_round_id,
            "workflowRunId": normalized_workflow_run_id,
            "meetingRoundIds": round_meeting_ids,
            "decision": normalized_decision,
            "rationale": normalized_rationale,
            "decidedBy": normalized_decided_by,
            "createdAt": now,
            "updatedAt": now,
        }
        _append_jsonl(_storage_path(team_id), record)
    return {"status": "created", "adjudication": record}


def _latest_round_adjudication(
    records: list[dict[str, Any]],
    *,
    question_id: str,
    round_id: str,
    meeting_ids: set[str] | None = None,
) -> dict[str, Any] | None:
    """Latest human adjudication record appended for one hypothesis round.

    Read-model counterpart of ``record_human_adjudication``: the appended
    HUMAN_ADJUDICATION_KIND record is the convergence authority, so the
    chain_state projection must consume it here (latest write wins, matching
    the v2 projection).  Records are scoped like every other chain_state
    input — question always, and the run's meeting ids when the caller reads
    a formal run — so retained history from another execution cannot decide
    this question.
    """

    normalized_question_id = str(question_id or "").strip().upper()
    normalized_round_id = str(round_id or "").strip()
    for item in reversed(records):
        if str(item.get("recordKind") or "") != HUMAN_ADJUDICATION_KIND:
            continue
        if str(item.get("questionId") or "").strip().upper() != normalized_question_id:
            continue
        if str(item.get("hypothesisRoundId") or "").strip() != normalized_round_id:
            continue
        if meeting_ids is not None:
            record_meeting_ids = {
                str(meeting_id or "").strip()
                for meeting_id in list(item.get("meetingRoundIds") or [])
            }
            if record_meeting_ids and not record_meeting_ids.intersection(
                meeting_ids
            ):
                continue
        return item
    return None


# ---------------------------------------------------------------------------
# Budget-exhaustion auto-advance (adjudication -> formal run creation)
#
# The review-round budget is a frozen server constant; once it is spent and
# the fan-in round closed, the chain used to dead-end on a human
# adjudication.  The closed loop below presses the chain's OWN idempotent
# buttons instead of waiting: ``auto_adjudicate_exhausted_round`` reuses
# ``record_human_adjudication`` (the claim-belief hard gate keeps its
# fail-closed semantics) and ``auto_create_formal_run_after_convergence``
# reuses the ``create_formal_run`` create + auto-start channel.  Both are
# best-effort: they never raise, blocked hard gates stay a structured
# ``failed`` left to the human (correct behavior, not a bug), and every
# outcome leaves a scene-event trail.
# ---------------------------------------------------------------------------


def _round_index_from_review_links(
    team_id: str,
    question_id: str,
    round_record: Mapping[str, Any],
) -> int | None:
    """Resolve the selection's spent review-round budget from lineage links.

    Persisted HypothesisRound records carry no ``roundIndex`` of their own
    (see :func:`_round_refs_meeting_ids`).  The exhaustion gate this feeds
    asks whether the SELECTION spent its whole meeting-round budget, so the
    answer is the highest ``roundIndex`` across the selection's links — not
    the round's own group.  A superseded budget-round closure (e.g. the
    newest round force-closed without a digest by a blocked-run recovery)
    never generates a round of its own; the fan-in correctly falls back to
    the older authoritative group, whose own link index would under-report
    the budget actually spent.  Selections are resolved through the links
    bound to the round's meeting refs; a round matching no link stays
    fail-closed (``None``) — exhaustion is never guessed.
    """
    meeting_ids = _round_refs_meeting_ids(round_record)
    if not meeting_ids:
        return None
    links = (list_review_round_links(team_id, question_id=question_id) or {}).get(
        "links"
    ) or []
    selection_ids = {
        str(link.get("selectionId") or "").strip()
        for link in links
        if str(link.get("meetingRoundId") or "").strip() in meeting_ids
        and str(link.get("selectionId") or "").strip()
    }
    if not selection_ids:
        return None
    highest: int | None = None
    for link in links:
        if str(link.get("selectionId") or "").strip() not in selection_ids:
            continue
        try:
            link_index = int(link.get("roundIndex") or 0)
        except (TypeError, ValueError):
            continue
        if highest is None or link_index > highest:
            highest = link_index
    return highest


def _latest_closed_exhausted_round(
    team_id: str, question_id: str
) -> dict[str, Any] | None:
    """The fan-in latest hypothesis round once the hard budget is spent."""
    rounds = _question_hypothesis_rounds(team_id, question_id)
    latest = rounds[-1] if rounds else None
    if not latest or str(latest.get("status") or "").strip().lower() != "closed":
        return None
    raw_index = latest.get("roundIndex")
    if raw_index is None:
        # Generated round records carry no roundIndex of their own; fall
        # back to the review-round lineage links.  No link match stays
        # fail-closed (None) instead of collapsing to round 0 and silently
        # disabling budget-exhaustion adjudication forever.
        round_index = _round_index_from_review_links(team_id, question_id, latest)
        if round_index is None:
            return None
    else:
        try:
            round_index = int(raw_index)
        except (TypeError, ValueError):
            return None
    if round_index < HARD_ROUND_LIMIT:
        return None
    return latest


def _auto_adjudication_idempotency_key(round_id: str) -> str:
    return f"hf2:auto-adjudication:{str(round_id or '').strip()}"


def _auto_adjudication_rejected_key(round_id: str) -> str:
    """Distinct key for the auto-recorded rejected (gate-blocked) outcome."""
    return f"hf2:auto-adjudication-rejected:{str(round_id or '').strip()}"


def _claim_gate_block_reason(exc: ClaimBeliefGateBlockedError) -> str:
    """The stable gate reason carried by the blocked verdict's blockers."""
    for blocker in list(getattr(exc, "blockers", None) or []):
        if isinstance(blocker, Mapping) and str(blocker.get("reason") or "").strip():
            return str(blocker["reason"]).strip()
    return "claim_belief_gate_blocked"


def auto_adjudicate_exhausted_round(
    team_id: str,
    *,
    question_id: str,
) -> dict[str, Any]:
    """Record the missing accepted adjudication for an exhausted review round.

    Budget-exhaustion auto-advance, step one.  Fires only when the question's
    latest HypothesisRound is ``closed`` with ``roundIndex >= HARD_ROUND_LIMIT``,
    no adjudication exists for it yet, and no collection request is still
    pending (the same pending-collection clause that blocks an accepted
    adjudication in the convergence read model).  The appended record is the
    ordinary convergence authority: deterministic rationale (no timestamps),
    idempotency key ``hf2:auto-adjudication:<roundId>`` and
    ``decidedBy=system:auto-advance:budget-exhausted`` keep replays returning
    ``reused`` forever.  A pre-existing human (or foreign-policy) adjudication
    is never overwritten — ``skipped``.

    Claim-belief hard gate: the gate keeps its fail-closed semantics (blocked
    never reaches the formal path), but per the challenge-cup retention policy
    the chain must still land in a terminal state with a formal result record.
    A blocked gate therefore auto-records a REJECTED adjudication
    (``hf2:auto-adjudication-rejected:<roundId>``,
    ``system:auto-advance:gate-blocked`` — rejecting is never gated, so this
    cannot self-lock) and returns ``rejected``; the projection flips to
    completed/rejected/terminal and the exhausted anomaly item disappears,
    while the re-selection unlock stays the existing human path.  Only the
    gate-blocked failure records an outcome — transient errors (storage etc.)
    return ``failed`` with no record so the sweep can retry.  No exception
    ever escapes this helper.
    """
    from core.web.services import team_service

    round_id = ""
    round_index = 0
    normalized_team_id = team_id
    normalized_question_id = str(question_id or "").strip().upper()
    try:
        normalized_team_id = team_service.assert_team_exists(team_id)
        latest_round = _latest_closed_exhausted_round(
            normalized_team_id, normalized_question_id
        )
        if latest_round is None:
            return {"status": "skipped", "reason": "round_not_exhausted"}
        round_id = str(latest_round.get("roundId") or "").strip()
        try:
            round_index = int(latest_round.get("roundIndex") or 0)
        except (TypeError, ValueError):
            round_index = 0
        idempotency_key = _auto_adjudication_idempotency_key(round_id)
        existing = _latest_round_adjudication(
            _records(normalized_team_id),
            question_id=normalized_question_id,
            round_id=round_id,
        )
        if existing is not None:
            existing_key = str(existing.get("idempotencyKey") or "")
            if existing_key == _auto_adjudication_rejected_key(round_id):
                # Our rejected outcome is already the recorded terminal
                # result; replays report reused and never flip it to accepted
                # (a repaired claim re-opens through the human selection
                # path, not by overwriting this verdict).
                return {
                    "status": "reused",
                    "reason": "claim_belief_gate_blocked",
                    "roundId": round_id,
                    "decision": "rejected",
                }
            if existing_key != idempotency_key:
                return {
                    "status": "skipped",
                    "reason": "adjudication_exists",
                    "roundId": round_id,
                    "decision": str(existing.get("decision") or ""),
                }
        if _pending_handoff_count(normalized_team_id, normalized_question_id):
            return {
                "status": "skipped",
                "reason": "pending_collection",
                "roundId": round_id,
            }
        result = record_human_adjudication(
            normalized_team_id,
            question_id=normalized_question_id,
            hypothesis_round_id=round_id,
            decision="accepted",
            rationale=(
                "auto-advance: review round budget exhausted "
                f"({round_index}/{HARD_ROUND_LIMIT}); auto-advanced per "
                "budget-exhaustion policy"
            ),
            idempotency_key=idempotency_key,
            decided_by="system:auto-advance:budget-exhausted",
        )
        status = str(result.get("status") or "")
        adjudication = result.get("adjudication")
        _record_scene_event(
            "hypothesis_first.auto_adjudication",
            outcome=status,
            fields={
                "teamId": normalized_team_id,
                "questionId": normalized_question_id,
                "roundId": round_id,
                "roundIndex": round_index,
                "adjudicationId": str(
                    (adjudication or {}).get("adjudicationId") or ""
                )
                if isinstance(adjudication, Mapping)
                else "",
            },
        )
        return {
            "status": status,
            "roundId": round_id,
            "decision": "accepted",
            "adjudicationId": str(
                (adjudication or {}).get("adjudicationId") or ""
            )
            if isinstance(adjudication, Mapping)
            else "",
        }
    except ClaimBeliefGateBlockedError as exc:
        # Fail-closed hard gate: the recommended candidate must not reach the
        # formal path.  The gate verdict is final for this chain, so the
        # formal failure outcome is recorded right here (challenge-cup
        # retention policy: even a rejected convergence must leave a
        # queryable result, not a dangling human wait).
        gate_reason = _claim_gate_block_reason(exc)
        _record_scene_event(
            "hypothesis_first.auto_adjudication",
            outcome="blocked_by_claim_gate",
            level="warning",
            fields={
                "teamId": normalized_team_id,
                "questionId": normalized_question_id,
                "roundId": round_id,
                "candidateId": str(getattr(exc, "candidate_id", "") or ""),
                "reason": "claim_belief_gate_blocked",
                "gateReason": gate_reason,
                "error": str(exc)[:400],
            },
        )
        try:
            result = record_human_adjudication(
                normalized_team_id,
                question_id=normalized_question_id,
                hypothesis_round_id=round_id,
                decision="rejected",
                rationale=(
                    "auto-advance: claim belief gate blocked "
                    f"({gate_reason}); review round budget exhausted "
                    f"({round_index}/{HARD_ROUND_LIMIT}); unconverged outcome "
                    "recorded per challenge-cup retention policy"
                ),
                idempotency_key=_auto_adjudication_rejected_key(round_id),
                decided_by="system:auto-advance:gate-blocked",
            )
        except Exception as record_exc:  # noqa: BLE001 - stay retryable
            # Even the outcome record failed (transient): leave nothing
            # behind so the sweep can retry the whole advance.
            _record_scene_event(
                "hypothesis_first.auto_adjudication",
                outcome="failed",
                level="warning",
                fields={
                    "teamId": normalized_team_id,
                    "questionId": normalized_question_id,
                    "roundId": round_id,
                    "reason": "claim_belief_gate_blocked",
                    "rejectedRecordError": str(record_exc)[:400],
                },
            )
            return {
                "status": "failed",
                "reason": "claim_belief_gate_blocked",
                "detail": str(record_exc)[:200],
            }
        rejected_status = str(result.get("status") or "")
        adjudication = result.get("adjudication")
        _record_scene_event(
            "hypothesis_first.auto_adjudication",
            outcome=rejected_status,
            fields={
                "teamId": normalized_team_id,
                "questionId": normalized_question_id,
                "roundId": round_id,
                "roundIndex": round_index,
                "decision": "rejected",
                "gateReason": gate_reason,
            },
        )
        return {
            # A fresh rejected outcome reads as "rejected"; replays read as
            # the ordinary idempotent "reused".
            "status": "rejected" if rejected_status == "created" else rejected_status,
            "reason": "claim_belief_gate_blocked",
            "roundId": round_id,
            "decision": "rejected",
            "adjudicationId": str(
                (adjudication or {}).get("adjudicationId") or ""
            )
            if isinstance(adjudication, Mapping)
            else "",
        }
    except Exception as exc:  # noqa: BLE001 - auto-advance is best-effort
        _record_scene_event(
            "hypothesis_first.auto_adjudication",
            outcome="failed",
            level="warning",
            fields={
                "teamId": normalized_team_id,
                "questionId": normalized_question_id,
                "roundId": round_id,
                "reason": type(exc).__name__,
                "error": str(exc)[:400],
            },
        )
        return {
            "status": "failed",
            "reason": type(exc).__name__,
            "detail": str(exc)[:200],
        }


def _formal_run_safety_limits() -> dict[str, Any]:
    """The create-formal-run safety limits (fresh copy per call).

    Stage token capacity must come from the shared budget contract (the 2M
    calibrated authority), never a copied literal: readiness compares
    run-cumulative settled usage against this frozen limit, and a stale
    smaller value false-rejects after 1-2 real nodes.
    """
    from .budget_contract import DEFAULT_STAGE_TOKENS, FORMAL_STAGE_IDS

    return {
        "stageTokens": {
            stage: DEFAULT_STAGE_TOKENS for stage in FORMAL_STAGE_IDS
        },
        "toolCalls": 300,
        "wallClockSeconds": 21_600,
        "maxRetries": 2,
    }


def _stage_one_catalog_run_authorization(
    team_id: str, question_id: str
) -> dict[str, Any] | None:
    """Durable catalog authorization for stage-one policy-covered questions.

    Returns ``None`` (no authorization needed) for uncovered questions;
    raises ``ChallengeCupRealBatchError`` when a covered question has no
    current authorization — callers translate that into their own structured
    failure.  Same pattern as ``_create_stage_one_question_run``.
    """
    from core.research.competition.stage_one_completion_policy import (
        STAGE_ONE_POLICY_QUESTION_IDS,
    )

    if str(question_id or "").strip().upper() not in STAGE_ONE_POLICY_QUESTION_IDS:
        return None
    from core.web.services.team_workflow import challenge_cup_real_batch

    return challenge_cup_real_batch._current_catalog_run_authorization(
        team_id,
        "real-1",
    )


def _question_non_archived_formal_run_exists(
    team_id: str, question_id: str
) -> bool | None:
    """Whether the question already owns a live formal run.

    Mirrors the ``formal_phase is None`` clause of the v2
    ``create_formal_run`` offer (non-archived runs only).  ``None`` means the
    formal read runtime is unavailable, so the guard cannot answer — callers
    must skip rather than risk a duplicate creation.
    """
    from .formal_read_runtime import get_query_service

    try:
        query_service = get_query_service()
        payload = query_service.list_runs(
            team_id=team_id, workflow_id=CHALLENGE_CUP_WORKFLOW_ID
        )
    except Exception:  # noqa: BLE001 - formal runtime absent (command line)
        return None
    normalized_question_id = str(question_id or "").strip().upper()
    return any(
        isinstance(run, Mapping)
        and str(run.get("questionId") or "").strip().upper()
        == normalized_question_id
        and str(run.get("status") or "").strip().lower() != "archived"
        for run in list((payload or {}).get("runs") or [])
    )


def auto_create_formal_run_after_convergence(
    team_id: str,
    *,
    question_id: str,
) -> dict[str, Any]:
    """Create + auto-start the formal run behind a converged review chain.

    Budget-exhaustion auto-advance, step two (safe to call standalone).  The
    guard mirrors the v2 ``create_formal_run`` offer projection exactly: the
    latest round holds an accepted adjudication, no collection request is
    pending, the claim-belief hard gate allows the confirmed candidate, the
    question owns no live formal run yet, and the recommended candidate id is
    present.  The action reuses the exact ``create_formal_run`` command
    channel — ``create_question_run`` plus ``_auto_start_created_formal_run``
    (the start rides its own offer gate; readiness is never bypassed) — with
    the deterministic idempotency key
    ``hf2:auto-formal-run:<questionId>:<roundId>``.  Stage-one policy-covered
    questions carry the durable CatalogRunAuthorization like the
    ``_create_stage_one_question_run`` precedent; a missing authorization or
    an authorization replay mismatch is a structured ``failed`` plus scene
    event, never a raise.
    """
    from core.web.services import team_service

    from core.web.services.team_workflow.research_runtime.run_creation import (
        create_question_run,
    )
    from .service import ResearchWorkflowError

    try:
        normalized_team_id = team_service.assert_team_exists(team_id)
        normalized_question_id = str(question_id or "").strip().upper()
        rounds = _question_hypothesis_rounds(
            normalized_team_id, normalized_question_id
        )
        latest_round = rounds[-1] if rounds else None
        round_id = str((latest_round or {}).get("roundId") or "").strip()
        if (
            not round_id
            or str((latest_round or {}).get("status") or "").strip().lower()
            != "closed"
        ):
            return {"status": "skipped", "reason": "no_closed_round"}
        adjudication = _latest_round_adjudication(
            _records(normalized_team_id),
            question_id=normalized_question_id,
            round_id=round_id,
        )
        if (
            adjudication is None
            or str(adjudication.get("decision") or "").strip().lower()
            != "accepted"
        ):
            return {"status": "skipped", "reason": "no_accepted_adjudication"}
        if _pending_handoff_count(normalized_team_id, normalized_question_id):
            return {
                "status": "skipped",
                "reason": "pending_collection",
                "roundId": round_id,
            }
        meta_review = (
            latest_round.get("metaReview")
            if isinstance(latest_round.get("metaReview"), Mapping)
            else {}
        )
        confirmed_candidate_id = str(
            meta_review.get("recommendationCandidateId") or ""
        ).strip()
        if not confirmed_candidate_id:
            return {
                "status": "skipped",
                "reason": "confirmed_candidate_missing",
                "roundId": round_id,
            }
        gate_verdict = evaluate_claim_belief_gate(
            normalized_team_id,
            normalized_question_id,
            [confirmed_candidate_id],
        ).get(confirmed_candidate_id) or _blocked_gate_verdict(
            confirmed_candidate_id, "claim_belief_evaluation_failed"
        )
        if str(gate_verdict.get("status") or "") != "allowed":
            return {
                "status": "skipped",
                "reason": "claim_belief_gate_not_allowed",
                "roundId": round_id,
                "gateReason": str(gate_verdict.get("reason") or ""),
            }
        formal_run_exists = _question_non_archived_formal_run_exists(
            normalized_team_id, normalized_question_id
        )
        if formal_run_exists is None:
            return {"status": "skipped", "reason": "formal_runtime_unavailable"}
        if formal_run_exists:
            return {
                "status": "skipped",
                "reason": "formal_run_exists",
                "roundId": round_id,
            }
        idempotency_key = f"hf2:auto-formal-run:{normalized_question_id}:{round_id}"
        authorization = _stage_one_catalog_run_authorization(
            normalized_team_id, normalized_question_id
        )
        result = create_question_run(
            CHALLENGE_CUP_WORKFLOW_ID,
            team_id=normalized_team_id,
            question_id=normalized_question_id,
            safety_limits=_formal_run_safety_limits(),
            idempotency_key=idempotency_key,
            formal_hypothesis_round_id=round_id,
            catalog_run_authorization=authorization,
        )
        run_id = (
            str(result.get("runId") or "").strip()
            if isinstance(result, Mapping)
            else ""
        )
        if run_id:
            # Same channel as the create_formal_run command: the entry
            # start_node rides the offer gate; readiness-blocked offers keep
            # the historical wait-for-manual-start behavior.
            _auto_start_created_formal_run(
                normalized_team_id,
                run=result,
                idempotency_key=idempotency_key,
            )
        _record_scene_event(
            "hypothesis_first.auto_formal_run",
            outcome="created",
            fields={
                "teamId": normalized_team_id,
                "questionId": normalized_question_id,
                "roundId": round_id,
                "runId": run_id,
            },
        )
        return {"status": "created", "roundId": round_id, "runId": run_id}
    except Exception as exc:  # noqa: BLE001 - auto-advance is best-effort
        # Run-creation contract errors (catalog_run_authorization_required /
        # catalog_run_authorization_replay_mismatch / idempotency_conflict)
        # and the real-batch authorization lookup keep their stable codes;
        # everything else degrades to the exception type name.
        from core.web.services.team_workflow.challenge_cup_real_batch import (
            ChallengeCupRealBatchError,
        )

        reason = (
            str(getattr(exc, "code", "") or "")
            if isinstance(exc, (ResearchWorkflowError, ChallengeCupRealBatchError))
            else type(exc).__name__
        )
        _record_scene_event(
            "hypothesis_first.auto_formal_run",
            outcome="failed",
            level="warning",
            fields={
                "teamId": team_id,
                "questionId": str(question_id or "").strip().upper(),
                "reason": reason or type(exc).__name__,
                "error": str(exc)[:400],
            },
        )
        return {
            "status": "failed",
            "reason": reason or type(exc).__name__,
            "detail": str(exc)[:200],
        }


# Transient readiness verdict the auto-advance loop itself resolves: a formal
# run node lands blocked with this problem code when the hypothesis review
# meeting had not closed yet at start time.  The in-place auto-advance closes
# the meeting; this constant gates which blocked runs the auto-retry may
# touch — every other blocked code is a real readiness gap or a human problem
# and stays manual (command_offers/retry_node.py reads the same verdict).
AUTO_ADVANCE_NOT_READY_CODE = "auto_advance_not_ready"


def _latest_auto_advance_blocked_attempt(
    store: Any,
    run_id: str,
) -> tuple[str, dict[str, Any]] | None:
    """Newest ``(nodeId, problem)`` blocked on ``auto_advance_not_ready``.

    Reads node-attempt problem JSON straight from the workflow ledger — the
    same truth the graph dispatch worker wrote when the run landed blocked.
    Only a node whose *latest* attempt (same latest-per-node resolution the
    retry offer builder uses) is blocked with exactly this transient code
    qualifies: a newer attempt that re-blocked on a different problem means
    the run moved on and must not be auto-retried.  ``None`` means no node
    qualifies, so the caller must not touch the run.
    """
    latest_by_node: dict[str, tuple[int, int, Any]] = {}
    for attempt in store.list_attempts(run_id):
        node_id = str(getattr(attempt, "node_id", "") or "").strip()
        if not node_id:
            continue
        key = (
            int(getattr(attempt, "attempt", 0) or 0),
            int(getattr(attempt, "updated_at_ms", 0) or 0),
        )
        current = latest_by_node.get(node_id)
        # Per-node latest resolves by attempt number first, exactly like the
        # retry offer builder's latest-per-node resolution.
        if current is None or key > (current[0], current[1]):
            latest_by_node[node_id] = (key[0], key[1], attempt)
    best_key: tuple[int, int] | None = None
    best: tuple[str, dict[str, Any]] | None = None
    for node_id, (_attempt_no, updated_at_ms, attempt) in latest_by_node.items():
        if str(getattr(attempt, "status", "") or "").strip() != "blocked":
            continue
        try:
            problem = json.loads(
                str(getattr(attempt, "problem_json", "") or "") or "{}"
            )
        except (TypeError, ValueError):
            continue
        if not isinstance(problem, Mapping):
            continue
        if str(problem.get("code") or "").strip() != AUTO_ADVANCE_NOT_READY_CODE:
            continue
        # Across nodes the wall-clock recency of the block decides: the most
        # recently blocked node is the deepest chain position to advance.
        key = (updated_at_ms, _attempt_no)
        if best_key is None or key > best_key:
            best_key = key
            best = (node_id, dict(problem))
    return best


def auto_retry_blocked_formal_nodes(
    team_id: str,
    *,
    question_id: str,
) -> dict[str, Any]:
    """Auto-retry formal nodes blocked on the transient auto-advance gate.

    Budget-exhaustion auto-advance, step three.  A formal run that auto-starts
    one instant before the hypothesis review meeting closes lands blocked with
    ``auto_advance_not_ready`` — a condition the auto-advance loop itself
    resolves moments later, so the run must not wait for a human retry click.
    This helper enumerates the question's blocked formal runs (same
    ``list_runs`` read as ``_question_non_archived_formal_run_exists``), keeps
    only runs whose latest blocked ledger attempt carries exactly this
    transient code, and submits the retry through the identical offer-gated
    channel as the manual ``retry_formal_node`` action
    (``_submit_formal_v2_command``): the offer projection is re-read at submit
    time and its own ``offer:{runId}:{nodeId}:retry_node:...`` idempotency key
    is reused, so an offer that readiness still blocks (or a stale run
    version) ends as a structured wait and the next maintenance tick retries —
    readiness is never bypassed.  Best-effort: nothing raises; every outcome
    is counted and recorded as a scene event.
    """
    normalized_question_id = str(question_id or "").strip().upper()
    summary: dict[str, Any] = {
        "blockedRuns": 0,
        "retried": 0,
        "skipped": 0,
        "ineligible": 0,
        "failed": 0,
    }
    try:
        from .formal_read_runtime import get_query_service

        payload = get_query_service().list_runs(
            team_id=team_id, workflow_id=CHALLENGE_CUP_WORKFLOW_ID
        )
    except Exception:  # noqa: BLE001 - formal runtime absent (command line)
        return summary
    from .runtime_factory import production_workflow_runtime

    runtime = production_workflow_runtime()
    if runtime is None:
        return summary
    blocked_runs = [
        run
        for run in list((payload or {}).get("runs") or [])
        if isinstance(run, Mapping)
        and str(run.get("questionId") or "").strip().upper()
        == normalized_question_id
        and str(run.get("status") or "").strip().lower() == "blocked"
    ]
    for run in blocked_runs:
        summary["blockedRuns"] += 1
        run_id = str(run.get("runId") or "").strip()
        if not run_id:
            continue
        try:
            target = _latest_auto_advance_blocked_attempt(runtime.store, run_id)
            if target is None:
                # Blocked on a real readiness gap or a human problem: the
                # auto-retry never touches this run.
                summary["ineligible"] += 1
                continue
            node_id, _problem = target
            _submit_formal_v2_command(
                team_id,
                run_id=run_id,
                node_id=node_id,
                command="retry_node",
                # Retry offers carry their own idempotency key and
                # _submit_formal_v2_command always submits with it; this
                # deterministic value only satisfies the signature.
                idempotency_key=f"hf2:auto-retry:{run_id}:{node_id}",
            )
        except HypothesisFirstChainError as exc:
            # The offer gate kept the retry out: readiness still blocks the
            # offer or the run version moved on.  Wait for the next tick.
            summary["skipped"] += 1
            _record_scene_event(
                "hypothesis_first.auto_retry_formal_node",
                outcome="waited_for_offer",
                fields={
                    "teamId": team_id,
                    "questionId": normalized_question_id,
                    "runId": run_id,
                    "reason": str(exc)[:200],
                },
            )
        except Exception as exc:  # noqa: BLE001 - one broken run is isolated
            summary["failed"] += 1
            _record_scene_event(
                "hypothesis_first.auto_retry_formal_node",
                outcome="failed",
                level="warning",
                fields={
                    "teamId": team_id,
                    "questionId": normalized_question_id,
                    "runId": run_id,
                    "reason": type(exc).__name__,
                    "error": str(exc)[:400],
                },
            )
        else:
            summary["retried"] += 1
            _record_scene_event(
                "hypothesis_first.auto_retry_formal_node",
                outcome="submitted",
                fields={
                    "teamId": team_id,
                    "questionId": normalized_question_id,
                    "runId": run_id,
                    "nodeId": node_id,
                },
            )
    return summary


def _auto_approve_digest_ttl_ms() -> int:
    """Configured auto-approve wait TTL; the env override is clamped to >=60s."""

    raw = str(os.environ.get(_AUTO_APPROVE_DIGEST_TTL_OVERRIDE_ENV) or "").strip()
    if raw:
        try:
            normalized = int(raw)
        except ValueError:
            normalized = 0
        if normalized > 0:
            return max(normalized, AUTO_APPROVE_DIGEST_TTL_MIN_MS)
    return DEFAULT_AUTO_APPROVE_DIGEST_TTL_MS


def _auto_regen_round_grace_ms() -> int:
    """Configured missing-round grace; the env override is clamped to >=0."""

    raw = str(os.environ.get(_AUTO_REGEN_ROUND_GRACE_OVERRIDE_ENV) or "").strip()
    if raw:
        try:
            normalized = int(raw)
        except ValueError:
            normalized = -1
        if normalized >= 0:
            return normalized
    return DEFAULT_AUTO_REGEN_ROUND_GRACE_MS


def _auto_retry_handoff_grace_ms() -> int:
    """Configured zombie-handoff grace; the env override is clamped to >=10s."""

    raw = str(os.environ.get(_AUTO_RETRY_HANDOFF_GRACE_OVERRIDE_ENV) or "").strip()
    if raw:
        try:
            normalized = int(raw)
        except ValueError:
            normalized = 0
        if normalized > 0:
            return max(normalized, AUTO_RETRY_HANDOFF_GRACE_MIN_MS)
    return DEFAULT_AUTO_RETRY_HANDOFF_GRACE_MS


def _iso_timestamp_ms(value: Any) -> int | None:
    """Parse one record ISO timestamp into epoch ms (tolerant, fail-open)."""

    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp() * 1000)


def auto_approve_awaiting_review_digests(
    team_id: str,
    *,
    question_id: str,
    now_ms: int | None = None,
) -> dict[str, Any]:
    """Auto-approve stale review digests (auto-advance step zero).

    The digest approval is the last per-round human gate of the
    hypothesis-first chain: every round parks at ``awaiting_approval`` once
    the digest draft lands and waits for the ``approve_summary`` command.
    This helper removes that wait by resolving it exactly the way the manual
    command resolves it — it calls the same ``approve_meeting_digest`` domain
    implementation the ``approve_summary`` command branch reaches, with the
    system identity as ``closed_by`` so the persisted decisions carry
    ``decidedBy=system:auto-approve:review-digest`` and every standard
    closure effect (request_new_evidence collection, fan-in round, deferred
    next review) runs unchanged through the owning services.

    Eligibility is strict, per meeting: the hypothesis-review type only,
    status ``awaiting_approval`` for this question, a real digest draft (a
    non-empty ``summaryDraftError`` or a missing draft is a failure state
    that belongs to the stuck-digest recovery, never to an approval), and an
    ``updatedAt`` older than the configured TTL.  No offer/idempotency layer
    is re-invented: the closure is idempotent on its closure hash and a
    meeting that closed in the meantime is rejected by the domain status
    assertion, so a replay can never approve twice.

    Best-effort like every auto-advance helper: nothing raises, each meeting
    is isolated, and every outcome lands as a
    ``hypothesis_first.auto_approve_review_digest`` scene event.
    """
    normalized_team_id = str(team_id or "").strip()
    normalized_question_id = str(question_id or "").strip().upper()
    summary: dict[str, Any] = {
        "awaitingApproval": 0,
        "approved": 0,
        "reused": 0,
        "skipped": 0,
        "failed": 0,
    }
    if not normalized_team_id or not normalized_question_id:
        return summary
    try:
        from core.web.services.team_workflow import meeting_rounds

        meetings = list(
            meeting_rounds.list_meeting_rounds(
                normalized_team_id, status="awaiting_approval"
            )["meetings"]
        )
    except Exception:  # noqa: BLE001 - enumeration outages stay invisible
        return summary
    now_value = int(now_ms if now_ms is not None else time.time() * 1000)
    ttl_ms = _auto_approve_digest_ttl_ms()
    for meeting in meetings:
        if not isinstance(meeting, Mapping):
            continue
        if (
            str(meeting.get("meetingType") or "").strip().lower()
            != HYPOTHESIS_REVIEW_MEETING_TYPE
        ):
            # Only hypothesis-review rounds own the digest approval gate;
            # other meeting types keep their own lifecycle owners.
            continue
        if (
            str(meeting.get("question") or "").strip().upper()
            != normalized_question_id
        ):
            continue
        summary["awaitingApproval"] += 1
        meeting_round_id = str(meeting.get("meetingRoundId") or "").strip()
        fields = {
            "teamId": normalized_team_id,
            "questionId": normalized_question_id,
            "meetingRoundId": meeting_round_id,
            "ttlMs": ttl_ms,
        }
        draft = (
            dict(meeting.get("digestDraft"))
            if isinstance(meeting.get("digestDraft"), Mapping)
            else {}
        )
        if str(meeting.get("summaryDraftError") or "").strip():
            summary["skipped"] += 1
            _record_scene_event(
                "hypothesis_first.auto_approve_review_digest",
                outcome="skipped",
                fields={**fields, "reason": "summary_draft_error"},
            )
            continue
        content_hash = str(draft.get("contentHash") or "").strip()
        if not content_hash:
            summary["skipped"] += 1
            _record_scene_event(
                "hypothesis_first.auto_approve_review_digest",
                outcome="skipped",
                fields={**fields, "reason": "digest_missing"},
            )
            continue
        updated_at_ms = _iso_timestamp_ms(meeting.get("updatedAt"))
        if updated_at_ms is None:
            summary["skipped"] += 1
            _record_scene_event(
                "hypothesis_first.auto_approve_review_digest",
                outcome="skipped",
                fields={**fields, "reason": "unreadable_updated_at"},
            )
            continue
        digest_age_ms = max(now_value - updated_at_ms, 0)
        if digest_age_ms < ttl_ms:
            summary["skipped"] += 1
            _record_scene_event(
                "hypothesis_first.auto_approve_review_digest",
                outcome="skipped",
                fields={
                    **fields,
                    "digestAgeMs": digest_age_ms,
                    "reason": "within_ttl",
                },
            )
            continue
        try:
            result = approve_meeting_digest(
                normalized_team_id,
                meeting_round_id,
                closed_by=AUTO_APPROVE_REVIEW_DIGEST_CLOSED_BY,
                expected_digest_content_hash=content_hash,
            )
        except HypothesisFirstChainError as exc:
            # The domain gate kept the approval out (status moved on, digest
            # regenerated between the read and the approve): a structured
            # wait, never an error — the next tick re-reads fresh state.
            summary["skipped"] += 1
            _record_scene_event(
                "hypothesis_first.auto_approve_review_digest",
                outcome="skipped",
                fields={
                    **fields,
                    "digestAgeMs": digest_age_ms,
                    "reason": str(exc)[:200],
                },
            )
        except Exception as exc:  # noqa: BLE001 - one broken meeting is isolated
            summary["failed"] += 1
            _record_scene_event(
                "hypothesis_first.auto_approve_review_digest",
                outcome="failed",
                level="warning",
                fields={
                    **fields,
                    "digestAgeMs": digest_age_ms,
                    "reason": type(exc).__name__,
                    "error": str(exc)[:400],
                },
            )
        else:
            status = str(result.get("status") or "")
            if status == "awaiting_approval":
                # Every drafted evidence request failed validation, so the
                # digest cannot close as-is: regenerate/human owns it now.
                summary["skipped"] += 1
                _record_scene_event(
                    "hypothesis_first.auto_approve_review_digest",
                    outcome="skipped",
                    fields={
                        **fields,
                        "digestAgeMs": digest_age_ms,
                        "reason": "digest_requests_invalid",
                    },
                )
            elif status in {"created", "reused"}:
                summary["approved" if status == "created" else "reused"] += 1
                _record_scene_event(
                    "hypothesis_first.auto_approve_review_digest",
                    outcome="approved" if status == "created" else "reused",
                    fields={
                        **fields,
                        "digestAgeMs": digest_age_ms,
                        "closedBy": AUTO_APPROVE_REVIEW_DIGEST_CLOSED_BY,
                        # Deterministic identity of the automatic approval
                        # (no timestamps): meetingRoundId + TTL semantics.
                        "rationale": (
                            "auto-approve: hypothesis review digest awaited "
                            f"beyond ttl ({ttl_ms} ms); meeting "
                            f"{meeting_round_id} approved with the standard "
                            "closure chain per auto-advance policy"
                        ),
                    },
                )
            else:
                summary["skipped"] += 1
                _record_scene_event(
                    "hypothesis_first.auto_approve_review_digest",
                    outcome="skipped",
                    fields={
                        **fields,
                        "digestAgeMs": digest_age_ms,
                        "reason": "unexpected_status",
                    },
                )
    return summary


def _round_refs_meeting_ids(round_record: Mapping[str, Any]) -> set[str]:
    """Meeting ids a stored HypothesisRound was generated from.

    ``meetingRefs`` is the only durable round-to-meeting association: round
    records carry no selectionId/roundIndex of their own, but a generated
    round references every bound meeting of its fan-in group here.
    """

    refs = round_record.get("meetingRefs")
    if not isinstance(refs, Sequence) or isinstance(refs, (str, bytes)):
        return set()
    return {
        str(item.get("id") or "").strip()
        for item in refs
        if isinstance(item, Mapping)
        and str(item.get("kind") or "").strip() == "meeting_round"
        and str(item.get("id") or "").strip()
    }


def _missing_round_plans_for_question(
    team_id: str,
    *,
    question_id: str,
    now_ms: int,
    grace_ms: int,
) -> list[dict[str, Any]]:
    """Detect per selection chain: newest review round closed but roundless.

    One plan per selection whose newest link round ``N`` satisfies all of:
    every latest-attempt meeting at round ``N`` is closed, the newest closure
    is older than ``grace_ms`` (a close still running its synchronous fan-in
    generation must never be raced), and no stored HypothesisRound references
    any round-``N`` meeting.  A plan that fails a guard returns its skip
    reason instead; the caller reports only the decisive outcomes.
    """

    from core.web.services.team_workflow import meeting_rounds

    links = [
        dict(item)
        for item in list_review_round_links(team_id, question_id=question_id).get(
            "links"
        )
        or []
        if isinstance(item, Mapping) and str(item.get("meetingRoundId") or "").strip()
    ]
    if not links:
        return [{"status": "skipped", "reason": "no_review_links"}]

    by_selection: dict[str, list[dict[str, Any]]] = {}
    for link in links:
        by_selection.setdefault(str(link.get("selectionId") or "").strip(), []).append(
            link
        )

    stored_rounds = _question_hypothesis_rounds(team_id, question_id)
    stored_meeting_ids: set[str] = set()
    for round_record in stored_rounds:
        if isinstance(round_record, Mapping):
            stored_meeting_ids |= _round_refs_meeting_ids(round_record)

    plans: list[dict[str, Any]] = []
    for selection_id, selection_links in sorted(by_selection.items()):
        for link in selection_links:
            try:
                link["roundIndex"] = int(link.get("roundIndex") or 1)
            except (TypeError, ValueError):
                link["roundIndex"] = 1
        latest_round_index = max(item["roundIndex"] for item in selection_links)
        round_links = [
            item
            for item in selection_links
            if item["roundIndex"] == latest_round_index
        ]
        fields: dict[str, Any] = {
            "teamId": team_id,
            "questionId": question_id,
            "selectionId": selection_id,
            "roundIndex": latest_round_index,
        }
        round_n_meeting_ids = [
            str(item.get("meetingRoundId") or "").strip() for item in round_links
        ]
        # The round id is content-addressed over the whole fan-in group, so a
        # stored round covers every attempt meeting of the round; any overlap
        # means the round landed and nothing is missing.
        if stored_meeting_ids.intersection(round_n_meeting_ids):
            plans.append({**fields, "status": "skipped", "reason": "round_exists"})
            continue
        # Retry attempts append one link per attempt while reusing the same
        # (candidateId, roundIndex) binding; only the newest attempt counts.
        latest_attempt: dict[str, dict[str, Any]] = {}
        for item in round_links:
            candidate = str(item.get("candidateId") or "").strip()
            existing = latest_attempt.get(candidate)
            if existing is None or str(item.get("createdAt") or "") >= str(
                existing.get("createdAt") or ""
            ):
                latest_attempt[candidate] = item
        attempt_links = list(latest_attempt.values())
        if not attempt_links:
            plans.append(
                {**fields, "status": "skipped", "reason": "no_round_meetings"}
            )
            continue
        attempt_meetings: list[dict[str, Any]] = []
        skip_reason = ""
        for item in attempt_links:
            meeting_id = str(item.get("meetingRoundId") or "").strip()
            try:
                meeting = dict(
                    meeting_rounds.get_meeting_round(team_id, meeting_id)[
                        "meetingRound"
                    ]
                )
            except Exception:  # noqa: BLE001 - unreadable state stays a skip
                skip_reason = "meeting_unreadable"
                break
            if str(meeting.get("status") or "").strip().lower() != "closed":
                skip_reason = "review_not_closed"
                break
            closed_at_ms = _iso_timestamp_ms(
                meeting.get("closedAt") or meeting.get("updatedAt")
            )
            if closed_at_ms is None:
                skip_reason = "unreadable_updated_at"
                break
            meeting["closedAtMs"] = closed_at_ms
            attempt_meetings.append(meeting)
        if skip_reason:
            plans.append({**fields, "status": "skipped", "reason": skip_reason})
            continue
        newest_closed_ms = max(
            int(meeting.get("closedAtMs") or 0) for meeting in attempt_meetings
        )
        closed_age_ms = max(now_ms - newest_closed_ms, 0)
        if closed_age_ms < grace_ms:
            plans.append(
                {
                    **fields,
                    "status": "skipped",
                    "reason": "within_grace",
                    "closedAgeMs": closed_age_ms,
                    "graceMs": grace_ms,
                }
            )
            continue
        attempt_meetings.sort(key=lambda item: int(item.get("closedAtMs") or 0))
        plans.append(
            {
                **fields,
                "status": "planned",
                "triggerMeetingRoundId": str(
                    attempt_meetings[-1].get("meetingRoundId") or ""
                ).strip(),
                "meetingRoundIds": [
                    str(meeting.get("meetingRoundId") or "").strip()
                    for meeting in attempt_meetings
                ],
            }
        )
    return plans


def auto_regenerate_missing_hypothesis_round(
    team_id: str,
    *,
    question_id: str,
    now_ms: int | None = None,
) -> dict[str, Any]:
    """Regenerate a HypothesisRound the closure fan-in never landed.

    Auto-advance step between digest approval and adjudication.  The live
    break this closes: :func:`close_review_meeting` persists the meeting
    ``closed`` and only then runs the selection-level round generation
    synchronously through the review LLMs; when that call times out, the
    closure artifacts stand but the round never lands — and with no round,
    no adjudication or convergence gate can ever fire, so the chain
    dead-waits forever.  Detection and action per selection chain: see
    :func:`_missing_round_plans_for_question`; the action reuses the
    existing :func:`regenerate_hypothesis_round` command path unchanged
    (all of its domain assertions and runner resolution stay authoritative),
    so a fan-in that judges siblings unready and an already-stored round are
    domain rejections, not errors.

    Result semantics: ``created`` (a round landed), ``skipped`` (guarded or
    domain-rejected; ``reason`` says which), ``failed`` (generation failed —
    the next sweep pass retries naturally).  Best-effort like every
    auto-advance helper: nothing raises and every outcome lands as a
    ``hypothesis_first.auto_regenerate_round`` scene event.  An in-process
    inflight marker keyed by ``(teamId, questionId)`` keeps a slow
    regeneration (the review-LLM budget is minutes against a 30s sweep
    interval) from being double-triggered for the same question.
    """
    normalized_team_id = str(team_id or "").strip()
    normalized_question_id = str(question_id or "").strip().upper()
    summary: dict[str, Any] = {
        "status": "skipped",
        "reason": "",
        "created": 0,
        "skipped": 0,
        "failed": 0,
    }
    if not normalized_team_id or not normalized_question_id:
        summary["reason"] = "missing_identity"
        return summary
    inflight_key = (normalized_team_id, normalized_question_id)
    inflight_token: object = object()
    if _ROUND_REGEN_INFLIGHT.setdefault(inflight_key, inflight_token) is not (
        inflight_token
    ):
        return {
            "status": "skipped",
            "reason": "already_in_flight",
            "created": 0,
            "skipped": 0,
            "failed": 0,
        }
    try:
        now_value = int(now_ms if now_ms is not None else time.time() * 1000)
        grace_ms = _auto_regen_round_grace_ms()
        try:
            plans = _missing_round_plans_for_question(
                normalized_team_id,
                question_id=normalized_question_id,
                now_ms=now_value,
                grace_ms=grace_ms,
            )
        except Exception as exc:  # noqa: BLE001 - detection stays best-effort
            summary["status"] = "failed"
            summary["reason"] = "detection_failed"
            summary["error"] = str(exc)[:400]
            _record_scene_event(
                "hypothesis_first.auto_regenerate_round",
                outcome="failed",
                level="warning",
                fields={
                    "teamId": normalized_team_id,
                    "questionId": normalized_question_id,
                    "reason": "detection_failed",
                    "errorType": type(exc).__name__,
                    "error": str(exc)[:400],
                },
            )
            return summary
        decisive: dict[str, Any] | None = None
        for plan in plans:
            fields = {
                "teamId": normalized_team_id,
                "questionId": normalized_question_id,
                "selectionId": str(plan.get("selectionId") or ""),
                "roundIndex": plan.get("roundIndex"),
                "graceMs": grace_ms,
            }
            if str(plan.get("status") or "") != "planned":
                summary["skipped"] += 1
                if decisive is None or decisive.get("status") == "skipped":
                    decisive = {
                        "status": "skipped",
                        "reason": str(plan.get("reason") or "unknown"),
                    }
                _record_scene_event(
                    "hypothesis_first.auto_regenerate_round",
                    outcome="skipped",
                    fields={**fields, "reason": str(plan.get("reason") or "")},
                )
                continue
            trigger_meeting_id = str(plan.get("triggerMeetingRoundId") or "").strip()
            plan_fields = {
                **fields,
                "meetingRoundId": trigger_meeting_id,
                "meetingRoundIds": list(plan.get("meetingRoundIds") or []),
            }
            try:
                result = regenerate_hypothesis_round(
                    normalized_team_id, trigger_meeting_id
                )
            except HypothesisFirstChainError as exc:
                # Domain rejection (the meeting moved, the closure state
                # disagrees): a structured wait, never an error.
                summary["skipped"] += 1
                if decisive is None:
                    decisive = {"status": "skipped", "reason": str(exc)[:200]}
                _record_scene_event(
                    "hypothesis_first.auto_regenerate_round",
                    outcome="skipped",
                    fields={**plan_fields, "reason": str(exc)[:200]},
                )
                continue
            except Exception as exc:  # noqa: BLE001 - one plan is isolated
                summary["failed"] += 1
                if decisive is None or decisive.get("status") != "created":
                    decisive = {
                        "status": "failed",
                        "reason": type(exc).__name__,
                        "error": str(exc)[:400],
                    }
                _record_scene_event(
                    "hypothesis_first.auto_regenerate_round",
                    outcome="failed",
                    level="warning",
                    fields={
                        **plan_fields,
                        "reason": type(exc).__name__,
                        "error": str(exc)[:400],
                    },
                )
                continue
            result_status = str(result.get("status") or "")
            if result_status == "created":
                round_record = (
                    result.get("round")
                    if isinstance(result.get("round"), Mapping)
                    else {}
                )
                summary["created"] += 1
                decisive = {
                    "status": "created",
                    "reason": "round_generated",
                    "roundId": str(round_record.get("roundId") or ""),
                }
                _record_scene_event(
                    "hypothesis_first.auto_regenerate_round",
                    outcome="created",
                    fields={
                        **plan_fields,
                        "roundId": str(round_record.get("roundId") or ""),
                    },
                )
            elif result_status == "reused":
                # The stored round predated detection (or a concurrent winner
                # landed it): the chain has its round either way.
                summary["skipped"] += 1
                decisive = {"status": "skipped", "reason": "round_reused"}
                _record_scene_event(
                    "hypothesis_first.auto_regenerate_round",
                    outcome="skipped",
                    fields={**plan_fields, "reason": "round_reused"},
                )
            elif result_status in {
                "waiting_for_sibling_reviews",
                "generation_in_progress",
            }:
                # Fan-in authority says siblings are not ready, or another
                # trigger is generating the same round: wait for the next pass.
                summary["skipped"] += 1
                decisive = {"status": "skipped", "reason": result_status}
                _record_scene_event(
                    "hypothesis_first.auto_regenerate_round",
                    outcome="skipped",
                    fields={**plan_fields, "reason": result_status},
                )
            elif result_status == "failed":
                # The generation failure trace is already durable (the
                # hypothesis_round_failures ledger); the next sweep retries.
                summary["failed"] += 1
                decisive = {
                    "status": "failed",
                    "reason": "generation_failed",
                    "error": str(result.get("error") or "")[:400],
                }
                _record_scene_event(
                    "hypothesis_first.auto_regenerate_round",
                    outcome="failed",
                    level="warning",
                    fields={
                        **plan_fields,
                        "reason": "generation_failed",
                        "errorType": str(result.get("errorType") or ""),
                        "error": str(result.get("error") or "")[:400],
                    },
                )
            else:
                summary["skipped"] += 1
                decisive = {
                    "status": "skipped",
                    "reason": f"unexpected_status:{result_status}",
                }
                _record_scene_event(
                    "hypothesis_first.auto_regenerate_round",
                    outcome="skipped",
                    fields={**plan_fields, "reason": "unexpected_status"},
                )
        if decisive is not None:
            summary.update(decisive)
        elif not plans:
            summary["reason"] = "no_review_links"
        return summary
    finally:
        if _ROUND_REGEN_INFLIGHT.get(inflight_key) is inflight_token:
            _ROUND_REGEN_INFLIGHT.pop(inflight_key, None)


def auto_retry_pending_collection_handoffs(
    team_id: str,
    *,
    question_id: str,
    now_ms: int | None = None,
) -> dict[str, Any]:
    """Re-run the idempotent handoff for zombie ``handoff_pending`` requests.

    Auto-advance step between round regeneration and adjudication.  The live
    break this closes: ``notify_collection_run_terminal`` runs the collection
    writeback exactly once when a run completes, and a handoff rejection
    there (historically: a review-round link already bound by a sibling
    request's fan-out) parked the request in ``handoff_pending`` forever —
    the run never completes again and no other path retried it, so the
    pending count blocked budget-exhaustion adjudication permanently.  A
    request is retried only when it is still ``handoff_pending`` AND its
    collection run already reached ``completed`` (a running or failed run
    stays owned by collection recovery) AND the configured grace since its
    last attempt has elapsed, so a persistently failing request is
    throttled by the grace instead of being hammered by every 30s sweep.

    The action reuses :func:`record_collection_handoff` unchanged (idempotent
    ``handed_off``/``reused`` semantics, claim materialization, and the
    newest-round guard that keeps a late handoff from stacking another
    round).  Every request is isolated: a domain rejection stays pending and
    retries on the next pass, nothing here raises, and each outcome lands as
    a ``hypothesis_first.auto_retry_handoff`` scene event.
    """
    normalized_team_id = str(team_id or "").strip()
    normalized_question_id = str(question_id or "").strip().upper()
    summary: dict[str, Any] = {
        "status": "skipped",
        "reason": "",
        "retried": 0,
        "skipped": 0,
        "failed": 0,
    }
    if not normalized_team_id or not normalized_question_id:
        summary["reason"] = "missing_identity"
        return summary
    now_value = int(now_ms if now_ms is not None else time.time() * 1000)
    grace_ms = _auto_retry_handoff_grace_ms()
    try:
        requests = [
            record
            for record in _collection_requests(_records(normalized_team_id))
            if str(record.get("questionId") or "").strip().upper()
            == normalized_question_id
        ]
    except Exception as exc:  # noqa: BLE001 - detection stays best-effort
        summary["status"] = "failed"
        summary["reason"] = "detection_failed"
        summary["error"] = str(exc)[:400]
        _record_scene_event(
            "hypothesis_first.auto_retry_handoff",
            outcome="failed",
            level="warning",
            fields={
                "teamId": normalized_team_id,
                "questionId": normalized_question_id,
                "reason": "detection_failed",
                "errorType": type(exc).__name__,
                "error": str(exc)[:400],
            },
        )
        return summary
    for request in requests:
        request_id = str(request.get("requestId") or "").strip()
        if not request_id:
            continue
        fields = {
            "teamId": normalized_team_id,
            "questionId": normalized_question_id,
            "requestId": request_id,
            "collectionRunId": str(request.get("collectionRunId") or ""),
            "graceMs": grace_ms,
        }
        if str(request.get("status") or "") != "handoff_pending":
            continue
        if str(request.get("collectionRunStatus") or "").strip().lower() != (
            "completed"
        ):
            # The run has not finished (or recovery owns a failed run): the
            # writeback will arrive on its own, retrying here would race it.
            summary["skipped"] += 1
            _record_scene_event(
                "hypothesis_first.auto_retry_handoff",
                outcome="skipped",
                fields={**fields, "reason": "run_not_completed"},
            )
            continue
        last_attempt_ms = _iso_timestamp_ms(
            request.get("lastAutoRetryAt") or request.get("handedOffAt")
        )
        if last_attempt_ms is not None and (
            now_value - last_attempt_ms
        ) < grace_ms:
            summary["skipped"] += 1
            _record_scene_event(
                "hypothesis_first.auto_retry_handoff",
                outcome="skipped",
                fields={**fields, "reason": "within_grace_period"},
            )
            continue
        try:
            # Refresh the attempt timestamp BEFORE the retry so a crashing
            # or hanging handoff still respects the grace on the next pass.
            _update_collection_request(
                normalized_team_id, request_id, lastAutoRetryAt=_utc_now()
            )
            handoff_ref = str(request.get("handoffRef") or "").strip()
            if not handoff_ref:
                run_id = str(request.get("collectionRunId") or "").strip()
                handoff_ref = (
                    f"source_collection_run:{run_id}" if run_id else ""
                )
            result = record_collection_handoff(
                normalized_team_id,
                request_id,
                handoff_ref=handoff_ref,
            )
        except HypothesisFirstChainError as exc:
            # Domain rejection (a guard disagrees): restore the pending
            # state the writeback would have left — the handoff already
            # flipped the record to handed_off before the rejection fired —
            # so the request stays visibly retryable on the next pass.
            summary["failed"] += 1
            try:
                _update_collection_request(
                    normalized_team_id,
                    request_id,
                    status="handoff_pending",
                    handoffError={
                        "code": "handoff_failed",
                        "message": str(exc)[:500],
                    },
                )
            except Exception:  # noqa: BLE001 - never mask the handoff error
                pass
            _record_scene_event(
                "hypothesis_first.auto_retry_handoff",
                outcome="failed",
                fields={
                    **fields,
                    "reason": "domain_rejected",
                    "error": str(exc)[:400],
                },
            )
            continue
        except Exception as exc:  # noqa: BLE001 - one request is isolated
            summary["failed"] += 1
            try:
                _update_collection_request(
                    normalized_team_id,
                    request_id,
                    status="handoff_pending",
                    handoffError={
                        "code": "handoff_failed",
                        "message": str(exc)[:500],
                    },
                )
            except Exception:  # noqa: BLE001 - never mask the retry error
                pass
            _record_scene_event(
                "hypothesis_first.auto_retry_handoff",
                outcome="failed",
                level="warning",
                fields={
                    **fields,
                    "reason": type(exc).__name__,
                    "error": str(exc)[:400],
                },
            )
            continue
        result_status = str(result.get("status") or "")
        if result_status in {"handed_off", "reused"}:
            summary["retried"] += 1
            _record_scene_event(
                "hypothesis_first.auto_retry_handoff",
                outcome="retried",
                fields={**fields, "handoffStatus": result_status},
            )
        else:
            summary["skipped"] += 1
            _record_scene_event(
                "hypothesis_first.auto_retry_handoff",
                outcome="skipped",
                fields={
                    **fields,
                    "reason": f"unexpected_status:{result_status}",
                },
            )
    if summary["retried"]:
        summary["status"] = "retried"
    elif summary["failed"]:
        summary["status"] = "failed"
    return summary


def auto_accept_knowledge_handoffs(
    team_id: str,
    *,
    question_id: str,
) -> dict[str, Any]:
    """Auto-accept pending ``knowledge_handoff`` human gates on formal runs.

    Budget-exhaustion auto-advance, after formal-run creation (safe to call
    standalone).  The knowledge ingestion governance chain (source review
    accepted -> knowledge review approved -> official sync) is itself the
    human decision, so per operator policy the residual ``knowledge_handoff``
    click is accepted automatically instead of dead-waiting on a human.  The
    helper enumerates the question's non-archived formal runs (the same
    ``list_runs`` read as the auto-retry / auto-create steps) and, per run,
    resolves every pending ``knowledge_handoff`` human task through the exact
    formal command SSOT the manual accept uses
    (``WorkflowCommandKind.RESOLVE_HUMAN_TASK``, deterministic idempotency key
    ``hf2:auto-knowledge-handoff:<runId>:<taskId>``).

    Fail-closed scoping: only ``nodeId == knowledge_handoff`` tasks are
    touched (task kind and the node attempt must both agree); the inbound
    ``e_ingest_handoff`` handoff must carry a ``knowledge_package_draft``
    artifact reference (proof the governed ingestion completed), otherwise the
    task is skipped unsubmitted; and the command service still re-verifies the
    materialized accepted knowledge package at accept time, so a missing
    package ends as a structured skip, never a blind accept.  Every other
    human gate (protocol_freeze / smoke_gate / candidate_promotion) keeps its
    human decision semantics and is never touched.

    Isolation and idempotency: typed command rejections (already resolved,
    stale run version, forbidden, artifact not materialized) count as
    ``skipped`` for the next tick, unexpected errors count as ``failed``, a
    previous auto-accept replayed from the bounded event window counts as
    ``reused``, and nothing here raises.  Every outcome is recorded as a
    ``hypothesis_first.auto_accept_knowledge_handoff`` scene event.
    """
    normalized_question_id = str(question_id or "").strip().upper()
    summary: dict[str, Any] = {
        "runsScanned": 0,
        "pendingTasks": 0,
        "accepted": 0,
        "reused": 0,
        "skipped": 0,
        "failed": 0,
    }
    try:
        from .formal_read_runtime import get_query_service

        payload = get_query_service().list_runs(
            team_id=team_id, workflow_id=CHALLENGE_CUP_WORKFLOW_ID
        )
    except Exception:  # noqa: BLE001 - formal runtime absent (command line)
        return summary
    from .runtime_factory import production_workflow_runtime

    runtime = production_workflow_runtime()
    if runtime is None:
        return summary
    runs = [
        run
        for run in list((payload or {}).get("runs") or [])
        if isinstance(run, Mapping)
        and str(run.get("questionId") or "").strip().upper()
        == normalized_question_id
        and str(run.get("status") or "").strip().lower() != "archived"
    ]
    for run in runs:
        summary["runsScanned"] += 1
        run_id = str(run.get("runId") or "").strip()
        if not run_id:
            continue
        try:
            scan = runtime.store.read(
                lambda repo: _scan_knowledge_handoff_targets(repo, run_id)
            )
        except Exception as exc:  # noqa: BLE001 - one broken run is isolated
            summary["failed"] += 1
            _record_scene_event(
                "hypothesis_first.auto_accept_knowledge_handoff",
                outcome="failed",
                level="warning",
                fields={
                    "teamId": team_id,
                    "questionId": normalized_question_id,
                    "runId": run_id,
                    "reason": type(exc).__name__,
                    "error": str(exc)[:400],
                },
            )
            continue
        # Replays of this sweep's own earlier accepts (bounded event window,
        # same discipline as the snapshot) are reported as reused — the task
        # is already resolved, so there is nothing pending to resubmit.
        for task_id in sorted(scan.get("autoAcceptedTaskIds") or []):
            summary["reused"] += 1
            _record_scene_event(
                "hypothesis_first.auto_accept_knowledge_handoff",
                outcome="reused",
                fields={
                    "teamId": team_id,
                    "questionId": normalized_question_id,
                    "runId": run_id,
                    "taskId": task_id,
                    "reason": "already_auto_accepted",
                },
            )
        for target in scan.get("pendingTargets") or []:
            task_id = str(target.get("taskId") or "")
            summary["pendingTasks"] += 1
            if not target.get("eligible"):
                # The nodeId could not be double-confirmed from the node
                # attempt: fail closed, never guess.
                reason = str(target.get("reason") or "task_not_eligible")
                summary["skipped"] += 1
                _record_scene_event(
                    "hypothesis_first.auto_accept_knowledge_handoff",
                    outcome="skipped",
                    fields={
                        "teamId": team_id,
                        "questionId": normalized_question_id,
                        "runId": run_id,
                        "taskId": task_id,
                        "reason": reason,
                    },
                )
                continue
            if not target.get("draftRefPresent"):
                # Without a knowledge_package_draft reference on the inbound
                # e_ingest_handoff the governance chain has not demonstrably
                # passed — the auto-accept never fires on a guess.
                summary["skipped"] += 1
                _record_scene_event(
                    "hypothesis_first.auto_accept_knowledge_handoff",
                    outcome="skipped",
                    fields={
                        "teamId": team_id,
                        "questionId": normalized_question_id,
                        "runId": run_id,
                        "taskId": task_id,
                        "reason": "artifact_refs_missing",
                    },
                )
                continue
            outcome, reason = _submit_auto_knowledge_handoff_accept(
                runtime,
                team_id=team_id,
                run_id=run_id,
                task_id=task_id,
            )
            summary[outcome] += 1
            _record_scene_event(
                "hypothesis_first.auto_accept_knowledge_handoff",
                outcome=outcome,
                level="warning" if outcome == "failed" else "info",
                fields={
                    "teamId": team_id,
                    "questionId": normalized_question_id,
                    "runId": run_id,
                    "taskId": task_id,
                    "reason": reason,
                },
            )
    return summary


def _scan_knowledge_handoff_targets(repo: Any, run_id: str) -> dict[str, Any]:
    """Read-only scan of one run's knowledge_handoff gate state.

    Returns the pending ``knowledge_handoff`` human tasks (each double-checked
    against its node attempt), whether the latest inbound
    ``e_ingest_handoff`` carries a ``knowledge_package_draft`` artifact
    reference, and the task ids this sweep already auto-accepted earlier
    (``handoff_accepted`` events carrying this sweep's idempotency prefix,
    read through the same bounded head+tail event window as the snapshot).
    """
    # The latest inbound handoff into knowledge_handoff (edge
    # knowledge_ingestion->knowledge_handoff) carries the draft refs bound at
    # agent-commit time; retries leave the newest row authoritative.
    inbound_handoff_id = ""
    for handoff_row in repo.list_handoffs_for_node(
        run_id, KNOWLEDGE_HANDOFF_NODE_ID
    ) or []:
        inbound_handoff_id = str(handoff_row[0] or "")
    draft_ref_present = False
    if inbound_handoff_id:
        for ref_row in repo.list_handoff_artifact_refs_for_run(run_id) or []:
            if str(ref_row[0] or "") != inbound_handoff_id:
                continue
            if str(ref_row[2] or "").startswith(KNOWLEDGE_PACKAGE_DRAFT_KIND):
                draft_ref_present = True
                break
    pending_targets: list[dict[str, Any]] = []
    for row in repo.list_pending_human_tasks(run_id) or []:
        if str(row[4] or "") != KNOWLEDGE_HANDOFF_TASK_KIND:
            # Other human gates (protocol_freeze / smoke_gate / ...) are real
            # human decisions: never selected, never touched.
            continue
        node_run_id = str(row[2] or "")
        attempt = repo.get_attempt(node_run_id) if node_run_id else None
        node_id = str(getattr(attempt, "node_id", "") or "")
        pending_targets.append(
            {
                "taskId": str(row[0] or ""),
                "nodeRunId": node_run_id,
                "handoffId": str(row[3] or ""),
                "eligible": node_id == KNOWLEDGE_HANDOFF_NODE_ID,
                "reason": ""
                if node_id == KNOWLEDGE_HANDOFF_NODE_ID
                else "task_node_unverifiable",
                "draftRefPresent": draft_ref_present,
            }
        )
    auto_accepted_task_ids: set[str] = set()
    latest_sequence = int(repo.latest_event_sequence(run_id) or 0)
    head = repo.list_events(run_id, 0, 250)
    tail = repo.list_events(run_id, max(0, latest_sequence - 250), 500)
    seen: set[tuple[int, str]] = set()
    idempotency_prefix = f"hf2:auto-knowledge-handoff:{run_id}:"
    for event in (*head, *tail):
        key = (
            int(getattr(event, "sequence", 0) or 0),
            str(getattr(event, "event_id", "") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        if str(getattr(event, "event_type", "") or "") != "handoff_accepted":
            continue
        correlation_id = str(getattr(event, "correlation_id", "") or "")
        if not correlation_id.startswith(idempotency_prefix):
            continue
        try:
            event_payload = json.loads(str(getattr(event, "payload_json", "") or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            event_payload = {}
        task_id = str(
            event_payload.get("taskId")
            if isinstance(event_payload, dict)
            else ""
        ).strip()
        if task_id:
            auto_accepted_task_ids.add(task_id)
    return {
        "pendingTargets": pending_targets,
        "draftRefPresent": draft_ref_present,
        "autoAcceptedTaskIds": auto_accepted_task_ids,
    }


def _submit_auto_knowledge_handoff_accept(
    runtime: Any,
    *,
    team_id: str,
    run_id: str,
    task_id: str,
) -> tuple[str, str]:
    """Submit one ``resolve_human_task`` accept through the command SSOT.

    Returns ``(summary_key, reason)`` where ``summary_key`` is ``accepted``,
    ``skipped``, or ``failed``.  The submit runs under a server-bound system
    operator scope (``AUTO_KNOWLEDGE_HANDOFF_ACTOR_ID`` with the operator
    role) because ``resolve_human_task`` is a high-impact command whose
    authorization must come from server context, never a client body; the
    identity mirrors the ``local_control_operator`` control-plane precedent.
    Typed command rejections (already resolved, stale run version, artifact
    not materialized, forbidden, conflict) are structured skips for the next
    tick; anything else is an unexpected failure.
    """

    from core.research.workflow.contracts import (
        ActorRef,
        CommandRequest,
        WorkflowCommandKind,
    )
    from core.research.workflow.ledger import (
        CommandNotAllowedError as LedgerCommandNotAllowedError,
        IdempotencyConflictError as LedgerIdempotencyConflictError,
        RunVersionConflictError as LedgerRunVersionConflictError,
    )

    from .command_service import WorkflowCommandError
    from .ids import new_id
    from .operator_authorization import server_operator_scope

    run = runtime.store.get_run(run_id)
    if run is None or str(run.team_id or "") != team_id:
        return "skipped", "formal_run_unavailable"
    try:
        with server_operator_scope(
            AUTO_KNOWLEDGE_HANDOFF_ACTOR_ID,
            display_name="Auto-advance knowledge handoff acceptance",
            # resolve_human_task is operator-gated; the sweep is a
            # server-internal control-plane caller, so it binds the same
            # privileged role the local control operator carries.
            roles=("operator",),
        ):
            receipt = runtime.command_service.submit(
                CommandRequest(
                    command_id=new_id("cmd"),
                    run_id=run_id,
                    team_id=team_id,
                    command=WorkflowCommandKind.RESOLVE_HUMAN_TASK,
                    node_id=KNOWLEDGE_HANDOFF_NODE_ID,
                    expected_run_version=int(run.run_version),
                    idempotency_key=f"hf2:auto-knowledge-handoff:{run_id}:{task_id}",
                    payload={
                        "taskId": task_id,
                        "decision": "accept",
                        "reason": AUTO_KNOWLEDGE_HANDOFF_REASON,
                    },
                    requested_by=ActorRef(
                        "system", AUTO_KNOWLEDGE_HANDOFF_ACTOR_ID
                    ),
                    requested_at_ms=int(time.time() * 1000),
                )
            )
    except HypothesisFirstChainError as exc:
        return "skipped", str(exc)[:200] or type(exc).__name__
    except (
        WorkflowCommandError,
        LedgerRunVersionConflictError,
        LedgerIdempotencyConflictError,
        LedgerCommandNotAllowedError,
    ) as exc:
        # Typed command rejection (InvalidHumanTaskStateError and friends are
        # WorkflowCommandError subclasses): a structured wait, never a crash.
        return "skipped", str(exc)[:200] or type(exc).__name__
    except Exception as exc:  # noqa: BLE001 - one submit is isolated
        return "failed", f"{type(exc).__name__}: {str(exc)[:180]}"
    receipt_status = ""
    try:
        receipt_payload = receipt.to_dict()
        receipt_status = str(receipt_payload.get("status") or "")
    except Exception:  # noqa: BLE001 - receipt shape is advisory only
        receipt_status = ""
    if receipt_status == "rejected":
        return "skipped", "command_rejected_by_runtime"
    return "accepted", f"resolve_human_task:{receipt_status or 'submitted'}"


def sweep_auto_advance_closure() -> dict[str, Any]:
    """Maintenance sweep: auto-advance every exhausted hypothesis chain.

    Restart-time recovery for chains stuck at an auto-advance gate (the
    closing tick may be long gone by the time this runs).  Enumerates the
    team ids that own a hypothesis-first chain ledger read-only, then walks
    each question through approve -> regenerate -> retry-handoffs ->
    adjudicate -> create -> accept-knowledge-handoffs -> retry: review
    digests that waited beyond the TTL
    get approved and closed first (so the fan-in / next-round advance can
    still progress within the same pass), a newest review round whose fan-in
    round generation never landed (the closure LLM died mid-close) gets its
    HypothesisRound regenerated before anything downstream could block on
    it, zombie collection requests parked in ``handoff_pending`` by a
    once-failed writeback get their idempotent handoff retried past the
    grace (unblocking the pending count in the same pass), exhausted rounds
    get their accepted adjudication, converged chains get the formal run
    created and started, and formal nodes blocked on the transient
    ``auto_advance_not_ready`` gate get their offer-gated retry resubmitted.
    Nothing here raises: one broken team or question is isolated and
    counted; questions whose latest round is not an unadjudicated exhausted
    round cost one cheap guard read.
    """
    summary: dict[str, Any] = {
        "teams": 0,
        "questions": 0,
        "approved": 0,
        "roundsRegenerated": 0,
        "handoffsRetried": 0,
        "adjudicated": 0,
        "rejected": 0,
        "formalRuns": 0,
        "knowledgeHandoffsAccepted": 0,
        "retried": 0,
        "failed": 0,
        "skipped": 0,
    }
    try:
        team_ids = _team_ids_with_chain_storage()
    except Exception:  # noqa: BLE001 - the sweep must never break its host
        _record_scene_event(
            "hypothesis_first.auto_advance_sweep",
            outcome="failed",
            level="warning",
            fields={"reason": "team_enumeration_failed"},
        )
        return summary
    for team_id in team_ids:
        summary["teams"] += 1
        try:
            question_ids = question_ids_with_chain_records(team_id)
        except Exception:  # noqa: BLE001 - one broken team cannot stop the sweep
            summary["skipped"] += 1
            continue
        for question_id in question_ids:
            summary["questions"] += 1
            try:
                # Step zero, before adjudication: approve review digests that
                # waited beyond the TTL so the closure chain (fan-in, next
                # round) can still progress within this same pass.
                approval = auto_approve_awaiting_review_digests(
                    team_id, question_id=question_id
                )
                summary["approved"] += int(approval.get("approved") or 0)
                # Step zero-five, after approval: a newest review round whose
                # fan-in round generation never landed (the closure's
                # synchronous review-LLM call died after the meeting was
                # already closed) is regenerated here — without the round,
                # every downstream gate below would wait forever.
                regeneration = auto_regenerate_missing_hypothesis_round(
                    team_id, question_id=question_id
                )
                if str(regeneration.get("status") or "") == "created":
                    summary["roundsRegenerated"] += 1
                elif str(regeneration.get("status") or "") == "failed":
                    summary["failed"] += 1
                # Step zero-eight, after regeneration and before
                # adjudication: a collection request left in handoff_pending
                # by a once-failed writeback (its run already completed) is
                # retried here — past the grace it unblocks the pending
                # count, so a chain rescued in this pass can be adjudicated
                # in the same pass instead of waiting another tick.
                handoff_retry = auto_retry_pending_collection_handoffs(
                    team_id, question_id=question_id
                )
                summary["handoffsRetried"] += int(
                    handoff_retry.get("retried") or 0
                )
                adjudication = auto_adjudicate_exhausted_round(
                    team_id, question_id=question_id
                )
                status = str(adjudication.get("status") or "")
                if status == "created":
                    summary["adjudicated"] += 1
                elif status == "rejected":
                    summary["rejected"] += 1
                elif status == "failed":
                    summary["failed"] += 1
                else:
                    summary["skipped"] += 1
                if status in {"created", "reused"}:
                    formal_run = auto_create_formal_run_after_convergence(
                        team_id, question_id=question_id
                    )
                    if str(formal_run.get("status") or "") == "created":
                        summary["formalRuns"] += 1
                    elif str(formal_run.get("status") or "") == "failed":
                        summary["failed"] += 1
                # Step two-five, every question every pass: accept the
                # knowledge_handoff human gate on formal runs whose ingestion
                # governance chain already passed (the operator-automation
                # policy removes the residual click).  Newly created runs have
                # no such task yet; live runs stuck on the gate unblock here.
                handoff_accept = auto_accept_knowledge_handoffs(
                    team_id, question_id=question_id
                )
                summary["knowledgeHandoffsAccepted"] += int(
                    handoff_accept.get("accepted") or 0
                )
                # Step three, every question every pass: resubmit the
                # offer-gated retry for formal nodes blocked on the transient
                # auto_advance_not_ready verdict (read-only unless an eligible
                # blocked run exists).
                retry_summary = auto_retry_blocked_formal_nodes(
                    team_id, question_id=question_id
                )
                summary["retried"] += int(retry_summary.get("retried") or 0)
            except Exception:  # noqa: BLE001 - one broken question is isolated
                summary["failed"] += 1
    _record_scene_event(
        "hypothesis_first.auto_advance_sweep",
        outcome="completed",
        fields={
            "teams": int(summary["teams"]),
            "questions": int(summary["questions"]),
            "approved": int(summary["approved"]),
            "roundsRegenerated": int(summary["roundsRegenerated"]),
            "handoffsRetried": int(summary["handoffsRetried"]),
            "adjudicated": int(summary["adjudicated"]),
            "rejected": int(summary["rejected"]),
            "formalRuns": int(summary["formalRuns"]),
            "knowledgeHandoffsAccepted": int(summary["knowledgeHandoffsAccepted"]),
            "retried": int(summary["retried"]),
            "failed": int(summary["failed"]),
            "skipped": int(summary["skipped"]),
        },
    )
    return summary


def _team_ids_with_chain_storage() -> list[str]:
    """Team ids that own a hypothesis-first chain ledger (read-only)."""
    root = developer_sandbox.seeded_sandbox_workspace_path(
        _project_root(), "teams"
    )
    if not root.exists():
        return []
    team_ids = [
        path.parts[-3]
        for path in root.glob("*/research_workflow/hypothesis_first_chain.jsonl")
        if path.is_file() and len(path.parts) >= 3 and path.parts[-3]
    ]
    return sorted(set(team_ids))


def question_ids_with_chain_records(team_id: str) -> list[str]:
    """Question ids present in one team's chain ledger (read-only scan).

    Reset questions have no remaining chain records, so a reset can never be
    resurrected from history.  Used by the maintenance sweep as the cheap
    enumeration step before the per-question guards run.
    """
    records = _read_jsonl(_storage_path(team_id))
    question_ids = {
        str(item.get("questionId") or "").strip().upper()
        for item in records
        if str(item.get("questionId") or "").strip().upper()
    }
    return sorted(question_ids)


def _submit_formal_v2_command(
    team_id: str,
    *,
    run_id: str,
    node_id: str = "",
    command: str,
    idempotency_key: str,
    output_record_id: str = "",
) -> dict[str, Any]:
    """Adapt a canonical hypothesis-first action to the formal command SSOT."""

    from core.research.workflow.contracts import (
        ActorRef,
        CommandRequest,
        WorkflowCommandKind,
    )

    from .formal_read_runtime import get_query_service
    from .ids import new_id
    from .operator_authorization import current_server_operator
    from .runtime_factory import production_workflow_runtime

    runtime = production_workflow_runtime()
    if runtime is None:
        raise HypothesisFirstChainError("formal workflow runtime is unavailable")
    run = runtime.store.get_run(str(run_id or "").strip())
    if run is None or str(run.team_id or "") != team_id:
        raise HypothesisFirstChainError("formal workflow run is unavailable in this team")
    try:
        kind = WorkflowCommandKind(command)
    except ValueError as exc:
        raise HypothesisFirstChainError(f"unsupported formal command: {command}") from exc
    payload: dict[str, Any] = {}
    command_node_id: str | None = None
    command_idempotency_key = idempotency_key
    if kind is WorkflowCommandKind.RETRY_NODE:
        requested_node_id = str(node_id or "").strip()
        if not requested_node_id:
            raise HypothesisFirstChainError("retry_node requires nodeId")
        snapshot = get_query_service().get_snapshot(
            team_id=team_id,
            run_id=run.run_id,
        )
        snapshot_payload = snapshot.to_dict() if hasattr(snapshot, "to_dict") else snapshot
        offers = (
            list(snapshot_payload.get("commandOffers") or [])
            if isinstance(snapshot_payload, Mapping)
            else []
        )
        offer = next(
            (
                item
                for item in offers
                if isinstance(item, Mapping)
                and str(item.get("command") or "") == WorkflowCommandKind.RETRY_NODE.value
                and str(item.get("nodeId") or "").strip() == requested_node_id
                and item.get("available") is True
            ),
            None,
        )
        if offer is None:
            raise HypothesisFirstChainError(
                "formal node retry offer is unavailable or no longer matches the node"
            )
        offered_version = offer.get("expectedRunVersion")
        if offered_version is not None:
            try:
                if int(offered_version) != int(run.run_version):
                    raise HypothesisFirstChainError(
                        "formal node retry offer is stale"
                    )
            except (TypeError, ValueError) as exc:
                raise HypothesisFirstChainError(
                    "formal node retry offer has an invalid run version"
                ) from exc
        offered_payload = offer.get("payload")
        if not isinstance(offered_payload, Mapping):
            raise HypothesisFirstChainError(
                "formal node retry offer has an invalid payload"
            )
        offered_idempotency_key = str(
            offer.get("idempotencyKey") or ""
        ).strip()
        if not offered_idempotency_key:
            raise HypothesisFirstChainError(
                "formal node retry offer has no idempotency key"
            )
        command_node_id = requested_node_id
        payload = dict(offered_payload)
        command_idempotency_key = offered_idempotency_key
    if kind is WorkflowCommandKind.START_NODE:
        requested_node_id = str(node_id or "").strip()
        if not requested_node_id:
            raise HypothesisFirstChainError("start_node requires nodeId")
        snapshot = get_query_service().get_snapshot(
            team_id=team_id,
            run_id=run.run_id,
        )
        snapshot_payload = snapshot.to_dict() if hasattr(snapshot, "to_dict") else snapshot
        offers = (
            list(snapshot_payload.get("commandOffers") or [])
            if isinstance(snapshot_payload, Mapping)
            else []
        )
        offer = next(
            (
                item
                for item in offers
                if isinstance(item, Mapping)
                and str(item.get("command") or "") == WorkflowCommandKind.START_NODE.value
                and str(item.get("nodeId") or "").strip() == requested_node_id
                and item.get("available") is True
            ),
            None,
        )
        if offer is None:
            raise HypothesisFirstChainError(
                "formal node start offer is unavailable or no longer matches the node"
            )
        offered_version = offer.get("expectedRunVersion")
        if offered_version is not None:
            try:
                if int(offered_version) != int(run.run_version):
                    raise HypothesisFirstChainError(
                        "formal node start offer is stale"
                    )
            except (TypeError, ValueError) as exc:
                raise HypothesisFirstChainError(
                    "formal node start offer has an invalid run version"
                ) from exc
        offered_payload = offer.get("payload")
        if not isinstance(offered_payload, Mapping):
            raise HypothesisFirstChainError(
                "formal node start offer has an invalid payload"
            )
        offered_idempotency_key = str(
            offer.get("idempotencyKey") or ""
        ).strip()
        if not offered_idempotency_key:
            raise HypothesisFirstChainError(
                "formal node start offer has no idempotency key"
            )
        command_node_id = requested_node_id
        payload = dict(offered_payload)
        command_idempotency_key = offered_idempotency_key
    if kind is WorkflowCommandKind.FORK_REVISION:
        snapshot = get_query_service().get_snapshot(team_id=team_id, run_id=run.run_id)
        snapshot_payload = snapshot.to_dict() if hasattr(snapshot, "to_dict") else snapshot
        offers = (
            list(snapshot_payload.get("commandOffers") or [])
            if isinstance(snapshot_payload, Mapping)
            else []
        )
        offer = next(
            (
                item
                for item in offers
                if isinstance(item, Mapping)
                and str(item.get("command") or "") == "fork_revision"
                and item.get("available") is True
            ),
            None,
        )
        if offer is None:
            raise HypothesisFirstChainError(
                "formal revision checkpoint is unavailable"
            )
        offered_payload = offer.get("payload")
        offered_payload = dict(offered_payload) if isinstance(offered_payload, Mapping) else {}
        checkpoint_id = str(offered_payload.get("checkpointId") or "").strip()
        if not checkpoint_id:
            raise HypothesisFirstChainError(
                "formal revision checkpoint is unavailable"
            )
        command_node_id = "hypothesis_design"
        payload = {
            **offered_payload,
            "fromNodeId": command_node_id,
            "checkpointId": checkpoint_id,
            "reason": f"Challenge Program review requested revision ({output_record_id})",
            "postApprovalRevision": True,
            "outputRecordId": output_record_id,
        }
    operator = current_server_operator()
    actor_id = str(operator.operator_id).strip() if operator is not None else ""
    try:
        receipt = runtime.command_service.submit(
            CommandRequest(
                command_id=new_id("cmd"),
                run_id=run.run_id,
                team_id=team_id,
                command=kind,
                node_id=command_node_id,
                expected_run_version=int(run.run_version),
                idempotency_key=command_idempotency_key,
                payload=payload,
                requested_by=ActorRef("user", actor_id or "operator"),
                requested_at_ms=int(time.time() * 1000),
            )
        )
    except Exception as exc:
        raise _formal_command_rejection(exc) from exc
    return receipt.to_dict()


def _formal_run_entry_node_id(run: Mapping[str, Any]) -> str:
    """Resolve the first startable node of the run's pinned definition.

    The graph compiles ``START -> nodes[0]`` from the resolved definition, so
    a fresh ``created`` run can only meaningfully start at its entry node.
    HUMAN nodes never receive start offers, so they are skipped exactly the
    way the offer builder skips them.
    """
    from core.research.workflow.definition_registry import (
        resolve_definition_for_run_record,
    )
    from core.research.workflow.models import ActorKind

    definition = resolve_definition_for_run_record(dict(run))
    return next(
        (
            node.nodeId
            for node in definition.nodes
            if node.actorKind is not ActorKind.HUMAN
        ),
        "",
    )


def _create_stage_one_question_run(
    team_id: str,
    *,
    question_id: str,
    idempotency_key: str,
) -> dict[str, Any]:
    """Create the stage-one run behind the v2 ``create_stage_one_run`` offer.

    This is the origin-level entry redirect: instead of opening an orphan R0
    with no run context, the projection routes the question through the run
    creation service so the frozen input carries the current stage-one
    policy and the durable CatalogRunAuthorization gate stays in force.  Run
    creation auto-opens the R0 exploratory round; replays reuse the
    deterministic run id derived from the v2 idempotency key.
    """

    from core.web.services.team_workflow import challenge_cup_real_batch
    from .run_creation import create_question_run

    authorization = challenge_cup_real_batch._current_catalog_run_authorization(
        team_id,
        "real-1",
    )
    result = create_question_run(
        CHALLENGE_CUP_WORKFLOW_ID,
        team_id=team_id,
        question_id=question_id,
        safety_limits=challenge_cup_real_batch._default_safety_limits(),
        idempotency_key=idempotency_key,
        catalog_run_authorization=authorization,
    )
    if (
        isinstance(result, Mapping)
        and str(result.get("runId") or "").strip()
    ):
        # A created run has no automatic start channel (graph-worker
        # reconciliation spares only hypothesis-first-era runs), so submit
        # the entry start_node immediately, exactly like create_formal_run.
        _auto_start_created_formal_run(
            team_id,
            run=result,
            idempotency_key=idempotency_key,
        )
    return result


def _auto_start_created_formal_run(
    team_id: str,
    *,
    run: Mapping[str, Any],
    idempotency_key: str,
) -> dict[str, Any] | None:
    """Submit the entry-node start_node right after ``create_formal_run``.

    Without this a created formal run waits indefinitely for a manual UI
    start (the graph worker's created-run reconciliation deliberately spares
    hypothesis-first-era runs only).  The start goes through the same offer
    gate as the UI: the offer's own idempotencyKey keeps replays idempotent,
    and an unavailable (readiness-blocked) offer keeps the historical
    behavior — wait for a human start, never bypass readiness.  Best-effort:
    any failure records a scene event and returns None instead of failing
    the create command.
    """
    run_id = str(run.get("runId") or "").strip()
    if not run_id:
        return None
    try:
        entry_node_id = _formal_run_entry_node_id(run)
        if not entry_node_id:
            raise HypothesisFirstChainError(
                "formal run definition has no startable entry node"
            )
        receipt = _submit_formal_v2_command(
            team_id,
            run_id=run_id,
            node_id=entry_node_id,
            command="start_node",
            idempotency_key=idempotency_key,
        )
    except HypothesisFirstChainError as exc:
        # Offer unavailable (readiness gate) or formal runtime absent (e.g.
        # command-line path): keep the historical wait-for-manual-start state.
        _record_scene_event(
            "formal_run_auto_start_waited",
            outcome="waited_for_manual_start",
            fields={
                "runId": run_id,
                "reason": str(exc),
                "errorType": type(exc).__name__,
            },
        )
        return None
    except Exception as exc:  # noqa: BLE001 - auto-start must never fail create
        _record_scene_event(
            "formal_run_auto_start_failed",
            outcome="failed",
            level="warning",
            fields={
                "runId": run_id,
                "reason": str(exc),
                "errorType": type(exc).__name__,
            },
        )
        return None
    _record_scene_event(
        "formal_run_auto_start_submitted",
        outcome="submitted",
        fields={
            "runId": run_id,
            "commandId": str(receipt.get("commandId") or ""),
            "receiptStatus": str(receipt.get("status") or ""),
        },
    )
    return receipt


def _retry_program_delivery(
    team_id: str,
    *,
    run_id: str,
    idempotency_key: str,
) -> dict[str, Any]:
    """Re-run delivery and append a fresh authoritative terminal event."""

    from .delivery_orchestration import (
        build_delivery_event,
        run_delivery_orchestration,
    )
    from .runtime_factory import production_workflow_runtime

    runtime = production_workflow_runtime()
    if runtime is None:
        raise HypothesisFirstChainError("formal workflow runtime is unavailable")
    run = runtime.store.get_run(str(run_id or "").strip())
    if run is None or str(run.team_id or "") != team_id:
        raise HypothesisFirstChainError("formal workflow run is unavailable in this team")
    existing = next(
        (
            event
            for event in reversed(runtime.store.list_events(run.run_id, 0, 1000))
            if str(getattr(event, "correlation_id", "") or "") == idempotency_key
        ),
        None,
    )
    if existing is not None:
        return {
            "status": "reused",
            "runId": run.run_id,
            "eventId": str(getattr(existing, "event_id", "") or ""),
        }
    now_ms = int(time.time() * 1000)
    try:
        outcome = run_delivery_orchestration(
            runtime.store,
            run_id=run.run_id,
            now_ms=now_ms,
        )
    except Exception as exc:
        raise HypothesisFirstChainError(str(exc)) from exc

    def mutate(uow: Any) -> dict[str, Any]:
        current = uow.repository.get_run(run.run_id)
        if current is None:
            raise HypothesisFirstChainError("formal workflow run disappeared")
        sequence = uow.repository.advance_last_sequence(run.run_id, 1, now_ms)
        if sequence is None:
            raise HypothesisFirstChainError("formal delivery event sequence conflict")
        event = build_delivery_event(
            run=current,
            sequence=sequence,
            outcome=outcome,
            actor_id="operator:v2-program-delivery",
            correlation_id=idempotency_key,
            now_ms=now_ms,
        )
        uow.repository.insert_event(event)
        return {
            "status": str(outcome.get("status") or ""),
            "runId": run.run_id,
            "eventId": event.event_id,
            "artifactRef": str(outcome.get("artifactRef") or ""),
            "programCandidateHandoff": dict(
                outcome.get("programCandidateHandoff") or {}
            ),
        }

    return runtime.store.submit(mutate, force_flush=True).result(timeout=30)


def execute_v2_command(
    team_id: str,
    request: Mapping[str, Any],
    *,
    question_id: str = "",
    workflow_run_id: str = "",
) -> dict[str, Any]:
    """Execute one V2 command under scope-lock reauthorization and CAS.

    Thin observability wrapper: every command outcome (executed, idempotent
    replay, rejection, or failure) leaves a runtime-scene event so chain
    stalls can be diagnosed without replaying the JSONL ledger.
    """

    started = time.perf_counter()
    envelope = dict(request) if isinstance(request, Mapping) else {}
    command = str(envelope.get("command") or "").strip()
    action_id = str(envelope.get("actionId") or "").strip()
    identity = {
        "teamId": str(team_id or ""),
        "questionId": str(question_id or ""),
        "workflowRunId": str(workflow_run_id or ""),
        "command": command,
        "actionId": action_id,
    }
    try:
        result = _execute_v2_command_impl(
            team_id,
            request,
            question_id=question_id,
            workflow_run_id=workflow_run_id,
        )
    except Exception as exc:
        _record_scene_event(
            "command.failed",
            outcome="failed",
            level="warning",
            fields={
                **identity,
                "errorType": type(exc).__name__,
                "durationMs": round((time.perf_counter() - started) * 1000, 1),
            },
        )
        raise
    replayed = str(result.get("status") or "").strip() == "reused"
    _record_scene_event(
        "command.executed",
        outcome="reused" if replayed else "executed",
        fields={
            **identity,
            "replay": replayed,
            "durationMs": round((time.perf_counter() - started) * 1000, 1),
        },
    )
    return result


def _execute_v2_command_impl(
    team_id: str,
    request: Mapping[str, Any],
    *,
    question_id: str = "",
    workflow_run_id: str = "",
) -> dict[str, Any]:
    """Execute one V2 command under scope-lock reauthorization and CAS.

    This is deliberately a small compatibility envelope over existing owning
    services.  It does not duplicate their facts or invent a second ledger;
    each branch calls the existing idempotent mutation and returns its result.
    """

    action_id = str(request.get("actionId") or "").strip()
    idempotency_key = str(request.get("idempotencyKey") or "").strip()
    expected = str(request.get("expectedStateVersion") or "").strip()
    command = str(request.get("command") or "").strip()
    payload = request.get("payload")
    payload = dict(payload) if isinstance(payload, Mapping) else {}
    action_input = request.get("input")
    action_input = dict(action_input) if isinstance(action_input, Mapping) else {}
    if not action_id or not idempotency_key:
        raise ContractValidationError("actionId and idempotencyKey are required")
    command = _selection_command_action_id(action_id, command)
    normalized_question_id = _command_question_id(
        team_id, command, payload, question_id=question_id
    )
    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    normalized_workflow_run_id = str(workflow_run_id or "").strip()
    with hypothesis_first_scope_lock(normalized_team_id, normalized_question_id):
        # Selection commands are the one V2 path whose external side effect
        # can already have committed when the response is lost.  Look up the
        # durable outcome before CAS so a retry with an old snapshot can be
        # answered without invoking selection/meeting services again.
        selection_version = ""
        selection_input_digest = ""
        if command == "record_selection":
            payload_question_id = str(payload.get("questionId") or "").strip().upper()
            if payload_question_id != normalized_question_id:
                raise ContractValidationError(
                    "record_selection payload.questionId must match the question scope"
                )
            records = _records(normalized_team_id)
            reset_id = _current_reset_id(
                normalized_team_id,
                normalized_question_id,
                records=records,
            )
            selected_candidate_ids = _normalized_str_list(
                action_input.get("candidateIds")
            )
            selection_scope_hash = ""
            try:
                scope = _question_scope_envelope(
                    normalized_team_id,
                    normalized_question_id,
                )
                if all(
                    str(scope.get(field) or "").strip()
                    for field in (*_SCOPE_FIELDS, "agentId", "mode")
                ):
                    selection_scope_hash = scope_hash_for(
                        **{field: str(scope[field]) for field in _SCOPE_FIELDS},
                        agent_id=str(scope["agentId"]),
                        mode=str(scope["mode"]),
                    )
            except Exception:  # noqa: BLE001 - partial legacy scope is handled below
                # Scope validation remains owned by hypothesis_selection.  A
                # partial test/legacy envelope simply uses the unscoped
                # version identity rather than inventing a second scope.
                selection_scope_hash = ""
            selection_version = selection_version_for(
                question_id=normalized_question_id,
                selected_candidate_ids=selected_candidate_ids,
                previous_selection_id=str(
                    payload.get("previousSelectionId")
                    or action_input.get("previousSelectionId")
                    or ""
                ),
                reset_id=reset_id,
                scope_hash=selection_scope_hash,
                workflow_run_id=normalized_workflow_run_id,
            )
            selection_input_digest = _selection_command_input_digest(
                action_id=action_id,
                question_id=normalized_question_id,
                payload=payload,
                candidate_ids=selected_candidate_ids,
                workflow_run_id=normalized_workflow_run_id,
            )
            existing_outcome = _selection_command_outcome(
                normalized_team_id,
                question_id=normalized_question_id,
                action_id=action_id,
                idempotency_key=idempotency_key,
                reset_id=reset_id,
                workflow_run_id=normalized_workflow_run_id,
                records=records,
            )
            if existing_outcome is not None:
                expected_digest = str(
                    existing_outcome.get("inputDigest") or ""
                ).strip()
                if expected_digest != selection_input_digest:
                    raise IdempotencyConflictError(
                        action_id=action_id,
                        idempotency_key=idempotency_key,
                        expected_input_digest=expected_digest,
                        actual_input_digest=selection_input_digest,
                    )
                return _selection_command_replay(
                    existing_outcome,
                    team_id=normalized_team_id,
                    question_id=normalized_question_id,
                    action_id=action_id,
                    idempotency_key=idempotency_key,
                    expected_state_version=expected,
                    workflow_run_id=normalized_workflow_run_id,
                )

            # A second client key can race after the first key's outcome has
            # been durably recorded.  The selection version is the business
            # uniqueness fence, so alias the original result instead of
            # invoking the owning selection service a second time.
            version_outcome = _selection_command_outcome_for_version(
                normalized_team_id,
                question_id=normalized_question_id,
                action_id=action_id,
                selection_version=selection_version,
                reset_id=reset_id,
                workflow_run_id=normalized_workflow_run_id,
                records=records,
            )
            if version_outcome is not None:
                expected_digest = str(
                    version_outcome.get("inputDigest") or ""
                ).strip()
                if expected_digest != selection_input_digest:
                    raise HypothesisFirstChainError(
                        "selectionVersion 已绑定到不同的选择输入，不能创建第二个活动评审"
                    )
                alias_outcome = {
                    **dict(version_outcome),
                    "outcomeId": f"hf2-selection-outcome-{_stable_hash({'actionId': action_id, 'idempotencyKey': idempotency_key})[:16]}",
                    "idempotencyKey": idempotency_key,
                    "acceptedStateVersion": expected,
                    "createdAt": _utc_now(),
                }
                _append_jsonl(_storage_path(normalized_team_id), alias_outcome)
                return _selection_command_replay(
                    alias_outcome,
                    team_id=normalized_team_id,
                    question_id=normalized_question_id,
                    action_id=action_id,
                    idempotency_key=idempotency_key,
                    expected_state_version=expected,
                    workflow_run_id=normalized_workflow_run_id,
                )

            # A crash can leave the review binding durable but not the command
            # outcome.  Reuse that binding as the recovery result and record a
            # new outcome for this key; no selection or model call is needed.
            active_bindings = _active_review_binding_groups(
                normalized_team_id,
                question_id=normalized_question_id,
                selection_version=selection_version,
                workflow_run_id=normalized_workflow_run_id,
                records=records,
            )
            if active_bindings:
                active_selection_ids = {
                    str(item.get("selectionId") or "").strip()
                    for item in active_bindings
                }
                if len(active_selection_ids) > 1:
                    raise HypothesisFirstChainError(
                        "同一 selectionVersion 存在多个活动评审绑定，已停止新的选择提交"
                    )
                active_binding = max(
                    active_bindings,
                    key=lambda item: int(item.get("roundIndex") or 0),
                )
                recovered_review = _review_binding_replay_result(
                    normalized_team_id,
                    active_binding,
                )
                recovered_candidate_ids = _normalized_str_list(
                    [
                        item.get("candidateId")
                        for item in sorted(
                            active_binding.get("links") or [],
                            key=lambda item: (
                                int(item.get("candidateOrder") or 0),
                                str(item.get("createdAt") or ""),
                                str(item.get("candidateId") or ""),
                            ),
                        )
                        if isinstance(item, Mapping)
                    ]
                )
                recovered_result = _selection_command_result(
                    {
                        "selection": {
                            "selectionId": str(
                                active_binding.get("selectionId") or ""
                            ),
                            "selectedCandidateIds": recovered_candidate_ids,
                        },
                        "reviewMeeting": recovered_review,
                    }
                )
                recovered_result["selectionVersion"] = selection_version
                outcome = {
                    "schemaVersion": SCHEMA_VERSION,
                    "recordKind": SELECTION_COMMAND_OUTCOME_KIND,
                    "outcomeId": f"hf2-selection-outcome-{_stable_hash({'actionId': action_id, 'idempotencyKey': idempotency_key})[:16]}",
                    "teamId": normalized_team_id,
                    "questionId": normalized_question_id,
                    "workflowRunId": normalized_workflow_run_id,
                    "actionId": action_id,
                    "idempotencyKey": idempotency_key,
                    "inputDigest": selection_input_digest,
                    "selectionVersion": selection_version,
                    "resetId": reset_id,
                    "acceptedStateVersion": expected,
                    "result": recovered_result,
                    "createdAt": _utc_now(),
                }
                _append_jsonl(_storage_path(normalized_team_id), outcome)
                return _selection_command_replay(
                    outcome,
                    team_id=normalized_team_id,
                    question_id=normalized_question_id,
                    action_id=action_id,
                    idempotency_key=idempotency_key,
                    expected_state_version=expected,
                    workflow_run_id=normalized_workflow_run_id,
                )

        snapshot = assert_expected_state_version(
            normalized_team_id,
            normalized_question_id,
            expected,
            workflow_run_id=normalized_workflow_run_id,
        )
        if not command:
            matching_actions = [
                item
                for item in list(snapshot.get("allowedActions") or [])
                if isinstance(item, Mapping)
                and item.get("kind") == "command"
                and str(item.get("actionId") or "") == action_id
                and dict(item.get("payload") or {}) == payload
            ]
            command = (
                str(matching_actions[0].get("command") or "")
                if matching_actions
                else ""
            )
        if not command:
            raise HypothesisFirstChainError(
                "command action is not authorized by the current state"
            )
        action = _find_allowed_command(
            snapshot,
            action_id=action_id,
            command=command,
            payload=payload,
        )
        # Replays must retain the exact action identity and payload.  Existing
        # owning services provide the durable idempotency behavior; this
        # envelope prevents a different payload from reusing the same key.
        if str(action.get("idempotencyKey") or "") != idempotency_key:
            raise HypothesisFirstChainError(
                "idempotencyKey does not match the server-authorized action"
            )
        from core.web.services.team_workflow import meeting_rounds, meeting_runtime

        if command in {"open_generation", "retry_generation"}:
            # The R1 offer carries its run in the payload so the origin-level
            # projection can route a click without a separate runId query;
            # an explicit query runId still wins.
            launch_run_id = normalized_workflow_run_id or str(
                payload.get("runId") or ""
            ).strip()
            launch = resolve_stage_one_generation_launch(
                normalized_team_id,
                normalized_question_id,
                launch_run_id,
            )
            result = open_candidate_generation_meeting(
                normalized_team_id,
                normalized_question_id,
                _model_invocation_receipt_authority=launch.get("receipt_authority"),
                _discussion_scope=launch.get("discussion_scope"),
                _candidate_authority=str(launch.get("candidate_authority") or ""),
                _generation_context=launch.get("generation_context"),
            )
        elif command == "record_selection":
            from core.web.services.team_workflow import hypothesis_selection

            selected_candidate_ids = [
                str(item or "").strip()
                for item in list(action_input.get("candidateIds") or [])
                if str(item or "").strip()
            ]
            if not selected_candidate_ids:
                raise ContractValidationError(
                    "record_selection requires input.candidateIds"
                )
            selected_candidate_ids = sorted(selected_candidate_ids)
            # The rejected-adjudication recovery re-offer carries the selection
            # the operator is re-selecting from; hypothesis_selection requires
            # it to open a second append-only selection chain.
            previous_selection_id = str(
                payload.get("previousSelectionId")
                or action_input.get("previousSelectionId")
                or ""
            ).strip()
            selection_scope = _question_scope_envelope(
                normalized_team_id,
                normalized_question_id,
            )
            screening = _screen_stage_one_selection_candidates(
                team_id=normalized_team_id,
                question_id=normalized_question_id,
                workflow_run_id=normalized_workflow_run_id,
                selected_candidate_ids=selected_candidate_ids,
                scope=selection_scope,
                screened_by=_OPERATOR_AGENT_ID,
            )
            selected_candidate_ids = list(screening["candidateIds"])
            selection_payload = {
                **selection_scope,
                "questionId": normalized_question_id,
                "workflowRunId": normalized_workflow_run_id,
                "selectedCandidateIds": selected_candidate_ids,
                "decidedBy": _OPERATOR_AGENT_ID,
            }
            if previous_selection_id:
                selection_payload["previousSelectionId"] = previous_selection_id
            result = hypothesis_selection.record_hypothesis_selection(
                normalized_team_id,
                selection_payload,
                background=True,
            )
            records = _records(normalized_team_id)
            reset_id = _current_reset_id(
                normalized_team_id,
                normalized_question_id,
                records=records,
            )
            selection_version = selection_version_for(
                question_id=normalized_question_id,
                selected_candidate_ids=selected_candidate_ids,
                previous_selection_id=previous_selection_id,
                reset_id=reset_id,
                scope_hash=selection_scope_hash,
                workflow_run_id=normalized_workflow_run_id,
            )
            selection_result = _selection_command_result(result)
            selection_result["selectionVersion"] = selection_version
            if screening.get("artifactRef"):
                selection_result["candidateScreeningArtifactRef"] = str(
                    screening["artifactRef"]
                )
            outcome = {
                "schemaVersion": SCHEMA_VERSION,
                "recordKind": SELECTION_COMMAND_OUTCOME_KIND,
                "outcomeId": f"hf2-selection-outcome-{_stable_hash({'actionId': action_id, 'idempotencyKey': idempotency_key})[:16]}",
                "teamId": normalized_team_id,
                "questionId": normalized_question_id,
                "workflowRunId": normalized_workflow_run_id,
                "actionId": action_id,
                "idempotencyKey": idempotency_key,
                "inputDigest": selection_input_digest,
                "selectionVersion": selection_version,
                "resetId": reset_id,
                "acceptedStateVersion": expected,
                "result": selection_result,
                "createdAt": _utc_now(),
            }
            with _LOCK:
                existing_outcome = _selection_command_outcome(
                    normalized_team_id,
                    question_id=normalized_question_id,
                    action_id=action_id,
                    idempotency_key=idempotency_key,
                    reset_id=reset_id,
                    workflow_run_id=normalized_workflow_run_id,
                )
                if existing_outcome is None:
                    _append_jsonl(_storage_path(normalized_team_id), outcome)
                else:
                    outcome = existing_outcome
        elif command == "approve_summary":
            meeting_id = str(payload.get("meetingRoundId") or "").strip()
            decision = str(action_input.get("decision") or "accepted").strip().lower()
            if decision == "accepted":
                meeting = meeting_rounds.get_meeting_round(
                    normalized_team_id, meeting_id
                )["meetingRound"]
                draft = meeting.get("digestDraft")
                content_hash = str(
                    (draft or {}).get("contentHash") if isinstance(draft, Mapping) else ""
                ).strip()
                result = approve_meeting_digest(
                    normalized_team_id,
                    meeting_id,
                    closed_by="operator",
                    expected_digest_content_hash=content_hash,
                )
            elif decision in {"rejected", "revised"}:
                meeting_rounds.reject_meeting_digest_draft(
                    normalized_team_id,
                    meeting_id,
                    actor="operator",
                    reason=f"v2:{decision}",
                )
                result = meeting_runtime.prepare_meeting_summary_draft(
                    normalized_team_id,
                    meeting_id,
                    actor="operator",
                    force=True,
                )
            else:
                raise ContractValidationError(
                    "approve_summary input.decision is invalid"
                )
        elif command == "resume_discussion":
            result = meeting_runtime.schedule_meeting_discussion(
                normalized_team_id,
                str(payload.get("meetingRoundId") or ""),
            )
        elif command == "reopen_review":
            result = reopen_failed_review_meeting(
                normalized_team_id,
                str(payload.get("meetingRoundId") or ""),
            )
        elif command == "stop_discussion":
            # The owning service picks the terminal shape: an attempt with
            # citable messages is closed as a stopped execution while the
            # transcript and produced drafts survive; an empty attempt keeps
            # the exact superseded-attempt recovery semantics.  Both reuse
            # idempotently, so a stalled meeting's stop action can never hit
            # a "cannot be superseded" dead end.
            result = meeting_rounds.stop_discussion_meeting(
                normalized_team_id,
                str(payload.get("meetingRoundId") or ""),
                actor="operator:v2-stop-discussion",
            )
        elif command == "regenerate_summary":
            result = meeting_runtime.prepare_meeting_summary_draft(
                normalized_team_id,
                str(payload.get("meetingRoundId") or ""),
                actor="operator",
                force=True,
            )
        elif command == "retry_review_dispatch":
            result = retry_review_dispatch(
                normalized_team_id,
                str(payload.get("selectionId") or ""),
                [str(item) for item in list(payload.get("candidateIds") or [])],
            )
        elif command in {"retry_collection", "continue_collection"}:
            result = recover_collection_request(
                normalized_team_id,
                str(payload.get("requestId") or ""),
            )
        elif command == "stop_collection":
            result = stop_collection_request(
                normalized_team_id,
                str(payload.get("requestId") or ""),
            )
        elif command == "handoff_collection":
            result = record_collection_handoff(
                normalized_team_id,
                str(payload.get("requestId") or ""),
                handoff_ref=f"v2:{idempotency_key}",
            )
        elif command == "open_next_review":
            result = open_next_review_meeting(
                normalized_team_id,
                previous_meeting_round_id=str(
                    payload.get("previousMeetingRoundId") or ""
                ),
                budget=payload.get("roundBudget"),
                fan_out_selection=True,
                enforce_sibling_archive_gate=True,
            )
        elif command == "record_program_review":
            from core.web.services.team_workflow.challenge_question_runs import (
                review_challenge_question_output,
            )

            if not action_input:
                raise ContractValidationError(
                    "record_program_review requires reviewer, rationale and decisions"
                )
            result = review_challenge_question_output(
                normalized_team_id,
                normalized_question_id,
                str(payload.get("outputRunId") or ""),
                action_input,
            )
        elif command == "human_adjudication":
            result = record_human_adjudication(
                normalized_team_id,
                question_id=normalized_question_id,
                hypothesis_round_id=str(payload.get("hypothesisRoundId") or ""),
                decision=str(action_input.get("decision") or ""),
                rationale=str(action_input.get("rationale") or ""),
                idempotency_key=idempotency_key,
                workflow_run_id=normalized_workflow_run_id,
            )
        elif command == "create_formal_run":
            from core.web.services.team_workflow.challenge_cup_real_batch import (
                ChallengeCupRealBatchError,
            )

            from .run_creation import create_question_run
            from .service import ResearchWorkflowError

            try:
                # Stage-one policy-covered runs freeze the durable catalog
                # authorization into the run input (same precedent as
                # _create_stage_one_question_run); uncovered questions pass
                # no authorization.
                result = create_question_run(
                    CHALLENGE_CUP_WORKFLOW_ID,
                    team_id=normalized_team_id,
                    question_id=normalized_question_id,
                    safety_limits=_formal_run_safety_limits(),
                    idempotency_key=idempotency_key,
                    formal_hypothesis_round_id=str(
                        payload.get("hypothesisRoundId") or ""
                    ),
                    catalog_run_authorization=_stage_one_catalog_run_authorization(
                        normalized_team_id, normalized_question_id
                    ),
                )
            except (
                ChallengeCupRealBatchError,
                ResearchWorkflowError,
            ) as exc:
                # Structured rejection instead of a flattened 500: the route
                # renders FormalCommandRejectedError with its stable code
                # (catalog_run_authorization_required,
                # catalog_run_authorization_replay_mismatch,
                # idempotency_conflict, ...).
                raise _formal_command_rejection(exc) from exc
            # A created run has no automatic start channel (graph-worker
            # reconciliation spares only hypothesis-first-era runs), so submit
            # the entry start_node immediately; readiness-blocked offers keep
            # the historical wait-for-manual-start behavior.
            if isinstance(result, Mapping) and str(result.get("runId") or "").strip():
                _auto_start_created_formal_run(
                    normalized_team_id,
                    run=result,
                    idempotency_key=idempotency_key,
                )
        elif command == "create_stage_one_run":
            result = _create_stage_one_question_run(
                normalized_team_id,
                question_id=normalized_question_id,
                idempotency_key=idempotency_key,
            )
        elif command == "retry_formal_node":
            result = _submit_formal_v2_command(
                normalized_team_id,
                run_id=str(payload.get("runId") or ""),
                node_id=str(payload.get("nodeId") or ""),
                command="retry_node",
                idempotency_key=idempotency_key,
            )
        elif command == "reconcile_formal_run":
            result = _submit_formal_v2_command(
                normalized_team_id,
                run_id=str(payload.get("runId") or ""),
                command="reconcile_run",
                idempotency_key=idempotency_key,
            )
        elif command == "cancel_run":
            result = _submit_formal_v2_command(
                normalized_team_id,
                run_id=str(payload.get("runId") or ""),
                command="cancel_run",
                idempotency_key=idempotency_key,
            )
        elif command == "archive_run":
            result = _submit_formal_v2_command(
                normalized_team_id,
                run_id=str(payload.get("runId") or ""),
                command="archive_run",
                idempotency_key=idempotency_key,
            )
        elif command == "retry_program_handoff":
            result = _retry_program_delivery(
                normalized_team_id,
                run_id=str(payload.get("runId") or ""),
                idempotency_key=idempotency_key,
            )
        elif command == "create_formal_revision":
            result = _submit_formal_v2_command(
                normalized_team_id,
                run_id=str(payload.get("runId") or ""),
                command="fork_revision",
                idempotency_key=idempotency_key,
                output_record_id=str(payload.get("outputRecordId") or ""),
            )
        else:
            raise HypothesisFirstChainError(
                f"V2 command {command} has no owning mutation adapter yet"
            )
        return {
            "schemaVersion": 2,
            "teamId": normalized_team_id,
            "questionId": normalized_question_id,
            "command": command,
            "actionId": action_id,
            "idempotencyKey": idempotency_key,
            "acceptedStateVersion": expected,
            "result": result,
        }


def _collection_requests(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for record in records:
        if str(record.get("recordKind") or "") != COLLECTION_REQUEST_KIND:
            continue
        latest[str(record.get("requestId") or "")] = record
    return sorted(latest.values(), key=lambda item: str(item.get("createdAt") or ""))


def _review_round_links(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for record in records:
        if str(record.get("recordKind") or "") != REVIEW_ROUND_LINK_KIND:
            continue
        latest[str(record.get("linkId") or "")] = record
    return sorted(latest.values(), key=lambda item: int(item.get("roundIndex") or 0))


def _review_dispatch_attempts(
    records: list[dict[str, Any]],
    *,
    selection_id: str = "",
    round_index: int | None = None,
) -> list[dict[str, Any]]:
    """Latest durable per-candidate review-dispatch attempt state, per attempt id."""
    normalized_selection_id = str(selection_id or "").strip()
    latest: dict[str, dict[str, Any]] = {}
    for record in records:
        if str(record.get("recordKind") or "") != REVIEW_DISPATCH_ATTEMPT_KIND:
            continue
        if (
            normalized_selection_id
            and str(record.get("selectionId") or "").strip() != normalized_selection_id
        ):
            continue
        if (
            round_index is not None
            and int(record.get("roundIndex") or 0) != int(round_index)
        ):
            continue
        attempt_id = str(record.get("attemptId") or "").strip()
        if attempt_id:
            latest[attempt_id] = record
    return sorted(
        latest.values(),
        key=lambda item: (
            int(item.get("attemptNumber") or 0),
            str(item.get("updatedAt") or item.get("createdAt") or ""),
        ),
    )


def _latest_review_dispatch_attempt(
    records: list[dict[str, Any]],
    *,
    selection_id: str,
    candidate_id: str,
    round_index: int,
) -> dict[str, Any] | None:
    """Newest attempt for one (selection, candidate, round) dispatch identity."""
    matched = [
        item
        for item in _review_dispatch_attempts(
            records, selection_id=selection_id, round_index=round_index
        )
        if str(item.get("candidateId") or "").strip() == str(candidate_id or "").strip()
    ]
    return matched[-1] if matched else None


def _append_review_dispatch_attempt_state(
    team_id: str,
    *,
    question_id: str,
    selection_id: str,
    selection_version: str,
    candidate_id: str,
    round_index: int,
    lifecycle: str,
    outcome: str = "none",
    meeting_round_id: str = "",
    error: str = "",
    error_type: str = "",
) -> dict[str, Any]:
    """Append one durable per-candidate review-dispatch attempt transition.

    ``lifecycle="queued"`` opens (or reuses) the current attempt before any
    meeting side effect: an existing non-failed attempt is reused so selection
    replays never stack duplicate attempts, while a latest failed attempt bumps
    the attempt number so retries supersede it in projection instead of
    rewriting history. A latest attempt whose bound meeting already terminated
    (closed) is superseded the same way, so a retry after a terminated review
    opens a fresh attempt instead of reusing the dead meeting. Terminal
    transitions update the same attempt id.
    """
    now = _utc_now()
    with _LOCK:
        records = _read_jsonl(_storage_path(team_id))
        current = _latest_review_dispatch_attempt(
            records,
            selection_id=selection_id,
            candidate_id=candidate_id,
            round_index=round_index,
        )
        if lifecycle == "queued":
            if (
                current is not None
                and str(current.get("lifecycle") or "") != "failed"
                and not _attempt_bound_meeting_is_terminal(team_id, current)
            ):
                return current
            attempt_number = int(current.get("attemptNumber") or 0) + 1 if current else 1
        else:
            if current is None:
                return {}
            attempt_number = int(current.get("attemptNumber") or 1)
        attempt_id = (
            "hf-rda-"
            + _stable_hash(
                {
                    "selectionId": selection_id,
                    "candidateId": candidate_id,
                    "roundIndex": round_index,
                    "attemptNumber": attempt_number,
                }
            )[:16]
        )
        previous = next(
            (
                item
                for item in reversed(records)
                if item.get("recordKind") == REVIEW_DISPATCH_ATTEMPT_KIND
                and str(item.get("attemptId") or "") == attempt_id
            ),
            {},
        )
        record = {
            "schemaVersion": SCHEMA_VERSION,
            "recordKind": REVIEW_DISPATCH_ATTEMPT_KIND,
            "attemptId": attempt_id,
            "attemptNumber": attempt_number,
            "idempotencyKey": (
                f"hf2:review-dispatch:{team_id}:{selection_id}:"
                f"{candidate_id}:r{round_index}:{attempt_number}"
            ),
            "questionId": question_id,
            "selectionId": selection_id,
            "selectionVersion": str(selection_version or "").strip(),
            "candidateId": candidate_id,
            "roundIndex": int(round_index),
            "lifecycle": lifecycle,
            "outcome": outcome,
            "meetingRoundId": str(meeting_round_id or "")
            or str(previous.get("meetingRoundId") or ""),
            "error": str(error or ""),
            "errorType": str(error_type or ""),
            "createdAt": str(previous.get("createdAt") or "") or now,
            "updatedAt": now,
        }
        _append_jsonl(_storage_path(team_id), record)
    return record


def _meeting_round_is_terminal(meeting_round: Any) -> bool:
    """True when one meeting round has reached its terminal ``closed`` status."""

    if not isinstance(meeting_round, Mapping):
        return False
    return str(meeting_round.get("status") or "").strip().lower() == "closed"


def _attempt_bound_meeting_is_terminal(
    team_id: str, attempt: Mapping[str, Any]
) -> bool:
    """True when the meeting bound to one attempt record already terminated.

    A terminated review meeting can never serve a fresh dispatch again, so the
    attempt ledger must supersede such attempts instead of replaying them.
    """

    from core.web.services.team_workflow import meeting_rounds

    meeting_round_id = str(attempt.get("meetingRoundId") or "").strip()
    if not meeting_round_id:
        return False
    try:
        meeting_round = meeting_rounds.get_meeting_round(team_id, meeting_round_id)[
            "meetingRound"
        ]
    except meeting_rounds.ResearchMeetingRoundNotFoundError:
        return False
    return _meeting_round_is_terminal(meeting_round)


def list_review_dispatch_attempts(
    team_id: str, *, selection_id: str = "", round_index: int | None = None
) -> dict[str, Any]:
    """List durable review-dispatch attempts, latest state per attempt."""
    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    attempts = _review_dispatch_attempts(
        _records(normalized_team_id), selection_id=selection_id, round_index=round_index
    )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "selectionId": str(selection_id or "").strip(),
        "attemptCount": len(attempts),
        "attempts": attempts,
    }


def _generation_attempts(
    records: list[dict[str, Any]], question_id: str = ""
) -> list[dict[str, Any]]:
    normalized_question_id = str(question_id or "").strip().upper()
    latest: dict[str, dict[str, Any]] = {}
    for record in records:
        if str(record.get("recordKind") or "") != GENERATION_ATTEMPT_KIND:
            continue
        if (
            normalized_question_id
            and str(record.get("questionId") or "").strip().upper()
            != normalized_question_id
        ):
            continue
        attempt_id = str(record.get("attemptId") or "").strip()
        if attempt_id:
            latest[attempt_id] = record
    return sorted(
        latest.values(),
        key=lambda item: (
            int(item.get("attemptNumber") or 0),
            str(item.get("updatedAt") or item.get("createdAt") or ""),
        ),
    )


def list_generation_attempts(
    team_id: str, *, question_id: str = ""
) -> dict[str, Any]:
    """List durable generation attempts, latest state per attempt."""
    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    attempts = _generation_attempts(_records(normalized_team_id), question_id)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "questionId": str(question_id or "").strip().upper(),
        "attemptCount": len(attempts),
        "attempts": attempts,
    }


def _append_generation_attempt_state(
    team_id: str,
    *,
    question_id: str,
    attempt_id: str,
    attempt_number: int,
    meeting_round_id: str,
    lifecycle: str,
    outcome: str = "none",
    supersedes_attempt_id: str = "",
    error: str = "",
) -> dict[str, Any]:
    now = _utc_now()
    with _LOCK:
        records = _read_jsonl(_storage_path(team_id))
        previous = next(
            (
                item
                for item in reversed(records)
                if item.get("recordKind") == GENERATION_ATTEMPT_KIND
                and str(item.get("attemptId") or "") == attempt_id
            ),
            {},
        )
        queued_at = str(previous.get("queuedAt") or "") or now
        started_at = str(previous.get("startedAt") or "") or (
            now if lifecycle in {"running", "waiting_human", "completed", "failed"} else ""
        )
        finished_at = (
            now
            if lifecycle in {"completed", "failed", "cancelled", "superseded"}
            else ""
        )
        record = {
            "schemaVersion": SCHEMA_VERSION,
            "recordKind": GENERATION_ATTEMPT_KIND,
            "attemptId": attempt_id,
            "attemptNumber": attempt_number,
            "idempotencyKey": f"hf2:generation:{team_id}:{question_id}:{attempt_number}",
            "questionId": question_id,
            "meetingRoundId": meeting_round_id,
            "lifecycle": lifecycle,
            "outcome": outcome,
            "queuedAt": queued_at,
            "startedAt": started_at,
            "heartbeatAt": now if lifecycle == "running" else str(previous.get("heartbeatAt") or ""),
            "finishedAt": finished_at,
            "supersedesAttemptId": supersedes_attempt_id,
            "error": error,
            "createdAt": str(previous.get("createdAt") or "") or now,
            "updatedAt": now,
        }
        _append_jsonl(_storage_path(team_id), record)
    return record


def _finish_generation_attempt_for_meeting(
    team_id: str,
    meeting_round_id: str,
    *,
    outcome: str,
) -> dict[str, Any] | None:
    with _LOCK:
        attempts = _generation_attempts(_read_jsonl(_storage_path(team_id)))
    current = next(
        (
            item
            for item in reversed(attempts)
            if str(item.get("meetingRoundId") or "") == meeting_round_id
        ),
        None,
    )
    if current is None:
        return None
    return _append_generation_attempt_state(
        team_id,
        question_id=str(current.get("questionId") or ""),
        attempt_id=str(current.get("attemptId") or ""),
        attempt_number=int(current.get("attemptNumber") or 1),
        meeting_round_id=meeting_round_id,
        lifecycle="completed",
        outcome=outcome,
        supersedes_attempt_id=str(current.get("supersedesAttemptId") or ""),
    )


def fail_generation_attempt_for_meeting(
    team_id: str,
    meeting_round_id: str,
    *,
    reason: str,
) -> dict[str, Any] | None:
    """Finish the active generation attempt when its bound meeting is fenced.

    The bound MeetingRound is the execution authority.  A formal chat-room
    stop must close the duplicate attempt projection in the same terminal
    callback so the UI never keeps reporting a dead attempt as ``running``.
    """

    normalized_reason = str(reason or "").strip()
    if not normalized_reason:
        raise HypothesisFirstChainError("generation terminal reason is required")
    with _LOCK:
        attempts = _generation_attempts(_read_jsonl(_storage_path(team_id)))
    current = next(
        (
            item
            for item in reversed(attempts)
            if str(item.get("meetingRoundId") or "") == meeting_round_id
        ),
        None,
    )
    if current is None:
        return None
    lifecycle = str(current.get("lifecycle") or "").strip().lower()
    if lifecycle in {"completed", "failed", "cancelled", "superseded"}:
        return current
    return _append_generation_attempt_state(
        team_id,
        question_id=str(current.get("questionId") or ""),
        attempt_id=str(current.get("attemptId") or ""),
        attempt_number=int(current.get("attemptNumber") or 1),
        meeting_round_id=meeting_round_id,
        lifecycle="cancelled" if "cancel" in normalized_reason else "failed",
        supersedes_attempt_id=str(current.get("supersedesAttemptId") or ""),
        error=normalized_reason,
    )


def list_collection_requests(
    team_id: str,
    *,
    question_id: str = "",
    workflow_run_id: str = "",
) -> dict[str, Any]:
    """List the latest record of every collection request, newest-last."""
    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    normalized_question_id = str(question_id or "").strip().upper()
    normalized_workflow_run_id = str(workflow_run_id or "").strip()
    if normalized_workflow_run_id and not normalized_question_id:
        raise ContractValidationError("questionId is required when runId is provided")
    requests = _collection_requests(_records(normalized_team_id))
    if normalized_question_id:
        requests = [
            record
            for record in requests
            if str(record.get("questionId") or "").upper() == normalized_question_id
        ]
    if normalized_workflow_run_id:
        meeting_ids = {
            str(meeting.get("meetingRoundId") or "").strip()
            for meeting in _question_meetings(
                normalized_team_id,
                normalized_question_id,
                workflow_run_id=normalized_workflow_run_id,
            )
        }
        requests = [
            record
            for record in requests
            if str(record.get("meetingRoundId") or "").strip() in meeting_ids
        ]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "requestCount": len(requests),
        "requests": requests,
        "storagePath": str(_storage_path(normalized_team_id)),
    }


def list_review_round_links(
    team_id: str,
    *,
    question_id: str = "",
    workflow_run_id: str = "",
) -> dict[str, Any]:
    """List review-round lineage links ordered by round index."""
    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    normalized_question_id = str(question_id or "").strip().upper()
    normalized_workflow_run_id = str(workflow_run_id or "").strip()
    if normalized_workflow_run_id and not normalized_question_id:
        raise ContractValidationError("questionId is required when runId is provided")
    links = _review_round_links(_records(normalized_team_id))
    if normalized_question_id:
        links = [
            record
            for record in links
            if str(record.get("questionId") or "").upper() == normalized_question_id
        ]
    if normalized_workflow_run_id:
        meeting_ids = {
            str(meeting.get("meetingRoundId") or "").strip()
            for meeting in _question_meetings(
                normalized_team_id,
                normalized_question_id,
                workflow_run_id=normalized_workflow_run_id,
            )
        }
        links = [
            record
            for record in links
            if str(record.get("meetingRoundId") or "").strip() in meeting_ids
        ]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "linkCount": len(links),
        "links": links,
        "storagePath": str(_storage_path(normalized_team_id)),
    }


# ---------------------------------------------------------------------------
# meeting opening (selection -> round 1; handoff -> round N)


def _resolve_hypothesis_participants(
    team_id: str,
    room_id: str,
    meeting_type: str,
) -> dict[str, Any]:
    from core.web.services.team_workflow import meeting_runtime

    return meeting_runtime.resolve_hypothesis_meeting_participants(
        team_id, room_id, meeting_type
    )


def _record_review_round_link(
    team_id: str,
    *,
    meeting_round_id: str,
    previous_meeting_round_id: str,
    selection_id: str,
    collection_request_id: str,
    question_id: str,
    round_index: int,
    round_budget: int = HARD_ROUND_LIMIT,
    candidate_id: str = "",
    candidate_order: int | None = None,
    selection_version: str = "",
) -> dict[str, Any]:
    link_id = f"hf-link-{_stable_hash({'meetingRoundId': meeting_round_id, 'roundIndex': round_index})[:16]}"
    record = {
        "schemaVersion": SCHEMA_VERSION,
        "recordKind": REVIEW_ROUND_LINK_KIND,
        "linkId": link_id,
        "meetingRoundId": meeting_round_id,
        "previousMeetingRoundId": previous_meeting_round_id,
        "selectionId": selection_id,
        "selectionVersion": str(selection_version or "").strip(),
        "collectionRequestId": collection_request_id,
        "questionId": question_id,
        "roundIndex": round_index,
        # Persist the single hard limit for audit/replay. Projection authority
        # remains the server constant so historical values cannot lower it.
        "roundBudget": HARD_ROUND_LIMIT,
        "candidateId": str(candidate_id or "").strip(),
        "candidateOrder": (
            int(candidate_order) if candidate_order is not None else None
        ),
        "createdAt": _utc_now(),
    }
    with _LOCK:
        records = _read_jsonl(_storage_path(team_id))
        existing = _latest_by_id(
            [item for item in records if str(item.get("recordKind") or "") == REVIEW_ROUND_LINK_KIND],
            "meetingRoundId",
            meeting_round_id,
        )
        if existing is not None:
            backfilled = dict(existing)
            sibling_request_only = False
            for key in (
                "previousMeetingRoundId",
                "collectionRequestId",
                "selectionId",
                "selectionVersion",
                "roundIndex",
                "roundBudget",
                "candidateId",
                "candidateOrder",
            ):
                existing_value = existing.get(key)
                # Links written before roundBudget existed replay fine.
                if key in {
                    "roundBudget",
                    "candidateId",
                    "candidateOrder",
                    "selectionVersion",
                } and existing_value is None:
                    if key == "selectionVersion" and record.get(key):
                        backfilled[key] = record[key]
                    continue
                if existing_value != record.get(key):
                    if key == "collectionRequestId":
                        # Defer the decision: a difference confined to the
                        # collectionRequestId is sibling fan-out (below);
                        # any other difference still rejects, so keep
                        # scanning and only decide after the loop.
                        sibling_request_only = True
                        continue
                    raise HypothesisFirstChainError(
                        f"review round link for {meeting_round_id} is already bound to different content"
                    )
            if sibling_request_only:
                # Sibling fan-out: the two sibling collection requests of one
                # logical round both hand off into the same fan-out of
                # next-round meetings, so both legitimately race to bind the
                # identical link.  That double-write is competition, not
                # content drift — reuse the existing link with the first
                # writer's collectionRequestId kept as provenance instead of
                # rejecting the late sibling (which used to park its request
                # in handoff_pending forever with no retry path).
                return existing
            if backfilled != existing:
                _append_jsonl(_storage_path(team_id), backfilled)
                return backfilled
            return existing
        _append_jsonl(_storage_path(team_id), record)
    return record


# C3 dispatch TOCTOU guard: the attempt ledger collapses concurrent "queued"
# writes onto one attempt (hence one deterministic meeting id), but the inner
# open sequence remains read-then-act — a second dispatch that reads before
# the first one binds its room round sees no meeting, falls through to open,
# and would leave one meeting bound to two discussion rounds (duplicated
# digest sources, doubled discussion tokens). ``create_meeting_round`` already
# reuses or fail-closes the meeting record itself, but its lock cannot span
# the slow ``start_chat_room_round``/bind tail, so the dispatch layer
# serializes the whole per-candidate open sequence here instead.
_CANDIDATE_DISPATCH_LOCKS_GUARD = threading.Lock()
_CANDIDATE_DISPATCH_LOCKS: dict[tuple[str, str, str], tuple[threading.Lock, int]] = {}


@contextmanager
def _candidate_dispatch_serialized(
    team_id: str, question_id: str, candidate_id: str
):
    """Hold the per-candidate dispatch lock for one whole open sequence.

    The registry is refcounted under the guard: every caller increments the
    waiters before blocking on the lock, and the entry is removed only when
    the last waiter leaves, so late arrivals always find the same lock object
    while the registry cannot grow without bound.
    """

    key = (
        str(team_id or "").strip(),
        str(question_id or "").strip().upper(),
        str(candidate_id or "").strip(),
    )
    with _CANDIDATE_DISPATCH_LOCKS_GUARD:
        entry = _CANDIDATE_DISPATCH_LOCKS.get(key)
        if entry is None:
            entry = (threading.Lock(), 0)
        lock = entry[0]
        _CANDIDATE_DISPATCH_LOCKS[key] = (lock, entry[1] + 1)
    try:
        with lock:
            yield
    finally:
        with _CANDIDATE_DISPATCH_LOCKS_GUARD:
            current = _CANDIDATE_DISPATCH_LOCKS.get(key)
            if current is not None and current[0] is lock:
                remaining = current[1] - 1
                if remaining <= 0:
                    _CANDIDATE_DISPATCH_LOCKS.pop(key, None)
                else:
                    _CANDIDATE_DISPATCH_LOCKS[key] = (lock, remaining)


def _candidate_review_meeting_id(
    selection_id: str,
    candidate_id: str,
    round_index: int,
    *,
    attempt_number: int = 1,
) -> str:
    """Deterministic candidate review meeting id for one dispatch attempt.

    Attempt 1 keeps the historical base id so existing data replays unchanged;
    later attempts carry an ``-a{N}`` suffix (same ladder as candidate
    generation) so a retry after a terminated review opens a fresh meeting
    instead of colliding with the closed one.
    """

    base = (
        f"hf-review-{selection_id}-"
        f"{_stable_hash({'candidateId': candidate_id})[:10]}-"
        f"r{round_index}"
    )
    if attempt_number > 1:
        return f"{base}-a{int(attempt_number)}"
    return base


def open_review_meeting_for_selection(
    team_id: str,
    selection: Mapping[str, Any],
    *,
    agent_runner: Any = None,
    background: bool = True,
    round_index: int = 1,
    previous_meeting_round_id: str = "",
    collection_request_id: str = "",
    meeting_round_id: str = "",
    round_budget: int = HARD_ROUND_LIMIT,
    fan_out_selection: bool = False,
    _selection_version: str = "",
    _formal_candidate_id: str = "",
    _formal_candidate_order: int | None = None,
) -> dict[str, Any]:
    """Open (or reuse) one candidate-level review meeting per selection item.

    Participants derive from the team's linked chat room; the meeting id is
    deterministic per selection/round so replays reuse instead of duplicating.
    """
    from core.web.services import team_service
    from core.web.services.team_workflow import meeting_rounds, meeting_runtime

    normalized_team_id = team_service.assert_team_exists(team_id)
    selection_record = dict(selection)
    selection_id = str(selection_record.get("selectionId") or "").strip()
    if not selection_id:
        raise ContractValidationError("selection requires a selectionId")
    question_id = str(selection_record.get("questionId") or "").strip()
    if not question_id:
        raise ContractValidationError("selection requires a questionId")
    from core.web.services.team_workflow.research_runtime.meeting_receipt_authority import (
        resolve_active_question_authority,
    )

    workflow_run_id = str(selection_record.get("workflowRunId") or "").strip()
    receipt_authority = resolve_active_question_authority(
        normalized_team_id,
        question_id,
        workflow_run_id,
    )
    normalized_round_index = max(1, int(round_index or 1))
    selected_candidate_ids = _normalized_str_list(
        selection_record.get("selectedCandidateIds")
    )
    if not selected_candidate_ids:
        raise ContractValidationError(
            "selection requires at least one selectedCandidateId"
        )
    selection_version = str(selection_record.get("selectionVersion") or "").strip()
    if not selection_version:
        selection_version = selection_version_for(
            question_id=question_id,
            selected_candidate_ids=selected_candidate_ids,
            previous_selection_id=str(
                selection_record.get("previousSelectionId") or ""
            ),
            reset_id=_current_reset_id(normalized_team_id, question_id),
            scope_hash=str(selection_record.get("scopeHash") or ""),
            workflow_run_id=workflow_run_id,
        )
    if _selection_version:
        selection_version = str(_selection_version).strip()
    selection_record["selectionVersion"] = selection_version

    # Every selected hypothesis owns a review meeting. Receipt authority
    # constrains model invocation evidence; it must never decide whether a
    # multi-candidate selection is fanned out. Otherwise a temporarily
    # unavailable formal Ledger silently produces one combined meeting with an
    # empty candidate link, while the UI correctly fails closed because it
    # cannot assign that meeting to any candidate.
    #
    # Recursive calls carry exactly one candidate. When a server-authored
    # workflow discussion scope is available, each child receives its own
    # candidate_review scope and child sessions; older DEV paths still keep
    # the same candidate-level meeting/link contract without inventing a
    # workflow identity.
    if not _formal_candidate_id:
        active_bindings = _active_review_binding_groups(
            normalized_team_id,
            question_id=question_id,
            selection_version=selection_version,
            workflow_run_id=workflow_run_id,
        )
        active_selection_ids = {
            str(item.get("selectionId") or "").strip()
            for item in active_bindings
        }
        if len(active_selection_ids) > 1:
            raise HypothesisFirstChainError(
                "同一 selectionVersion 存在多个活动评审绑定，无法安全恢复"
            )
        if active_bindings and str(
            active_bindings[0].get("selectionId") or ""
        ).strip() != selection_id:
            return _review_binding_replay_result(
                normalized_team_id,
                max(
                    active_bindings,
                    key=lambda item: int(item.get("roundIndex") or 0),
                ),
            )
        if previous_meeting_round_id and not fan_out_selection:
            previous = meeting_rounds.get_meeting_round(
                normalized_team_id, str(previous_meeting_round_id).strip()
            )["meetingRound"]
            previous_scope = previous.get("discussionScope")
            previous_candidate_id = (
                str(previous_scope.get("candidateId") or "").strip()
                if isinstance(previous_scope, Mapping)
                else ""
            )
            if previous_candidate_id:
                selected_candidate_ids = [previous_candidate_id]

        discussion_scope_base = _review_discussion_scope_base(
            normalized_team_id,
            question_id,
            selected_candidate_ids,
            receipt_authority=receipt_authority,
            workflow_run_id=workflow_run_id,
        )
        # Fan-out intents are queued on disk before any meeting side effect
        # (same contract as generation attempts): a crash mid-fan-out still
        # explains, per candidate, that dispatch was attempted. Replays reuse
        # the existing attempt instead of stacking duplicates, while attempts
        # whose meeting already terminated are superseded so retries open a
        # fresh meeting. The queued record is the single attempt authority:
        # the meeting id below takes its attempt number, keeping ledger and
        # meeting identity consistent.
        candidate_attempt_numbers: dict[str, int] = {}
        for candidate_id in selected_candidate_ids:
            attempt_record = _append_review_dispatch_attempt_state(
                normalized_team_id,
                question_id=question_id,
                selection_id=selection_id,
                selection_version=selection_version,
                candidate_id=candidate_id,
                round_index=normalized_round_index,
                lifecycle="queued",
            )
            candidate_attempt_numbers[candidate_id] = int(
                attempt_record.get("attemptNumber") or 1
            )
        _record_scene_event(
            "review_dispatch.started",
            outcome="started",
            fields={
                "teamId": normalized_team_id,
                "questionId": question_id,
                "selectionId": selection_id,
                "roundIndex": normalized_round_index,
                "candidateCount": len(selected_candidate_ids),
            },
        )
        opened_candidates: list[dict[str, Any]] = []
        for candidate_order, candidate_id in enumerate(selected_candidate_ids):
            candidate_meeting_id = _candidate_review_meeting_id(
                selection_id,
                candidate_id,
                normalized_round_index,
                attempt_number=candidate_attempt_numbers.get(candidate_id, 1),
            )
            candidate_selection = {
                **selection_record,
                "selectedCandidateIds": [candidate_id],
                "candidateId": candidate_id,
            }
            if discussion_scope_base is not None:
                from core.research.workflow.contracts.discussion_scope import (
                    WorkflowDiscussionScopeV1,
                )

                discussion_scope = WorkflowDiscussionScopeV1.review(
                    teamId=normalized_team_id,
                    researchProjectId=discussion_scope_base.researchProjectId,
                    workflowRunId=discussion_scope_base.workflowRunId,
                    workflowNodeId=discussion_scope_base.workflowNodeId,
                    questionId=question_id,
                    selectionId=selection_id,
                    candidateId=candidate_id,
                )
                candidate_selection.update(
                    {
                        "discussionScope": discussion_scope.to_dict(),
                        "workflowRunId": discussion_scope.workflowRunId,
                        "workflowNodeId": discussion_scope.workflowNodeId,
                        "researchProjectId": discussion_scope.researchProjectId,
                    }
                )
            try:
                # Every dispatch entry (selection commit, human retry, next
                # round auto-open) funnels through this recursive call, so the
                # per-candidate lock here covers the whole read-then-act open
                # sequence: the loser waits, then replays into the
                # "meeting exists with bound rounds -> reused" branch instead
                # of starting a second discussion round for the same meeting.
                with _candidate_dispatch_serialized(
                    normalized_team_id, question_id, candidate_id
                ):
                    opened_candidate = open_review_meeting_for_selection(
                        normalized_team_id,
                        candidate_selection,
                        agent_runner=agent_runner,
                        background=background,
                        round_index=normalized_round_index,
                        previous_meeting_round_id=previous_meeting_round_id,
                        collection_request_id=collection_request_id,
                        meeting_round_id=candidate_meeting_id,
                        round_budget=round_budget,
                        fan_out_selection=fan_out_selection,
                        _selection_version=selection_version,
                        _formal_candidate_id=candidate_id,
                        _formal_candidate_order=candidate_order,
                    )
            except Exception as exc:  # noqa: BLE001 - attempt fact stays durable
                _append_review_dispatch_attempt_state(
                    normalized_team_id,
                    question_id=question_id,
                    selection_id=selection_id,
                    selection_version=selection_version,
                    candidate_id=candidate_id,
                    round_index=normalized_round_index,
                    lifecycle="failed",
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
                _record_scene_event(
                    "review_dispatch.candidate_failed",
                    outcome="failed",
                    level="warning",
                    fields={
                        "teamId": normalized_team_id,
                        "questionId": question_id,
                        "selectionId": selection_id,
                        "candidateId": candidate_id,
                        "roundIndex": normalized_round_index,
                        "errorType": type(exc).__name__,
                    },
                )
                raise
            opened_meeting = (
                opened_candidate.get("meetingRound")
                if isinstance(opened_candidate.get("meetingRound"), Mapping)
                else {}
            )
            _append_review_dispatch_attempt_state(
                normalized_team_id,
                question_id=question_id,
                selection_id=selection_id,
                selection_version=selection_version,
                candidate_id=candidate_id,
                round_index=normalized_round_index,
                lifecycle="completed",
                outcome="succeeded",
                # Bind the attempt to the meeting that actually opened so the
                # ledger and the meeting identity can never drift apart.
                meeting_round_id=str(
                    opened_meeting.get("meetingRoundId") or ""
                ).strip()
                or candidate_meeting_id,
            )
            opened_candidates.append(opened_candidate)
        _record_scene_event(
            "review_dispatch.completed",
            outcome="completed",
            fields={
                "teamId": normalized_team_id,
                "questionId": question_id,
                "selectionId": selection_id,
                "roundIndex": normalized_round_index,
                "openedCount": len(opened_candidates),
            },
        )
        discussion_drivers: list[dict[str, Any]] = []
        if background and agent_runner is None:
            for opened in opened_candidates:
                meeting = (
                    opened.get("meetingRound")
                    if isinstance(opened.get("meetingRound"), Mapping)
                    else {}
                )
                candidate_meeting_id = str(
                    meeting.get("meetingRoundId") or ""
                ).strip()
                if not candidate_meeting_id:
                    continue
                try:
                    discussion_drivers.append(
                        meeting_runtime.schedule_meeting_discussion(
                            normalized_team_id,
                            candidate_meeting_id,
                        )
                    )
                except Exception as exc:  # noqa: BLE001 - selection fact remains replayable
                    discussion_drivers.append(
                        {
                            "status": "failed",
                            "meetingRoundId": candidate_meeting_id,
                            "errorType": type(exc).__name__,
                            "error": str(exc),
                        }
                    )
        primary = opened_candidates[0]
        if len(opened_candidates) == 1:
            # Preserve the long-standing single-candidate status contract
            # (for example ``opened``) while still recording its candidate
            # identity in the meeting/link.
            return {
                **primary,
                "reviewMeetings": opened_candidates,
                "candidateCount": 1,
                "discussionDrivers": discussion_drivers,
            }
        return {
            **primary,
            "status": (
                "reused"
                if all(item.get("status") == "reused" for item in opened_candidates)
                else str(primary.get("status") or "opened")
            ),
            "reviewMeetings": opened_candidates,
            "candidateCount": len(opened_candidates),
            "discussionDrivers": discussion_drivers,
        }

    normalized_meeting_round_id = (
        str(meeting_round_id or "").strip()
        or f"hf-review-{selection_id}-r{normalized_round_index}"
    )
    normalized_previous_id = str(previous_meeting_round_id or "").strip()
    normalized_request_id = str(collection_request_id or "").strip()

    try:
        existing_round = meeting_rounds.get_meeting_round(
            normalized_team_id, normalized_meeting_round_id
        )["meetingRound"]
    except meeting_rounds.ResearchMeetingRoundNotFoundError:
        existing_round = None
    if (
        isinstance(existing_round, Mapping)
        and str(existing_round.get("meetingType") or "").strip().lower()
        == HYPOTHESIS_REVIEW_MEETING_TYPE
        and _normalized_str_list(existing_round.get("chatRoomRoundIds"))
        and _meeting_round_is_terminal(existing_round)
    ):
        # A closed meeting is a terminated dispatch, never a fresh reuse.
        # Reconcile the attempt this meeting belonged to, then derive the next
        # attempt id so the dispatch opens a new meeting instead of reporting
        # success on the dead one. Reached only when the durable attempt ledger
        # could not see the termination (for example a dispatch that stayed
        # ``queued`` across a crash); the regular retry path supersedes
        # terminal attempts before this id is ever cast.
        _append_review_dispatch_attempt_state(
            normalized_team_id,
            question_id=question_id,
            selection_id=selection_id,
            selection_version=selection_version,
            candidate_id=_formal_candidate_id,
            round_index=normalized_round_index,
            lifecycle="failed",
            outcome="superseded",
            meeting_round_id=normalized_meeting_round_id,
            error="bound review meeting already closed",
            error_type="ReviewMeetingClosed",
        )
        attempt_record = _append_review_dispatch_attempt_state(
            normalized_team_id,
            question_id=question_id,
            selection_id=selection_id,
            selection_version=selection_version,
            candidate_id=_formal_candidate_id,
            round_index=normalized_round_index,
            lifecycle="queued",
        )
        fresh_meeting_round_id = _candidate_review_meeting_id(
            selection_id,
            _formal_candidate_id,
            normalized_round_index,
            attempt_number=int(attempt_record.get("attemptNumber") or 1),
        )
        if fresh_meeting_round_id == normalized_meeting_round_id:
            raise HypothesisFirstChainError(
                "review meeting "
                f"{normalized_meeting_round_id} is closed and no fresh review "
                "attempt could be derived for this dispatch"
            )
        normalized_meeting_round_id = fresh_meeting_round_id
        existing_round = None
    if (
        isinstance(existing_round, Mapping)
        and str(existing_round.get("meetingType") or "").strip().lower()
        == HYPOTHESIS_REVIEW_MEETING_TYPE
        and _normalized_str_list(existing_round.get("chatRoomRoundIds"))
    ):
        meeting_runtime._require_matching_model_invocation_receipt_authority(
            existing_round,
            receipt_authority,
            team_id=normalized_team_id,
            question_id=question_id,
        )
        link = _record_review_round_link(
            normalized_team_id,
            meeting_round_id=normalized_meeting_round_id,
            previous_meeting_round_id=normalized_previous_id,
            selection_id=selection_id,
            collection_request_id=normalized_request_id,
            question_id=question_id,
            round_index=normalized_round_index,
            round_budget=round_budget,
            candidate_id=_formal_candidate_id,
            candidate_order=_formal_candidate_order,
            selection_version=selection_version,
        )
        bound_round_ids = _normalized_str_list(existing_round.get("chatRoomRoundIds"))
        return {
            "schemaVersion": meeting_rounds.SCHEMA_VERSION,
            "teamId": normalized_team_id,
            "status": "reused",
            "meetingRound": existing_round,
            "roomId": str(existing_round.get("linkedChatRoomId") or ""),
            "roundId": bound_round_ids[-1],
            "chatRoomRoundIds": bound_round_ids,
            "link": link,
        }

    _team, room_id = meeting_runtime._ensure_linked_room(normalized_team_id)
    participant_resolution = _resolve_hypothesis_participants(
        normalized_team_id, room_id, HYPOTHESIS_REVIEW_MEETING_TYPE
    )

    extra_refs: list[str] = []
    if normalized_previous_id:
        extra_refs.append(f"meeting_round:{normalized_previous_id}")
    if normalized_request_id:
        extra_refs.append(f"collection_request:{normalized_request_id}")
    # Gap-notice injection (bounded side channel): a gap-resolved collection
    # request carries its unavailability verdict into the next round's
    # meeting agenda and input refs, so reviewers stop re-requesting the
    # same dead goal and can legally converge with gaps.  The notice never
    # participates in meeting/context identity seeds — without a gap the
    # payload below is byte-identical to the legacy path.
    gap_notices = _collection_request_gap_notice(
        normalized_team_id, normalized_request_id
    )
    if gap_notices:
        extra_refs.extend(
            f"evidence_gap_marker:{item['markerId']}"
            for item in gap_notices
            if item.get("markerId")
        )

    payload: dict[str, Any] = {
        key: selection_record.get(key)
        for key in (
            *_SCOPE_FIELDS,
            "agentId",
            "mode",
            "discussionScope",
            "workflowRunId",
            "workflowNodeId",
            "researchProjectId",
            "candidateId",
        )
        if selection_record.get(key) is not None
    }
    payload.update(
        {
            "selectionId": selection_id,
            "questionId": question_id,
            "selectedCandidateIds": list(selection_record.get("selectedCandidateIds") or []),
            "decidedBy": str(selection_record.get("decidedBy") or ""),
            "meetingRoundId": normalized_meeting_round_id,
            **participant_resolution,
            "inputArtifactRefs": extra_refs,
            # Default agenda stays first when a gap notice exists: the notice
            # is appended to the standard agenda, never replaces it.
            **(
                {
                    "agenda": [
                        *list(getattr(meeting_runtime, "_DEFAULT_AGENDA", ()) or ()),
                        *(str(item.get("agendaLine") or "") for item in gap_notices),
                    ]
                }
                if gap_notices
                else {}
            ),
        }
    )
    candidate_contexts = _build_round_candidates(
        normalized_team_id,
        {
            "question": question_id,
            "discussionItemRefs": [
                f"hypothesis_candidate:{candidate_id}"
                for candidate_id in payload["selectedCandidateIds"]
            ],
        },
        workflow_run_id=str(
            (receipt_authority or {}).get("workflowRunId") or workflow_run_id
        ).strip(),
    )
    opened = meeting_runtime.open_hypothesis_review_meeting(
        normalized_team_id,
        payload,
        agent_runner=agent_runner,
        background=background,
        candidate_contexts=candidate_contexts,
        _model_invocation_receipt_authority=receipt_authority,
    )
    link = _record_review_round_link(
        normalized_team_id,
        meeting_round_id=normalized_meeting_round_id,
        previous_meeting_round_id=normalized_previous_id,
        selection_id=selection_id,
        collection_request_id=normalized_request_id,
        question_id=question_id,
        round_index=normalized_round_index,
        round_budget=round_budget,
        candidate_id=_formal_candidate_id,
        candidate_order=_formal_candidate_order,
        selection_version=selection_version,
    )
    return {
        **opened,
        "roundIndex": normalized_round_index,
        "link": link,
    }


def _review_discussion_scope_base(
    team_id: str,
    question_id: str,
    selected_candidate_ids: list[str],
    *,
    receipt_authority: Mapping[str, Any] | None,
    workflow_run_id: str = "",
):
    """Resolve a server-owned workflow identity for candidate review rooms.

    The current formal Ledger remains the preferred authority. If it is
    temporarily unavailable after a run was already created, reuse the scope
    persisted on the generation meeting that produced this exact selected
    candidate set. That meeting was server-written during run creation, so
    this is not a client-controlled fallback. No scope is synthesized when
    neither source is available: candidate fan-out still proceeds, but the
    legacy meeting remains deliberately unscoped.
    """

    from core.research.workflow.contracts.discussion_scope import (
        QUESTION_GENERATION_SCOPE_KIND,
        WorkflowDiscussionScopeV1,
        parse_discussion_scope,
    )

    if receipt_authority is not None:
        project = _question_research_project(team_id, question_id)
        research_project_id = str((project or {}).get("projectId") or "").strip()
        workflow_run_id = str(receipt_authority.get("workflowRunId") or "").strip()
        if not research_project_id or not workflow_run_id:
            raise HypothesisFirstChainError(
                "formal hypothesis review requires research project and workflow run authority"
            )
        return WorkflowDiscussionScopeV1.generation(
            teamId=team_id,
            researchProjectId=research_project_id,
            workflowRunId=workflow_run_id,
            workflowNodeId=HYPOTHESIS_DESIGN_NODE_ID,
            questionId=question_id,
        )

    selected = set(selected_candidate_ids)
    normalized_workflow_run_id = str(workflow_run_id or "").strip()
    try:
        candidates = list_hypothesis_candidates(
            team_id,
            question_id=question_id,
            workflow_run_id=normalized_workflow_run_id,
        )["candidates"]
    except Exception:  # noqa: BLE001 - unscoped legacy fallback remains valid
        return None
    source_meeting_ids = {
        str(candidate.get("meetingRoundId") or "").strip()
        for candidate in candidates
        if isinstance(candidate, Mapping)
        and str(candidate.get("candidateId") or "").strip() in selected
        and str(candidate.get("meetingRoundId") or "").strip()
    }
    if len(source_meeting_ids) != 1:
        return None
    source_meeting_id = next(iter(source_meeting_ids))
    source_meeting = next(
        (
            meeting
            for meeting in _question_generation_meetings(
                team_id,
                question_id,
                workflow_run_id=normalized_workflow_run_id,
            )
            if str(meeting.get("meetingRoundId") or "").strip() == source_meeting_id
        ),
        None,
    )
    raw_scope = (
        source_meeting.get("discussionScope")
        if isinstance(source_meeting, Mapping)
        else None
    )
    if not isinstance(raw_scope, Mapping):
        return None
    try:
        scope = parse_discussion_scope(raw_scope)
    except ContractValidationError:
        return None
    if (
        scope.kind != QUESTION_GENERATION_SCOPE_KIND
        or scope.teamId != team_id
        or scope.questionId.upper() != question_id.upper()
    ):
        return None
    return scope


def _selection_id_from_meeting(meeting_round: Mapping[str, Any]) -> str:
    for ref in _normalized_str_list(meeting_round.get("inputArtifactRefs")):
        if ref.startswith("hypothesis_selection:"):
            return ref.split(":", 1)[-1].strip()
    return ""


# ---------------------------------------------------------------------------
# round-0 candidate generation (cold start for catalog questions)
# ---------------------------------------------------------------------------


def _question_scope_envelope(team_id: str, question_id: str) -> dict[str, str]:
    """Derive the server-authoritative scope envelope for one catalog question.

    Mirrors the selection-context route: the frozen program registry supplies
    theme/campaign when the question is registered; otherwise a dev theme is
    resolved so DEV teams can still run the hypothesis-first chain.
    """
    from core.web.services.team_workflow.research_scope import (
        frozen_theme_registry,
        resolve_theme_contract,
    )

    normalized_question_id = str(question_id or "").strip().upper()
    theme_record = next(
        (
            record
            for record in frozen_theme_registry().values()
            if str(record.get("questionId") or "").upper() == normalized_question_id
        ),
        None,
    )
    if theme_record is not None:
        contract = resolve_theme_contract(
            team_id,
            theme_id=str(theme_record.get("themeId") or ""),
            campaign_id=str(theme_record.get("campaignId") or ""),
        )
    else:
        contract = resolve_theme_contract(
            team_id,
            theme_id=f"dev-{normalized_question_id.lower()}",
            campaign_id="dev-campaign",
        )
    if contract.is_dev_theme():
        mode = "dev"
    elif contract.is_activated():
        mode = "formal"
    else:
        mode = "platform"
    return {
        "program": contract.programId,
        "theme": contract.themeId,
        "campaign": contract.campaignId,
        "question": normalized_question_id,
        "branch": _DEFAULT_BRANCH,
        "workflow": _HYPOTHESIS_FIRST_WORKFLOW,
        "agentId": _OPERATOR_AGENT_ID,
        "mode": mode,
    }


def _meeting_workflow_run_id(meeting_round: Mapping[str, Any]) -> str:
    """Return the immutable workflow-run identity persisted on a meeting.

    The model invocation receipt is the execution authority.  Older formal
    meetings may only carry the server-validated discussion scope, so retain
    that as a read-compatible fallback without trusting arbitrary fields.
    """

    receipt_authority = meeting_round.get("modelInvocationReceiptAuthority")
    if isinstance(receipt_authority, Mapping):
        workflow_run_id = str(receipt_authority.get("workflowRunId") or "").strip()
        if workflow_run_id:
            return workflow_run_id

    discussion_scope = meeting_round.get("discussionScope")
    if not isinstance(discussion_scope, Mapping):
        return ""
    from core.research.workflow.contracts.discussion_scope import (
        parse_discussion_scope,
    )

    try:
        return parse_discussion_scope(discussion_scope).workflowRunId
    except ContractValidationError:
        return ""


def _question_generation_meetings(
    team_id: str,
    question_id: str,
    *,
    workflow_run_id: str = "",
) -> list[dict[str, Any]]:
    from core.web.services.team_workflow import meeting_rounds

    normalized_workflow_run_id = str(workflow_run_id or "").strip()
    meetings = meeting_rounds.list_meeting_rounds(team_id)["meetings"]
    return [
        meeting
        for meeting in meetings
        if str(meeting.get("meetingType") or "") == CANDIDATE_GENERATION_MEETING_TYPE
        and str(meeting.get("question") or "").upper() == question_id.upper()
        and (
            not normalized_workflow_run_id
            or _meeting_workflow_run_id(meeting) == normalized_workflow_run_id
        )
    ]


_TRAIL_CACHE: dict[tuple[str, str, str], tuple[float, dict[str, Any]]] = {}
_TRAIL_CACHE_MAX_ENTRIES = 32


def _trail_source_stamp(team_id: str) -> float:
    """Newest mtime across the stores the trail reads."""
    root = developer_sandbox.seeded_sandbox_workspace_path(
        _project_root(), "teams", _safe_team_id(team_id)
    ) / "research_workflow"
    stamp = 0.0
    for name in ("meeting_rounds.jsonl", "hypothesis_first_chain.jsonl"):
        try:
            stamp = max(stamp, (root / name).stat().st_mtime)
        except OSError:
            continue
    # Trail content also comes from bound chat-room rounds; a growing room
    # without a meeting-record write must still invalidate the trail cache.
    try:
        from core.ui.chat_state import chat_state_path

        chat_root = chat_state_path(_project_root()).parent
        for child in chat_root.glob("*.json"):
            stamp = max(stamp, child.stat().st_mtime)
    except Exception:  # noqa: BLE001 - cache stamp must never fail the trail
        pass
    return stamp


def candidate_evidence_trail(
    team_id: str,
    question_id: str,
    *,
    workflow_run_id: str = "",
    excerpt_chars: int = 240,
) -> dict[str, Any]:
    """Per-candidate trail of discussion messages that cite it.

    Cold-start candidates carry no structured ``supporting_evidence_refs``;
    their real evidence lives in the generation and review speeches that
    mention the candidate id alongside literature anchors (PaperQA2-style
    click-through, built on data that exists). Each trail entry is a cited
    excerpt: meeting label, speaker, message id, and a window around the
    candidate mention.
    """
    from core.web.services import team_service
    from core.web.services.team_workflow import meeting_rounds

    normalized_team_id = team_service.assert_team_exists(team_id)
    normalized_question_id = str(question_id or "").strip().upper()
    normalized_workflow_run_id = str(workflow_run_id or "").strip()
    if not normalized_question_id:
        raise ContractValidationError("questionId is required")

    cache_key = (
        normalized_team_id,
        normalized_question_id,
        normalized_workflow_run_id,
    )
    source_stamp = _trail_source_stamp(normalized_team_id)
    cached = _TRAIL_CACHE.get(cache_key)
    if cached is not None and cached[0] == source_stamp:
        return cached[1]

    candidates = list_hypothesis_candidates(
        normalized_team_id,
        question_id=normalized_question_id,
        workflow_run_id=normalized_workflow_run_id,
    )["candidates"]
    candidate_ids = [
        str(record.get("candidateId") or "").strip()
        for record in candidates
        if str(record.get("candidateId") or "").strip()
    ]

    trail: dict[str, list[dict[str, Any]]] = {cid: [] for cid in candidate_ids}
    meetings = meeting_rounds.list_meeting_rounds(normalized_team_id)["meetings"]
    question_meetings = [
        meeting
        for meeting in meetings
        if str(meeting.get("question") or "").upper() == normalized_question_id
        and (
            not normalized_workflow_run_id
            or _meeting_workflow_run_id(meeting) == normalized_workflow_run_id
        )
        and str(meeting.get("meetingType") or "")
        in {CANDIDATE_GENERATION_MEETING_TYPE, HYPOTHESIS_REVIEW_MEETING_TYPE}
    ]
    for meeting in question_meetings:
        meeting_round_id = str(meeting.get("meetingRoundId") or "")
        label = (
            "候选生成"
            if str(meeting.get("meetingType") or "") == CANDIDATE_GENERATION_MEETING_TYPE
            else f"评审 {meeting_round_id.rsplit('-', 1)[-1]}"
        )
        for message in meeting_rounds.completed_meeting_source_messages(meeting):
            content = str(message.get("content") or "")
            message_id = str(message.get("messageId") or "")
            speaker = (
                str(message.get("speakerTitle") or "").strip()
                or str(message.get("participantId") or "").strip()
                or "participant"
            )
            for cid in candidate_ids:
                index = content.find(cid)
                if index < 0:
                    continue
                start = max(0, index - excerpt_chars // 3)
                excerpt = content[start : start + excerpt_chars].strip()
                trail[cid].append(
                    {
                        "meetingRoundId": meeting_round_id,
                        "meetingLabel": label,
                        "messageId": message_id,
                        "speaker": speaker,
                        "excerpt": excerpt,
                        "createdAt": str(message.get("createdAt") or ""),
                    }
                )

    for entries in trail.values():
        entries.sort(key=lambda item: str(item.get("createdAt") or ""))

    result = {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "questionId": normalized_question_id,
        "workflowRunId": normalized_workflow_run_id,
        "trails": [
            {"candidateId": cid, "entries": trail[cid]}
            for cid in candidate_ids
        ],
        "storagePath": str(_storage_path(normalized_team_id)),
    }
    if len(_TRAIL_CACHE) >= _TRAIL_CACHE_MAX_ENTRIES:
        _TRAIL_CACHE.clear()
    _TRAIL_CACHE[cache_key] = (source_stamp, result)
    return result


def list_hypothesis_candidates(
    team_id: str,
    *,
    question_id: str = "",
    workflow_run_id: str = "",
) -> dict[str, Any]:
    """List ledger-registered hypothesis candidates (round-0 output)."""
    from core.web.services import team_service

    normalized_team_id = team_service.assert_team_exists(team_id)
    normalized_question_id = str(question_id or "").strip().upper()
    normalized_workflow_run_id = str(workflow_run_id or "").strip()
    generation_meeting_ids = (
        {
            str(meeting.get("meetingRoundId") or "").strip()
            for meeting in _question_generation_meetings(
                normalized_team_id,
                normalized_question_id,
                workflow_run_id=normalized_workflow_run_id,
            )
            if str(meeting.get("meetingRoundId") or "").strip()
        }
        if normalized_workflow_run_id
        else set()
    )
    candidates = [
        record
        for record in _records(normalized_team_id)
        if str(record.get("recordKind") or "") == CANDIDATE_KIND
        and (
            not normalized_question_id
            or str(record.get("questionId") or "").upper() == normalized_question_id
        )
        and (
            not normalized_workflow_run_id
            or str(record.get("meetingRoundId") or "") in generation_meeting_ids
        )
    ]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "candidateCount": len(candidates),
        "candidates": candidates,
        "storagePath": str(_storage_path(normalized_team_id)),
    }


def list_exploratory_drafts(
    team_id: str,
    *,
    question_id: str = "",
    workflow_run_id: str = "",
) -> dict[str, Any]:
    """List R0 drafts without exposing them as selectable candidates."""
    from core.web.services import team_service

    normalized_team_id = team_service.assert_team_exists(team_id)
    normalized_question_id = str(question_id or "").strip().upper()
    normalized_workflow_run_id = str(workflow_run_id or "").strip()
    meeting_ids = (
        {
            str(meeting.get("meetingRoundId") or "").strip()
            for meeting in _question_generation_meetings(
                normalized_team_id,
                normalized_question_id,
                workflow_run_id=normalized_workflow_run_id,
            )
            if _meeting_candidate_authority(meeting) == EXPLORATORY_DRAFT_AUTHORITY
        }
        if normalized_workflow_run_id
        else set()
    )
    drafts = [
        record
        for record in _records(normalized_team_id)
        if str(record.get("recordKind") or "") == EXPLORATORY_DRAFT_KIND
        and (
            not normalized_question_id
            or str(record.get("questionId") or "").upper() == normalized_question_id
        )
        and (
            not normalized_workflow_run_id
            or str(record.get("meetingRoundId") or "") in meeting_ids
        )
    ]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "draftCount": len(drafts),
        "drafts": drafts,
        "storagePath": str(_storage_path(normalized_team_id)),
    }


def _available_exploratory_drafts(
    team_id: str,
    question_id: str,
    *,
    workflow_run_id: str = "",
) -> list[dict[str, Any]]:
    """Resolve consumable R0 drafts for one question (run first, origin fallback).

    A stage-one run consumes its own in-run exploratory drafts; when the run
    has none (for example the SCI-091 field state where the origin layer
    closed an R0 round before any run existed), the same-question origin
    drafts become the R1 input instead of raising.  Each draft keeps its
    original ``meetingRoundId`` so lineage still points at the producing
    round, and the two sources are never mixed: origin drafts are only
    consulted when the run-scoped list is empty.
    """

    normalized_workflow_run_id = str(workflow_run_id or "").strip()
    drafts: list[dict[str, Any]] = []
    if normalized_workflow_run_id:
        drafts = list_exploratory_drafts(
            team_id,
            question_id=question_id,
            workflow_run_id=normalized_workflow_run_id,
        )["drafts"]
    if not drafts:
        drafts = list_exploratory_drafts(
            team_id,
            question_id=question_id,
        )["drafts"]
    return drafts


def _meeting_candidate_authority(meeting_round: Mapping[str, Any]) -> str:
    return str(meeting_round.get("candidateAuthority") or "").strip().lower()


def _candidate_id_for(question_id: str, meeting_round_id: str, statement: str) -> str:
    digest = _stable_hash(
        {
            "questionId": question_id,
            "meetingRoundId": meeting_round_id,
            "statement": statement,
        }
    )
    return f"{question_id.lower()}-c{digest[:8]}"


def _append_generation_candidates(
    team_id: str,
    meeting_round: Mapping[str, Any],
    proposals: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Register R0 drafts or R1 selectable candidates (idempotent)."""
    meeting_round_id = str(meeting_round.get("meetingRoundId") or "")
    question_id = str(meeting_round.get("question") or "").strip().upper()
    candidate_authority = _meeting_candidate_authority(meeting_round)
    record_kind = (
        EXPLORATORY_DRAFT_KIND
        if candidate_authority == EXPLORATORY_DRAFT_AUTHORITY
        else CANDIDATE_KIND
    )
    allowed_evidence_refs = set(
        _normalized_str_list(meeting_round.get("allowedEvidenceRefs"))
    )
    derived_from_drafts = _normalized_str_list(
        meeting_round.get("exploratoryDraftRefs")
    )
    if candidate_authority == FORMAL_GROUNDED_CANDIDATE_AUTHORITY:
        if not allowed_evidence_refs:
            raise HypothesisFirstChainError(
                "formal grounded generation requires an evidence whitelist"
            )
        if not derived_from_drafts:
            raise HypothesisFirstChainError(
                "formal grounded generation requires R0 exploratory drafts"
            )
    appended: list[dict[str, Any]] = []
    with _LOCK:
        records = _read_jsonl(_storage_path(team_id))
        existing_by_id = {
            str(record.get("candidateId") or ""): record
            for record in records
            if str(record.get("recordKind") or "") == record_kind
        }
        for proposal in proposals:
            statement = str(proposal.get("statement") or "").strip()
            if not statement:
                continue
            lineage_refs = _normalized_str_list(proposal.get("lineageRefs"))
            testable_prediction = str(
                proposal.get("testablePrediction") or ""
            ).strip()
            falsifier = str(proposal.get("falsifier") or "").strip()
            axis_profile = proposal.get("axisProfile")
            if candidate_authority == FORMAL_GROUNDED_CANDIDATE_AUTHORITY:
                if not lineage_refs or any(
                    ref not in allowed_evidence_refs for ref in lineage_refs
                ):
                    raise HypothesisFirstChainError(
                        "formal grounded candidate refs must match the evidence whitelist"
                    )
                if not testable_prediction:
                    raise HypothesisFirstChainError(
                        "formal grounded candidate requires CHECK prediction"
                    )
                if not falsifier:
                    raise HypothesisFirstChainError(
                        "formal grounded candidate requires a mechanism-targeting falsifier"
                    )
                from core.research.workflow.contracts import HypothesisAxisProfile

                if not isinstance(axis_profile, Mapping):
                    raise HypothesisFirstChainError(
                        "formal grounded candidate requires a complete axisProfile"
                    )
                normalized_axis_profile = HypothesisAxisProfile.from_dict(
                    axis_profile
                ).to_dict()
            else:
                normalized_axis_profile = None
            candidate_id = _candidate_id_for(question_id, meeting_round_id, statement)
            existing = existing_by_id.get(candidate_id)
            if existing is not None:
                appended.append(existing)
                continue
            record = {
                "schemaVersion": SCHEMA_VERSION,
                "recordKind": record_kind,
                "candidateId": candidate_id,
                **(
                    {"draftId": candidate_id}
                    if record_kind == EXPLORATORY_DRAFT_KIND
                    else {}
                ),
                "questionId": question_id,
                "statement": statement,
                "rationale": str(proposal.get("rationale") or "").strip(),
                "proposedBy": str(proposal.get("proposedBy") or "").strip(),
                "meetingRoundId": meeting_round_id,
                **(
                    {
                        "candidateAuthority": candidate_authority,
                        "lineageRefs": lineage_refs,
                        "testablePrediction": testable_prediction,
                        "falsifier": falsifier,
                        "axisProfile": normalized_axis_profile,
                        "revisionOrdinal": int(
                            meeting_round.get("revisionOrdinal") or 0
                        ),
                        "derivedFromDraftRefs": derived_from_drafts,
                        "knowledgePackageRefs": _normalized_str_list(
                            meeting_round.get("knowledgePackageRefs")
                        ),
                    }
                    if candidate_authority
                    else {}
                ),
                "createdAt": _utc_now(),
            }
            _append_jsonl(_storage_path(team_id), record)
            existing_by_id[candidate_id] = record
            appended.append(record)
    if (
        candidate_authority == FORMAL_GROUNDED_CANDIDATE_AUTHORITY
        and appended
    ):
        from .agent_claim_evidence_materializer import (
            materialize_candidate_claim_bindings_from_existing_evidence,
        )

        materialize_candidate_claim_bindings_from_existing_evidence(
            project_root=_project_root(),
            team_id=team_id,
            workflow_run_id=str(meeting_round.get("workflowRunId") or ""),
            question_scope=_question_scope_envelope(team_id, question_id),
            candidates=appended,
        )
    _finish_generation_attempt_for_meeting(
        team_id,
        meeting_round_id,
        outcome="succeeded" if appended else "empty",
    )
    return appended


def _materialize_grounded_revision_authority(
    team_id: str,
    meeting_round: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Write the real R0 -> R1 lineage from a formal grounded meeting."""

    if (
        str(meeting_round.get("mode") or "").strip().lower() != "formal"
        or _meeting_candidate_authority(meeting_round)
        != FORMAL_GROUNDED_CANDIDATE_AUTHORITY
    ):
        return {"status": "not_applicable"}
    authority = (
        dict(meeting_round.get("modelInvocationReceiptAuthority"))
        if isinstance(meeting_round.get("modelInvocationReceiptAuthority"), Mapping)
        else {}
    )
    workflow_run_id = str(
        authority.get("workflowRunId") or meeting_round.get("workflowRunId") or ""
    ).strip()
    question_id = str(meeting_round.get("question") or "").strip().upper()
    meeting_round_id = str(meeting_round.get("meetingRoundId") or "").strip()
    from core.web.services.team_workflow import hypothesis_review_executor

    from .model_invocation_receipt_registry import (
        question_model_invocation_receipt_refs,
    )

    receipt_refs = question_model_invocation_receipt_refs(
        team_id,
        question_id=question_id,
        workflow_run_id=workflow_run_id,
    )
    revision_receipts = [
        dict(item)
        for item in receipt_refs
        if "revision" in list(item.get("outcomeKinds") or [])
        and isinstance(item.get("evidenceLocator"), Mapping)
        and str((item.get("evidenceLocator") or {}).get("meetingRoundId") or "")
        == meeting_round_id
    ]
    if not revision_receipts:
        return _blocked_round_authority(
            "feedback_iterations", "hypothesis_grounded_revision_receipt_missing"
        )
    draft_refs = _normalized_str_list(meeting_round.get("exploratoryDraftRefs"))
    draft_ids = [item.split(":", 1)[-1].strip() for item in draft_refs]
    available_drafts = _available_exploratory_drafts(
        team_id,
        question_id=question_id,
        workflow_run_id=workflow_run_id,
    )
    drafts_by_id = {
        str(item.get("draftId") or item.get("candidateId") or "").strip(): item
        for item in available_drafts
        if isinstance(item, Mapping)
    }
    drafts = [drafts_by_id[item] for item in draft_ids if item in drafts_by_id]
    if not draft_ids or len(drafts) != len(draft_ids) or not candidates:
        return _blocked_round_authority(
            "feedback_iterations", "hypothesis_grounded_revision_source_missing"
        )
    r0_snapshot = hypothesis_review_executor.canonical_hypothesis_revision_snapshot(
        drafts
    )
    r1_snapshot = hypothesis_review_executor.canonical_hypothesis_revision_snapshot(
        candidates
    )
    r1_refs = [
        f"hypothesis_candidate:{item['candidateId']}:r1" for item in r1_snapshot
    ]
    source_collection_run_id = str(
        authority.get("sourceCollectionRunId")
        or meeting_round.get("sourceCollectionRunId")
        or hypothesis_review_executor._source_collection_run_id_for_formal_workflow(
            workflow_run_id
        )
        or workflow_run_id
    ).strip()
    from .feedback_iterations_artifact_writer import (
        write_feedback_iterations_artifact,
    )

    return write_feedback_iterations_artifact(
        team_id=team_id,
        workflow_run_id=workflow_run_id,
        node_run_id=str(revision_receipts[0].get("nodeRunId") or "").strip(),
        question_id=question_id,
        iteration_round=1,
        feedback={
            "trigger": "formal_grounded_generation",
            "humanFeedback": (
                "Use the approved evidence whitelist and R0 lineage to produce "
                "testable, falsifiable hypotheses."
            ),
            "inputRefs": [
                f"exploratory_draft:{item['candidateId']}:r0" for item in r0_snapshot
            ],
            "inputHash": _stable_hash(r0_snapshot),
        },
        revision={
            "changes": [
                f"Grounded {len(r1_snapshot)} hypotheses against the approved evidence whitelist."
            ],
            "unresolvedIssues": [
                "Independent review and MetaReview remain pending."
            ],
            "outputRefs": r1_refs,
            "outputHash": _stable_hash(r1_snapshot),
            "status": "completed",
            "actual": True,
        },
        source_collection_run_id=source_collection_run_id,
        node_id="hypothesis_design",
        revision_phase="grounded_revision",
    )


def resolve_stage_one_generation_launch(
    team_id: str,
    question_id: str,
    workflow_run_id: str,
) -> dict[str, Any]:
    """Resolve the grounded R1 launch bundle for one run-scoped generation.

    The v2 command path and the REST candidate-generation entry must open the
    same authority: receipt authority verified from the canonical ledger, the
    generation discussion scope, and — when the run is pinned to the current
    stage-one policy — the formal grounded candidate authority together with
    its grounded context.  A blocked context (for example a knowledge package
    without evidence claims) raises :class:`StageOneContextBlockedError`
    before any meeting opens; an empty return means the caller has no run
    context and proceeds with the plain exploratory path.
    """

    from core.research.workflow.contracts.discussion_scope import (
        WorkflowDiscussionScopeV1,
    )
    from core.web.services.team_workflow.research_runtime.meeting_receipt_authority import (
        resolve_active_question_authority,
    )

    normalized_team_id = str(team_id or "").strip()
    normalized_question_id = str(question_id or "").strip().upper()
    normalized_workflow_run_id = str(workflow_run_id or "").strip()
    if not normalized_workflow_run_id:
        return {}
    receipt_authority = resolve_active_question_authority(
        normalized_team_id,
        normalized_question_id,
        normalized_workflow_run_id,
    )
    if receipt_authority is None:
        raise HypothesisFirstChainError(
            "workflow run authority is unavailable for generation"
        )
    project = _question_research_project(normalized_team_id, normalized_question_id)
    research_project_id = str((project or {}).get("projectId") or "").strip()
    if not research_project_id:
        raise HypothesisFirstChainError(
            "research project authority is unavailable for generation"
        )
    discussion_scope = WorkflowDiscussionScopeV1.generation(
        teamId=normalized_team_id,
        researchProjectId=research_project_id,
        workflowRunId=normalized_workflow_run_id,
        workflowNodeId=HYPOTHESIS_DESIGN_NODE_ID,
        questionId=normalized_question_id,
    ).to_dict()
    from core.web.services.team_workflow.research_project_hypothesis_context import (
        build_stage_one_grounded_generation_context,
    )

    generation_context = build_stage_one_grounded_generation_context(
        normalized_team_id,
        normalized_workflow_run_id,
        question_id=normalized_question_id,
    )
    candidate_authority = ""
    if generation_context is not None:
        if str(generation_context.get("status") or "") == "blocked":
            raise StageOneContextBlockedError(generation_context)
        candidate_authority = FORMAL_GROUNDED_CANDIDATE_AUTHORITY
    return {
        "receipt_authority": receipt_authority,
        "discussion_scope": discussion_scope,
        "candidate_authority": candidate_authority,
        "generation_context": generation_context,
    }


def _abandon_open_generation_meeting_without_rounds(
    team_id: str, meeting_round_id: str
) -> None:
    """Close a just-created zero-round meeting after a failed opening.

    The meeting runtime commits the open MeetingRound record before it starts
    the opening chat-room round; a busy/failed launch must not leave that
    zero-round record open and polluting the state surface.  The supersede is
    the same append-only empty-discussion recovery used for dead discussions:
    it refuses to touch meetings whose discussion round actually started, so
    an open meeting with a bound round is left untouched here.
    """

    from core.web.services.team_workflow import meeting_rounds

    try:
        meeting = meeting_rounds.get_meeting_round(team_id, meeting_round_id)[
            "meetingRound"
        ]
    except Exception:  # noqa: BLE001 - no record to abandon must mask the launch error
        return
    if (
        str(meeting.get("meetingType") or "").strip().lower()
        != CANDIDATE_GENERATION_MEETING_TYPE
        or str(meeting.get("status") or "").strip().lower() != "open"
        or _normalized_str_list(meeting.get("chatRoomRoundIds"))
    ):
        return
    try:
        meeting_rounds.supersede_empty_discussion_meeting(
            team_id,
            meeting_round_id,
            actor="system:generation-open-failed",
        )
    except Exception:  # noqa: BLE001 - supersede race keeps the primary launch error
        return


def open_candidate_generation_meeting(
    team_id: str,
    question_id: str,
    *,
    agent_runner: Any = None,
    background: bool = True,
    _model_invocation_receipt_authority: Mapping[str, Any] | None = None,
    _discussion_scope: Mapping[str, Any] | None = None,
    _candidate_authority: str = "",
    _generation_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Open (or reuse) the round-0 candidate-generation discussion.

    Deterministic per scope/question/attempt: replays reuse the open meeting
    instead of duplicating the discussion, and a closed attempt that already
    registered candidates is reused as-is.  Only a closed attempt that
    produced nothing rolls to a fresh per-attempt id so regeneration stays
    possible.  A terminal attempt with no successful discussion evidence is
    superseded before the next attempt opens.  Participants come from the
    team's linked chat room, same as review meetings.
    """
    from core.web.services import team_service
    from core.web.services.team_workflow import meeting_rounds, meeting_runtime

    normalized_team_id = team_service.assert_team_exists(team_id)
    candidate_authority = str(_candidate_authority or "").strip().lower()
    if candidate_authority not in {
        "",
        EXPLORATORY_DRAFT_AUTHORITY,
        FORMAL_GROUNDED_CANDIDATE_AUTHORITY,
    }:
        raise HypothesisFirstChainError("candidate generation authority is invalid")
    generation_context = (
        dict(_generation_context) if isinstance(_generation_context, Mapping) else {}
    )
    if candidate_authority == FORMAL_GROUNDED_CANDIDATE_AUTHORITY:
        if str(generation_context.get("status") or "") != "ready":
            raise HypothesisFirstChainError(
                "formal grounded generation requires an accepted knowledge package"
            )
        if not _normalized_str_list(generation_context.get("allowedEvidenceRefs")):
            raise HypothesisFirstChainError(
                "formal grounded generation requires accepted evidence refs"
            )
    scope = _question_scope_envelope(normalized_team_id, question_id)
    normalized_question_id = scope["question"]
    receipt_workflow_run_id = ""
    if isinstance(_model_invocation_receipt_authority, Mapping):
        receipt_workflow_run_id = str(
            _model_invocation_receipt_authority.get("workflowRunId") or ""
        ).strip()
    discussion_workflow_run_id = ""
    if _discussion_scope is not None:
        from core.research.workflow.contracts.discussion_scope import (
            QUESTION_GENERATION_SCOPE_KIND,
            parse_discussion_scope,
        )

        parsed_discussion_scope = parse_discussion_scope(_discussion_scope)
        if (
            parsed_discussion_scope.kind != QUESTION_GENERATION_SCOPE_KIND
            or parsed_discussion_scope.teamId != normalized_team_id
            or parsed_discussion_scope.questionId.upper() != normalized_question_id
        ):
            raise HypothesisFirstChainError(
                "candidate generation discussion scope does not match team/question"
            )
        discussion_workflow_run_id = parsed_discussion_scope.workflowRunId
        _discussion_scope = parsed_discussion_scope.to_dict()
    if (
        receipt_workflow_run_id
        and discussion_workflow_run_id
        and receipt_workflow_run_id != discussion_workflow_run_id
    ):
        raise HypothesisFirstChainError(
            "candidate generation receipt and discussion scope belong to different workflow runs"
        )
    workflow_run_id = receipt_workflow_run_id or discussion_workflow_run_id
    scope_hash = scope_hash_for(
        **{field: scope[field] for field in _SCOPE_FIELDS},
        agent_id=scope["agentId"],
        mode=scope["mode"],
    )
    all_meetings = [
        meeting
        for meeting in _question_generation_meetings(
            normalized_team_id, normalized_question_id
        )
        if _meeting_candidate_authority(meeting) == candidate_authority
    ]
    run_meetings = (
        [
            meeting
            for meeting in _question_generation_meetings(
                normalized_team_id,
                normalized_question_id,
                workflow_run_id=workflow_run_id,
            )
            if _meeting_candidate_authority(meeting) == candidate_authority
        ]
        if workflow_run_id
        else all_meetings
    )
    open_meeting = next(
        (
            meeting
            for meeting in run_meetings
            if str(meeting.get("status") or "")
            in {"open", "summarizing", "awaiting_approval"}
        ),
        None,
    )
    if (
        open_meeting is not None
        and str(open_meeting.get("status") or "").strip().lower()
        in {"open", "summarizing"}
        and _normalized_str_list(open_meeting.get("chatRoomRoundIds"))
        and not meeting_rounds.running_bound_round_ids(open_meeting)
        and not meeting_rounds.completed_meeting_source_messages(open_meeting)
    ):
        meeting_rounds.supersede_empty_discussion_meeting(
            normalized_team_id,
            str(open_meeting.get("meetingRoundId") or ""),
        )
        failed_meeting_id = str(open_meeting.get("meetingRoundId") or "")
        with _LOCK:
            failed_attempts = _generation_attempts(
                _read_jsonl(_storage_path(normalized_team_id)),
                normalized_question_id,
            )
        failed_attempt = next(
            (
                item
                for item in reversed(failed_attempts)
                if str(item.get("meetingRoundId") or "") == failed_meeting_id
            ),
            None,
        )
        if failed_attempt is not None:
            _append_generation_attempt_state(
                normalized_team_id,
                question_id=normalized_question_id,
                attempt_id=str(failed_attempt.get("attemptId") or ""),
                attempt_number=int(failed_attempt.get("attemptNumber") or 1),
                meeting_round_id=failed_meeting_id,
                lifecycle="failed",
                error="discussion_has_no_completed_messages",
            )
        all_meetings = [
            meeting
            for meeting in _question_generation_meetings(
                normalized_team_id, normalized_question_id
            )
            if _meeting_candidate_authority(meeting) == candidate_authority
        ]
        run_meetings = (
            [
                meeting
                for meeting in _question_generation_meetings(
                    normalized_team_id,
                    normalized_question_id,
                    workflow_run_id=workflow_run_id,
                )
                if _meeting_candidate_authority(meeting) == candidate_authority
            ]
            if workflow_run_id
            else all_meetings
        )
        open_meeting = None
    if open_meeting is not None and _normalized_str_list(
        open_meeting.get("chatRoomRoundIds")
    ):
        meeting_runtime._require_matching_model_invocation_receipt_authority(
            open_meeting,
            _model_invocation_receipt_authority,
            team_id=normalized_team_id,
            question_id=normalized_question_id,
        )
        bound_round_ids = _normalized_str_list(open_meeting.get("chatRoomRoundIds"))
        return {
            "schemaVersion": SCHEMA_VERSION,
            "teamId": normalized_team_id,
            "status": "reused",
            "meetingRound": open_meeting,
            "roomId": str(open_meeting.get("linkedChatRoomId") or ""),
            "roundId": bound_round_ids[-1],
            "chatRoomRoundIds": bound_round_ids,
            "questionId": normalized_question_id,
        }
    latest_closed_meeting = (
        run_meetings[-1] if open_meeting is None and run_meetings else None
    )
    if (
        latest_closed_meeting is not None
        and not _is_execution_stopped_meeting(latest_closed_meeting)
    ):
        # All attempts are closed.  When candidates were registered the latest
        # closed meeting is the answer and replays reuse it; a closed attempt
        # that produced nothing must not block a fresh attempt, so the new
        # meeting gets a deterministic per-attempt id instead of reopening the
        # closed record.
        # Crash between the closure write and the candidate registration left
        # a closed meeting whose proposals never landed; re-register them
        # (idempotent) instead of forcing a whole new generation discussion.
        _heal_generation_candidates(normalized_team_id, latest_closed_meeting)
        if candidate_authority == EXPLORATORY_DRAFT_AUTHORITY:
            return {
                "schemaVersion": SCHEMA_VERSION,
                "teamId": normalized_team_id,
                "status": "reused",
                "meetingRound": latest_closed_meeting,
                "roomId": str(latest_closed_meeting.get("linkedChatRoomId") or ""),
                "chatRoomRoundIds": _normalized_str_list(
                    latest_closed_meeting.get("chatRoomRoundIds")
                ),
                "questionId": normalized_question_id,
            }
        candidates = list_hypothesis_candidates(
            normalized_team_id,
            question_id=normalized_question_id,
            workflow_run_id=workflow_run_id,
        )["candidates"]
        candidate_count = len(candidates)
        # A single candidate can never satisfy the >=2 selection floor; reuse
        # only when the registered set is actually selectable, otherwise let a
        # fresh generation attempt run instead of dead-locking the question.
        has_candidates = candidate_count >= 2
        if has_candidates:
            existing = latest_closed_meeting
            meeting_runtime._require_matching_model_invocation_receipt_authority(
                existing,
                _model_invocation_receipt_authority,
                team_id=normalized_team_id,
                question_id=normalized_question_id,
            )
            return {
                "schemaVersion": SCHEMA_VERSION,
                "teamId": normalized_team_id,
                "status": "reused",
                "meetingRound": existing,
                "roomId": str(existing.get("linkedChatRoomId") or ""),
                "chatRoomRoundIds": _normalized_str_list(existing.get("chatRoomRoundIds")),
            }
    if _discussion_scope is None:
        # A retry can be initiated after the creation request has completed.
        # Carry forward the latest valid server-written generation scope so a
        # transient retry does not lose the run/node identity needed later by
        # candidate-level reviews.
        from core.research.workflow.contracts.discussion_scope import (
            QUESTION_GENERATION_SCOPE_KIND,
            parse_discussion_scope,
        )

        for previous in reversed(run_meetings):
            if _is_execution_stopped_meeting(previous):
                continue
            previous_scope = previous.get("discussionScope")
            if not isinstance(previous_scope, Mapping):
                continue
            try:
                parsed_scope = parse_discussion_scope(previous_scope)
            except ContractValidationError:
                continue
            if (
                parsed_scope.kind == QUESTION_GENERATION_SCOPE_KIND
                and parsed_scope.teamId == normalized_team_id
                and parsed_scope.questionId.upper() == normalized_question_id
            ):
                _discussion_scope = parsed_scope.to_dict()
                break
    authority_suffix = (
        "-r0"
        if candidate_authority == EXPLORATORY_DRAFT_AUTHORITY
        else "-r1"
        if candidate_authority == FORMAL_GROUNDED_CANDIDATE_AUTHORITY
        else ""
    )
    base_id = f"hf-candgen-{scope_hash[:16]}{authority_suffix}"
    if open_meeting is not None:
        meeting_round_id = str(open_meeting.get("meetingRoundId") or "")
    else:
        attempt = len(all_meetings) + 1
        meeting_round_id = base_id if attempt == 1 else f"{base_id}-a{attempt}"
    with _LOCK:
        previous_attempts = _generation_attempts(
            _read_jsonl(_storage_path(normalized_team_id)),
            normalized_question_id,
        )
    attempt_number = max(
        [int(item.get("attemptNumber") or 0) for item in previous_attempts]
        + [len(all_meetings) + 1]
    )
    previous_attempt_id = (
        str(previous_attempts[-1].get("attemptId") or "")
        if previous_attempts
        else ""
    )
    attempt_id = f"hf2-generation-{_stable_hash({'teamId': normalized_team_id, 'questionId': normalized_question_id, 'attemptNumber': attempt_number})[:20]}"
    if previous_attempt_id == attempt_id:
        previous_attempt_id = str(
            previous_attempts[-1].get("supersedesAttemptId") or ""
        )
    _append_generation_attempt_state(
        normalized_team_id,
        question_id=normalized_question_id,
        attempt_id=attempt_id,
        attempt_number=attempt_number,
        meeting_round_id=meeting_round_id,
        lifecycle="queued",
        supersedes_attempt_id=previous_attempt_id,
    )
    try:
        _team, room_id = meeting_runtime._ensure_linked_room(normalized_team_id)
    except Exception as exc:
        _append_generation_attempt_state(
            normalized_team_id,
            question_id=normalized_question_id,
            attempt_id=attempt_id,
            attempt_number=attempt_number,
            meeting_round_id=meeting_round_id,
            lifecycle="failed",
            supersedes_attempt_id=previous_attempt_id,
            error=f"{type(exc).__name__}: {exc}",
        )
        raise
    participant_resolution = _resolve_hypothesis_participants(
        normalized_team_id, room_id, CANDIDATE_GENERATION_MEETING_TYPE
    )
    payload = {
        **scope,
        "questionId": normalized_question_id,
        "meetingRoundId": meeting_round_id,
        **participant_resolution,
        "candidateAuthority": candidate_authority,
    }
    if candidate_authority == FORMAL_GROUNDED_CANDIDATE_AUTHORITY:
        drafts = _available_exploratory_drafts(
            normalized_team_id,
            normalized_question_id,
            workflow_run_id=workflow_run_id,
        )
        draft_refs = [
            f"exploratory_draft:{str(item.get('draftId') or item.get('candidateId') or '').strip()}"
            for item in drafts
            if str(item.get("draftId") or item.get("candidateId") or "").strip()
        ]
        if not draft_refs:
            raise HypothesisFirstChainError(
                "formal grounded generation requires R0 exploratory drafts"
            )
        knowledge_package = (
            dict(generation_context.get("knowledgePackage") or {})
            if isinstance(generation_context.get("knowledgePackage"), Mapping)
            else {}
        )
        knowledge_refs = _normalized_str_list(
            knowledge_package.get("sourceArtifactIds")
        )
        payload.update(
            {
                "allowedEvidenceRefs": _normalized_str_list(
                    generation_context.get("allowedEvidenceRefs")
                ),
                "exploratoryDraftRefs": draft_refs,
                "knowledgePackageRefs": knowledge_refs,
                "revisionOrdinal": 1,
                "inputArtifactRefs": [*knowledge_refs, *draft_refs],
                "generationContext": {
                    "candidateAuthority": candidate_authority,
                    "evidenceClaims": list(
                        generation_context.get("evidenceClaims") or []
                    )[:8],
                    "exploratoryDrafts": drafts[:8],
                },
            }
        )
    if isinstance(_discussion_scope, Mapping):
        payload["discussionScope"] = dict(_discussion_scope)
    try:
        opened = meeting_runtime.open_candidate_generation_meeting(
            normalized_team_id,
            payload,
            agent_runner=agent_runner,
            background=background,
            _model_invocation_receipt_authority=_model_invocation_receipt_authority,
        )
    except Exception as exc:
        _append_generation_attempt_state(
            normalized_team_id,
            question_id=normalized_question_id,
            attempt_id=attempt_id,
            attempt_number=attempt_number,
            meeting_round_id=meeting_round_id,
            lifecycle="failed",
            supersedes_attempt_id=previous_attempt_id,
            error=f"{type(exc).__name__}: {exc}",
        )
        _abandon_open_generation_meeting_without_rounds(
            normalized_team_id, meeting_round_id
        )
        raise
    _append_generation_attempt_state(
        normalized_team_id,
        question_id=normalized_question_id,
        attempt_id=attempt_id,
        attempt_number=attempt_number,
        meeting_round_id=meeting_round_id,
        lifecycle="running",
        supersedes_attempt_id=previous_attempt_id,
    )
    return {
        **opened,
        "questionId": normalized_question_id,
        "generationAttemptId": attempt_id,
    }


def needs_candidate_generation(
    team_id: str,
    question_id: str,
    *,
    workflow_run_id: str = "",
) -> bool:
    """True when the question has no selectable candidates and no generation meeting."""
    from core.web.services.team_workflow import hypothesis_selection

    normalized_workflow_run_id = str(workflow_run_id or "").strip()
    if normalized_workflow_run_id:
        meetings = [
            meeting
            for meeting in _question_generation_meetings(
                team_id,
                question_id,
                workflow_run_id=normalized_workflow_run_id,
            )
            if _meeting_candidate_authority(meeting) != EXPLORATORY_DRAFT_AUTHORITY
        ]
        candidate_ids = hypothesis_selection._approved_candidate_ids(
            team_id,
            question_id,
            workflow_run_id=normalized_workflow_run_id,
        )
        if len(candidate_ids) >= 2:
            return False
        if any(
            str(meeting.get("status") or "").strip().lower()
            in _ACTIVE_MEETING_STATUSES
            for meeting in meetings
        ):
            return False
        # Same-question R0 drafts (in-run first, origin fallback) already
        # satisfy the R1 input floor, so a fresh stage-one run must not open
        # a second exploratory round on top of them — the next step is the
        # grounded R1 generation that consumes those drafts.
        if (
            len(
                _available_exploratory_drafts(
                    team_id,
                    question_id,
                    workflow_run_id=normalized_workflow_run_id,
                )
            )
            >= 2
        ):
            return False
        return True
    # _approved_candidate_ids already unions the approved artifact and the
    # chain-ledger candidates, so a non-empty set means selection can start.
    if hypothesis_selection._approved_candidate_ids(team_id, question_id):
        return False
    return not [
        meeting
        for meeting in _question_generation_meetings(team_id, question_id)
        if _meeting_candidate_authority(meeting) != EXPLORATORY_DRAFT_AUTHORITY
    ]


def _generation_proposals_from_digest(digest: Any) -> list[dict[str, Any]]:
    if not isinstance(digest, Mapping):
        return []
    return [
        dict(item)
        for item in list(digest.get("proposedCandidates") or [])
        if isinstance(item, Mapping)
    ]


def _generation_proposals_from_messages(
    meeting_round: Mapping[str, Any],
) -> list[dict[str, Any]]:
    from core.web.services.team_workflow import meeting_rounds

    markers = meeting_rounds.extract_discussion_markers(
        meeting_rounds.meeting_source_messages(meeting_round)
    )
    return [
        dict(item)
        for item in list(markers.get("proposedCandidates") or [])
        if isinstance(item, Mapping)
    ]


def _heal_generation_candidates(team_id: str, closed_meeting: Mapping[str, Any]) -> None:
    if (
        str(closed_meeting.get("status") or "") != "closed"
        or _is_execution_stopped_meeting(closed_meeting)
    ):
        return
    digest = closed_meeting.get("digest")
    if not isinstance(digest, Mapping):
        digest = closed_meeting.get("digestDraft")
    proposals = _generation_proposals_from_digest(digest)
    if not proposals:
        proposals = _generation_proposals_from_messages(closed_meeting)
    _append_generation_candidates(team_id, closed_meeting, proposals)


def _close_generation_meeting(
    team_id: str,
    meeting_round: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Approve a candidate-generation closure and register its proposals."""
    from core.web.services.team_workflow import meeting_rounds

    normalized_team_id = team_id
    normalized_round_id = str(meeting_round.get("meetingRoundId") or "")
    request = dict(payload)
    digest_draft = (
        dict(meeting_round.get("digestDraft"))
        if isinstance(meeting_round.get("digestDraft"), Mapping)
        else {}
    )
    proposals = _generation_proposals_from_digest(digest_draft)
    if not proposals:
        proposals = _generation_proposals_from_messages(meeting_round)
        if proposals:
            # A stale or raced summary draft may have dropped this field.  Feed
            # the recovered proposals into the approved digest as well as the
            # chain ledger so the closure remains self-describing and replayable.
            request["proposedCandidates"] = proposals
    if not [item for item in list(request.get("decisions") or []) if isinstance(item, Mapping)]:
        # The §15.4 closure gate requires at least one decision; for a
        # generation round the decision IS the proposed candidate list, so
        # synthesize it from the digest when the approver did not pass one.
        candidate_refs = [
            str(item.get("candidateId") or "").strip()
            for item in proposals
            if str(item.get("candidateId") or "").strip()
        ]
        source_refs = _normalized_str_list(digest_draft.get("sourceMessageRefs"))
        request["decisions"] = [
            {
                "decision": "propose_candidates",
                "rationale": f"第 0 轮候选生成讨论产出 {len(proposals)} 条候选假说",
                "decidedBy": str(request.get("closedBy") or "").strip() or _OPERATOR_AGENT_ID,
                "candidateRefs": candidate_refs,
                "evidenceRefs": source_refs[:1] or [f"meeting_round:{normalized_round_id}"],
                "status": "adopted",
            }
        ]
    result = meeting_rounds.approve_meeting_closure(
        normalized_team_id, normalized_round_id, request
    )
    closed_record = result["meetingRound"]
    generated_records = _append_generation_candidates(
        normalized_team_id, closed_record, proposals
    )
    exploratory = (
        _meeting_candidate_authority(closed_record) == EXPLORATORY_DRAFT_AUTHORITY
    )
    candidates = [] if exploratory else generated_records
    drafts = generated_records if exploratory else []
    grounded_revision_authority: dict[str, Any] | None = None
    if not exploratory:
        try:
            grounded_revision_authority = _materialize_grounded_revision_authority(
                normalized_team_id, closed_record, candidates
            )
        except Exception as exc:  # noqa: BLE001 - closure fact stays append-only
            grounded_revision_authority = {
                **_blocked_round_authority(
                    "feedback_iterations",
                    "hypothesis_grounded_revision_authority_persistence_failed",
                ),
                "error": str(exc) or type(exc).__name__,
            }
    # Active-policy hook (autoSelectCandidates): gated, audited, quiet.  With
    # no active policy configured this is a no-op before any I/O.
    if not exploratory:
        _auto_advance_selection_tick(normalized_team_id, meeting_round, candidates)
    # Shadow decision point "meeting_close" (generation digest confirmation):
    # advisory record only; the return value and every executed branch below
    # are identical with or without a configured shadow policy.
    _record_policy_shadow_decisions(
        normalized_team_id,
        meeting_round,
        lambda: [
            (
                "meeting_close",
                {
                    "meetingRoundId": normalized_round_id,
                    "meetingType": str(meeting_round.get("meetingType") or ""),
                    "closureApproved": True,
                    "digestConfirmed": bool(digest_draft),
                    "decisionsResolved": bool(
                        [
                            item
                            for item in list(request.get("decisions") or [])
                            if isinstance(item, Mapping)
                        ]
                    ),
                    "closedBy": str(request.get("closedBy") or "").strip(),
                    "candidateCount": len(candidates),
                },
                {
                    "outcome": "generation_digest_approved",
                    "outcomeClass": "acted",
                    "command": "close_generation_meeting",
                    "ref": f"meeting_round:{normalized_round_id}",
                },
            )
        ],
    )
    return {
        **result,
        "candidates": candidates,
        "candidateCount": len(candidates),
        "drafts": drafts,
        "draftCount": len(drafts),
        **(
            {"feedbackIterationsAuthority": grounded_revision_authority}
            if grounded_revision_authority is not None
            else {}
        ),
    }


def _normalize_budget(budget: Any) -> int:
    if budget is None:
        return HARD_ROUND_LIMIT
    try:
        normalized = int(budget)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"round limit must be an integer: {budget!r}") from exc
    if normalized != HARD_ROUND_LIMIT:
        raise ValueError(
            f"round limit is fixed at {HARD_ROUND_LIMIT}: {normalized}"
        )
    return HARD_ROUND_LIMIT


def reopen_failed_review_meeting(
    team_id: str,
    meeting_round_id: str,
    *,
    agent_runner: Any = None,
    background: bool = True,
    budget: Any = None,
) -> dict[str, Any]:
    """Restart one review round whose discussion produced no successful speech.

    The recovery a blocked summarize surfaces as ``重新发起讨论`` for review
    rounds: the failed attempt is superseded (append-only, no digest) and the
    next budget-gated round opens with the same selection lineage.  Guards
    live in ``meeting_rounds.supersede_empty_discussion_meeting`` — only a
    terminal round with zero completed messages may be recovered this way.
    """
    from core.web.services import team_service
    from core.web.services.team_workflow import meeting_rounds

    normalized_team_id = team_service.assert_team_exists(team_id)
    normalized_round_id = str(meeting_round_id or "").strip()
    if not normalized_round_id:
        raise HypothesisFirstChainError("meeting_round_id is required.")
    meeting_round = meeting_rounds.get_meeting_round(
        normalized_team_id, normalized_round_id
    )["meetingRound"]
    if str(meeting_round.get("meetingType") or "") != HYPOTHESIS_REVIEW_MEETING_TYPE:
        raise HypothesisFirstChainError(
            "reopen-failed-discussion only applies to hypothesis_review meetings."
        )
    superseded = meeting_rounds.supersede_empty_discussion_meeting(
        normalized_team_id,
        normalized_round_id,
        actor="operator:failed-discussion-restart",
    )
    reopened = open_next_review_meeting(
        normalized_team_id,
        previous_meeting_round_id=normalized_round_id,
        agent_runner=agent_runner,
        background=background,
        budget=budget,
    )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "status": "reopened",
        "openStatus": str(reopened.get("status") or ""),
        "supersededMeetingRound": superseded.get("meetingRound") or {},
        **{
            key: value
            for key, value in reopened.items()
            if key not in {"schemaVersion", "teamId", "status"}
        },
    }


def open_next_review_meeting(
    team_id: str,
    *,
    previous_meeting_round_id: str,
    collection_request_id: str = "",
    agent_runner: Any = None,
    background: bool = True,
    budget: Any = None,
    fan_out_selection: bool = False,
    enforce_sibling_archive_gate: bool = False,
) -> dict[str, Any]:
    """Open the next review round after knowledge back-fill, hard-limit gated.

    Each completed meta-review decides whether the hypothesis has converged or
    needs another round.  The only round limit is ``HARD_ROUND_LIMIT``; once it
    is reached without convergence, no further meeting opens and the result
    reports ``budget_exhausted`` for an explicit blocked/manual decision.

    With ``enforce_sibling_archive_gate`` the open also waits for the
    selection's newest logical round to be fully archived: while any sibling
    review meeting of that round is still actionable
    (open/summarizing/awaiting_approval) the result reports
    ``sibling_reviews_pending`` instead of opening, so the sibling's digest
    confirmation gate survives.  Superseded attempts stay on their
    ``retry_review_dispatch`` recovery and never block.
    """
    from core.web.services import team_service
    from core.web.services.team_workflow import hypothesis_selection as selections
    from core.web.services.team_workflow import meeting_rounds

    normalized_team_id = team_service.assert_team_exists(team_id)
    previous_id = str(previous_meeting_round_id or "").strip()
    if not previous_id:
        raise HypothesisFirstChainError("previous_meeting_round_id is required.")
    normalized_request_id = str(collection_request_id or "").strip()
    previous = meeting_rounds.get_meeting_round(normalized_team_id, previous_id)[
        "meetingRound"
    ]
    selection_id = _selection_id_from_meeting(previous)
    if not selection_id:
        raise HypothesisFirstChainError(
            f"meeting round {previous_id} carries no hypothesis_selection ref"
        )
    selection = selections.get_hypothesis_selection(normalized_team_id, selection_id)[
        "selection"
    ]

    if normalized_request_id:
        existing_link = next(
            (
                link
                for link in _review_round_links(_records(normalized_team_id))
                if str(link.get("collectionRequestId") or "") == normalized_request_id
            ),
            None,
        )
        if existing_link is not None:
            meeting = meeting_rounds.get_meeting_round(
                normalized_team_id, str(existing_link.get("meetingRoundId") or "")
            )["meetingRound"]
            return {
                "schemaVersion": SCHEMA_VERSION,
                "teamId": normalized_team_id,
                "status": "reused",
                "meetingRound": meeting,
                "roundIndex": int(existing_link.get("roundIndex") or 0),
                "link": existing_link,
            }

    links = [
        link
        for link in _review_round_links(_records(normalized_team_id))
        if str(link.get("selectionId") or "") == selection_id
    ]
    round_index = max((int(link.get("roundIndex") or 0) for link in links), default=0) + 1
    if enforce_sibling_archive_gate:
        gate = _latest_round_sibling_gate(normalized_team_id, selection_id)
        if gate["pendingMeetingRoundIds"]:
            return {
                "schemaVersion": SCHEMA_VERSION,
                "teamId": normalized_team_id,
                "status": "sibling_reviews_pending",
                "selectionId": selection_id,
                "roundIndex": round_index,
                "previousMeetingRoundId": previous_id,
                "pendingMeetingRoundIds": gate["pendingMeetingRoundIds"],
                "pendingCandidateIds": gate["pendingCandidateIds"],
            }
    effective_budget = _normalize_budget(budget)
    if round_index > effective_budget:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "teamId": normalized_team_id,
            "status": "budget_exhausted",
            "roundIndex": round_index,
            "budget": effective_budget,
            "selectionId": selection_id,
            "previousMeetingRoundId": previous_id,
        }
    return open_review_meeting_for_selection(
        normalized_team_id,
        selection,
        agent_runner=agent_runner,
        background=background,
        round_index=round_index,
        previous_meeting_round_id=previous_id,
        collection_request_id=normalized_request_id,
        round_budget=effective_budget,
        fan_out_selection=fan_out_selection,
    )


# ---------------------------------------------------------------------------
# closure -> collection trigger


def _decision_id_for(meeting_round: Mapping[str, Any], raw: Mapping[str, Any]) -> str:
    """Recompute the persisted DecisionRecord id for one raw closure decision."""
    from core.web.services.team_workflow import meeting_rounds

    candidate_refs = _normalized_str_list(raw.get("candidateRefs"))
    evidence_refs = _normalized_str_list(raw.get("evidenceRefs"))
    return f"decision-{meeting_rounds._stable_hash({'meetingRoundId': meeting_round['meetingRoundId'], 'scopeHash': meeting_round['scopeHash'], 'decision': str(raw.get('decision') or '').strip().lower(), 'candidateRefs': candidate_refs, 'evidenceRefs': evidence_refs})[:16]}"


def _question_research_project(team_id: str, question_id: str) -> dict[str, Any] | None:
    """Resolve the research project that owns one question, never the switcher.

    ``resolve_research_project_identity`` answers with the team's active
    project, which misbinds a question's identity as soon as the operator
    activates another question (production: SCI-003 meetings and their
    collection runs carried challenge-sci-002).  The question binding in the
    research-project store is authoritative; the read is best-effort, so any
    store/unreadable-team failure falls back to the exact legacy
    ``resolve_research_project_identity`` behavior (including its exceptions).
    """
    from core.web.services import team_service
    from core.web.services.team_workflow import research_projects
    from core.web.services.team_workflow.research_project_agent_sessions import (
        resolve_research_project_identity,
    )

    try:
        bound = research_projects.get_research_project_for_question(team_id, question_id)
    except (research_projects.ResearchProjectError, team_service.TeamServiceError):
        bound = None
    if bound is not None:
        return bound
    return resolve_research_project_identity(team_id)


def _question_workflow_run_binding(
    team_id: str,
    meeting_round: Mapping[str, Any],
) -> tuple[str, str]:
    """Return ``(workflowRunId, researchProjectId)`` for chain collection runs.

    The workflow run comes from the meeting's server-owned discussion-scope
    binding (the question's current formal run); the project is resolved from
    the question ownership, never from the meeting's own project field, which
    may still carry an older question's lineage.  The project id is only
    resolved when a workflow run is known: ``start_source_collection_run``
    honors a non-active project exclusively on workflow-run-scoped payloads.
    """
    workflow_run_id = str(meeting_round.get("workflowRunId") or "").strip()
    if not workflow_run_id:
        return "", ""
    question_project = _question_research_project(
        team_id, str(meeting_round.get("question") or "")
    )
    research_project_id = str((question_project or {}).get("projectId") or "").strip()
    return workflow_run_id, research_project_id


def _recovery_workflow_run_binding(
    team_id: str,
    request: Mapping[str, Any],
) -> tuple[str, str]:
    """Best-effort ``(workflowRunId, researchProjectId)`` for request recovery.

    Recovery requests only carry ``meetingRoundId``; the formal run binding
    lives on that meeting round.  A missing or legacy unscoped meeting keeps
    both fields empty so recovery proceeds with the legacy unscoped payload
    instead of failing the repair.
    """
    from core.web.services.team_workflow import meeting_rounds

    meeting_round_id = str(request.get("meetingRoundId") or "").strip()
    if not meeting_round_id:
        return "", ""
    try:
        meeting_round = meeting_rounds.get_meeting_round(team_id, meeting_round_id)[
            "meetingRound"
        ]
    except meeting_rounds.ResearchMeetingRoundNotFoundError:
        return "", ""
    return _question_workflow_run_binding(team_id, meeting_round)


def _scope_envelope_for_meeting(meeting_round: Mapping[str, Any]) -> dict[str, str]:
    """Rebuild the facade scope envelope from the meeting's validated scope."""
    from core.web.services.team_workflow import research_scope as scope_service

    identity = {
        field: str(meeting_round.get(field) or "").strip() for field in _SCOPE_FIELDS
    }
    agent_id = str(meeting_round.get("agentId") or "").strip()
    mode = str(meeting_round.get("mode") or "").strip().lower()
    scope_hash = str(meeting_round.get("scopeHash") or "").strip()
    expected = scope_hash_for(**identity, agent_id=agent_id, mode=mode)
    if not scope_hash or scope_hash != expected:
        raise HypothesisFirstChainError(
            "meeting round scopeHash does not match its scope identity"
        )
    return {
        **identity,
        "agentId": agent_id,
        "mode": mode,
        "scopeHash": scope_hash,
        "artifactLocator": scope_service._artifact_locator(identity, scope_hash),
        "ledgerRoot": scope_service._ledger_root(identity, scope_hash),
        "cacheKey": scope_service._cache_key(identity, agent_id, scope_hash),
    }


def _request_hash(
    meeting_round: Mapping[str, Any],
    decision_id: str,
    envelope: Mapping[str, Any],
    requirements: Mapping[str, Any],
    writeback_policy: Mapping[str, Any],
) -> str:
    return _stable_hash(
        {
            "meetingRoundId": str(meeting_round.get("meetingRoundId") or ""),
            "decisionId": decision_id,
            "searchEnvelope": dict(envelope),
            "requirements": dict(requirements),
            "writebackPolicy": dict(writeback_policy),
        }
    )


def _append_collection_request(
    team_id: str,
    meeting_round: Mapping[str, Any],
    decision_id: str,
    envelope: Mapping[str, Any],
    requirements: Mapping[str, Any],
    writeback_policy: Mapping[str, Any],
    collection_run_id: str,
    *,
    hypothesis_candidate_ids: list[str] | None = None,
) -> dict[str, Any]:
    request_hash = _request_hash(
        meeting_round, decision_id, envelope, requirements, writeback_policy
    )
    request_id = f"hfcr-{request_hash[:16]}"
    # Hypothesis candidate ids (``_candidate_id_for`` space) carried by the
    # decision's ``candidateRefs``.  They bridge the collection run back to the
    # claim belief gate's candidate dimension; the request id already hashes
    # candidateRefs through decisionId, so the hash itself stays unchanged.
    candidates = list(
        dict.fromkeys(
            str(item or "").strip()
            for item in list(hypothesis_candidate_ids or [])
            if str(item or "").strip()
        )
    )
    record = {
        "schemaVersion": SCHEMA_VERSION,
        "recordKind": COLLECTION_REQUEST_KIND,
        "requestId": request_id,
        "requestHash": request_hash,
        "status": "pending",
        "meetingRoundId": str(meeting_round.get("meetingRoundId") or ""),
        "decisionId": decision_id,
        "questionId": str(meeting_round.get("question") or ""),
        **{field: str(meeting_round.get(field) or "") for field in _SCOPE_FIELDS},
        "agentId": str(meeting_round.get("agentId") or ""),
        "mode": str(meeting_round.get("mode") or ""),
        "scopeHash": str(meeting_round.get("scopeHash") or ""),
        "searchEnvelope": dict(envelope),
        "requirements": dict(requirements),
        "writebackPolicy": dict(writeback_policy),
        "hypothesisCandidateIds": candidates,
        "collectionRunId": str(collection_run_id or ""),
        "collectionRunStatus": "",
        "createdAt": _utc_now(),
        "handedOffAt": "",
        "handoffRef": "",
        "handoffError": {},
    }
    with _LOCK:
        records = _read_jsonl(_storage_path(team_id))
        existing = _latest_by_id(
            [item for item in records if item.get("recordKind") == COLLECTION_REQUEST_KIND],
            "requestId",
            request_id,
        )
        if existing is not None:
            if str(existing.get("requestHash") or "") != request_hash:
                raise HypothesisFirstChainError(
                    f"collection request {request_id} is already bound to different content"
                )
            return existing
        _append_jsonl(_storage_path(team_id), record)
    return record


def _find_request_for_decision(
    team_id: str, meeting_round_id: str, decision_id: str
) -> dict[str, Any] | None:
    for record in _collection_requests(_records(team_id)):
        if (
            str(record.get("meetingRoundId") or "") == meeting_round_id
            and str(record.get("decisionId") or "") == decision_id
        ):
            return record
    return None


def _process_collection_decisions(
    team_id: str,
    meeting_round: Mapping[str, Any],
    close_result: Mapping[str, Any],
    request: Mapping[str, Any],
) -> dict[str, Any]:
    from core.web.services.team_workflow.source_collection import facade
    from core.web.services.team_workflow.source_collection import search_circuit
    from core.web.services.team_workflow.source_collection import (
        runs as source_collection_runs,
    )

    background_payload = _hypothesis_collection_background_payload()
    # Workflow-run-scoped binding for the created collection run: the formal
    # run id enables extraction-claim materialization and formal node
    # discovery by scope, and the question-owned project replaces the team's
    # active-project pointer (which may still sit on an older question).
    workflow_run_id, research_project_id = _question_workflow_run_binding(
        team_id, meeting_round
    )

    persisted_ids = {
        str(item.get("decisionId") or "")
        for item in list(close_result.get("decisions") or [])
        if isinstance(item, Mapping)
    }
    requests_out: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    start_candidates: dict[str, list[dict[str, Any]]] = {}
    gap_resolved: list[dict[str, Any]] = []
    raw_decisions = [
        item for item in list(request.get("decisions") or []) if isinstance(item, Mapping)
    ]
    for raw in raw_decisions:
        if str(raw.get("decision") or "").strip().lower() != REQUEST_EVIDENCE_DECISION:
            continue
        decision_id = _decision_id_for(meeting_round, raw)
        if decision_id not in persisted_ids:
            skipped.append(
                {"decisionId": decision_id, "reason": "decision_not_persisted"}
            )
            continue
        existing = _find_request_for_decision(
            team_id, str(meeting_round.get("meetingRoundId") or ""), decision_id
        )
        if existing is not None:
            requests_out.append(existing)
            continue
        # ``candidateRefs`` on a request_new_evidence decision are hypothesis
        # candidate ids — the claim belief gate's aggregation dimension.  A
        # decision without them can only materialize an empty dimension and
        # fail that gate closed at convergence, so it is rejected structurally
        # here (visible in ``collection.skipped`` plus a scene event) instead
        # of silently creating a request.  Replays with an already persisted
        # request stay above and keep their idempotent reuse.
        hypothesis_candidate_ids = list(
            dict.fromkeys(_normalized_str_list(raw.get("candidateRefs")))
        )
        if not hypothesis_candidate_ids:
            skipped.append(
                {
                    "decisionId": decision_id,
                    "reason": "candidate_refs_missing",
                    "error": (
                        "request_new_evidence decision carries no candidateRefs; "
                        "the claim belief gate aggregates evidence on this dimension"
                    ),
                }
            )
            _record_scene_event(
                "hypothesis_first.collection_decision_candidate_refs_missing",
                outcome="blocked",
                level="warning",
                fields={
                    "teamId": team_id,
                    "meetingRoundId": str(meeting_round.get("meetingRoundId") or ""),
                    "decisionId": decision_id,
                },
            )
            continue
        try:
            envelope = facade._normalize_search_envelope(
                raw.get("searchEnvelope"), require_keywords=True
            )
        except Exception as exc:  # noqa: BLE001 - closure stays visible and retryable
            reason = (
                "search_envelope_missing"
                if getattr(exc, "code", "") == "search_keywords_required"
                else "search_envelope_invalid"
            )
            skipped.append(
                {"decisionId": decision_id, "reason": reason, "error": str(exc)}
            )
            continue
        try:
            requirements = facade._normalize_requirements(raw.get("requirements"))
            writeback_policy = facade._normalize_writeback_policy(
                raw.get("writebackPolicy")
            )
        except Exception as exc:
            skipped.append(
                {
                    "decisionId": decision_id,
                    "reason": "collection_payload_invalid",
                    "error": str(exc),
                }
            )
            continue
        scope_envelope = _scope_envelope_for_meeting(meeting_round)
        # Retrieval-circuit consumption: a live evidence_gap_unavailable
        # marker for this exact goal means the rewrite budget is already
        # exhausted.  Never ensure a new collection run for it — record the
        # request in gap state and hand off to the next round carrying the
        # gap notice, so the review can converge with gaps instead of
        # re-running (and re-paying for) the same dead retrieval.
        gap_marker = search_circuit.live_evidence_gap_marker_for_goal(team_id, envelope)
        if gap_marker:
            record = _append_collection_request(
                team_id,
                meeting_round,
                decision_id,
                envelope,
                requirements,
                writeback_policy,
                "",
                hypothesis_candidate_ids=hypothesis_candidate_ids,
            )
            resolved = _resolve_request_evidence_gap(
                team_id, str(record.get("requestId") or ""), gap_marker
            )
            requests_out.append(resolved["request"])
            gap_resolved.append(resolved)
            continue
        ensured = facade.research_knowledge_collection_facade(
            action="ensure",
            scope=scope_envelope,
            searchEnvelope=envelope,
            requirements=requirements,
            writebackPolicy=writeback_policy,
            hypothesisCandidateIds=hypothesis_candidate_ids,
            workflowRunId=workflow_run_id,
            researchProjectId=research_project_id,
            team_id=team_id,
        )
        locator = ensured.get("locator") if isinstance(ensured.get("locator"), Mapping) else {}
        record = _append_collection_request(
            team_id,
            meeting_round,
            decision_id,
            envelope,
            requirements,
            writeback_policy,
            str(locator.get("runId") or ""),
            hypothesis_candidate_ids=hypothesis_candidate_ids,
        )
        _record_shadow_knowledge_invocation_for_chain(
            team_id,
            question_id=str(meeting_round.get("question") or ""),
            scope_envelope=scope_envelope,
            search_envelope=envelope,
            requirements=requirements,
            collection_run_id=str(record.get("collectionRunId") or ""),
            collection_request_id=str(record.get("requestId") or ""),
            meeting_round_id=str(meeting_round.get("meetingRoundId") or ""),
            decision_id=decision_id,
        )
        requests_out.append(record)
        collection_run_id = str(record.get("collectionRunId") or "").strip()
        if not collection_run_id:
            failed = _update_collection_request(
                team_id,
                str(record.get("requestId") or ""),
                status="failed",
                collectionRunStatus="failed",
                startError={
                    "code": "collection_run_missing",
                    "message": "资料搜集子运行未创建，无法启动搜索。",
                },
            )
            requests_out[-1] = failed
            continue
        start_candidates.setdefault(collection_run_id, []).append(record)

    for collection_run_id, records in start_candidates.items():
        try:
            source_collection_runs.start_source_collection_search_background(
                team_id,
                collection_run_id,
                background_payload,
            )
        except Exception as exc:
            start_error = {
                "code": "search_start_failed",
                "message": str(exc) or type(exc).__name__,
            }
            failed_by_request_id = {
                str(record.get("requestId") or ""): _update_collection_request(
                    team_id,
                    str(record.get("requestId") or ""),
                    status="failed",
                    collectionRunStatus="failed",
                    startError=start_error,
                )
                for record in records
            }
            requests_out = [
                failed_by_request_id.get(str(record.get("requestId") or ""), record)
                for record in requests_out
            ]
    return {
        "requests": requests_out,
        "skipped": skipped,
        **({"evidenceGaps": gap_resolved} if gap_resolved else {}),
    }


def _hypothesis_collection_background_payload() -> dict[str, Any]:
    """Drain a normal hypothesis evidence plan within the executor hard cap.

    The generic source-collection UI intentionally defaults to four queries per
    operator-triggered batch.  Hypothesis-first collection is an automatic
    workflow step, so it uses the executor's existing bounded maximum instead
    of pausing a typical eight-query plan halfway through.
    """
    from core.web.services import team_workflow_orchestration_service as service

    return {
        "backgroundExecution": True,
        "maxQueries": service.SOURCE_COLLECTION_SEARCH_EXECUTION_MAX_QUERIES,
    }


def _record_shadow_knowledge_invocation_for_chain(
    team_id: str,
    *,
    question_id: str,
    scope_envelope: Mapping[str, Any],
    search_envelope: Mapping[str, Any],
    requirements: Mapping[str, Any],
    collection_run_id: str = "",
    collection_request_id: str = "",
    meeting_round_id: str = "",
    decision_id: str = "",
    legacy_scope_hash: str = "",
) -> None:
    """Shadow-rollout hook (Task 7): mirror one legacy collection request.

    Only writes in ``[research.knowledge_sideflow] mode = "shadow"``; a no-op
    in every other mode and never raises.  The legacy chain's return values,
    records and behavior stay byte-for-byte identical.
    """
    from .knowledge_rollout import record_shadow_knowledge_invocation

    resolved_scope_hash = str(legacy_scope_hash or "").strip()
    if not resolved_scope_hash and isinstance(scope_envelope, Mapping):
        resolved_scope_hash = str(scope_envelope.get("scopeHash") or "")
    record_shadow_knowledge_invocation(
        team_id=team_id,
        question_id=str(question_id or ""),
        scope=dict(scope_envelope or {}),
        search_envelope=dict(search_envelope or {}),
        requirements=dict(requirements or {}),
        collection_run_id=collection_run_id,
        collection_request_id=collection_request_id,
        meeting_round_id=meeting_round_id,
        decision_id=decision_id,
        legacy_scope_hash=resolved_scope_hash,
    )


# ---------------------------------------------------------------------------
# closure -> HypothesisRound generation (HF-3 executor entry point)


_EMPTY_DISCUSSION_RECOVERY_REASON = "discussion_has_no_completed_messages"


def _is_execution_stopped_meeting(meeting_round: Mapping[str, Any]) -> bool:
    """True when a Challenge execution fence made the meeting non-evidence."""

    recovery_reason = str(meeting_round.get("recoveryReason") or "").strip()
    return (
        str(meeting_round.get("executionStatus") or "").strip().lower()
        == "stopped"
        or recovery_reason.startswith("challenge_")
    )


def _is_superseded_review_attempt(meeting_round: Mapping[str, Any]) -> bool:
    """True when a closed meeting is abandoned and cannot be review authority.

    Empty-discussion recovery and Challenge execution fences both close the
    attempt append-only without making its partial discussion authoritative.
    """
    return (
        str(meeting_round.get("status") or "").strip().lower() == "closed"
        and (
            str(meeting_round.get("recoveryReason") or "").strip()
            == _EMPTY_DISCUSSION_RECOVERY_REASON
            or _is_execution_stopped_meeting(meeting_round)
        )
    )


def _review_meeting_fan_in_group(
    team_id: str, meeting_round: Mapping[str, Any]
) -> dict[str, Any]:
    """Resolve the authoritative selection-level review group for one meeting.

    Authority is per candidate lineage, not per round index.  The group keeps
    the meeting's own round membership (round 1 spans the whole selection;
    later rounds are candidate-scoped follow-ups), but every group candidate
    resolves its authority by walking that candidate's links from the newest
    round downwards and binding the newest non-superseded closed meeting:

    - a superseded closure (``recoveryReason=discussion_has_no_completed_
      messages``, no digest/decisions) is skipped and never treated as
      evidence;
    - a newer still-active round blocks the candidate (the in-flight attempt
      outranks any older round, so a superseded round with a live successor is
      stale rather than authoritative);
    - a candidate whose newest attempt is superseded with no closed successor
      stays pending (its review is still waiting, not silently authoritative).

    A ready group therefore can never contain a superseded digest-less
    meeting, and the group's ``roundIndex`` is the highest authoritative round
    so close replays resolve to the same idempotent HypothesisRound instead of
    raising "missing digestId or decisionRefs" on structurally failed closes.
    """
    from core.web.services.team_workflow import hypothesis_selection as selections
    from core.web.services.team_workflow import meeting_rounds

    meeting_round_id = str(meeting_round.get("meetingRoundId") or "").strip()
    links = list_review_round_links(team_id).get("links") or []
    current_link = next(
        (
            dict(item)
            for item in links
            if str(item.get("meetingRoundId") or "").strip() == meeting_round_id
        ),
        {},
    )
    candidate_id = str(current_link.get("candidateId") or "").strip()
    if not candidate_id:
        return {
            "status": "ready",
            "selectionId": _selection_id_from_meeting(meeting_round),
            "roundIndex": int(current_link.get("roundIndex") or 1),
            "meetings": [dict(meeting_round)],
        }

    selection_id = str(current_link.get("selectionId") or "").strip()
    round_index = int(current_link.get("roundIndex") or 1)
    if not selection_id:
        raise HypothesisFirstChainError("candidate review link has no selectionId")
    selection = selections.get_hypothesis_selection(team_id, selection_id)["selection"]
    selected_candidate_ids = _normalized_str_list(
        selection.get("selectedCandidateIds")
    )
    if not selected_candidate_ids:
        raise HypothesisFirstChainError("selection has no selected candidates")

    selection_links = [
        dict(item)
        for item in links
        if str(item.get("selectionId") or "").strip() == selection_id
        and str(item.get("candidateId") or "").strip()
    ]
    # Retry attempts append one link per attempt while reusing the same
    # (candidateId, roundIndex).  Fold that append-only attempt history down
    # to its newest link before the duplicate-binding guard below, which
    # otherwise raises for every selection that ever retried a dispatch.
    latest_attempt_link: dict[tuple[str, int], dict[str, Any]] = {}
    for item in selection_links:
        binding_key = (
            str(item.get("candidateId") or "").strip(),
            int(item.get("roundIndex") or 1),
        )
        existing_link = latest_attempt_link.get(binding_key)
        if existing_link is None or str(item.get("createdAt") or "") >= str(
            existing_link.get("createdAt") or ""
        ):
            latest_attempt_link[binding_key] = item
    selection_links = list(latest_attempt_link.values())
    seen_bindings: set[tuple[str, int]] = set()
    for item in selection_links:
        binding = (
            str(item.get("candidateId") or "").strip(),
            int(item.get("roundIndex") or 1),
        )
        if binding in seen_bindings:
            raise HypothesisFirstChainError(
                "candidate review group contains duplicate candidate bindings"
            )
        seen_bindings.add(binding)

    group_links = [
        item for item in selection_links if int(item.get("roundIndex") or 1) == round_index
    ]
    if round_index == 1:
        expected_candidate_ids = selected_candidate_ids
    else:
        expected_candidate_ids = [
            str(item.get("candidateId") or "").strip()
            for item in sorted(
                group_links,
                key=lambda item: (
                    int(item.get("candidateOrder") or 0),
                    str(item.get("meetingRoundId") or ""),
                ),
            )
        ]

    meeting_cache: dict[str, dict[str, Any]] = {}

    def _meeting(meeting_id: str) -> dict[str, Any]:
        cached = meeting_cache.get(meeting_id)
        if cached is None:
            cached = meeting_rounds.get_meeting_round(team_id, meeting_id)[
                "meetingRound"
            ]
            meeting_cache[meeting_id] = cached
        return cached

    authority_by_candidate: dict[str, tuple[int, dict[str, Any]]] = {}
    missing_candidate_ids: list[str] = []
    pending_meeting_ids: list[str] = []
    superseded_candidate_ids: list[str] = []
    superseded_meeting_ids: list[str] = []
    for candidate in expected_candidate_ids:
        candidate_links = [
            item
            for item in selection_links
            if str(item.get("candidateId") or "").strip() == candidate
        ]
        if not candidate_links:
            missing_candidate_ids.append(candidate)
            continue
        candidate_links.sort(
            key=lambda item: int(item.get("roundIndex") or 0), reverse=True
        )
        # Classify the candidate's whole lineage first: every superseded
        # attempt is reported, and the newest non-superseded attempt decides
        # the outcome (a live newer round always outranks older rounds).
        resolution: tuple[str, int, dict[str, Any]] | None = None
        candidate_superseded_ids: list[str] = []
        for link in candidate_links:
            linked_meeting = _meeting(str(link.get("meetingRoundId") or "").strip())
            if _is_superseded_review_attempt(linked_meeting):
                candidate_superseded_ids.append(
                    str(linked_meeting.get("meetingRoundId") or "").strip()
                )
                continue
            if resolution is not None:
                continue
            if str(linked_meeting.get("status") or "").strip().lower() != "closed":
                resolution = (
                    "active",
                    int(link.get("roundIndex") or 1),
                    linked_meeting,
                )
            else:
                resolution = (
                    "authority",
                    int(link.get("roundIndex") or 1),
                    linked_meeting,
                )
        superseded_meeting_ids.extend(candidate_superseded_ids)
        if resolution is None:
            # Newest attempt superseded with no closed successor: the
            # candidate's review is still pending and must not enter the group.
            superseded_candidate_ids.append(candidate)
        elif resolution[0] == "active":
            pending_meeting_ids.append(
                str(resolution[2].get("meetingRoundId") or "").strip()
            )
        else:
            authority_by_candidate[candidate] = (resolution[1], resolution[2])

    if missing_candidate_ids or pending_meeting_ids or superseded_candidate_ids:
        return {
            "status": "waiting_for_sibling_reviews",
            "selectionId": selection_id,
            "roundIndex": round_index,
            "closed": False,
            "missingCandidateIds": missing_candidate_ids,
            "pendingMeetingRoundIds": pending_meeting_ids,
            "supersededCandidateIds": superseded_candidate_ids,
            "supersededMeetingRoundIds": superseded_meeting_ids,
            "closedMeetingRoundIds": [
                str(authority_by_candidate[candidate][1].get("meetingRoundId") or "").strip()
                for candidate in expected_candidate_ids
                if candidate in authority_by_candidate
            ],
        }
    ordered_meetings = [
        authority_by_candidate[candidate][1]
        for candidate in expected_candidate_ids
        if candidate in authority_by_candidate
    ]
    return {
        "status": "ready",
        "selectionId": selection_id,
        "roundIndex": max(
            int(item[0]) for item in authority_by_candidate.values()
        ),
        "meetings": ordered_meetings,
    }


def _latest_round_sibling_gate(team_id: str, selection_id: str) -> dict[str, Any]:
    """Classify the selection's newest logical review round for open-next gating.

    The newest round's own links (latest attempt per candidate binding)
    decide: a closed or superseded meeting is archived or owns its retry
    recovery and never blocks, while a still-actionable meeting
    (open/summarizing/awaiting_approval) blocks the next round so its digest
    confirmation gate cannot be overwritten by a newer round.
    """
    from core.web.services.team_workflow import meeting_rounds

    selection_links = [
        dict(item)
        for item in list_review_round_links(team_id).get("links") or []
        if str(item.get("selectionId") or "").strip() == selection_id
        and str(item.get("candidateId") or "").strip()
    ]
    latest_round_index = max(
        (int(item.get("roundIndex") or 0) for item in selection_links), default=0
    )
    latest_attempt: dict[str, dict[str, Any]] = {}
    for item in selection_links:
        if int(item.get("roundIndex") or 0) != latest_round_index:
            continue
        candidate = str(item.get("candidateId") or "").strip()
        existing = latest_attempt.get(candidate)
        if existing is None or str(item.get("createdAt") or "") >= str(
            existing.get("createdAt") or ""
        ):
            latest_attempt[candidate] = item
    pending_meeting_ids: list[str] = []
    pending_candidate_ids: list[str] = []
    for candidate in sorted(latest_attempt):
        link = latest_attempt[candidate]
        meeting = meeting_rounds.get_meeting_round(
            team_id, str(link.get("meetingRoundId") or "").strip()
        )["meetingRound"]
        if str(meeting.get("status") or "").strip().lower() in _ACTIVE_MEETING_STATUSES:
            pending_meeting_ids.append(
                str(meeting.get("meetingRoundId") or "").strip()
            )
            pending_candidate_ids.append(candidate)
    return {
        "selectionId": selection_id,
        "roundIndex": latest_round_index,
        "pendingMeetingRoundIds": pending_meeting_ids,
        "pendingCandidateIds": pending_candidate_ids,
    }


def _build_round_candidates(
    team_id: str,
    meeting_round: Mapping[str, Any],
    *,
    candidate_ids: list[str] | None = None,
    workflow_run_id: str = "",
) -> list[dict[str, Any]]:
    """Assemble review inputs for explicit candidates or one meeting's refs.

    The authoritative source is the approved v2 question artifact (the same
    read path HF-1 selection validation uses): ``statement`` maps to the
    required ``claim``, ``mechanism`` to ``rationale``, and ``novelty_basis``
    to ``differenceFromAlternatives`` when present (HF-3 otherwise applies its
    default fallback wording).
    """
    from core.web.services.team_workflow.research_runtime import question_launch

    normalized_candidate_ids = (
        _normalized_str_list(candidate_ids)
        if candidate_ids is not None
        else [
            ref.split(":", 1)[1].strip()
            for ref in _normalized_str_list(meeting_round.get("discussionItemRefs"))
            if ref.startswith("hypothesis_candidate:")
            and ref.split(":", 1)[1].strip()
        ]
    )
    question_id = str(meeting_round.get("question") or "").strip()
    detail = question_launch._approved_details(team_id).get(question_id.upper())
    if detail is None:
        resolved_workflow_run_id = str(
            workflow_run_id or _meeting_workflow_run_id(meeting_round)
        ).strip()
        ledger_candidates = list_hypothesis_candidates(
            team_id,
            question_id=question_id,
            workflow_run_id=resolved_workflow_run_id,
        )["candidates"]
        artifact_by_id = {
            str(item.get("candidateId") or "").strip(): {
                "hypothesis_id": str(item.get("candidateId") or "").strip(),
                "statement": str(item.get("statement") or item.get("claim") or "").strip(),
                "mechanism": str(item.get("rationale") or "").strip(),
                "novelty_basis": str(item.get("differenceFromAlternatives") or "").strip(),
                "candidateAuthority": str(item.get("candidateAuthority") or "").strip(),
                "lineageRefs": _normalized_str_list(item.get("lineageRefs")),
                "testablePrediction": str(item.get("testablePrediction") or "").strip(),
                "falsifier": str(item.get("falsifier") or "").strip(),
                "axisProfile": (
                    dict(item.get("axisProfile"))
                    if isinstance(item.get("axisProfile"), Mapping)
                    else {}
                ),
            }
            for item in ledger_candidates
            if isinstance(item, Mapping)
        }
    else:
        output = detail.get("output") if isinstance(detail.get("output"), Mapping) else {}
        hypotheses = [
            item
            for item in list(output.get("hypotheses") or [])
            if isinstance(item, Mapping)
        ]
        artifact_by_id = {
            str(item.get("hypothesis_id") or "").strip(): item for item in hypotheses
        }
    candidates: list[dict[str, Any]] = []
    for candidate_id in normalized_candidate_ids:
        artifact = artifact_by_id.get(candidate_id) or {}
        candidate: dict[str, Any] = {
            "candidateId": candidate_id,
            "claim": str(artifact.get("statement") or "").strip(),
            "rationale": str(artifact.get("mechanism") or "").strip(),
            "candidateAuthority": str(artifact.get("candidateAuthority") or "").strip(),
            "lineageRefs": _normalized_str_list(artifact.get("lineageRefs")),
            "testablePrediction": str(artifact.get("testablePrediction") or "").strip(),
            "falsifier": str(artifact.get("falsifier") or "").strip(),
            "axisProfile": (
                dict(artifact.get("axisProfile"))
                if isinstance(artifact.get("axisProfile"), Mapping)
                else {}
            ),
        }
        difference = str(artifact.get("novelty_basis") or "").strip()
        if difference:
            candidate["differenceFromAlternatives"] = difference
        candidates.append(candidate)
    return candidates


def _blocked_round_authority(kind: str, code: str) -> dict[str, Any]:
    return {
        "status": "blocked",
        "reason": "NEEDS_CONTEXT",
        "blockerCodes": [code],
        "missingAuthorities": [kind],
        "artifact": None,
    }


# ---------------------------------------------------------------------------
# real-batch (chain-driven dev/platform rounds) authority recovery helpers.
#
# The three recoveries below close the same architectural gap the coherence
# recovery already closed: legacy question-run lifecycle artifacts (approved
# question details, formal revision envelopes, canonical evidence refs) do not
# exist for rounds driven directly by the real-batch research workflow, but the
# equivalent authorities are already persisted in live records.  Every recovery
# is fail-closed: missing, ambiguous, or unreadable inputs keep the existing
# blocker, and nothing is regenerated through a model call.


def _candidate_revision_snapshot(entry: Mapping[str, Any]) -> dict[str, Any]:
    """Deterministic per-candidate content projection for revision hashing."""
    axis = entry.get("axisProfile") if isinstance(entry.get("axisProfile"), Mapping) else {}
    return {
        "candidateId": str(entry.get("candidateId") or "").strip(),
        "statement": str(
            entry.get("statement") or entry.get("claim") or ""
        ).strip(),
        "rationale": str(
            entry.get("rationale") or entry.get("mechanism") or ""
        ).strip(),
        "testablePrediction": str(entry.get("testablePrediction") or "").strip(),
        "falsifier": str(entry.get("falsifier") or "").strip(),
        "axisProfile": dict(axis),
    }


def _canonical_snapshot_hash(snapshots: Sequence[Mapping[str, Any]]) -> str:
    from .human_gate_artifacts import canonical_sha256

    ordered = sorted(
        (dict(item) for item in snapshots if isinstance(item, Mapping)),
        key=lambda item: str(item.get("candidateId") or ""),
    )
    return canonical_sha256(ordered)


def _review_round_meeting_chain(
    team_id: str,
    *,
    selection_id: str,
    candidate_ids: Sequence[str],
) -> dict[int, dict[str, dict[str, Any]]]:
    """Resolve each review round's closed authority meeting per candidate.

    Authority mirrors ``_review_meeting_fan_in_group``: the newest
    non-superseded link per (candidateId, roundIndex) wins, the meeting must be
    closed with a digest and decisions, and every round's group must cover all
    round candidates.  Returns ``{roundIndex: {candidateId: record}}``.
    """
    from core.web.services.team_workflow import meeting_rounds as meetings

    links = [
        dict(item)
        for item in list(list_review_round_links(team_id).get("links") or [])
        if str(item.get("selectionId") or "").strip() == selection_id
        and str(item.get("candidateId") or "").strip() in set(candidate_ids)
    ]
    if not links:
        return {}
    latest_links: dict[tuple[str, int], dict[str, Any]] = {}
    for link in links:
        key = (
            str(link.get("candidateId") or "").strip(),
            int(link.get("roundIndex") or 1),
        )
        existing = latest_links.get(key)
        if existing is None or str(link.get("createdAt") or "") >= str(
            existing.get("createdAt") or ""
        ):
            latest_links[key] = link
    meeting_by_id = {
        str(meeting.get("meetingRoundId") or "").strip(): meeting
        for meeting in meetings._read_jsonl(meetings._rounds_path(team_id))
        if isinstance(meeting, Mapping)
    }
    chain: dict[int, dict[str, dict[str, Any]]] = {}
    for (candidate_id, round_index), link in latest_links.items():
        meeting = meeting_by_id.get(
            str(link.get("meetingRoundId") or "").strip()
        )
        if not isinstance(meeting, Mapping):
            continue
        if _is_superseded_review_attempt(meeting):
            continue
        if str(meeting.get("status") or "").strip().lower() != "closed":
            continue
        if not str(meeting.get("digestId") or "").strip():
            continue
        if not _normalized_str_list(meeting.get("decisionRefs")):
            continue
        chain.setdefault(round_index, {})[candidate_id] = dict(meeting)
    return {
        round_index: bindings
        for round_index, bindings in sorted(chain.items())
        if set(bindings) == set(candidate_ids)
    }


def _materialize_review_feedback_iterations_authority(
    *,
    team_id: str,
    workflow_run_id: str,
    node_run_id: str,
    question_id: str,
    source_collection_run_id: str,
    accepted_round: Mapping[str, Any],
    selection_id: str,
) -> dict[str, Any]:
    """Replay the recorded review-round chain as feedback-iteration authority.

    Chain-driven review rounds never persist a ``revisionEnvelope`` (dev/
    platform rounds carry no formal revision fork), but the r1→rN review
    meetings themselves are recorded revision evidence: round i's digest
    proposes the revised candidate and its decision records the review
    feedback.  Each adjacent round pair therefore replays as one iteration:

    - feedback: the round's real decision/digest/meeting ids plus the decision
      rationale (the review's open issues);
    - revision: the digest-proposed candidate delta, hashed over the exact
      persisted snapshots (input = prior round state — the ledger candidate for
      round 1, the prior round's digest proposal afterwards), so the iteration
      chain stays continuous by construction.

    Fail-closed: rounds below 2, any candidate without a closed authoritative
    meeting, a missing digest proposal, or a snapshot with no actual change
    stops the replay at the last derivable iteration; fewer than one
    derivable iteration keeps the existing blocker.
    """
    from core.web.services.team_workflow import meeting_rounds as meetings

    candidate_ids = [
        str(item.get("candidateId") or "").strip()
        for item in list(accepted_round.get("candidates") or [])
        if isinstance(item, Mapping) and str(item.get("candidateId") or "").strip()
    ]
    if len(candidate_ids) < 1 or not selection_id:
        return {"status": "blocked", "blockerCodes": ["hypothesis_revision_evidence_missing"]}
    chain = _review_round_meeting_chain(
        team_id,
        selection_id=selection_id,
        candidate_ids=candidate_ids,
    )
    if not chain or min(chain) != 1 or max(chain) < 2:
        return {"status": "blocked", "blockerCodes": ["hypothesis_revision_evidence_missing"]}
    digest_by_id = {
        str(item.get("digestId") or "").strip(): dict(item)
        for item in meetings._read_jsonl(meetings._digests_path(team_id))
        if isinstance(item, Mapping) and str(item.get("digestId") or "").strip()
    }
    decision_by_id = {
        str(item.get("decisionId") or "").strip(): dict(item)
        for item in meetings._read_jsonl(meetings._decisions_path(team_id))
        if isinstance(item, Mapping) and str(item.get("decisionId") or "").strip()
    }

    # Round-0 input state: the ledger-registered generation candidates.
    input_state: dict[str, dict[str, Any]] | None = {}
    ledger = list_hypothesis_candidates(team_id, question_id=question_id)
    ledger_by_id = {
        str(item.get("candidateId") or "").strip(): dict(item)
        for item in list(ledger.get("candidates") or [])
        if isinstance(item, Mapping)
    }
    for candidate_id in candidate_ids:
        entry = ledger_by_id.get(candidate_id)
        if entry is None:
            input_state = None
            break
        input_state[candidate_id] = _candidate_revision_snapshot(entry)

    from .feedback_iterations_artifact_writer import write_feedback_iterations_artifact

    written = 0
    blockers: list[str] = []
    for round_index in sorted(chain):
        if input_state is None:
            break
        bindings = chain[round_index]
        round_blockers: list[str] = []
        feedback_refs = [f"hypothesis_selection:{selection_id}"]
        rationales: list[str] = []
        output_state: dict[str, dict[str, Any]] = {}
        for candidate_id in candidate_ids:
            meeting = bindings[candidate_id]
            digest = digest_by_id.get(str(meeting.get("digestId") or "").strip())
            decision_ref = _normalized_str_list(meeting.get("decisionRefs"))[0]
            decision = decision_by_id.get(decision_ref)
            if not isinstance(digest, Mapping) or not isinstance(decision, Mapping):
                round_blockers.append("hypothesis_revision_evidence_missing")
                break
            proposal = next(
                (
                    dict(item)
                    for item in list(digest.get("proposedCandidates") or [])
                    if isinstance(item, Mapping)
                    and str(item.get("candidateId") or "").strip() == candidate_id
                ),
                None,
            )
            if proposal is None:
                # This round recorded no revision proposal for the candidate:
                # no digest-backed iteration can be derived beyond here.
                round_blockers.append("hypothesis_revision_evidence_missing")
                break
            rationale = str(decision.get("rationale") or "").strip()
            if not rationale:
                round_blockers.append("hypothesis_revision_evidence_missing")
                break
            meeting_ref = str(meeting.get("meetingRoundId") or "").strip()
            feedback_refs.extend(
                [
                    f"meeting_round:{meeting_ref}",
                    f"meeting_digest:{digest.get('digestId')}",
                    f"decision_record:{decision_ref}",
                ]
            )
            rationales.append(rationale)
            output_state[candidate_id] = _candidate_revision_snapshot(proposal)
        if round_blockers:
            blockers = round_blockers
            break
        input_hash = _canonical_snapshot_hash(list(input_state.values()))
        output_hash = _canonical_snapshot_hash(list(output_state.values()))
        if output_hash == input_hash:
            # The digest re-proposed an identical candidate: recorded, but not
            # an actual revision, so it cannot establish an iteration.
            blockers = ["hypothesis_revision_evidence_missing"]
            break
        changes = [
            (
                f"{candidate_id}: revised per review round {round_index} "
                f"({feedback_refs[1 + index * 3]}, "
                f"{feedback_refs[2 + index * 3]}, "
                f"{feedback_refs[3 + index * 3]})"
            )
            for index, candidate_id in enumerate(candidate_ids)
        ]
        try:
            recorded = write_feedback_iterations_artifact(
                team_id=team_id,
                workflow_run_id=workflow_run_id,
                node_run_id=node_run_id,
                question_id=question_id,
                iteration_round=round_index,
                feedback={
                    "trigger": "review_round_feedback",
                    "humanFeedback": rationales[0],
                    "inputRefs": list(dict.fromkeys(feedback_refs)),
                    "inputHash": input_hash,
                },
                revision={
                    "changes": changes,
                    "unresolvedIssues": list(dict.fromkeys(rationales)),
                    "outputRefs": [
                        f"hypothesis_candidate:{candidate_id}:r{round_index}"
                        for candidate_id in candidate_ids
                    ],
                    "outputHash": output_hash,
                    "status": "revised",
                },
                source_collection_run_id=source_collection_run_id,
                node_id="hypothesis_design",
                revision_phase=(
                    "grounded_revision" if round_index == 1 else "review_revision"
                ),
            )
        except Exception:  # noqa: BLE001 - stay fail-closed, try earlier rounds only
            blockers = ["hypothesis_revision_authority_persistence_failed"]
            break
        if str(recorded.get("status") or "").strip().lower() not in {
            "recorded",
            "written",
        }:
            blockers = [
                str(item)
                for item in list(recorded.get("blockerCodes") or [])
                if str(item).strip()
            ] or ["hypothesis_revision_evidence_missing"]
            break
        written += 1
        blockers = []
        input_state = output_state
    if written < 1:
        return {
            "status": "blocked",
            "blockerCodes": blockers or ["hypothesis_revision_evidence_missing"],
        }
    return {"status": "written", "blockerCodes": [], "iterationCount": written}


def _source_candidate_batch_ref_index(
    team_id: str,
) -> dict[str, tuple[str, str]]:
    """Map bare source-candidate ids to (scRunId, canonical batch ref).

    Authority is the team candidate store: each bare evidence id resolves to
    the exactly one source-collection run that scoped it, and the run's
    ``source_candidate_batch`` canonical ref is verified through the same
    read-back the writer uses.  Ambiguous or unknown ids are simply absent
    from the index, which keeps every caller fail-closed.
    """
    from core.web.services.team_workflow.source_collection.candidates import (
        list_candidate_store,
    )
    from .artifact_readback_registry import (
        build_canonical_ref,
        load_scoped_artifact_payload,
        read_domain_artifact,
    )
    from .human_gate_artifacts import canonical_sha256

    try:
        store_rows = list(
            list_candidate_store(team_id, limit=500).get("candidates") or []
        )
    except Exception:  # noqa: BLE001 - unreadable store means no mapping
        return {}
    runs_by_id: dict[str, set[str]] = {}
    for row in store_rows:
        if not isinstance(row, Mapping):
            continue
        candidate_id = str(row.get("candidateId") or "").strip()
        meta = (
            row.get("metadata")
            if isinstance(row.get("metadata"), Mapping)
            else {}
        )
        sc_run = str(
            row.get("sourceCollectionRunId") or meta.get("sourceCollectionRunId") or ""
        ).strip()
        if candidate_id and sc_run:
            runs_by_id.setdefault(candidate_id, set()).add(sc_run)
    index: dict[str, tuple[str, str]] = {}
    ref_by_run: dict[str, str] = {}
    for candidate_id, sc_runs in runs_by_id.items():
        if len(sc_runs) != 1:
            continue
        sc_run = next(iter(sc_runs))
        ref = ref_by_run.get(sc_run)
        if ref is None:
            try:
                payload = load_scoped_artifact_payload(
                    "source_candidate_batch",
                    team_id=team_id,
                    authority_run_id=sc_run,
                )
            except Exception:  # noqa: BLE001 - unreadable batch stays unmapped
                payload = None
            if not isinstance(payload, Mapping) or not payload.get("candidates"):
                continue
            ref = build_canonical_ref(
                kind="source_candidate_batch",
                team_id=team_id,
                authority_run_id=sc_run,
                content_hash=canonical_sha256(payload),
            )
            if read_domain_artifact(ref) is None:
                continue
            ref_by_run[sc_run] = ref
        index[candidate_id] = (sc_run, ref)
    return index


def _repair_dimension_review_evidence_refs(
    team_id: str,
    review: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Repair bare source-candidate evidence refs into canonical batch refs.

    Chain-driven review rows cite bare ``candidate-...`` source ids, while the
    writer only accepts readable canonical refs.  The repair is deterministic
    and narrow:

    - each bare id must resolve to exactly one scoped source-collection run
      whose verified ``source_candidate_batch`` canonical ref is substituted;
    - a row that cites no evidence at all inherits the reviewed candidate's
      own mapped lineage refs (the grounded sources the candidate is built
      on) — never invented content;
    - any bare id without a unique readable mapping — or an inheritable-empty
      row without a mappable lineage — is left untouched, so the writer's
      existing fail-closed blockers keep firing for exactly those rows.

    Returns ``(repaired_review, report)``; ``report`` records what was
    repaired for auditability.
    """
    from .artifact_readback_registry import parse_canonical_ref

    # The reviewed (round) candidates own the rows' lineage: an empty row can
    # only inherit the lineage of the exact candidate the review is about.
    lineage_by_candidate = {
        str(
            item.get("candidateId")
            or item.get("candidate_id")
            or item.get("hypothesis_id")
            or ""
        ).strip(): [
            str(ref or "").strip()
            for ref in list(item.get("lineageRefs") or [])
            if str(ref or "").strip()
        ]
        for item in list(review.get("candidates") or [])
        if isinstance(item, Mapping)
    }
    repaired_review = dict(review)
    repaired_candidates: list[Any] = []
    repaired_rows = 0
    inherited_rows = 0
    unresolved_refs: list[str] = []
    bare_index: dict[str, str] = {}

    def _canonical_or_none(ref: str) -> str:
        if not ref:
            return ""
        if parse_canonical_ref(ref) is not None:
            return ref
        return bare_index.get(ref, "")

    for candidate in list(review.get("candidates") or []):
        if not isinstance(candidate, Mapping):
            repaired_candidates.append(candidate)
            continue
        candidate_id = str(
            candidate.get("candidateId")
            or candidate.get("candidate_id")
            or candidate.get("hypothesis_id")
            or ""
        ).strip()
        rows = list(candidate.get("dimensionReviews") or [])
        if not rows:
            repaired_candidates.append(candidate)
            continue
        # Lazy index build: only rows that actually carry bare ids pay for it.
        bare_ids = {
            str(ref or "").strip()
            for row in rows
            if isinstance(row, Mapping)
            for ref in list(row.get("evidence_refs") or row.get("evidenceRefs") or [])
            if isinstance(ref, str) and parse_canonical_ref(str(ref or "").strip()) is None
        }
        bare_ids |= {
            str(ref or "").strip()
            for ref in lineage_by_candidate.get(candidate_id) or []
            if parse_canonical_ref(ref) is None
        }
        if bare_ids and not bare_index:
            bare_index = {
                bare_id: mapped_ref
                for bare_id, (_sc_run, mapped_ref) in _source_candidate_batch_ref_index(
                    team_id
                ).items()
            }
        for bare_id in sorted(bare_ids):
            if bare_id and bare_id not in bare_index and bare_id not in unresolved_refs:
                unresolved_refs.append(bare_id)
        repaired_row_candidates = []
        for row in rows:
            if not isinstance(row, Mapping):
                repaired_row_candidates.append(row)
                continue
            raw_refs = [
                str(ref or "").strip()
                for ref in list(row.get("evidence_refs") or row.get("evidenceRefs") or [])
                if str(ref or "").strip()
            ]
            mapped: list[str] = []
            resolvable = True
            for ref in raw_refs:
                canonical = _canonical_or_none(ref)
                if not canonical:
                    resolvable = False
                    break
                if canonical not in mapped:
                    mapped.append(canonical)
            if not raw_refs:
                # No explicit citations: inherit the candidate's own lineage.
                for ref in lineage_by_candidate.get(candidate_id) or []:
                    canonical = _canonical_or_none(ref)
                    if not canonical:
                        resolvable = False
                        break
                    if canonical not in mapped:
                        mapped.append(canonical)
                if resolvable and mapped:
                    inherited_rows += 1
            elif resolvable and mapped != raw_refs:
                repaired_rows += 1
            if resolvable and mapped:
                updated_row = dict(row)
                updated_row["evidence_refs"] = mapped
                repaired_row_candidates.append(updated_row)
                continue
            repaired_row_candidates.append(row)
        updated_candidate = dict(candidate)
        updated_candidate["dimensionReviews"] = repaired_row_candidates
        repaired_candidates.append(updated_candidate)
    repaired_review["candidates"] = repaired_candidates
    return repaired_review, {
        "repairedRows": repaired_rows,
        "inheritedRows": inherited_rows,
        "unresolvedRefs": unresolved_refs,
    }


def _project_live_stage_one_question_detail(
    team_id: str,
    question_id: str,
    *,
    workflow_run_id: str,
    accepted_round: Mapping[str, Any],
    selected_candidate_id: str,
) -> dict[str, Any] | None:
    """Project the canonical approved-question shape from live authorities.

    Real-batch rounds never created a legacy question-run record, so the
    plan/alignment projection falls back to the only live authorities: the
    hash-pinned frozen 125-question catalog (question text and catalog
    identity), the problem-understanding artifact already in the immutable
    workflow store, and the accepted round's persisted candidates and
    recommendation.  Every projected gate decision is the accepted-round
    acceptance itself; ``None`` is returned for any missing input so the
    caller keeps the existing fail-closed blocker.
    """
    from core.research.competition.resources import (
        CATALOG_SHA256,
        load_science_question_catalog,
    )
    from .workflow_artifact_store import list_workflow_artifacts

    meta_review = (
        accepted_round.get("metaReview")
        if isinstance(accepted_round.get("metaReview"), Mapping)
        else {}
    )
    recommendation = str(meta_review.get("recommendationCandidateId") or "").strip()
    if recommendation != selected_candidate_id:
        return None
    try:
        catalog = load_science_question_catalog()
    except Exception:  # noqa: BLE001 - frozen resource unavailable: fail closed
        return None
    entry = next(
        (
            dict(item)
            for item in list(catalog.get("questions") or [])
            if isinstance(item, Mapping)
            and str(item.get("id") or "").strip().upper() == question_id
        ),
        None,
    )
    question_en = str(entry.get("question_en") or "").strip() if entry else ""
    catalog_id = str(catalog.get("catalog_id") or "").strip()
    if entry is None or not question_en or not catalog_id:
        return None
    understanding_rows = [
        dict(item)
        for item in list_workflow_artifacts(
            team_id,
            kind="problem_understanding",
            workflow_run_id=workflow_run_id,
        )
        if isinstance(item.get("payload"), Mapping)
    ]
    if not understanding_rows:
        return None
    understanding = understanding_rows[-1]["payload"]
    scope = str(understanding.get("scope") or "").strip()
    if not scope:
        return None
    subquestions = [
        str(item or "").strip()
        for item in list(understanding.get("subquestions") or [])
        if str(item or "").strip()
    ]
    round_candidates = [
        dict(item)
        for item in list(accepted_round.get("candidates") or [])
        if isinstance(item, Mapping)
        and str(item.get("candidateId") or "").strip()
        and str(item.get("claim") or "").strip()
    ]
    selected_row = next(
        (
            item
            for item in round_candidates
            if str(item.get("candidateId") or "").strip() == selected_candidate_id
        ),
        None,
    )
    if selected_row is None:
        return None
    selected_statement = str(selected_row.get("claim") or "").strip()
    selected_rationale = str(selected_row.get("rationale") or "").strip()
    round_id = str(accepted_round.get("roundId") or "").strip()
    acceptance_gate = {
        "required": True,
        "decision": "approved",
        "rationale": (
            f"Hypothesis round {round_id} was meta-review accepted; the "
            "stage-one projection stays proposal-only."
        ),
    }
    methods = subquestions or [selected_statement]
    plan: dict[str, Any] = {
        "proposal_only": True,
        "objective": scope,
        "method": selected_rationale or selected_statement,
        "human_gate": dict(acceptance_gate),
    }
    if subquestions:
        plan["work_packages"] = [
            {
                "work_package_id": f"wp-{index + 1}",
                "goal": text,
                "inputs": [question_en],
                "procedure": [selected_rationale or selected_statement],
                "outputs": [f"wp-{index + 1} resolution"],
                "dependencies": [],
            }
            for index, text in enumerate(subquestions)
        ]
    competition_view = {
        "problem_statement": question_en,
        "rationale": scope,
        "technical_details": selected_rationale or selected_statement,
        "datasets": {"planned": [], "used": []},
        "methods": methods,
        "experiments": [],
        "results": ["not executed at stage one"],
        "references": [],
        "paper_title": f"Stage-one research proposal: {question_en}",
        "paper_abstract": selected_statement,
    }
    return {
        "record": {
            "runId": round_id,
            "questionId": question_id,
            "schemaVersion": 2,
            "status": "approved",
            "validation": {
                # Projection equivalence (mirrors the coherence recovery): the
                # catalog resource is hash-pinned, the problem-understanding
                # artifact is content-addressed in the immutable store, and
                # the accepted round is the persisted acceptance authority.
                "schemaValidation": "passed",
                "citationValidation": "passed",
                "officialModelCall": True,
            },
        },
        "artifact": {"sha256": str(CATALOG_SHA256).lower(), "immutable": True},
        "output": {
            "schema_version": 2,
            "identity": {
                "catalog_id": catalog_id,
                "question_id": question_id,
                "question_en": question_en,
                "domain": str(entry.get("domain") or "").strip(),
            },
            "hypotheses": [
                {
                    "hypothesis_id": str(item.get("candidateId") or "").strip(),
                    "statement": str(item.get("claim") or "").strip(),
                }
                for item in round_candidates
            ],
            "selection": {
                "selected_hypothesis_id": selected_candidate_id,
                "human_gate": dict(acceptance_gate),
            },
            "research_plan": plan,
            "competition_result_view": competition_view,
        },
    }


def _materialize_hypothesis_revision_authority(
    *,
    team_id: str,
    workflow_run_id: str,
    node_run_id: str,
    question_id: str,
    source_collection_run_id: str,
    round_record: Mapping[str, Any],
) -> dict[str, Any]:
    envelope = (
        dict(round_record.get("revisionEnvelope"))
        if isinstance(round_record.get("revisionEnvelope"), Mapping)
        else {}
    )
    phase = str(envelope.get("phase") or "").strip()
    round_by_phase = {"grounded_revision": 1, "review_revision": 2}
    if phase not in round_by_phase:
        return _blocked_round_authority(
            "feedback_iterations", "hypothesis_revision_evidence_missing"
        )
    feedback = envelope.get("feedback")
    revision = envelope.get("revision")
    if not isinstance(feedback, Mapping) or not isinstance(revision, Mapping):
        return _blocked_round_authority(
            "feedback_iterations", "hypothesis_revision_evidence_missing"
        )
    if phase == "review_revision":
        receipt_ref = str(envelope.get("revisionReceiptRef") or "").strip()
        matching_receipts = [
            item
            for item in list(round_record.get("modelInvocationReceipts") or [])
            if isinstance(item, Mapping)
            and str(item.get("receiptId") or "").strip() == receipt_ref
            and "revision"
            in list(
                (
                    item.get("metadata")
                    if isinstance(item.get("metadata"), Mapping)
                    else {}
                ).get("outcomeKinds")
                or []
            )
        ]
        if len(matching_receipts) != 1:
            return _blocked_round_authority(
                "feedback_iterations", "hypothesis_revision_receipt_missing"
            )
        from .workflow_artifact_store import list_workflow_artifacts

        prior = [
            item
            for item in list_workflow_artifacts(
                team_id,
                kind="feedback_iterations",
                workflow_run_id=workflow_run_id,
            )
            if isinstance(item.get("payload"), Mapping)
            and item["payload"].get("iterationRound") == 1
            and str(item["payload"].get("revisionPhase") or "")
            == "grounded_revision"
        ]
        if len(prior) != 1:
            return _blocked_round_authority(
                "feedback_iterations", "hypothesis_grounded_revision_authority_missing"
            )
        prior_envelope = (
            prior[0]["payload"].get("revisionEnvelope")
            if isinstance(prior[0]["payload"].get("revisionEnvelope"), Mapping)
            else {}
        )
        prior_child = (
            prior_envelope.get("childOutput")
            if isinstance(prior_envelope.get("childOutput"), Mapping)
            else {}
        )
        from core.web.services.team_workflow import hypothesis_review_executor

        candidate_result = list_hypothesis_candidates(
            team_id,
            question_id=question_id,
            workflow_run_id=workflow_run_id,
        )
        r1_candidates = [
            dict(item)
            for item in list(candidate_result.get("candidates") or [])
            if isinstance(item, Mapping)
        ]
        try:
            r1_snapshot = (
                hypothesis_review_executor.canonical_hypothesis_revision_snapshot(
                    r1_candidates
                )
            )
        except ContractValidationError:
            return _blocked_round_authority(
                "feedback_iterations", "hypothesis_revision_lineage_discontinuous"
            )
        r1_refs = [
            f"hypothesis_candidate:{item['candidateId']}:r1"
            for item in r1_snapshot
        ]
        r1_hash = _stable_hash(r1_snapshot)
        if (
            r1_refs != list(prior_child.get("refs") or [])
            or r1_hash
            != str(prior_child.get("sha256") or "").strip().lower()
        ):
            return _blocked_round_authority(
                "feedback_iterations", "hypothesis_revision_lineage_discontinuous"
            )
        revision_output = (
            revision.get("output")
            if isinstance(revision.get("output"), Mapping)
            else {}
        )
        revised_candidates = [
            dict(item)
            for item in list(revision_output.get("candidates") or [])
            if isinstance(item, Mapping)
        ]
        revised_candidate_id = str(
            envelope.get("parentCandidateId") or ""
        ).strip()
        revised_matches = [
            item
            for item in revised_candidates
            if str(item.get("candidateId") or "").strip() == revised_candidate_id
        ]
        if (
            not revised_candidate_id
            or len(revised_matches) != 1
            or revised_candidate_id
            not in {str(item["candidateId"]) for item in r1_snapshot}
        ):
            return _blocked_round_authority(
                "feedback_iterations", "hypothesis_revision_evidence_missing"
            )
        revised_candidate = revised_matches[0]
        try:
            r2_snapshot = (
                hypothesis_review_executor.canonical_hypothesis_revision_snapshot(
                    [
                        revised_candidate
                        if str(item.get("candidateId") or "").strip()
                        == revised_candidate_id
                        else item
                        for item in r1_snapshot
                    ]
                )
            )
        except ContractValidationError:
            return _blocked_round_authority(
                "feedback_iterations", "hypothesis_revision_evidence_missing"
            )
        if r2_snapshot == r1_snapshot:
            return _blocked_round_authority(
                "feedback_iterations", "hypothesis_revision_evidence_missing"
            )
        feedback = {
            **dict(feedback),
            "inputRefs": r1_refs,
            "inputHash": r1_hash,
        }
        revision = {
            **dict(revision),
            "outputRefs": [
                f"hypothesis_candidate:{item['candidateId']}:r2"
                for item in r2_snapshot
            ],
            "outputHash": _stable_hash(r2_snapshot),
            "output": {"candidates": r2_snapshot},
        }
    from .feedback_iterations_artifact_writer import (
        write_feedback_iterations_artifact,
    )

    return write_feedback_iterations_artifact(
        team_id=team_id,
        workflow_run_id=workflow_run_id,
        node_run_id=node_run_id,
        question_id=question_id,
        iteration_round=round_by_phase[phase],
        feedback=feedback,
        revision=revision,
        source_collection_run_id=source_collection_run_id,
        node_id="hypothesis_design",
        revision_phase=phase,
    )


def _latest_chain_records_by_id(
    records: list[Mapping[str, Any]], id_field: str
) -> dict[str, dict[str, Any]]:
    """Fold the append-only chain ledger down to its newest record per id."""
    latest: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, Mapping):
            continue
        key = str(record.get(id_field) or "").strip()
        if key:
            latest[key] = dict(record)
    return latest


def _is_sha256_hex(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return len(text) == 64 and all(char in "0123456789abcdef" for char in text)


def _chain_iteration_links(
    team_id: str, question_id: str
) -> dict[int, dict[str, dict[str, Any]]]:
    """Latest review-round link per candidate for every round index.

    The chain ledger appends one link per dispatch attempt; retries reuse the
    same (candidateId, roundIndex), so the newest link is the candidate's
    authoritative binding for that round — the same fold the fan-in resolver
    applies before binding meetings.
    """
    links: dict[int, dict[str, dict[str, Any]]] = {}
    for record in _records(team_id):
        if not isinstance(record, Mapping):
            continue
        if str(record.get("recordKind") or "") != "review_round_link":
            continue
        if str(record.get("questionId") or "").upper() != str(question_id or "").upper():
            continue
        candidate_id = str(record.get("candidateId") or "").strip()
        round_index = record.get("roundIndex")
        if (
            not candidate_id
            or isinstance(round_index, bool)
            or not isinstance(round_index, int)
            or round_index < 1
        ):
            continue
        links.setdefault(round_index, {})[candidate_id] = dict(record)
    return links


def _chain_iteration_evidence(
    *,
    team_id: str,
    question_id: str,
    selected_candidate_ids: list[str],
    links_by_round: dict[int, dict[str, dict[str, Any]]],
    meetings: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Resolve the chain's review-round iteration evidence, fail-closed.

    A chain-driven review set carries its iteration history in the
    ``review_round_link`` / ``collection_request`` / ``decision_record``
    ledgers instead of a HypothesisRound ``revisionEnvelope`` (the convergence
    fan-in is the only round record the chain appends).  For every consecutive
    round pair this demands, and binds verbatim:

    - links for EVERY selected candidate at round k and k+1;
    - the round-(k+1) links' single shared collection request: completed,
      handed off to a source-collection run, hash-identified, decision-bound;
    - the adopted ``request_new_evidence`` decision with its persisted
      rationale (the review findings that opened the request);
    - closed round-(k+1) meetings with hash-pinned digests (the re-review
      output), and the round-k digest risks as the still-unresolved issues.

    Raises ``LookupError`` naming the first missing piece; nothing is ever
    substituted or fabricated.
    """
    from core.web.services.team_workflow import meeting_rounds as meeting_rounds_service

    candidate_ids = {str(item or "").strip() for item in selected_candidate_ids} - {""}
    if len(candidate_ids) < 2:
        raise LookupError("chain_iteration_candidates_missing")
    round_indexes = sorted(links_by_round)
    if len(round_indexes) < 2:
        raise LookupError("chain_iteration_rounds_missing")
    if round_indexes != list(range(1, round_indexes[-1] + 1)):
        raise LookupError("chain_iteration_rounds_not_consecutive")

    meeting_by_id = {
        str(meeting.get("meetingRoundId") or "").strip(): meeting
        for meeting in meetings
        if isinstance(meeting, Mapping)
    }
    digest_by_id = _latest_chain_records_by_id(
        meeting_rounds_service._read_jsonl(
            meeting_rounds_service._digests_path(team_id)
        ),
        "digestId",
    )

    def _round_digest(round_index: int) -> list[dict[str, Any]]:
        digests: list[dict[str, Any]] = []
        for link in links_by_round[round_index].values():
            meeting_id = str(link.get("meetingRoundId") or "").strip()
            meeting = meeting_by_id.get(meeting_id)
            if meeting is None:
                raise LookupError("chain_iteration_meeting_unbound")
            if str(meeting.get("status") or "") != "closed":
                raise LookupError("chain_iteration_meeting_not_closed")
            digest_id = str(meeting.get("digestId") or "").strip()
            if not digest_id:
                raise LookupError("chain_iteration_digest_missing")
            digest = digest_by_id.get(digest_id)
            if not isinstance(digest, Mapping) or not _is_sha256_hex(
                digest.get("contentHash")
            ):
                raise LookupError("chain_iteration_digest_hash_missing")
            risks: list[str] = []
            for item in list(digest.get("risks") or []):
                if isinstance(item, str):
                    text = item.strip()
                elif isinstance(item, Mapping):
                    text = str(
                        item.get("text") or item.get("description") or ""
                    ).strip()
                else:
                    text = ""
                if text:
                    risks.append(text)
            digests.append(
                {
                    "meetingRoundId": meeting_id,
                    "digestId": digest_id,
                    "contentHash": str(digest.get("contentHash")).strip().lower(),
                    "risks": risks,
                }
            )
        digests.sort(key=lambda item: item["meetingRoundId"])
        return digests

    from .human_gate_artifacts import canonical_sha256

    iterations: list[dict[str, Any]] = []
    for round_index in round_indexes[:-1]:
        next_index = round_index + 1
        current_digests = _round_digest(round_index)
        next_digests = _round_digest(next_index)
        request_ids = {
            str(link.get("collectionRequestId") or "").strip()
            for link in links_by_round[next_index].values()
        } - {""}
        if len(request_ids) != 1:
            raise LookupError("chain_iteration_request_missing")
        request_id = next(iter(request_ids))
        request = _latest_chain_records_by_id(
            [
                record
                for record in _records(team_id)
                if isinstance(record, Mapping)
                and str(record.get("recordKind") or "") == "collection_request"
            ],
            "requestId",
        ).get(request_id)
        if not isinstance(request, Mapping):
            raise LookupError("chain_iteration_request_missing")
        if (
            str(request.get("collectionRunStatus") or "") != "completed"
            or not str(request.get("handoffRef") or "").strip()
            or not _is_sha256_hex(request.get("requestHash"))
        ):
            raise LookupError("chain_iteration_request_incomplete")
        decision_id = str(request.get("decisionId") or "").strip()
        decision = _latest_chain_records_by_id(
            meeting_rounds_service._read_jsonl(
                meeting_rounds_service._decisions_path(team_id)
            ),
            "decisionId",
        ).get(decision_id)
        if (
            not isinstance(decision, Mapping)
            or str(decision.get("decision") or "") != "request_new_evidence"
            or str(decision.get("status") or "adopted") != "adopted"
            or not str(decision.get("rationale") or "").strip()
        ):
            raise LookupError("chain_iteration_decision_missing")
        keywords = _normalized_str_list(
            (request.get("searchEnvelope") or {}).get("keywords")
            if isinstance(request.get("searchEnvelope"), Mapping)
            else []
        )
        if not keywords:
            raise LookupError("chain_iteration_revision_scope_missing")
        unresolved = [
            risk
            for digest in current_digests
            for risk in digest["risks"]
            if risk
        ]
        if not unresolved:
            raise LookupError("chain_iteration_unresolved_missing")
        iterations.append(
            {
                "iterationRound": round_index,
                "revisionPhase": (
                    "grounded_revision" if round_index == 1 else "review_revision"
                ),
                "feedback": {
                    "trigger": "request_new_evidence",
                    "humanFeedback": str(decision.get("rationale") or "").strip(),
                    "inputRefs": [
                        f"collection_request:{request_id}",
                        f"decision:{decision_id}",
                        *[
                            f"meeting_round:{digest['meetingRoundId']}"
                            for digest in current_digests
                        ],
                    ],
                    "inputHash": str(request.get("requestHash")).strip().lower(),
                },
                "revision": {
                    "changes": keywords,
                    "unresolvedIssues": unresolved,
                    "outputRefs": [
                        *[
                            f"meeting_round:{digest['meetingRoundId']}"
                            for digest in next_digests
                        ],
                        *[f"meeting_digest:{digest['digestId']}" for digest in next_digests],
                    ],
                    # Content address over the persisted round-(k+1) digest
                    # hashes: derived deterministically, never invented.
                    "outputHash": canonical_sha256(
                        [digest["contentHash"] for digest in next_digests]
                    ),
                    "status": "revised",
                },
            }
        )
    return iterations


def _recover_chain_feedback_iterations_authority(
    *,
    team_id: str,
    question_id: str,
    workflow_run_id: str,
    node_run_id: str,
    source_collection_run_id: str,
    selected_candidate_ids: list[str],
    meetings: list[Mapping[str, Any]],
) -> dict[str, Any]:
    """Replay the chain's review-round iterations as feedback_iterations rows.

    Recovery source is the chain's own persisted iteration evidence (see
    :func:`_chain_iteration_evidence`); the canonical fail-closed writer stays
    the only persistence path.  A question without any chain review-round link
    is ``not_applicable`` — the caller keeps its original blocker, so
    non-chain shapes behave exactly as before.
    """
    links_by_round = _chain_iteration_links(team_id, question_id)
    if not links_by_round:
        return {"status": "not_applicable", "blockerCodes": [], "rounds": []}
    try:
        iterations = _chain_iteration_evidence(
            team_id=team_id,
            question_id=question_id,
            selected_candidate_ids=selected_candidate_ids,
            links_by_round=links_by_round,
            meetings=meetings,
        )
    except LookupError as exc:
        return {
            "status": "blocked",
            "blockerCodes": ["hypothesis_revision_evidence_missing"],
            "reason": str(exc),
            "rounds": [],
        }
    except Exception as exc:  # noqa: BLE001 - recovery failure stays visible
        return {
            "status": "blocked",
            "blockerCodes": ["feedback_iteration_recovery_failed"],
            "error": str(exc) or type(exc).__name__,
            "rounds": [],
        }
    from .feedback_iterations_artifact_writer import (
        write_feedback_iterations_artifact,
    )

    written_rounds: list[int] = []
    for iteration in iterations:
        try:
            recorded = write_feedback_iterations_artifact(
                team_id=team_id,
                workflow_run_id=workflow_run_id,
                node_run_id=node_run_id,
                question_id=question_id,
                iteration_round=iteration["iterationRound"],
                feedback=iteration["feedback"],
                revision=iteration["revision"],
                source_collection_run_id=source_collection_run_id,
                node_id="hypothesis_design",
                revision_phase=iteration["revisionPhase"],
            )
        except Exception as exc:  # noqa: BLE001 - fail-closed blocker
            return {
                "status": "blocked",
                "blockerCodes": ["hypothesis_revision_authority_persistence_failed"],
                "error": str(exc) or type(exc).__name__,
                "rounds": written_rounds,
            }
        if str(recorded.get("status") or "").strip().lower() not in {
            "recorded",
            "written",
        }:
            return {
                "status": "blocked",
                "blockerCodes": [
                    str(code)
                    for code in list(recorded.get("blockerCodes") or [])
                    if str(code).strip()
                ]
                or ["hypothesis_revision_evidence_missing"],
                "rounds": written_rounds,
            }
        written_rounds.append(int(iteration["iterationRound"]))
    return {"status": "written", "blockerCodes": [], "rounds": written_rounds}


def _materialize_stage_one_plan_authority(
    *,
    team_id: str,
    workflow_run_id: str,
    node_run_id: str,
    question_id: str,
    source_collection_run_id: str,
    round_record: Mapping[str, Any],
) -> dict[str, Any]:
    meta_review = (
        dict(round_record.get("metaReview"))
        if isinstance(round_record.get("metaReview"), Mapping)
        else {}
    )
    if meta_review.get("accepted") is not True:
        return _blocked_round_authority(
            "stage1_research_plan", "hypothesis_round_not_accepted"
        )
    selected = str(meta_review.get("recommendationCandidateId") or "").strip()
    if not selected:
        return _blocked_round_authority(
            "stage1_research_plan", "hypothesis_round_selection_missing"
        )
    from core.web.services.team_workflow.research_runtime import question_launch
    from .stage_one_plan_artifact_writer import write_stage_one_plan_artifacts

    detail = question_launch._approved_details(team_id).get(question_id.upper())
    if not isinstance(detail, Mapping):
        # No legacy question-run record (real-batch rounds never create one):
        # project the equivalent question authority from the live authorities.
        detail = _project_live_stage_one_question_detail(
            team_id,
            question_id.upper(),
            workflow_run_id=str(workflow_run_id or "").strip(),
            accepted_round=round_record,
            selected_candidate_id=selected,
        )
    if not isinstance(detail, Mapping):
        return _blocked_round_authority(
            "stage1_research_plan", "stage_one_question_authority_missing"
        )
    return write_stage_one_plan_artifacts(
        team_id=team_id,
        workflow_run_id=workflow_run_id,
        node_run_id=node_run_id,
        question_id=question_id,
        selected_candidate_id=selected,
        question_detail=detail,
        source_collection_run_id=source_collection_run_id,
    )


def _materialize_hypothesis_set_human_gate(
    *,
    team_id: str,
    workflow_run_id: str,
    question_id: str,
    source_collection_run_id: str,
    round_record: Mapping[str, Any],
    meeting_ids: set[str],
    errors: dict[str, str],
) -> dict[str, Any]:
    """Embed the closeout human gate into the node's ``hypothesis_set`` row.

    The stage-one closeout demands a ``human_gate`` mapping inside the
    ``hypothesis_set`` payload, and the only real authority for that gate is
    the persisted chain human adjudication of the accepted round
    (``HUMAN_ADJUDICATION_KIND`` with ``decision == "accepted"``).  So the
    gate is embedded only from that record — never synthesized — and a
    missing/rejected adjudication stays blocked: closeout keeps failing with
    ``stage_one_human_gate_missing`` exactly as before.

    The ungated row itself is immutable; the gated payload is appended as a
    new row whose identity derives from the row it upgrades, so the scoped
    readback (latest row wins) resolves the gated authority and replays are
    idempotent.  Field shape mirrors the stage1_research_plan gate
    (``required``/``decision``/``rationale``) plus the adjudication
    provenance that makes the decision traceable.
    """

    from .stage_one_closeout import payload_human_gates
    from .workflow_artifact_store import list_workflow_artifacts, put_workflow_artifact

    rows = [
        row
        for row in list_workflow_artifacts(
            team_id,
            kind="hypothesis_set",
            workflow_run_id=workflow_run_id,
            source_collection_run_id=source_collection_run_id,
        )
        if isinstance(row.get("payload"), Mapping) and row.get("payload")
    ]
    if not rows:
        # The artifact requirement gate owns the missing-artifact semantics;
        # there is nothing to gate yet.
        return {"status": "absent", "blockerCodes": []}
    base_row = rows[-1]
    base_payload = dict(base_row["payload"])
    report = {
        "status": "blocked",
        "blockerCodes": [],
        "baseRecordId": str(base_row.get("recordId") or ""),
    }
    if next(payload_human_gates(base_payload), None) is not None:
        # The latest authority already carries a gate (replay, or the
        # writeback already recorded one): reuse, never rewrite.
        return {**report, "status": "present"}
    adjudication = _latest_round_adjudication(
        _read_jsonl(_storage_path(team_id)),
        question_id=question_id,
        round_id=str(round_record.get("roundId") or "").strip(),
        meeting_ids=meeting_ids or None,
    )
    if adjudication is None or (
        str(adjudication.get("decision") or "").strip().lower() != "accepted"
    ):
        return {
            **report,
            "blockerCodes": ["stage_one_human_gate_missing"],
        }
    adjudication_id = str(adjudication.get("adjudicationId") or "").strip()
    round_id = str(round_record.get("roundId") or "").strip()
    decided_by = str(adjudication.get("decidedBy") or "").strip()
    decided_at = str(adjudication.get("createdAt") or "").strip()
    rationale = str(adjudication.get("rationale") or "").strip() or (
        f"Human adjudication {adjudication_id} accepted hypothesis round "
        f"{round_id}."
    )
    gate = {
        "required": True,
        "decision": "approved",
        "rationale": rationale,
        "source": "chain_human_adjudication",
        "adjudicationId": adjudication_id,
        "hypothesisRoundId": round_id,
        "decidedBy": decided_by,
        "decidedAt": decided_at,
    }
    gated_payload = {**copy.deepcopy(base_payload), "human_gate": gate}
    base_record_id = str(base_row.get("recordId") or "").strip()
    try:
        stored = put_workflow_artifact(
            team_id,
            kind="hypothesis_set",
            workflow_run_id=workflow_run_id,
            source_collection_run_id=str(
                base_row.get("sourceCollectionRunId") or source_collection_run_id
            ).strip(),
            artifact_identity=(
                f"{base_record_id}:human-gate" if base_record_id else ""
            ),
            payload=gated_payload,
        )
    except Exception as exc:  # noqa: BLE001 - fail closed, report the cause
        errors["hypothesis_set"] = str(exc) or type(exc).__name__
        return {
            **report,
            "blockerCodes": ["stage_one_human_gate_embedding_failed"],
        }
    return {
        "status": "embedded",
        "baseRecordId": base_record_id,
        "recordId": str(stored.get("recordId") or ""),
        "contentHash": str(stored.get("contentHash") or ""),
        "adjudicationId": adjudication_id,
        "hypothesisRoundId": round_id,
        "decidedBy": decided_by,
    }


# Stage-one closeout demands one real model-invocation receipt per policy
# ``requiredReceiptStages`` stage inside the required artifact payloads
# (``stage_one_receipt_missing`` otherwise).  Like the human gate above, the
# only real authorities for those receipts are the persisted chain records —
# never a synthesized payload.
_STAGE_ONE_RECEIPT_KEY = "modelInvocationReceipts"
_MAX_EMBEDDED_RECEIPTS_PER_STAGE = 4


def _read_chat_rooms_snapshot() -> list[dict[str, Any]]:
    """Durable chat-room authority without reconciliation or repair.

    Kept as an indirection so workflow materialization stays zero-write and
    tests can seed the persisted room shape directly.
    """

    from core.web.services import chat_room_service

    rooms = chat_room_service.read_chat_rooms_snapshot()
    return [dict(room) for room in rooms if isinstance(room, dict)]


def _question_generation_meetings_for_run(
    team_id: str,
    question_id: str,
    workflow_run_id: str,
) -> list[dict[str, Any]]:
    """Candidate-generation meetings bound to this run's question chain."""

    from core.web.services.team_workflow import meeting_rounds

    normalized_run = str(workflow_run_id or "").strip()
    return [
        meeting
        for meeting in meeting_rounds.list_meeting_rounds(team_id)["meetings"]
        if str(meeting.get("meetingType") or "") == CANDIDATE_GENERATION_MEETING_TYPE
        and str(meeting.get("question") or "").upper() == question_id.upper()
        and (
            not normalized_run
            or _meeting_workflow_run_id(meeting) == normalized_run
        )
    ]


def _meeting_chat_room_journal_receipts(
    meetings: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Read receipts from the bound meetings' speaker turn journals.

    Mirrors the exact read path ``meeting_receipt_authority`` uses for formal
    meeting turns: the speaker turn identity is ``chat-room:<round id>:<participant>``
    inside the participant session's turn journal, and receipts are read with
    ``read_model_invocation_receipts_from_events`` (source
    ``canonical_turn_outcome``).  Room/round/session resolution comes from the
    durable room snapshot plus each meeting's persisted chat-room bindings;
    anything unreadable simply contributes no receipts — the closeout stays
    the fail-closed gate.
    """

    from core.chat.conversation_ledger import load_conversation_events
    from core.chat.turn_journal import read_model_invocation_receipts_from_events

    deduped_meetings: dict[str, Mapping[str, Any]] = {}
    for meeting in meetings:
        meeting_id = str(meeting.get("meetingRoundId") or "").strip()
        if meeting_id:
            deduped_meetings[meeting_id] = meeting
    if not deduped_meetings:
        return []
    try:
        rooms = _read_chat_rooms_snapshot()
    except Exception:  # noqa: BLE001 - journal source stays best-effort
        return []
    rooms_by_id = {
        str(room.get("roomId") or "").strip(): room
        for room in rooms
        if str(room.get("roomId") or "").strip()
    }
    receipts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for meeting in deduped_meetings.values():
        room = rooms_by_id.get(str(meeting.get("linkedChatRoomId") or "").strip())
        if room is None:
            continue
        wanted_round_ids = {
            str(item or "").strip()
            for item in list(meeting.get("chatRoomRoundIds") or [])
            if str(item or "").strip()
        }
        for chat_round in room.get("rounds") or []:
            if not isinstance(chat_round, Mapping):
                continue
            round_id = str(chat_round.get("roundId") or "").strip()
            if not round_id or (
                wanted_round_ids and round_id not in wanted_round_ids
            ):
                continue
            for message in chat_round.get("messages") or []:
                if not isinstance(message, Mapping):
                    continue
                session_id = str(message.get("sessionId") or "").strip()
                participant_id = (
                    str(message.get("participantId") or "").strip() or session_id
                )
                if not session_id or not participant_id:
                    continue
                turn_identity = f"chat-room:{round_id}:{participant_id}"
                try:
                    events = load_conversation_events(PROJECT_ROOT, session_id)
                    found = read_model_invocation_receipts_from_events(
                        events,
                        turn_id=turn_identity,
                    )
                except Exception:  # noqa: BLE001 - unreadable journal, skip
                    continue
                for raw_receipt in found:
                    receipt_id = str(raw_receipt.get("receiptId") or "").strip()
                    if receipt_id:
                        if receipt_id in seen:
                            continue
                        seen.add(receipt_id)
                    receipts.append(dict(raw_receipt))
    return receipts


def _question_registered_receipts(
    team_id: str,
    question_id: str,
    workflow_run_id: str,
) -> list[dict[str, Any]]:
    """Registered node agent-turn receipts (the Challenge Cup audit store)."""

    from .model_invocation_receipt_registry import (
        question_model_invocation_receipts,
    )

    try:
        return question_model_invocation_receipts(
            team_id,
            question_id=question_id,
            workflow_run_id=workflow_run_id,
        )
    except Exception:  # noqa: BLE001 - corrupt store fails closed as empty
        return []


def _stage_one_policy_receipt_stages(
    input_snapshot: Mapping[str, Any] | None,
) -> tuple[str, ...]:
    """The receipt stages this run's closeout policy demands (canonical 3)."""

    from core.research.workflow.contracts.question_stage_binding import (
        QUESTION_PACKAGE_STAGES,
    )

    snapshot = input_snapshot if isinstance(input_snapshot, Mapping) else {}
    raw_policy = snapshot.get("stageOneCompletionPolicy")
    stages = tuple(
        str(item or "").strip().lower()
        for item in (
            raw_policy.get("requiredReceiptStages") if isinstance(raw_policy, Mapping) else ()
        )
        if str(item or "").strip()
    )
    canonical = tuple(sorted(QUESTION_PACKAGE_STAGES))
    if not stages:
        return canonical
    known = set(canonical)
    return tuple(item for item in stages if item in known) or canonical


def _collect_stage_one_receipt_candidates(
    *,
    team_id: str,
    question_id: str,
    workflow_run_id: str,
    accepted_round: Mapping[str, Any],
    bound_meetings: Sequence[Mapping[str, Any]],
    generation_meetings: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Gather candidate receipts, round first, then journal, then registry."""

    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    source_counts = {"round": 0, "meeting_journal": 0, "registered": 0}

    def _extend(source: str, found: Sequence[Any]) -> None:
        for raw in found:
            if not isinstance(raw, Mapping):
                continue
            receipt_id = str(raw.get("receiptId") or "").strip()
            if receipt_id:
                if receipt_id in seen:
                    continue
                seen.add(receipt_id)
            candidates.append(dict(raw))
            source_counts[source] += 1

    _extend(
        "round",
        [
            item
            for item in list(accepted_round.get("modelInvocationReceipts") or [])
            if isinstance(item, Mapping)
        ],
    )
    _extend(
        "meeting_journal",
        _meeting_chat_room_journal_receipts([*bound_meetings, *generation_meetings]),
    )
    _extend(
        "registered",
        _question_registered_receipts(team_id, question_id, workflow_run_id),
    )
    return candidates, source_counts


def _stage_one_bound_receipts_by_stage(
    candidates: Sequence[Mapping[str, Any]],
    *,
    question_id: str,
    workflow_run_id: str,
    required_stages: Sequence[str],
    bound_meeting_ids: Sequence[str],
) -> tuple[dict[str, list[dict[str, Any]]], int]:
    """Validate and classify receipts exactly like the closeout walk.

    Faithful classification rule: the closeout reads each receipt's OWN
    ``scope.stageId`` — the server-owned ``QuestionStageBinding.questionStage``
    the producer minted ("generation" meeting speakers and hypothesis-design /
    earlier agent tasks, "review" meeting speakers and the review-step
    executor, "revision" protocol/iteration agent tasks).  A receipt is only
    embedded when it parses, its status is succeeded/retried, its scope is
    bound to THIS question and run, and its real stage is one the policy
    demands — scope is never synthesized, rewritten, or re-mapped.  A stage
    whose real receipt does not exist stays missing and closeout keeps failing
    closed with ``stage_one_receipt_missing`` (the live G1 smoke shape: real
    generation/review receipts exist, while every revision-stage producer is a
    policy-deferred node, so no revision receipt can exist yet).
    """

    from core.research.workflow.contracts.model_invocation_receipt import (
        ModelInvocationReceipt,
        ModelInvocationStatus,
    )

    meeting_prefixes = tuple(
        f"meeting:{str(item or '').strip()}:"
        for item in bound_meeting_ids
        if str(item or "").strip()
    )
    by_stage: dict[str, list[dict[str, Any]]] = {stage: [] for stage in required_stages}
    rejected = 0
    indexed = list(enumerate(candidates))
    ordered = sorted(
        indexed,
        key=lambda item: (
            0
            if str(item[1].get("nodeRunId") or "").startswith(meeting_prefixes)
            else 1,
            item[0],
        ),
    )
    for _, raw in ordered:
        try:
            receipt = ModelInvocationReceipt.from_dict(raw)
        except (KeyError, TypeError, ValueError, ContractValidationError):
            rejected += 1
            continue
        if receipt.status not in {
            ModelInvocationStatus.SUCCEEDED,
            ModelInvocationStatus.RETRIED,
        }:
            rejected += 1
            continue
        scope = dict(receipt.scope or {})
        stage = str(scope.get("stageId") or scope.get("stage_id") or "").lower()
        if (
            stage not in by_stage
            or str(scope.get("questionId") or "").upper() != question_id.upper()
            or str(scope.get("runId") or "") != workflow_run_id
        ):
            rejected += 1
            continue
        by_stage[stage].append(receipt.to_dict())
    return by_stage, rejected


def _materialize_stage_one_receipt_evidence(
    *,
    team_id: str,
    workflow_run_id: str,
    question_id: str,
    source_collection_run_id: str,
    accepted_round: Mapping[str, Any],
    bound_meetings: Sequence[Mapping[str, Any]],
    generation_meetings: Sequence[Mapping[str, Any]],
    required_stages: Sequence[str],
    errors: dict[str, str],
) -> dict[str, Any]:
    """Embed the accepted chain's real receipts into the ``hypothesis_set`` row.

    Same append-only pattern as the closeout human gate: the base row is
    immutable, the receipt-carrying payload is appended as a new row whose
    identity derives from the row it upgrades (``<recordId>:model-receipts``),
    so the scoped readback (latest row wins) resolves the receipt authority
    and replays are idempotent.  No receipts means no row: closeout keeps
    failing with ``stage_one_receipt_missing`` exactly as before.
    """

    from .workflow_artifact_store import list_workflow_artifacts, put_workflow_artifact

    report: dict[str, Any] = {
        "status": "absent",
        "blockerCodes": [],
        "stageCoverage": {},
        "embeddedCount": 0,
        "candidateCount": 0,
        "rejectedCount": 0,
        "sourceCounts": {},
    }
    rows = [
        row
        for row in list_workflow_artifacts(
            team_id,
            kind="hypothesis_set",
            workflow_run_id=workflow_run_id,
            source_collection_run_id=source_collection_run_id,
        )
        if isinstance(row.get("payload"), Mapping) and row.get("payload")
    ]
    if not rows:
        # The artifact requirement gate owns the missing-artifact semantics.
        return report
    base_row = rows[-1]
    base_payload = dict(base_row["payload"])
    report["baseRecordId"] = str(base_row.get("recordId") or "")
    if (
        _STAGE_ONE_RECEIPT_KEY in base_payload
        or "model_invocation_receipts" in base_payload
        or "receipts" in base_payload
    ):
        # The latest authority already carries receipts (replay): reuse,
        # never rewrite.
        report["status"] = "present"
        return report
    candidates, source_counts = _collect_stage_one_receipt_candidates(
        team_id=team_id,
        question_id=question_id,
        workflow_run_id=workflow_run_id,
        accepted_round=accepted_round,
        bound_meetings=bound_meetings,
        generation_meetings=generation_meetings,
    )
    report["candidateCount"] = len(candidates)
    report["sourceCounts"] = source_counts
    by_stage, rejected = _stage_one_bound_receipts_by_stage(
        candidates,
        question_id=question_id,
        workflow_run_id=workflow_run_id,
        required_stages=required_stages,
        bound_meeting_ids=[
            str(meeting.get("meetingRoundId") or "").strip()
            for meeting in [*bound_meetings, *generation_meetings]
        ],
    )
    report["rejectedCount"] = rejected
    embedded: list[dict[str, Any]] = []
    stage_coverage: dict[str, list[str]] = {}
    for stage in required_stages:
        stage_receipts = by_stage.get(stage) or []
        stage_coverage[stage] = [
            str(receipt.get("receiptId") or "")
            for receipt in stage_receipts[:_MAX_EMBEDDED_RECEIPTS_PER_STAGE]
        ]
        embedded.extend(stage_receipts[:_MAX_EMBEDDED_RECEIPTS_PER_STAGE])
    report["stageCoverage"] = stage_coverage
    if not embedded:
        # Nothing real to embed: keep the fail-closed closeout blocker
        # (``stage_one_receipt_missing``) untouched — never fake coverage.
        return report
    receipt_payload = {
        **copy.deepcopy(base_payload),
        _STAGE_ONE_RECEIPT_KEY: embedded,
    }
    base_record_id = str(base_row.get("recordId") or "").strip()
    try:
        stored = put_workflow_artifact(
            team_id,
            kind="hypothesis_set",
            workflow_run_id=workflow_run_id,
            source_collection_run_id=str(
                base_row.get("sourceCollectionRunId") or source_collection_run_id
            ).strip(),
            artifact_identity=(
                f"{base_record_id}:model-receipts" if base_record_id else ""
            ),
            payload=receipt_payload,
        )
    except Exception as exc:  # noqa: BLE001 - fail closed, report the cause
        errors["hypothesis_set"] = str(exc) or type(exc).__name__
        return {
            **report,
            "status": "blocked",
            "blockerCodes": ["stage_one_receipt_embedding_failed"],
        }
    return {
        **report,
        "status": "embedded",
        "recordId": str(stored.get("recordId") or ""),
        "embeddedCount": len(embedded),
    }


def _classify_round_failure(exc: BaseException) -> str:
    """Map one generation failure to a stable machine-readable failure code."""
    type_name = type(exc).__name__
    message = str(exc)
    if "already bound to different content" in message:
        # hypothesis_rounds append-only idempotency guard: the round id is
        # already bound to different candidate/lineage content.
        return "hypothesis_round_content_conflict"
    if type_name == "ResearchHypothesisRoundGenerationInProgressError":
        # Pre-generation dedup guard: a concurrent trigger is already
        # generating this content-addressed round id.
        return "hypothesis_round_generation_in_progress"
    if type_name == "HypothesisReviewExecutionError":
        return (
            "formal_receipt_fence"
            if message.startswith("FORMAL")
            else "review_execution_failed"
        )
    if type_name == "ContractValidationError":
        return "hypothesis_round_validation_failed"
    if type_name in {
        "ResearchHypothesisRoundError",
        "ResearchHypothesisRoundNotFoundError",
    }:
        return "hypothesis_round_precondition_failed"
    if type_name == "HypothesisFirstChainError":
        return "chain_precondition_failed"
    return "hypothesis_round_generation_error"


def _record_round_persistence_failure(
    team_id: str,
    meeting_round: Mapping[str, Any],
    *,
    status: str,
    failure_code: str,
    reason: str,
    error_type: str = "",
    fan_in: Mapping[str, Any] | None = None,
    round_id: str = "",
    selection_id: str = "",
    round_index: int | None = None,
    meeting_round_ids: list[str] | None = None,
    retry_hint: str = "",
    context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist one failure trace for a round generation attempt (best-effort).

    The trace lands in the ``hypothesis_round_failures`` sibling ledger so a
    spent review budget is never silently lost; ``hypothesis_rounds.jsonl``
    itself only ever carries real generated rounds.  When the trace write
    fails, the returned ``failureRecordError`` keeps the diagnostic visible
    in the caller's structural report instead of raising.
    """
    try:
        from core.web.services.team_workflow import hypothesis_rounds

        bound_meeting_ids = list(meeting_round_ids or [])
        if not bound_meeting_ids:
            bound_meeting_ids = [
                str(item.get("meetingRoundId") or "").strip()
                for item in list((fan_in or {}).get("meetings") or [])
                if isinstance(item, Mapping)
            ]
        if not bound_meeting_ids:
            primary_meeting_id = str(meeting_round.get("meetingRoundId") or "").strip()
            if primary_meeting_id:
                bound_meeting_ids = [primary_meeting_id]
        scope = (
            meeting_round.get("discussionScope")
            if isinstance(meeting_round.get("discussionScope"), Mapping)
            else {}
        )
        receipt_authority = (
            meeting_round.get("modelInvocationReceiptAuthority")
            if isinstance(meeting_round.get("modelInvocationReceiptAuthority"), Mapping)
            else {}
        )
        recorded = hypothesis_rounds.record_hypothesis_round_failure(
            team_id,
            {
                "status": status,
                "failureCode": failure_code,
                "reason": reason,
                "errorType": error_type,
                "roundId": round_id,
                "meetingRoundIds": bound_meeting_ids,
                "selectionId": selection_id
                or str((fan_in or {}).get("selectionId") or "").strip(),
                "roundIndex": round_index,
                "questionId": str(meeting_round.get("question") or "").strip(),
                "workflowRunId": str(
                    (receipt_authority or {}).get("workflowRunId")
                    or (scope or {}).get("workflowRunId")
                    or meeting_round.get("workflowRunId")
                    or ""
                ).strip(),
                "scopeHash": str(meeting_round.get("scopeHash") or "").strip(),
                "retryHint": retry_hint,
                "context": dict(context or {}),
            },
        )
        failure = (
            recorded.get("failure")
            if isinstance(recorded.get("failure"), Mapping)
            else {}
        )
        return {"failureRecordId": str(failure.get("failureId") or "")}
    except Exception as exc:  # noqa: BLE001 - trace failure stays diagnostic
        return {"failureRecordError": str(exc) or type(exc).__name__}


# Stage-one closure authorities the hypothesis_design node readback expects on
# top of the node's own hypothesis_set (challenge_cup_stage_one_scope_v1).
STAGE_ONE_NODE_AUTHORITY_KINDS: tuple[str, ...] = (
    "dimension_reviews",
    "review_independence",
    "review_disagreement",
    "feedback_iterations",
    "core_hypothesis_coherence",
    "stage1_research_plan",
    "competition_alignment",
)


def _stage_one_node_kind_readable(
    kind: str,
    *,
    team_id: str,
    workflow_run_id: str,
    source_collection_run_id: str,
) -> bool:
    """Mirror the closure readback scope used by ``collect_required_artifact_refs``."""
    try:
        from .artifact_readback_registry import load_scoped_artifact_payload

        payload = load_scoped_artifact_payload(
            kind,
            team_id=team_id,
            authority_run_id=str(source_collection_run_id or workflow_run_id or "").strip(),
            workflow_run_id=str(workflow_run_id or "").strip(),
        )
    except Exception:  # noqa: BLE001 - unreadable means not satisfied
        return False
    return isinstance(payload, Mapping) and bool(payload.get("payload"))


def _formal_source_collection_run_id(workflow_run_id: str) -> str:
    """Resolve the formal run's artifact authority run id (shared resolver)."""
    from core.web.services.team_workflow import hypothesis_review_executor

    return str(
        hypothesis_review_executor._source_collection_run_id_for_formal_workflow(
            workflow_run_id
        )
        or ""
    ).strip()


def materialize_stage_one_node_authority(
    team_id: str,
    question_id: str,
    *,
    workflow_run_id: str,
    node_run_id: str,
    input_snapshot_hash: str = "",
    source_collection_run_id: str = "",
    input_snapshot: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Bind an already-accepted chain round's stage-one authorities to a live node.

    Integration repair for the hypothesis-first closure node: the round is
    generated (and its authorities materialized) before adjudication and
    inside whatever node context triggered the review, so when adjudication
    lands later the current ``hypothesis_design`` attempt finds no readable
    closure authority and blocks on ``required_artifact_missing``.  This
    function re-runs the exact same fail-closed writer set as
    ``_generate_hypothesis_round``, re-bound to the live formal run
    (``workflow_run_id``/``node_run_id``/``input_snapshot_hash``), for any
    question whose latest closed HypothesisRound is meta-review accepted.

    Idempotency: every kind is first probed through the same scoped readback
    the completion gate uses; a readable authority is reused (the store is
    append-only) and never rewritten, so replays neither duplicate rows nor
    raise ``WorkflowArtifactConflictError``.  Writers stay fail-closed: any
    blocker is reported per kind and never faked into success.  A missing
    ``core_hypothesis_coherence`` authority is recovered from the accepted
    round's persisted per-candidate coherence verdicts (dev/platform rounds
    skip the artifact write at generation time, so the recovery replays it
    with ``require_receipts=False``); verdict data that is absent, incomplete,
    or not fully passed is reported as missing instead of being regenerated.

    When the closed rounds carry no ``revisionEnvelope`` — the chain-driven
    review shape, whose iteration history lives in the review-round link /
    collection-request / decision ledgers instead — the authority is recovered
    from that persisted evidence and replayed through the same canonical
    writer.  Kinds the run's launch shape structurally cannot demand (see
    ``stage_one_shape_gate``) are waived with persisted evidence and reported
    under ``downgradedKinds``; they never count as satisfied.
    """
    from core.web.services.team_service import assert_team_exists

    team = str(assert_team_exists(team_id) or "").strip()
    question = str(question_id or "").strip().upper()
    run = str(workflow_run_id or "").strip()
    node = str(node_run_id or "").strip()
    snapshot_hash = str(input_snapshot_hash or "").strip().lower()
    if not team or not question or not run or not node:
        return {
            "status": "skipped",
            "reason": "node_binding_missing",
            "missingKinds": [],
        }
    meetings = _question_meetings(team, question, workflow_run_id=run)
    meeting_ids = {
        str(meeting.get("meetingRoundId") or "").strip() for meeting in meetings
    }
    rounds = [
        round_record
        for round_record in _question_hypothesis_rounds(team, question)
        if any(
            isinstance(ref, Mapping)
            and str(ref.get("kind") or "") == "meeting_round"
            and str(ref.get("id") or "") in meeting_ids
            for ref in list(round_record.get("meetingRefs") or [])
        )
    ]
    closed_rounds = [
        round_record
        for round_record in rounds
        if str(round_record.get("status") or "") == "closed"
    ]
    if not closed_rounds:
        return {
            "status": "skipped",
            "reason": "hypothesis_round_missing",
            "missingKinds": [],
        }
    # The LATEST closed round is the convergence authority (mirrors
    # ``chain_state``): a newer rejected/unaccepted round means the chain
    # moved past the older acceptance, so nothing may be re-materialized.
    latest_round = closed_rounds[-1]
    latest_meta_review = (
        dict(latest_round.get("metaReview"))
        if isinstance(latest_round.get("metaReview"), Mapping)
        else {}
    )
    if latest_meta_review.get("accepted") is not True:
        return {
            "status": "skipped",
            "reason": "hypothesis_round_not_accepted",
            "missingKinds": [],
        }
    accepted_round = latest_round
    source = str(
        source_collection_run_id
        or _formal_source_collection_run_id(run)
        or run
    ).strip()
    meeting_by_id = {
        str(meeting.get("meetingRoundId") or ""): meeting for meeting in meetings
    }
    primary_meeting: dict[str, Any] = {}
    for ref in list(accepted_round.get("meetingRefs") or []):
        if not isinstance(ref, Mapping) or str(ref.get("kind") or "") != "meeting_round":
            continue
        bound = meeting_by_id.get(str(ref.get("id") or "").strip())
        if bound is not None:
            primary_meeting = dict(bound)
            break
    if not primary_meeting:
        return {
            "status": "skipped",
            "reason": "primary_meeting_missing",
            "missingKinds": list(STAGE_ONE_NODE_AUTHORITY_KINDS),
        }
    try:
        fan_in = _review_meeting_fan_in_group(team, primary_meeting)
    except Exception as exc:  # noqa: BLE001 - stay fail-closed, never fake success
        return {
            "status": "skipped",
            "reason": "fan_in_resolution_failed",
            "error": str(exc) or type(exc).__name__,
            "missingKinds": list(STAGE_ONE_NODE_AUTHORITY_KINDS),
        }
    if fan_in.get("status") != "ready":
        return {
            "status": "skipped",
            "reason": "fan_in_not_ready",
            "missingKinds": list(STAGE_ONE_NODE_AUTHORITY_KINDS),
        }
    bound_meetings = [
        dict(item)
        for item in list(fan_in.get("meetings") or [])
        if isinstance(item, Mapping)
    ]
    selection_id = str(fan_in.get("selectionId") or "").strip()
    selected_candidate_ids = _normalized_str_list(
        fan_in.get("selectedCandidateIds")
    ) or _normalized_str_list(primary_meeting.get("selectedCandidateIds"))
    if not selected_candidate_ids:
        try:
            from core.web.services.team_workflow import (
                hypothesis_selection as selections,
            )

            selected = selections.get_hypothesis_selection(team, selection_id)[
                "selection"
            ]
            selected_candidate_ids = _normalized_str_list(
                selected.get("selectedCandidateIds")
            )
        except Exception:  # noqa: BLE001 - candidates stay a writer precondition
            selected_candidate_ids = []
    if snapshot_hash:
        input_snapshot_hash = snapshot_hash
    else:
        input_snapshot_hash = str(
            primary_meeting.get("inputSnapshotHash")
            or accepted_round.get("inputSnapshotHash")
            or ""
        ).strip().lower()
    # Re-bound receipt authority: the historical meeting authority may point at
    # a predecessor node run (or none), so the writers validate against the
    # live formal-run binding instead.
    workflow_authority = {
        "teamId": team,
        "workflowRunId": run,
        "questionId": question,
        "nodeRunId": node,
        "sourceCollectionRunId": source,
        "inputSnapshotHash": input_snapshot_hash,
    }
    input_refs = [
        *[
            ref
            for bound_meeting in bound_meetings
            for ref in _normalized_str_list(bound_meeting.get("inputArtifactRefs"))
        ],
        *[
            ref
            for bound_meeting in bound_meetings
            for ref in _normalized_str_list(bound_meeting.get("discussionItemRefs"))
        ],
    ]
    round_id = str(accepted_round.get("roundId") or "")
    reviewer_assignments = (
        dict(accepted_round.get("roles"))
        if isinstance(accepted_round.get("roles"), Mapping)
        else {}
    )
    receipt_contexts = [
        dict(item)
        for item in list(accepted_round.get("modelInvocationReceipts") or [])
        if isinstance(item, Mapping)
    ]
    try:
        candidates = _build_round_candidates(
            team,
            primary_meeting,
            candidate_ids=selected_candidate_ids,
            workflow_run_id=run,
        )
    except Exception as exc:  # noqa: BLE001 - reported, never faked
        candidates = []
        candidate_error = str(exc) or type(exc).__name__
    else:
        candidate_error = ""

    def _probe(kind: str) -> bool:
        return _stage_one_node_kind_readable(
            kind,
            team_id=team,
            workflow_run_id=run,
            source_collection_run_id=source,
        )

    satisfied: list[str] = []
    written: list[str] = []
    reused: list[str] = []
    blockers_by_kind: dict[str, list[str]] = {}
    errors: dict[str, str] = {}
    dimension_ref_repair: dict[str, Any] = {}

    # dimension_reviews — canonical audit projection of the accepted round.
    if _probe("dimension_reviews"):
        satisfied.append("dimension_reviews")
        reused.append("dimension_reviews")
    elif candidate_error:
        blockers_by_kind["dimension_reviews"] = ["round_candidates_unavailable"]
        errors["dimension_reviews"] = candidate_error
    else:
        try:
            from .dimension_reviews_artifact_writer import (
                materialize_dimension_reviews_authority,
            )

            # Ref repair happens on the materializer input side only: the
            # writer keeps its exact canonical-ref validation and sees the
            # repaired (or untouched, for unmappable ids) rows.
            repaired_review, dimension_ref_repair = (
                _repair_dimension_review_evidence_refs(team, accepted_round)
            )
            dimension_authority = materialize_dimension_reviews_authority(
                team_id=team,
                workflow_run_id=run,
                node_run_id=node,
                question_id=question,
                selection_id=selection_id,
                review_round_id=round_id,
                input_refs=input_refs,
                input_snapshot_hash=input_snapshot_hash,
                candidates=candidates,
                review=repaired_review,
                workflow_authority=workflow_authority,
                source_collection_run_id=source,
            )
        except Exception as exc:  # noqa: BLE001 - fail-closed blocker
            dimension_authority = {
                "status": "blocked",
                "blockerCodes": ["dimension_reviews_authority_persistence_failed"],
                "error": str(exc) or type(exc).__name__,
            }
        if str(dimension_authority.get("status") or "") == "written":
            satisfied.append("dimension_reviews")
            written.append("dimension_reviews")
        else:
            blockers_by_kind["dimension_reviews"] = [
                str(item)
                for item in list(dimension_authority.get("blockerCodes") or [])
                if str(item).strip()
            ] or ["dimension_reviews_authority_persistence_failed"]
            error = str(dimension_authority.get("error") or "").strip()
            if error:
                errors["dimension_reviews"] = error

    # review_independence + review_disagreement — one shared writer pair.
    if _probe("review_independence") and _probe("review_disagreement"):
        satisfied.extend(("review_independence", "review_disagreement"))
        reused.extend(("review_independence", "review_disagreement"))
    else:
        try:
            from .review_independence_artifact_writer import (
                write_review_independence_artifacts,
            )

            independence_authority = write_review_independence_artifacts(
                team_id=team,
                workflow_run_id=run,
                node_run_id=node,
                review_round_id=round_id,
                review=accepted_round,
                reviewer_assignments=reviewer_assignments,
                receipt_contexts=receipt_contexts,
                source_collection_run_id=source,
            )
        except Exception as exc:  # noqa: BLE001 - fail-closed blocker
            independence_authority = {
                "status": "blocked",
                "blockerCodes": ["review_independence_authority_persistence_failed"],
                "error": str(exc) or type(exc).__name__,
            }
        if str(independence_authority.get("status") or "") == "written":
            satisfied.extend(("review_independence", "review_disagreement"))
            written.extend(("review_independence", "review_disagreement"))
        else:
            pair_blockers = [
                str(item)
                for item in list(independence_authority.get("blockerCodes") or [])
                if str(item).strip()
            ] or ["review_independence_authority_persistence_failed"]
            blockers_by_kind["review_independence"] = pair_blockers
            blockers_by_kind["review_disagreement"] = list(pair_blockers)
            error = str(independence_authority.get("error") or "").strip()
            if error:
                errors["review_independence"] = error

    # feedback_iterations — every closed round's revision envelope replays in
    # chain order until the run-scope iteration authority is readable.
    if _probe("feedback_iterations"):
        satisfied.append("feedback_iterations")
        reused.append("feedback_iterations")
    else:
        feedback_blockers: list[str] = []
        for round_record in closed_rounds:
            envelope = (
                dict(round_record.get("revisionEnvelope"))
                if isinstance(round_record.get("revisionEnvelope"), Mapping)
                else {}
            )
            if not envelope:
                continue
            try:
                recorded = _materialize_hypothesis_revision_authority(
                    team_id=team,
                    workflow_run_id=run,
                    node_run_id=node,
                    question_id=question,
                    source_collection_run_id=source,
                    round_record=round_record,
                )
            except Exception as exc:  # noqa: BLE001 - try the next round
                feedback_blockers = ["hypothesis_revision_authority_persistence_failed"]
                errors["feedback_iterations"] = str(exc) or type(exc).__name__
                continue
            if str(recorded.get("status") or "").strip().lower() in {
                "recorded",
                "written",
            }:
                satisfied.append("feedback_iterations")
                written.append("feedback_iterations")
                feedback_blockers = []
                break
            feedback_blockers = [
                str(item)
                for item in list(recorded.get("blockerCodes") or [])
                if str(item).strip()
            ] or ["hypothesis_revision_evidence_missing"]
        if "feedback_iterations" not in satisfied:
            # Chain-driven dev/platform rounds never persist a round
            # ``revisionEnvelope``, so two complementary fail-closed
            # recoveries replay the canonical writer before blocking:
            # first the accepted selection's recorded review round chain
            # (closed hash-pinned digest meetings with per-candidate
            # proposals and decision rationales), then the review-round
            # link / collection-request / adopted-decision ledger trail.
            # Underivable evidence keeps the original blocker untouched.
            try:
                review_feedback_authority = (
                    _materialize_review_feedback_iterations_authority(
                        team_id=team,
                        workflow_run_id=run,
                        node_run_id=node,
                        question_id=question,
                        source_collection_run_id=source,
                        accepted_round=accepted_round,
                        selection_id=selection_id,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - keep the fail-closed blocker
                errors["feedback_iterations"] = str(exc) or type(exc).__name__
                review_feedback_authority = {
                    "status": "blocked",
                    "blockerCodes": ["hypothesis_revision_evidence_missing"],
                }
            if str(review_feedback_authority.get("status") or "") == "written":
                satisfied.append("feedback_iterations")
                written.append("feedback_iterations")
            else:
                derivation_blockers = [
                    str(item)
                    for item in list(review_feedback_authority.get("blockerCodes") or [])
                    if str(item).strip()
                ]
                # Second recovery: collection-request / decision ledger
                # evidence (a question without any chain review-round link is
                # ``not_applicable`` and keeps the derivation blocker).
                recovery = _recover_chain_feedback_iterations_authority(
                    team_id=team,
                    question_id=question,
                    workflow_run_id=run,
                    node_run_id=node,
                    source_collection_run_id=source,
                    selected_candidate_ids=selected_candidate_ids,
                    meetings=meetings,
                )
                if str(recovery.get("status") or "") == "written":
                    satisfied.append("feedback_iterations")
                    written.append("feedback_iterations")
                    errors.pop("feedback_iterations", None)
                elif str(recovery.get("status") or "") == "blocked":
                    recovery_blockers = [
                        str(item)
                        for item in list(recovery.get("blockerCodes") or [])
                        if str(item).strip()
                    ]
                    blockers_by_kind["feedback_iterations"] = (
                        recovery_blockers
                        or derivation_blockers
                        or feedback_blockers
                        or ["hypothesis_revision_evidence_missing"]
                    )
                    recovery_reason = str(recovery.get("reason") or "").strip()
                    if recovery_reason:
                        errors["feedback_iterations"] = recovery_reason
                else:
                    blockers_by_kind["feedback_iterations"] = (
                        derivation_blockers
                        or feedback_blockers
                        or ["hypothesis_revision_evidence_missing"]
                    )
        if "feedback_iterations" not in satisfied and (
            "feedback_iterations" not in blockers_by_kind
        ):
            blockers_by_kind["feedback_iterations"] = feedback_blockers or [
                "hypothesis_revision_evidence_missing"
            ]

    # core_hypothesis_coherence — a readable authority is reused. An absent one
    # is recovered from the accepted round's persisted per-candidate verdicts:
    # chain-driven reviews may run with executionMode=dev, in which case the
    # review executor never wrote the artifact (no formal receipts), but the
    # complete verdict itself is persisted on every round candidate. Recovery
    # replays the exact same fail-closed writer (probe first, so replays stay
    # idempotent); fewer than two unique candidates, any non-passed verdict, or
    # a persistence error keeps the fail-closed blocker — nothing is faked.
    if _probe("core_hypothesis_coherence"):
        satisfied.append("core_hypothesis_coherence")
        reused.append("core_hypothesis_coherence")
    else:
        coherence_results = [
            dict(item.get("coreHypothesisCoherence"))
            for item in list(accepted_round.get("candidates") or [])
            if isinstance(item, Mapping)
            and isinstance(item.get("coreHypothesisCoherence"), Mapping)
        ]
        coherence_ids = {
            str(item.get("candidateId") or "").strip()
            for item in coherence_results
        }
        if (
            len(coherence_ids) < 2
            or "" in coherence_ids
            or not all(item.get("passed") is True for item in coherence_results)
        ):
            blockers_by_kind["core_hypothesis_coherence"] = [
                "core_hypothesis_coherence_authority_missing"
            ]
        else:
            try:
                from core.web.services.team_workflow.research_runtime.core_hypothesis_coherence_artifact_writer import (
                    record_core_hypothesis_coherence_artifact,
                )

                record_core_hypothesis_coherence_artifact(
                    team_id=team,
                    workflow_run_id=run,
                    source_collection_run_id=source,
                    review_context_id=str(
                        accepted_round.get("reviewContextId") or ""
                    ),
                    results=coherence_results,
                    # Dev/platform rounds carry no model-invocation receipts by
                    # design; an empty receiptRef is the persisted truth here,
                    # not a defect. Formal callers keep require_receipts=True.
                    require_receipts=False,
                )
            except Exception as exc:  # noqa: BLE001 - fail-closed blocker
                blockers_by_kind["core_hypothesis_coherence"] = [
                    "core_hypothesis_coherence_authority_persistence_failed"
                ]
                errors["core_hypothesis_coherence"] = (
                    str(exc) or type(exc).__name__
                )
            else:
                satisfied.append("core_hypothesis_coherence")
                written.append("core_hypothesis_coherence")

    # stage1_research_plan + competition_alignment — projected from the
    # approved question authority under the accepted round's recommendation.
    if _probe("stage1_research_plan") and _probe("competition_alignment"):
        satisfied.extend(("stage1_research_plan", "competition_alignment"))
        reused.extend(("stage1_research_plan", "competition_alignment"))
    else:
        try:
            stage_one_plan_authority = _materialize_stage_one_plan_authority(
                team_id=team,
                workflow_run_id=run,
                node_run_id=node,
                question_id=question,
                source_collection_run_id=source,
                round_record=accepted_round,
            )
        except Exception as exc:  # noqa: BLE001 - fail-closed blocker
            stage_one_plan_authority = _blocked_round_authority(
                "stage1_research_plan",
                "stage_one_plan_authority_persistence_failed",
            )
            errors["stage1_research_plan"] = str(exc) or type(exc).__name__
        if str(stage_one_plan_authority.get("status") or "") == "written":
            satisfied.extend(("stage1_research_plan", "competition_alignment"))
            written.extend(("stage1_research_plan", "competition_alignment"))
        else:
            plan_blockers = [
                str(item)
                for item in list(stage_one_plan_authority.get("blockerCodes") or [])
                if str(item).strip()
            ] or ["stage_one_plan_authority_persistence_failed"]
            blockers_by_kind["stage1_research_plan"] = plan_blockers
            blockers_by_kind["competition_alignment"] = list(plan_blockers)

    # hypothesis_set human gate — the node's own authority still needs its
    # closeout human gate.  The gate is ONLY the persisted real chain human
    # adjudication of the accepted round (decision ``accepted``): without such
    # a record nothing is embedded and closeout keeps failing closed with
    # ``stage_one_human_gate_missing``.  The gated payload is written as a new
    # append-only row whose identity derives from the ungated row it upgrades,
    # so replays are idempotent and no existing artifact is rewritten.
    hypothesis_set_gate_report = _materialize_hypothesis_set_human_gate(
        team_id=team,
        workflow_run_id=run,
        question_id=question,
        source_collection_run_id=source,
        round_record=accepted_round,
        meeting_ids=meeting_ids,
        errors=errors,
    )
    if hypothesis_set_gate_report.get("status") == "blocked":
        blockers_by_kind["hypothesis_set"] = [
            str(code)
            for code in list(hypothesis_set_gate_report.get("blockerCodes") or [])
            if str(code).strip()
        ] or ["stage_one_human_gate_missing"]

    # hypothesis_set receipt evidence — the closeout demands one real model
    # invocation receipt per policy ``requiredReceiptStages`` stage inside the
    # required payloads (``stage_one_receipt_missing`` otherwise).  Only real
    # receipts are embedded (accepted round → meeting speaker journals → the
    # registered agent-turn audit store), classified by their own scope stage
    # and validated against this run; a stage without a real receipt stays
    # missing and closeout keeps failing closed.
    hypothesis_set_receipt_report = _materialize_stage_one_receipt_evidence(
        team_id=team,
        workflow_run_id=run,
        question_id=question,
        source_collection_run_id=source,
        accepted_round=accepted_round,
        bound_meetings=bound_meetings,
        generation_meetings=_question_generation_meetings_for_run(
            team, question, run
        ),
        required_stages=_stage_one_policy_receipt_stages(input_snapshot),
        errors=errors,
    )

    ordered = list(STAGE_ONE_NODE_AUTHORITY_KINDS)
    # Launch-shape conditional waivers: hypothesis-first chain launches cannot
    # demand authorities whose source (approved question artifact /
    # canonically addressable review rows) the shape never produces.  The
    # waiver needs persisted evidence, is never applied to a readable
    # authority, and a downgraded kind stays in ``blockerCodes`` (the real
    # underlying evidence) while being excluded from ``missingKinds``.
    try:
        from .stage_one_shape_gate import (
            downgraded_stage_one_kinds,
            drop_downgraded_kinds,
        )

        downgrades = downgraded_stage_one_kinds(
            ordered,
            team_id=team,
            question_id=question,
            input_snapshot=input_snapshot,
            source_collection_run_id=source,
            workflow_run_id=run,
        )
    except Exception:  # noqa: BLE001 - no waiver on doubt, stay fail-closed
        downgrades = {}
    missing = [kind for kind in ordered if kind not in satisfied]
    effective_missing = [
        kind for kind in drop_downgraded_kinds(missing, downgrades)
    ]
    repair_report = (
        {
            "repairedRows": int(dimension_ref_repair.get("repairedRows") or 0),
            "inheritedRows": int(dimension_ref_repair.get("inheritedRows") or 0),
            "unresolvedRefs": list(
                dimension_ref_repair.get("unresolvedRefs") or []
            ),
        }
        if dimension_ref_repair
        else {}
    )
    return {
        "status": "materialized" if not effective_missing else "blocked",
        "reason": "" if not effective_missing else "stage_one_authority_missing",
        "teamId": team,
        "questionId": question,
        "workflowRunId": run,
        "nodeRunId": node,
        "roundId": round_id,
        "selectionId": selection_id,
        "satisfiedKinds": [kind for kind in ordered if kind in satisfied],
        "writtenKinds": written,
        "reusedKinds": reused,
        "missingKinds": effective_missing,
        **({"downgradedKinds": dict(downgrades)} if downgrades else {}),
        "blockerCodes": blockers_by_kind,
        **({"errors": errors} if errors else {}),
        **({"dimensionRefRepair": repair_report} if repair_report else {}),
        **(
            {"hypothesisSetGate": dict(hypothesis_set_gate_report)}
            if hypothesis_set_gate_report.get("status") != "absent"
            else {}
        ),
        # Always reported: the receipt stage coverage (or its deliberate
        # absence) is the operator-visible explanation for a lingering
        # ``stage_one_receipt_missing`` closeout blocker.
        "hypothesisSetReceipts": dict(hypothesis_set_receipt_report),
    }


def _generate_hypothesis_round(
    team_id: str,
    meeting_round: Mapping[str, Any],
    *,
    reflection_runner: Any = None,
    pairwise_runner: Any = None,
    pareto_runner: Any = None,
    metareview_runner: Any = None,
    revision_runner: Any = None,
) -> dict[str, Any]:
    """Best-effort selection-level HypothesisRound fan-in after closure.

    Mirrors the auto-open failure semantics: the closed meeting is an
    append-only fact, so a generation failure is reported structurally and
    never rolls the closure back; the readiness layer keeps blocking on
    ``hypothesis_round_unconverged`` until a round converges (fail-closed).
    Replays reuse the already-generated round through HF-3 idempotency.

    Every non-ready or failed attempt additionally appends a durable trace
    to the ``hypothesis_round_failures`` ledger (``blocked`` for a pending
    fan-in, ``failed`` with a classified ``failureCode`` otherwise) so the
    spent review work stays recoverable: the fan-in path regenerates
    automatically when the last sibling review closes, and the other
    failure codes rerun through :func:`regenerate_hypothesis_round`.
    """
    fan_in: dict[str, Any] = {}
    round_id = ""
    selection_id = ""
    round_index: int | None = None
    meeting_round_ids: list[str] = []
    try:
        from core.web.services.team_workflow import (
            hypothesis_review_executor,
            hypothesis_rounds,
        )
        from core.web.services.team_workflow import (
            hypothesis_selection as selections,
        )

        fan_in = _review_meeting_fan_in_group(team_id, meeting_round)
        if fan_in.get("status") != "ready":
            failure_trace = _record_round_persistence_failure(
                team_id,
                meeting_round,
                status="blocked",
                failure_code="fan_in_waiting_for_sibling_reviews",
                reason=(
                    "review fan-in is not ready; the HypothesisRound is "
                    "regenerated automatically when every sibling review closes"
                ),
                fan_in=fan_in,
                round_index=(
                    int(fan_in.get("roundIndex") or 1)
                    if fan_in.get("roundIndex") is not None
                    else None
                ),
                retry_hint=(
                    "close the pending sibling review meetings; the last "
                    "sibling close regenerates the round automatically"
                ),
                context={
                    "missingCandidateIds": list(fan_in.get("missingCandidateIds") or []),
                    "pendingMeetingRoundIds": list(
                        fan_in.get("pendingMeetingRoundIds") or []
                    ),
                    "supersededCandidateIds": list(
                        fan_in.get("supersededCandidateIds") or []
                    ),
                    "supersededMeetingRoundIds": list(
                        fan_in.get("supersededMeetingRoundIds") or []
                    ),
                    "closedMeetingRoundIds": list(
                        fan_in.get("closedMeetingRoundIds") or []
                    ),
                },
            )
            if failure_trace:
                fan_in = {
                    **fan_in,
                    **{key: value for key, value in failure_trace.items() if value},
                }
            return fan_in
        bound_meetings = [
            dict(item)
            for item in list(fan_in.get("meetings") or [])
            if isinstance(item, Mapping)
        ]
        if not bound_meetings:
            raise HypothesisFirstChainError("review fan-in resolved no meetings")
        primary_meeting = bound_meetings[0]
        meeting_round_ids = [
            str(item.get("meetingRoundId") or "").strip() for item in bound_meetings
        ]
        meeting_round_id = meeting_round_ids[0]
        selection_id = str(fan_in.get("selectionId") or "").strip()
        if not selection_id:
            raise HypothesisFirstChainError(
                "meeting carries no hypothesis_selection ref"
            )
        selection = selections.get_hypothesis_selection(team_id, selection_id)[
            "selection"
        ]
        for bound_meeting in bound_meetings:
            if str(selection.get("scopeHash") or "") != str(
                bound_meeting.get("scopeHash") or ""
            ) or str(selection.get("questionId") or "").upper() != str(
                bound_meeting.get("question") or ""
            ).upper():
                raise HypothesisFirstChainError(
                    "selection scope/question does not match the meeting scope"
                )
        workflow_run_ids = {
            str((item.get("discussionScope") or {}).get("workflowRunId") or "").strip()
            for item in bound_meetings
            if isinstance(item.get("discussionScope"), Mapping)
            and str((item.get("discussionScope") or {}).get("workflowRunId") or "").strip()
        }
        if len(workflow_run_ids) > 1:
            raise HypothesisFirstChainError(
                "fan-in meetings belong to different workflow runs"
            )
        selected_candidate_ids = _normalized_str_list(
            selection.get("selectedCandidateIds")
        )
        if not selected_candidate_ids:
            raise HypothesisFirstChainError("selection has no selected candidates")
        # Candidate-scoped follow-up meetings may review only the hypothesis
        # that requested new evidence.  The generated HypothesisRound remains
        # a selection-level comparison, so its candidate authority must stay
        # the full ordered selection while meetingRefs preserve exactly which
        # scoped discussions supplied this round's evidence.
        candidates = _build_round_candidates(
            team_id,
            primary_meeting,
            candidate_ids=selected_candidate_ids,
        )
        round_index = int(fan_in.get("roundIndex") or 1)
        round_payload: dict[str, Any] = {"candidates": candidates}
        if len(meeting_round_ids) > 1:
            # Content-addressed group identity: the same ordered meeting set
            # reuses one round on replay, while a different authoritative
            # fan-in (for example the round-1 group resolving a superseded
            # candidate to its reopened round-2 meeting) never collides with
            # a candidate-scoped round generated from a subset.
            group_round_id = (
                f"hround-{_stable_hash({'selectionId': selection_id, 'roundIndex': round_index, 'meetingRoundIds': meeting_round_ids, 'scopeHash': selection.get('scopeHash')})[:12]}"
            )
            round_payload.update(
                {
                    "meetingRoundIds": meeting_round_ids,
                    "roundId": group_round_id,
                }
            )
            round_id = group_round_id
        result = hypothesis_rounds.generate_hypothesis_round_from_meeting(
            team_id,
            meeting_round_id,
            round_payload,
            reflection_runner=reflection_runner,
            pairwise_runner=pairwise_runner,
            pareto_runner=pareto_runner,
            metareview_runner=metareview_runner,
            revision_runner=revision_runner,
        )
        round_record = result.get("round") if isinstance(result.get("round"), Mapping) else {}
        receipt_authority = (
            dict(primary_meeting.get("modelInvocationReceiptAuthority"))
            if isinstance(primary_meeting.get("modelInvocationReceiptAuthority"), Mapping)
            else None
        )
        workflow_run_id = str(
            (receipt_authority or {}).get("workflowRunId")
            or primary_meeting.get("workflowRunId")
            or ""
        ).strip()
        node_run_id = str(
            primary_meeting.get("nodeRunId")
            or (receipt_authority or {}).get("nodeRunId")
            or ""
        ).strip()
        revision_receipt_ref = str(
            (
                round_record.get("revisionEnvelope")
                if isinstance(round_record.get("revisionEnvelope"), Mapping)
                else {}
            ).get("revisionReceiptRef")
            or ""
        ).strip()
        if revision_receipt_ref:
            revision_receipt = next(
                (
                    item
                    for item in list(
                        round_record.get("modelInvocationReceipts") or []
                    )
                    if isinstance(item, Mapping)
                    and str(item.get("receiptId") or "").strip()
                    == revision_receipt_ref
                ),
                None,
            )
            if isinstance(revision_receipt, Mapping):
                node_run_id = str(
                    revision_receipt.get("nodeRunId") or node_run_id
                ).strip()
        source_collection_run_id = str(
            (receipt_authority or {}).get("sourceCollectionRunId")
            or primary_meeting.get("sourceCollectionRunId")
            or hypothesis_review_executor._source_collection_run_id_for_formal_workflow(
                workflow_run_id
            )
            or workflow_run_id
        ).strip()
        # The HypothesisRound preserves the independent 5+2 score projection
        # and explicit audit-seven rows.  Each canonical authority is written
        # from the same immutable round; neither is derived from the other.
        dimension_reviews_authority: dict[str, Any]
        try:
            from core.web.services.team_workflow.research_runtime.dimension_reviews_artifact_writer import (
                materialize_dimension_reviews_authority,
            )

            input_refs = [
                *[
                    ref
                    for bound_meeting in bound_meetings
                    for ref in _normalized_str_list(bound_meeting.get("inputArtifactRefs"))
                ],
                *[
                    ref
                    for bound_meeting in bound_meetings
                    for ref in _normalized_str_list(bound_meeting.get("discussionItemRefs"))
                ],
            ]
            input_snapshot_hash = str(
                primary_meeting.get("inputSnapshotHash")
                or round_record.get("inputSnapshotHash")
                or (receipt_authority or {}).get("inputSnapshotHash")
                or ""
            ).strip()
            dimension_reviews_authority = materialize_dimension_reviews_authority(
                team_id=team_id,
                workflow_run_id=workflow_run_id,
                node_run_id=node_run_id,
                question_id=str(primary_meeting.get("question") or ""),
                selection_id=selection_id,
                review_round_id=str(round_record.get("roundId") or ""),
                input_refs=input_refs,
                input_snapshot_hash=input_snapshot_hash,
                candidates=candidates,
                review=round_record,
                workflow_authority=receipt_authority,
                source_collection_run_id=source_collection_run_id,
            )
        except Exception as exc:
            # A closed meeting/round is append-only and remains valid.  A
            # persistence or binding failure must be visible to readiness and
            # never be converted into a fake successful authority.
            dimension_reviews_authority = {
                "status": "blocked",
                "reason": "NEEDS_CONTEXT",
                "blockerCodes": ["dimension_reviews_authority_persistence_failed"],
                "missingAuthorities": ["dimension_reviews"],
                "error": str(exc) or type(exc).__name__,
            }
        review_independence_authority: dict[str, Any]
        try:
            from core.web.services.team_workflow.research_runtime.review_independence_artifact_writer import (
                write_review_independence_artifacts,
            )

            review_independence_authority = write_review_independence_artifacts(
                team_id=team_id,
                workflow_run_id=workflow_run_id,
                node_run_id=node_run_id,
                review_round_id=str(round_record.get("roundId") or ""),
                review=round_record,
                reviewer_assignments=(
                    dict(round_record.get("roles"))
                    if isinstance(round_record.get("roles"), Mapping)
                    else {}
                ),
                receipt_contexts=[
                    dict(item)
                    for item in list(
                        round_record.get("modelInvocationReceipts") or []
                    )
                    if isinstance(item, Mapping)
                ],
                source_collection_run_id=source_collection_run_id,
            )
        except Exception as exc:  # noqa: BLE001 - persist failure becomes a blocker
            review_independence_authority = {
                "status": "blocked",
                "reason": "NEEDS_CONTEXT",
                "blockerCodes": ["review_independence_authority_persistence_failed"],
                "missingAuthorities": [
                    "review_independence",
                    "review_disagreement",
                ],
                "error": str(exc) or type(exc).__name__,
            }
        try:
            feedback_iterations_authority = (
                _materialize_hypothesis_revision_authority(
                    team_id=team_id,
                    workflow_run_id=workflow_run_id,
                    node_run_id=node_run_id,
                    question_id=str(primary_meeting.get("question") or ""),
                    source_collection_run_id=source_collection_run_id,
                    round_record=round_record,
                )
            )
        except Exception as exc:  # noqa: BLE001 - authority stays fail-closed
            feedback_iterations_authority = {
                **_blocked_round_authority(
                    "feedback_iterations",
                    "hypothesis_revision_authority_persistence_failed",
                ),
                "error": str(exc) or type(exc).__name__,
            }
        try:
            stage_one_plan_authority = _materialize_stage_one_plan_authority(
                team_id=team_id,
                workflow_run_id=workflow_run_id,
                node_run_id=node_run_id,
                question_id=str(primary_meeting.get("question") or ""),
                source_collection_run_id=source_collection_run_id,
                round_record=round_record,
            )
        except Exception as exc:  # noqa: BLE001 - authority stays fail-closed
            stage_one_plan_authority = {
                **_blocked_round_authority(
                    "stage1_research_plan",
                    "stage_one_plan_authority_persistence_failed",
                ),
                "missingAuthorities": [
                    "stage1_research_plan",
                    "competition_alignment",
                ],
                "error": str(exc) or type(exc).__name__,
            }
        generation_result: dict[str, Any] = {
            "status": str(result.get("status") or ""),
            "roundId": str(round_record.get("roundId") or ""),
            "round": dict(round_record),
            "closed": True,
            "dimensionReviewsAuthority": dimension_reviews_authority,
            "reviewIndependenceAuthority": review_independence_authority,
            "feedbackIterationsAuthority": feedback_iterations_authority,
            "stageOnePlanAuthority": stage_one_plan_authority,
        }
        # Bookkeeping backfill: mark any open failure traces this successful
        # generation resolves.  The rounds ledger is untouched either way;
        # a resolution error must never turn a generated round into a failure.
        try:
            hypothesis_rounds.resolve_hypothesis_round_failures(
                team_id,
                resolved_by_round_id=str(round_record.get("roundId") or ""),
                round_id=str(round_record.get("roundId") or ""),
                selection_id=selection_id,
                round_index=round_index,
                meeting_round_ids=meeting_round_ids,
            )
        except Exception as exc:  # noqa: BLE001 - bookkeeping stays non-fatal
            generation_result["failureResolutionError"] = (
                str(exc) or type(exc).__name__
            )
        return generation_result
    except Exception as exc:  # closure fact stays; report the side effect
        from core.web.services.team_workflow import (
            hypothesis_rounds as _hypothesis_rounds_service,
        )

        if isinstance(
            exc,
            _hypothesis_rounds_service.ResearchHypothesisRoundGenerationInProgressError,
        ):
            # Pre-generation dedup: another trigger is already generating the
            # same content-addressed round id.  No review budget was spent by
            # this attempt, so report a structured wait/reuse rejection —
            # never a failure trace (that would be a ghost record) and never
            # a faked success.  A later replay (or the winning trigger itself)
            # lands the round under the same round id and replays reuse it.
            rejection: dict[str, Any] = {
                "status": "generation_in_progress",
                "roundId": str(getattr(exc, "round_id", "") or "") or round_id,
                "selectionId": selection_id,
                "meetingRoundIds": meeting_round_ids,
                "error": str(exc),
                "errorType": type(exc).__name__,
                "retryHint": (
                    "a concurrent trigger is generating the same hypothesis "
                    "round; wait for it to finish — replaying "
                    "close_review_meeting or regenerate_hypothesis_round then "
                    "reuses the stored round without new review calls"
                ),
            }
            return rejection
        failure_trace = _record_round_persistence_failure(
            team_id,
            meeting_round,
            status="failed",
            failure_code=_classify_round_failure(exc),
            reason=str(exc) or type(exc).__name__,
            error_type=type(exc).__name__,
            fan_in=fan_in,
            round_id=round_id,
            selection_id=selection_id,
            round_index=round_index,
            meeting_round_ids=meeting_round_ids,
            retry_hint=(
                "after the failure cause is resolved, rerun through "
                "regenerate_hypothesis_round(team_id, meeting_round_id); "
                "replaying close_review_meeting with the original closure "
                "payload regenerates the round as well"
            ),
        )
        reported: dict[str, Any] = {
            "status": "failed",
            "error": str(exc),
            "errorType": type(exc).__name__,
        }
        if failure_trace:
            reported.update(
                {key: value for key, value in failure_trace.items() if value}
            )
        return reported


def _update_collection_request(
    team_id: str, request_id: str, **fields: Any
) -> dict[str, Any]:
    with _LOCK:
        records = _read_jsonl(_storage_path(team_id))
        latest = _latest_by_id(
            [item for item in records if item.get("recordKind") == COLLECTION_REQUEST_KIND],
            "requestId",
            request_id,
        )
        if latest is None:
            raise HypothesisFirstChainNotFoundError(
                f"Collection request {request_id} not found."
            )
        updated = {**latest, **fields}
        _append_jsonl(_storage_path(team_id), updated)
        return updated


def _bounded_evidence_gap_payload(marker: Mapping[str, Any]) -> dict[str, Any]:
    """Bounded projection of a circuit gap marker onto chain records.

    Only the audit-relevant fields survive; the raw marker (with full attempt
    envelopes) stays authoritative in the circuit ledger.
    """
    summary = (
        marker.get("unavailableReasonsSummary")
        if isinstance(marker.get("unavailableReasonsSummary"), Mapping)
        else {}
    )
    try:
        rewrite_count = int(marker.get("rewriteAttemptCount") or 0)
    except (TypeError, ValueError):
        rewrite_count = 0
    return {
        "status": EVIDENCE_GAP_STATUS,
        "markerId": str(marker.get("markerId") or "")[:80],
        "goalKey": str(marker.get("goalKey") or "")[:64],
        "question": str(marker.get("question") or "")[:200],
        "summary": str(summary.get("summary") or "")[:600],
        "markedAt": str(marker.get("markedAt") or "")[:40],
        "rewriteAttemptCount": max(0, rewrite_count),
    }


def _resolve_request_evidence_gap(
    team_id: str,
    request_id: str,
    marker: Mapping[str, Any],
) -> dict[str, Any]:
    """Mark one collection request gap-resolved and open the next review round.

    Stop-dispatch alone would deadlock the loop: the next round normally opens
    through the collection-run handoff.  A gap-resolved request therefore
    reuses the idempotent handoff machinery with an
    ``evidence_gap:<markerId>`` handoffRef — no child run, no provider calls,
    but the next round opens and carries the gap notice in its bounded agenda
    so the review can converge with gaps instead of re-requesting.
    """
    gap_payload = _bounded_evidence_gap_payload(marker)
    updated = _update_collection_request(
        team_id,
        request_id,
        status=EVIDENCE_GAP_STATUS,
        collectionRunStatus=EVIDENCE_GAP_STATUS,
        startError={},
        evidenceGap=gap_payload,
    )
    _record_scene_event(
        "collection_request.evidence_gap_unavailable",
        outcome="recorded",
        fields={
            "teamId": team_id,
            "requestId": str(request_id)[:80],
            "markerId": gap_payload["markerId"],
            "goalKey": gap_payload["goalKey"],
        },
    )
    next_meeting: dict[str, Any] = {}
    handoff_error: dict[str, Any] = {}
    try:
        handoff = record_collection_handoff(
            team_id,
            request_id,
            handoff_ref=f"evidence_gap:{gap_payload['markerId']}",
        )
        next_meeting = (
            dict(handoff.get("nextMeeting"))
            if isinstance(handoff.get("nextMeeting"), Mapping)
            else {}
        )
    except Exception as exc:  # noqa: BLE001 - gap fact stays durable and retryable
        handoff_error = {
            "code": "gap_handoff_failed",
            "message": str(exc) or type(exc).__name__,
        }
    resolved = {
        "status": EVIDENCE_GAP_STATUS,
        "request": updated,
        "evidenceGap": gap_payload,
        "nextMeeting": next_meeting,
    }
    if handoff_error:
        resolved["request"] = {**updated, "handoffError": handoff_error}
        resolved["handoffError"] = handoff_error
    return resolved


def _collection_request_gap_notice(
    team_id: str, request_id: str
) -> list[dict[str, str]]:
    """Bounded gap-notice agenda entries carried by a gap-resolved request.

    Read at next-round opening time so the reviewers who would re-issue the
    same evidence request see the unavailability verdict with its reason
    summary.  Side-channel only: nothing here participates in meeting or
    context identity hashes.
    """
    normalized_request_id = str(request_id or "").strip()
    if not normalized_request_id:
        return []
    request = _latest_by_id(
        [
            item
            for item in _records(team_id)
            if item.get("recordKind") == COLLECTION_REQUEST_KIND
        ],
        "requestId",
        normalized_request_id,
    )
    if request is None:
        return []
    gap = (
        request.get("evidenceGap")
        if isinstance(request.get("evidenceGap"), Mapping)
        else {}
    )
    marker_id = str(gap.get("markerId") or "").strip()
    if not marker_id:
        return []
    envelope = (
        request.get("searchEnvelope")
        if isinstance(request.get("searchEnvelope"), Mapping)
        else {}
    )
    keywords = _normalized_str_list(envelope.get("keywords"))[:6]
    summary = str(gap.get("summary") or "").strip()
    agenda_line = (
        f"证据缺口提示：证据请求（{'、'.join(keywords) or '同前轮请求'}）已由检索熔断判定当前不可得"
        f"（marker {marker_id[:24]}）——{summary[:400] or '原因见 marker 审计'}。"
        "评审可基于现有证据带缺口收敛，请勿再次请求同一证据。"
    )
    return [
        {
            "markerId": marker_id[:80],
            "agendaLine": agenda_line[:900],
        }
    ]


def _record_gap_convergence(
    team_id: str,
    meeting_round: Mapping[str, Any],
    gap_manifest: list[dict[str, Any]],
) -> dict[str, Any]:
    """Durable ``hypothesis_gap_convergence`` audit record (idempotent).

    Records that one review round legally converged while its evidence
    requests were all judged unavailable, together with the full gap
    manifest — the auditable "converged with gaps" fact beside the persisted
    close_round decision.
    """
    meeting_round_id = str(meeting_round.get("meetingRoundId") or "")
    marker_ids = [str(item.get("markerId") or "") for item in gap_manifest]
    convergence_id = f"hfgap-{_stable_hash({'meetingRoundId': meeting_round_id, 'markerIds': marker_ids})[:16]}"
    with _LOCK:
        records = _read_jsonl(_storage_path(team_id))
        existing = _latest_by_id(
            [item for item in records if item.get("recordKind") == GAP_CONVERGENCE_KIND],
            "convergenceId",
            convergence_id,
        )
        if existing is not None:
            return existing
        record = {
            "schemaVersion": SCHEMA_VERSION,
            "recordKind": GAP_CONVERGENCE_KIND,
            "convergenceId": convergence_id,
            "teamId": team_id,
            "meetingRoundId": meeting_round_id,
            "questionId": str(meeting_round.get("question") or ""),
            "decision": "close_round",
            "evidenceGaps": [dict(item) for item in gap_manifest],
            "createdAt": _utc_now(),
        }
        _append_jsonl(_storage_path(team_id), record)
    _record_scene_event(
        "hypothesis_review.converged_with_gaps",
        outcome="recorded",
        fields={
            "teamId": team_id,
            "meetingRoundId": meeting_round_id[:80],
            "gapCount": len(gap_manifest),
        },
    )
    return record


def _converge_with_gaps_decision(
    meeting_round: Mapping[str, Any],
    gap_manifest: list[dict[str, Any]],
    *,
    closed_by: str,
    source_refs: list[str],
) -> dict[str, Any]:
    """close_round decision that explicitly records the gap manifest.

    The persisted DecisionRecord keeps only the contract fields, so the gap
    manifest is carried by the rationale text plus ``evidence_gap_marker:``
    evidence refs; the full manifest lives in the dedicated
    ``hypothesis_gap_convergence`` ledger record.
    """
    meeting_round_id = str(meeting_round.get("meetingRoundId") or "")
    marker_ids = "、".join(
        str(item.get("markerId") or "")[:24] for item in gap_manifest[:4]
    )
    evidence_refs = [
        f"evidence_gap_marker:{str(item.get('markerId') or '')[:80]}"
        for item in gap_manifest
        if str(item.get("markerId") or "").strip()
    ]
    fallback_ref = source_refs[:1] if source_refs else [f"meeting_round:{meeting_round_id}"]
    for ref in fallback_ref:
        if ref and ref not in evidence_refs:
            evidence_refs.append(ref)
    return {
        "decision": "close_round",
        "rationale": (
            f"带缺口收敛：本轮 {len(gap_manifest)} 项证据请求均已由检索熔断判定当前不可得"
            f"（marker {marker_ids}），不再合成新的资料搜集；"
            "评审基于现有证据带缺口收敛。"
        ),
        "decidedBy": closed_by,
        "candidateRefs": [
            ref.split(":", 1)[-1]
            for ref in _normalized_str_list(meeting_round.get("discussionItemRefs"))
            if ref.startswith("hypothesis_candidate:")
        ],
        "evidenceRefs": evidence_refs or [f"meeting_round:{meeting_round_id}"],
        "status": "adopted",
    }


def _scope_envelope_for_collection_request(
    request: Mapping[str, Any],
) -> dict[str, str]:
    """Rebuild the validated facade scope from the immutable request fields."""
    identity = {
        field: str(request.get(field) or "").strip() for field in _SCOPE_FIELDS
    }
    agent_id = str(request.get("agentId") or "").strip()
    mode = str(request.get("mode") or "").strip().lower()
    if not all(identity.values()) or not agent_id or not mode:
        raise HypothesisFirstChainError(
            "collection request scope is incomplete and cannot be recovered"
        )
    expected_hash = scope_hash_for(
        **identity,
        agent_id=agent_id,
        mode=mode,
    )
    stored_hash = str(request.get("scopeHash") or "").strip()
    if stored_hash and stored_hash != expected_hash:
        raise HypothesisFirstChainError(
            "collection request scopeHash does not match its scope identity"
        )
    # Older requests did not persist derived locators. They are pure functions
    # of the request identity, so deriving them here preserves the original
    # scope without introducing a second source of truth.
    return {
        **identity,
        "agentId": agent_id,
        "mode": mode,
        "scopeHash": stored_hash or expected_hash,
        "artifactLocator": (
            f"research-artifact://{identity['program']}/{identity['theme']}/"
            f"{identity['campaign']}/{identity['branch']}/{identity['question']}/"
            f"{stored_hash or expected_hash}"
        ),
        "ledgerRoot": (
            f"research-ledger://{identity['program']}/{identity['theme']}/"
            f"{identity['campaign']}/{stored_hash or expected_hash}"
        ),
        "cacheKey": f"scope:{stored_hash or expected_hash}:{identity['branch']}:{agent_id}",
    }


def _recover_collection_request_locked(
    team_id: str,
    request_id: str,
    *,
    reset_auto_retry: bool = True,
) -> dict[str, Any]:
    """Idempotently bind and restart one orphaned hypothesis collection request.

    The request is the durable idempotency key. Existing candidates, selections,
    meetings and review records are never rewritten; only the request's child
    run binding and collection status are appended.
    """
    from core.web.services import team_service
    from core.web.services.team_workflow.source_collection import facade
    from core.web.services.team_workflow.source_collection import search_circuit
    from core.web.services.team_workflow.source_collection import (
        runs as source_collection_runs,
    )

    normalized_team_id = team_service.assert_team_exists(team_id)
    normalized_request_id = str(request_id or "").strip()
    if not normalized_request_id:
        raise HypothesisFirstChainError("Collection request id is required.")
    request = _latest_by_id(
        [
            item
            for item in _records(normalized_team_id)
            if item.get("recordKind") == COLLECTION_REQUEST_KIND
        ],
        "requestId",
        normalized_request_id,
    )
    if request is None:
        raise HypothesisFirstChainNotFoundError(
            f"Collection request {normalized_request_id} not found."
        )
    if str(request.get("status") or "").strip().lower() == "handed_off":
        return {
            "schemaVersion": SCHEMA_VERSION,
            "teamId": normalized_team_id,
            "status": "reused",
            "request": request,
            "reused": True,
        }
    existing_run_id = str(request.get("collectionRunId") or "").strip()
    if (
        str(request.get("status") or "").strip().lower() == "pending"
        and existing_run_id
        and str(request.get("collectionRunStatus") or "").strip().lower()
        in {"starting", "running"}
    ):
        return {
            "schemaVersion": SCHEMA_VERSION,
            "teamId": normalized_team_id,
            "status": "reused",
            "request": request,
            "reused": True,
        }

    scope = _scope_envelope_for_collection_request(request)
    search_envelope = request.get("searchEnvelope") if isinstance(request.get("searchEnvelope"), Mapping) else {}
    requirements = request.get("requirements") if isinstance(request.get("requirements"), Mapping) else {}
    writeback_policy = request.get("writebackPolicy") if isinstance(request.get("writebackPolicy"), Mapping) else {}
    # Retrieval-circuit consumption on the recovery path: an orphaned/failed
    # request whose goal already carries a live gap marker must not re-bind
    # and restart a search.  Resolve it as gap-resolved (same stop-dispatch +
    # next-round-with-gap-notice semantics as the close path).
    recovery_gap_marker = search_circuit.live_evidence_gap_marker_for_goal(
        normalized_team_id, dict(search_envelope)
    )
    if recovery_gap_marker:
        return _resolve_request_evidence_gap(
            normalized_team_id, normalized_request_id, recovery_gap_marker
        )
    workflow_run_id, research_project_id = _recovery_workflow_run_binding(
        normalized_team_id, request
    )
    ensured = facade.research_knowledge_collection_facade(
        action="ensure",
        scope=scope,
        searchEnvelope=search_envelope,
        requirements=requirements,
        writebackPolicy=writeback_policy,
        workflowRunId=workflow_run_id,
        researchProjectId=research_project_id,
        team_id=normalized_team_id,
    )
    locator = ensured.get("locator") if isinstance(ensured.get("locator"), Mapping) else {}
    run_id = str(locator.get("runId") or "").strip()
    if not run_id:
        updated = _update_collection_request(
            normalized_team_id,
            normalized_request_id,
            status="failed",
            collectionRunStatus="failed",
            startError={
                "code": "collection_run_missing",
                "message": "资料搜集子运行未创建，无法启动搜索。",
            },
        )
        return {
            "schemaVersion": SCHEMA_VERSION,
            "teamId": normalized_team_id,
            "status": "collection_recovery",
            "request": updated,
            "reused": False,
        }

    previous_run_id = str(request.get("collectionRunId") or "").strip()
    _record_shadow_knowledge_invocation_for_chain(
        normalized_team_id,
        question_id=str(request.get("questionId") or ""),
        scope_envelope=scope,
        search_envelope=search_envelope,
        requirements=requirements,
        collection_run_id=run_id,
        collection_request_id=normalized_request_id,
        meeting_round_id=str(request.get("meetingRoundId") or ""),
        decision_id=str(request.get("decisionId") or ""),
        legacy_scope_hash=str(request.get("scopeHash") or ""),
    )
    _update_collection_request(
        normalized_team_id,
        normalized_request_id,
        status="pending",
        collectionRunId=run_id,
        collectionRunStatus="starting",
        startError={},
    )
    try:
        source_collection_runs.start_source_collection_search_background(
            normalized_team_id,
            run_id,
            _hypothesis_collection_background_payload(),
        )
    except Exception as exc:  # noqa: BLE001 - request remains visibly retryable
        failed = _update_collection_request(
            normalized_team_id,
            normalized_request_id,
            status="failed",
            collectionRunStatus="failed",
            startError={
                "code": "search_start_failed",
                "message": str(exc) or type(exc).__name__,
            },
        )
        return {
            "schemaVersion": SCHEMA_VERSION,
            "teamId": normalized_team_id,
            "status": "collection_recovery",
            "request": failed,
            "reused": bool(previous_run_id == run_id),
            "error": str(exc),
        }
    updated = _update_collection_request(
        normalized_team_id,
        normalized_request_id,
        status="pending",
        collectionRunStatus="running",
        startError={},
        **({"autoRetry": {}} if reset_auto_retry else {}),
    )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "status": "reused" if previous_run_id == run_id else "recovered",
        "request": updated,
        "reused": bool(previous_run_id == run_id),
    }


def _collection_recovery_lock(team_id: str, request_id: str) -> threading.Lock:
    key = f"{team_id}\x00{request_id}"
    with _LOCK:
        return _RECOVERY_LOCKS.setdefault(key, threading.Lock())


def recover_collection_request(
    team_id: str,
    request_id: str,
    *,
    reset_auto_retry: bool = True,
) -> dict[str, Any]:
    """Serialize recovery for one durable request without holding the ledger lock.

    ``reset_auto_retry=True`` (the human/endpoint default) also clears the
    bounded auto-retry budget so a fresh failure episode can self-heal again;
    the automatic retry path passes ``False`` to keep its attempt counting.
    """
    from core.web.services import team_service

    normalized_team_id = team_service.assert_team_exists(team_id)
    normalized_request_id = str(request_id or "").strip()
    if not normalized_request_id:
        raise HypothesisFirstChainError("Collection request id is required.")
    with _collection_recovery_lock(normalized_team_id, normalized_request_id):
        return _recover_collection_request_locked(
            normalized_team_id,
            normalized_request_id,
            reset_auto_retry=reset_auto_retry,
        )


def clear_evidence_gap_marker(
    team_id: str,
    marker_id: str,
    *,
    reason: str = "",
) -> dict[str, Any]:
    """Operator action: clear one evidence-gap marker by id.

    Clearing lets the same retrieval goal re-enter the search circuit as a
    brand-new request (fresh original run plus rewrite budget) on its next
    evidence request — the sanctioned path after remediations that change
    what is retrievable (for example the quote-anchor abstract-level
    degradation).  There is deliberately no TTL: reopening a dead goal is an
    explicit operator decision, never a silent background restart.  The
    result carries an operator-facing ``retryHint``; markers whose attempts
    retrieved results that never became new records note that the
    quote-anchor remediation may make a retry succeed.
    """
    from core.web.services import team_service
    from core.web.services.team_workflow.source_collection import search_circuit

    normalized_team_id = team_service.assert_team_exists(team_id)
    normalized_marker_id = str(marker_id or "").strip()
    if not normalized_marker_id:
        raise HypothesisFirstChainError("Evidence gap marker id is required.")
    result = search_circuit.clear_evidence_gap_marker(
        normalized_team_id, normalized_marker_id
    )
    error = str(result.get("error") or "").strip()
    if error:
        raise HypothesisFirstChainError(
            f"clearing evidence gap marker {normalized_marker_id} failed: {error}"
        )
    cleared = bool(result.get("cleared"))
    _record_scene_event(
        "evidence_gap_marker.clear",
        outcome="cleared" if cleared else "not_found",
        fields={
            "teamId": normalized_team_id,
            "markerId": normalized_marker_id[:80],
            "reason": str(reason or "")[:200],
        },
    )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "markerId": normalized_marker_id,
        "cleared": cleared,
        "retryHint": str(result.get("retryHint") or ""),
        "marker": dict(result.get("marker") or {}),
        "reason": str(reason or "")[:300],
    }


def stop_collection_request(team_id: str, request_id: str) -> dict[str, Any]:
    """Stop one running child collection and make the request retry/reset safe."""

    from core.web.services import team_service
    from core.web.services.team_workflow.source_collection import runs as source_collection_runs

    normalized_team_id = team_service.assert_team_exists(team_id)
    normalized_request_id = str(request_id or "").strip()
    if not normalized_request_id:
        raise HypothesisFirstChainError("Collection request id is required.")
    request = _latest_by_id(
        _collection_requests(_records(normalized_team_id)),
        "requestId",
        normalized_request_id,
    )
    if request is None:
        raise HypothesisFirstChainNotFoundError(
            f"Collection request {normalized_request_id} not found."
        )
    run_id = str(request.get("collectionRunId") or "").strip()
    if not run_id:
        updated = _update_collection_request(
            normalized_team_id,
            normalized_request_id,
            status="failed",
            collectionRunStatus="cancelled",
            stopReason="missing_collection_run",
        )
        return {"status": "stopped", "request": updated, "run": {}}
    stopped = source_collection_runs.stop_source_collection_search(
        normalized_team_id,
        run_id,
    )
    updated = _update_collection_request(
        normalized_team_id,
        normalized_request_id,
        status="failed",
        collectionRunStatus="cancelled",
        stoppedAt=_utc_now(),
        stopReason="operator_stopped",
    )
    return {"status": "stopped", "request": updated, "run": stopped}


def _requests_for_collection_run(
    team_id: str, collection_run_id: str
) -> list[dict[str, Any]]:
    run_id = str(collection_run_id or "").strip()
    if not run_id:
        return []
    return [
        record
        for record in _collection_requests(_records(team_id))
        if str(record.get("collectionRunId") or "") == run_id
    ]


def _merge_evidence_requests(
    requests: list[Mapping[str, Any]],
    *,
    closed_by: str,
    meeting_round_id: str,
) -> dict[str, Any]:
    keywords: list[str] = []
    source_types: list[str] = []
    evidence_levels: list[str] = []
    candidate_refs: list[str] = []
    evidence_refs: list[str] = []
    rationales: list[str] = []
    requirements: dict[str, Any] = {}
    writeback_policy: dict[str, Any] = {}

    def _extend_unique(target: list[str], values: Any) -> None:
        for item in _normalized_str_list(values):
            if item not in target:
                target.append(item)

    for raw in requests:
        envelope = raw.get("searchEnvelope") if isinstance(raw.get("searchEnvelope"), Mapping) else {}
        _extend_unique(keywords, envelope.get("keywords"))
        _extend_unique(source_types, envelope.get("sourceTypes"))
        _extend_unique(evidence_levels, envelope.get("evidenceLevels"))
        _extend_unique(candidate_refs, raw.get("candidateRefs"))
        _extend_unique(evidence_refs, raw.get("evidenceRefs"))
        rationale = str(raw.get("rationale") or "").strip()
        if rationale:
            rationales.append(rationale)
        if isinstance(raw.get("requirements"), Mapping):
            requirements.update(dict(raw.get("requirements") or {}))
        if isinstance(raw.get("writebackPolicy"), Mapping):
            writeback_policy.update(dict(raw.get("writebackPolicy") or {}))
    return {
        "decision": REQUEST_EVIDENCE_DECISION,
        "rationale": "；".join(rationales) or "确认本轮搜集范围",
        "decidedBy": closed_by,
        "candidateRefs": candidate_refs,
        "evidenceRefs": evidence_refs or [f"meeting_round:{meeting_round_id}"],
        "status": "adopted",
        "searchEnvelope": {
            "keywords": keywords,
            "sourceTypes": source_types,
            "evidenceLevels": evidence_levels,
        },
        "requirements": requirements,
        "writebackPolicy": writeback_policy,
    }


def approve_meeting_digest(
    team_id: str,
    meeting_round_id: str,
    *,
    closed_by: str,
    expected_digest_content_hash: str,
    runtime: Any = None,
) -> dict[str, Any]:
    """Confirm the current digest draft and apply generation/review side effects."""

    from core.web.services import team_service
    from core.web.services.team_workflow import meeting_rounds, meeting_runtime

    normalized_team_id = team_service.assert_team_exists(team_id)
    normalized_round_id = str(meeting_round_id or "").strip()
    if not normalized_round_id:
        raise HypothesisFirstChainError("Meeting round id is required.")
    closed_by_id = str(closed_by or "").strip()
    if not closed_by_id:
        raise HypothesisFirstChainError("closedBy is required.")
    expected_hash = str(expected_digest_content_hash or "").strip()
    if not expected_hash:
        raise HypothesisFirstChainError("expectedDigestContentHash is required.")
    meeting_round = meeting_rounds.get_meeting_round(normalized_team_id, normalized_round_id)[
        "meetingRound"
    ]
    draft = (
        dict(meeting_round.get("digestDraft"))
        if isinstance(meeting_round.get("digestDraft"), Mapping)
        else {}
    )
    actual_hash = str(draft.get("contentHash") or "").strip()
    if not draft or str(meeting_round.get("status") or "") != "awaiting_approval":
        raise HypothesisFirstChainError(
            "approve-digest requires a meeting in awaiting_approval with a digest draft"
        )
    if actual_hash != expected_hash:
        raise StaleDigestError(
            "digest content hash is stale; reload the draft and confirm again",
            expected=expected_hash,
            actual=actual_hash,
        )
    meeting_type = str(meeting_round.get("meetingType") or "")
    if meeting_type == CANDIDATE_GENERATION_MEETING_TYPE:
        return _close_generation_meeting(
            normalized_team_id,
            meeting_round,
            {"closedBy": closed_by_id, "decisions": []},
        )
    if meeting_type != HYPOTHESIS_REVIEW_MEETING_TYPE:
        raise HypothesisFirstChainError(
            "approve-digest only handles hypothesis review or candidate generation meetings"
        )
    source_refs = _normalized_str_list(draft.get("sourceMessageRefs"))
    raw_requests = [
        item for item in list(draft.get("evidenceRequests") or []) if isinstance(item, Mapping)
    ]
    validation_errors = [
        dict(item)
        for item in list(draft.get("validationErrors") or [])
        if isinstance(item, Mapping)
    ]
    valid_requests: list[dict[str, Any]] = []
    for raw in raw_requests:
        normalized, errors = meeting_runtime.validate_evidence_request_draft(
            raw, meeting_round, source_refs=source_refs
        )
        validation_errors.extend(errors)
        if normalized is not None:
            valid_requests.append(normalized)
    attempted = bool(raw_requests) or bool(draft.get("validationErrors"))
    if attempted and not valid_requests:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "teamId": normalized_team_id,
            "status": "awaiting_approval",
            "closed": False,
            "meetingRound": meeting_round,
            "digestDraft": draft,
            "validationErrors": validation_errors,
        }
    if valid_requests:
        from core.web.services.team_workflow.source_collection import search_circuit

        # Gap-aware close semantics: requests whose goal already carries a
        # live evidence_gap_unavailable marker are "already satisfied by a
        # verdict", not outstanding.  As long as at least one open request
        # remains, the legacy merge runs unchanged; when EVERY requested
        # piece of evidence is already judged unavailable, the round legally
        # converges with gaps instead of synthesizing another dead
        # request_new_evidence decision.
        open_requests: list[Mapping[str, Any]] = []
        gap_requests: list[tuple[Mapping[str, Any], dict[str, Any]]] = []
        for normalized_request in valid_requests:
            request_envelope = (
                normalized_request.get("searchEnvelope")
                if isinstance(normalized_request.get("searchEnvelope"), Mapping)
                else {}
            )
            marker = search_circuit.live_evidence_gap_marker_for_goal(
                normalized_team_id, dict(request_envelope)
            )
            if marker:
                gap_requests.append((normalized_request, marker))
            else:
                open_requests.append(normalized_request)
        if open_requests:
            decisions = [
                _merge_evidence_requests(
                    valid_requests,
                    closed_by=closed_by_id,
                    meeting_round_id=normalized_round_id,
                )
            ]
        else:
            gap_manifest = [
                _bounded_evidence_gap_payload(marker) for _, marker in gap_requests
            ]
            decisions = [
                _converge_with_gaps_decision(
                    meeting_round,
                    gap_manifest,
                    closed_by=closed_by_id,
                    source_refs=source_refs,
                )
            ]
            close_result = close_review_meeting(
                normalized_team_id,
                normalized_round_id,
                {"closedBy": closed_by_id, "decisions": decisions},
                runtime=runtime,
            )
            # Durable "converged with gaps" audit record with the full gap
            # manifest (the persisted decision keeps only rationale + marker
            # refs).  Recorded after the closure settled so it never claims a
            # close that failed; idempotent on replay.
            _record_gap_convergence(
                normalized_team_id, meeting_round, gap_manifest
            )
            return close_result
    else:
        decisions = [
            {
                "decision": "close_round",
                "rationale": "本轮评审确认现有结论，不再启动新的资料搜集",
                "decidedBy": closed_by_id,
                "candidateRefs": [
                    ref.split(":", 1)[-1]
                    for ref in _normalized_str_list(meeting_round.get("discussionItemRefs"))
                    if ref.startswith("hypothesis_candidate:")
                ],
                "evidenceRefs": source_refs[:1] or [f"meeting_round:{normalized_round_id}"],
                "status": "adopted",
            }
        ]
    return close_review_meeting(
        normalized_team_id,
        normalized_round_id,
        {"closedBy": closed_by_id, "decisions": decisions},
        runtime=runtime,
    )


# ---------------------------------------------------------------------------
# failed collection auto-retry (bounded self-healing) and escalation


def _collection_auto_retry_delay_seconds(attempt_count: int) -> float:
    """Backoff before the next automatic recover attempt.

    Exponential from ``SOURCE_COLLECTION_AUTO_RETRY_INITIAL_DELAY_SECONDS``
    with factor 2, capped at ``SOURCE_COLLECTION_AUTO_RETRY_MAX_DELAY_SECONDS``.
    Pure function so tests can pin the schedule.
    """
    index = max(int(attempt_count), 0)
    delay = SOURCE_COLLECTION_AUTO_RETRY_INITIAL_DELAY_SECONDS * (
        SOURCE_COLLECTION_AUTO_RETRY_BACKOFF_FACTOR**index
    )
    return min(delay, SOURCE_COLLECTION_AUTO_RETRY_MAX_DELAY_SECONDS)


def _start_collection_auto_retry_timer(
    delay_seconds: float, callback: Callable[[], None]
) -> threading.Timer:
    """Run the backoff wait on a daemon thread, then invoke ``callback``.

    The terminal notification can arrive on synchronous request paths (the
    source-collection search has a synchronous execute route), so the wait
    must never happen on the caller's thread — same discipline as the
    background search thread's own sleeps.
    """
    timer = threading.Timer(max(float(delay_seconds), 0.0), callback)
    timer.daemon = True
    timer.start()
    return timer


def _failed_collection_run_error_hint(run_id: str) -> str:
    """Best-effort terminal error text from the child run's work-run snapshot.

    Never raises and never blocks the chain: a missing or unreadable snapshot
    degrades to an empty hint (the request's own start/handoff errors remain
    the fallback inside the escalation message).
    """
    normalized_run_id = str(run_id or "").strip()
    if not normalized_run_id:
        return ""
    try:
        from core.runtime_manager import work_run_store as work_run_store_module

        store = work_run_store_module.WorkRunStore(
            root=work_run_store_module.WORK_RUNS_DIR
        )
        snapshot = store.load_snapshot(
            "source_collection_run", normalized_run_id
        )
    except Exception:  # noqa: BLE001 - diagnostics only
        return ""
    if not isinstance(snapshot, Mapping):
        return ""
    message = str(snapshot.get("error") or "").strip()
    if not message:
        message = str(snapshot.get("summary") or "").strip()
    return message[:500]


def _collection_request_error_hint(request: Mapping[str, Any]) -> str:
    """Last error recorded on the request record itself (fallback hint)."""
    for field in ("startError", "handoffError"):
        value = request.get(field)
        if isinstance(value, Mapping):
            message = str(value.get("message") or "").strip()
            if message:
                return message[:500]
    return ""


def _latest_collection_request_locked(team_id: str, request_id: str) -> dict[str, Any] | None:
    with _LOCK:
        return _latest_by_id(
            [
                item
                for item in _read_jsonl(_storage_path(team_id))
                if item.get("recordKind") == COLLECTION_REQUEST_KIND
            ],
            "requestId",
            request_id,
        )


def _merge_collection_auto_retry_state(
    team_id: str, request_id: str, fields: Mapping[str, Any]
) -> dict[str, Any]:
    """Read-modify-write the ``autoRetry`` state block of one request."""
    with _LOCK:
        latest = _latest_collection_request_locked(team_id, request_id)
        if latest is None:
            raise HypothesisFirstChainNotFoundError(
                f"Collection request {request_id} not found."
            )
        state = (
            dict(latest.get("autoRetry"))
            if isinstance(latest.get("autoRetry"), Mapping)
            else {}
        )
        state.update(dict(fields))
        return _update_collection_request(team_id, request_id, autoRetry=state)


def _escalate_collection_auto_retry_exhausted(
    team_id: str,
    request: Mapping[str, Any],
    *,
    auto_retry: Mapping[str, Any],
) -> dict[str, Any]:
    """Emit the anomaly-inbox escalation once the retry budget is spent.

    Same emission pattern as the bounded auto-revision parking: the pure
    ``build_anomaly_inbox`` projector turns the frozen-taxonomy
    ``human_required`` problem into the canonical item, which is persisted on
    the request record (``anomalyEscalation``).  The request itself stays in
    its failed recovery state so the human recover endpoint keeps working
    unchanged.
    """
    request_id = str(request.get("requestId") or "")
    run_id = str(request.get("collectionRunId") or "")
    now = _utc_now()
    attempts = int(auto_retry.get("attemptCount") or 0)
    last_error = str(auto_retry.get("lastError") or "").strip()
    message = (
        f"资料搜集请求 {request_id} 自动重试预算已耗尽"
        f"（{attempts}/{SOURCE_COLLECTION_AUTO_RETRY_MAX_ATTEMPTS} 次），"
        "子运行保持 failed，需要人工恢复。"
    )
    if last_error:
        message += f" 最后错误：{last_error}"
    items: list[dict[str, Any]] = []
    try:
        from core.web.services.team_workflow.research_runtime.anomaly_inbox_service import (
            build_anomaly_inbox,
        )

        inbox = build_anomaly_inbox(
            {
                "teamId": team_id,
                "questionId": str(request.get("questionId") or ""),
                "problems": [
                    {
                        "code": COLLECTION_AUTO_RETRY_TAXONOMY_CODE,
                        "category": "execution",
                        "sourceKind": "collection_request",
                        "sourceId": request_id,
                        "message": message,
                        "detectedAt": (
                            str(auto_retry.get("exhaustedAt") or "").strip() or now
                        ),
                    }
                ],
            },
            generated_at=now,
        )
        items = [item.to_dict() for item in inbox.items]
    except Exception:  # noqa: BLE001 - escalation must not depend on the projector
        items = []
    escalation = {
        "status": "emitted" if items else "unavailable",
        "taxonomyCode": COLLECTION_AUTO_RETRY_TAXONOMY_CODE,
        "requestId": request_id,
        "collectionRunId": run_id,
        "attempts": attempts,
        "lastError": last_error,
        "emittedAt": now,
        "items": items,
    }
    _record_scene_event(
        "collection_auto_retry_exhausted",
        outcome="escalated" if items else "projector_unavailable",
        level="warning",
        fields={
            "requestId": request_id,
            "collectionRunId": run_id,
            "attempts": attempts,
            "anomalyItemCount": len(items),
        },
    )
    try:
        _update_collection_request(team_id, request_id, anomalyEscalation=escalation)
    except Exception:  # noqa: BLE001 - the exhausted marker is already durable
        pass
    return {"phase": "exhausted", "escalation": escalation}


def _claim_collection_auto_retry(
    team_id: str,
    request_id: str,
    *,
    run_id: str = "",
) -> dict[str, Any] | None:
    """Claim one ``failed`` terminal event for a bounded automatic recover.

    Compare-and-set under the ledger lock so a replayed terminal notification
    never schedules a second attempt: a claim succeeds only when the request's
    ``autoRetry.phase`` is idle or finished for the previous event
    (``""`` / ``dispatched`` / ``dispatch_failed`` / ``superseded``).
    ``backoff`` means the same failure event is already claimed (replay);
    ``exhausted`` means the budget is spent.  When the budget is spent the
    claim parks the request in ``exhausted`` and emits the anomaly-inbox
    escalation exactly once; the request stays ``failed`` and recoverable.
    """
    outcome: tuple[str, dict[str, Any]] | None = None
    with _LOCK:
        latest = _latest_collection_request_locked(team_id, request_id)
        if latest is not None and str(latest.get("status") or "").strip().lower() != "handed_off":
            previous = (
                dict(latest.get("autoRetry"))
                if isinstance(latest.get("autoRetry"), Mapping)
                else {}
            )
            phase = str(previous.get("phase") or "").strip().lower()
            if phase not in {"backoff", "exhausted"}:
                attempt_count = int(previous.get("attemptCount") or 0)
                if (
                    phase == "dispatch_failed"
                    and str(previous.get("lastError") or "").strip()
                ):
                    # The chained claim after a failed dispatch: the freshest
                    # error is the dispatch failure itself, not the run's
                    # stale terminal snapshot.
                    last_error = str(previous.get("lastError") or "").strip()[:500]
                else:
                    last_error = (
                        _failed_collection_run_error_hint(run_id)
                        or _collection_request_error_hint(latest)
                    )
                now = _utc_now()
                if attempt_count >= SOURCE_COLLECTION_AUTO_RETRY_MAX_ATTEMPTS:
                    exhausted = {
                        **previous,
                        "phase": "exhausted",
                        "exhaustedAt": now,
                        "lastError": last_error,
                    }
                    _update_collection_request(
                        team_id, request_id, autoRetry=exhausted
                    )
                    outcome = ("exhausted", exhausted)
                else:
                    delay = _collection_auto_retry_delay_seconds(attempt_count)
                    claimed = {
                        **previous,
                        "phase": "backoff",
                        "attemptCount": attempt_count + 1,
                        "scheduledAt": now,
                        "nextRetryAt": (
                            datetime.now(timezone.utc) + timedelta(seconds=delay)
                        ).isoformat().replace("+00:00", "Z"),
                        "lastError": last_error,
                    }
                    _update_collection_request(
                        team_id, request_id, autoRetry=claimed
                    )
                    outcome = ("backoff", claimed)
    if outcome is None:
        return None
    kind, state = outcome
    if kind == "backoff":
        delay = _collection_auto_retry_delay_seconds(
            max(int(state.get("attemptCount") or 1) - 1, 0)
        )
        _start_collection_auto_retry_timer(
            delay,
            lambda: _dispatch_collection_auto_retry(
                team_id, request_id, run_id=run_id
            ),
        )
        return {"phase": "backoff", "autoRetry": state, "delaySeconds": delay}
    escalation = _escalate_collection_auto_retry_exhausted(
        team_id,
        _latest_collection_request_locked(team_id, request_id) or {},
        auto_retry=state,
    )
    return {
        "phase": "exhausted",
        "autoRetry": state,
        "escalation": escalation["escalation"],
    }


def _dispatch_collection_auto_retry(team_id: str, request_id: str, *, run_id: str = "") -> None:
    """Timer callback: run one claimed automatic recover attempt.

    Skips when the claim was superseded (a human already recovered, stopped or
    handed off the request).  The recover call is the same in-process
    implementation the recover endpoint uses; ``reset_auto_retry=False``
    keeps the attempt budget.  A failed dispatch consumes the attempt and
    chains the next claim so the budget still terminates in an escalation.
    """
    try:
        with _LOCK:
            latest = _latest_collection_request_locked(team_id, request_id)
            if latest is None:
                return
            state = (
                dict(latest.get("autoRetry"))
                if isinstance(latest.get("autoRetry"), Mapping)
                else {}
            )
            if str(state.get("phase") or "").strip().lower() != "backoff":
                return  # superseded: a human already moved the request
        result = recover_collection_request(
            team_id, request_id, reset_auto_retry=False
        )
        # ``reused`` covers both the idempotent same-run rebind (a normal
        # restart) and the nothing-to-do early returns; the restarted run is
        # recognised by its ``running`` collection status.
        recovered_request = (
            result.get("request") if isinstance(result.get("request"), Mapping) else {}
        )
        restarted = (
            str(recovered_request.get("collectionRunStatus") or "").strip().lower()
            == "running"
        )
        phase = "dispatched" if restarted else "superseded"
        _merge_collection_auto_retry_state(
            team_id,
            request_id,
            {"phase": phase, "lastAttemptAt": _utc_now()},
        )
        _record_scene_event(
            "collection_auto_retry_dispatched",
            outcome="ok",
            fields={
                "requestId": request_id,
                "collectionRunId": run_id,
                "recoverStatus": str(result.get("status") or ""),
                "restarted": restarted,
            },
        )
    except Exception as exc:  # noqa: BLE001 - request stays visibly failed/retryable
        try:
            _merge_collection_auto_retry_state(
                team_id,
                request_id,
                {
                    "phase": "dispatch_failed",
                    "lastAttemptAt": _utc_now(),
                    "lastError": str(exc)[:500],
                },
            )
        except Exception:  # noqa: BLE001 - never mask the dispatch error
            pass
        _record_scene_event(
            "collection_auto_retry_dispatch_failed",
            outcome="error",
            level="warning",
            fields={"requestId": request_id, "error": str(exc)[:500]},
        )
        # The attempt never reached the run: consume the next budget slot so
        # persistent recover failures still terminate in the escalation
        # instead of stopping silently.
        try:
            _claim_collection_auto_retry(team_id, request_id, run_id=run_id)
        except Exception:  # noqa: BLE001
            pass


def notify_collection_run_terminal(
    team_id: str,
    collection_run_id: str,
    terminal_status: str,
) -> dict[str, Any]:
    """Bridge a source-collection terminal status into the hypothesis-first chain.

    Must be called outside workflow/ledger writer locks. Only ``completed``
    handoffs; ``failed`` / ``needs_continue`` stay in collection recovery.
    """
    from core.web.services import team_service

    normalized_team_id = team_service.assert_team_exists(team_id)
    run_id = str(collection_run_id or "").strip()
    status = str(terminal_status or "").strip().lower()
    if not run_id:
        return {"status": "ignored", "reason": "missing_collection_run_id"}
    requests = _requests_for_collection_run(normalized_team_id, run_id)
    if not requests:
        return {"status": "ignored", "reason": "no_bound_request"}
    if status in {"failed", "needs_continue", "cancelled"}:
        updated = [
            _update_collection_request(
                normalized_team_id,
                str(record.get("requestId") or ""),
                **({"status": "failed"} if status == "cancelled" else {}),
                collectionRunStatus=status,
            )
            for record in requests
        ]
        result: dict[str, Any] = {
            "status": "collection_recovery",
            "requests": updated,
            "request": updated[-1] if updated else {},
        }
        if status == "failed":
            # Bounded self-healing: only ``failed`` schedules the automatic
            # recover chain; ``needs_continue`` stays fatal (retry taxonomy
            # P0: never auto-reconciled) and ``cancelled`` is a verdict.
            escalations: list[dict[str, Any]] = []
            for record in requests:
                request_id = str(record.get("requestId") or "").strip()
                if not request_id:
                    continue
                outcome = _claim_collection_auto_retry(
                    normalized_team_id,
                    request_id,
                    run_id=run_id,
                )
                if outcome and outcome.get("phase") == "exhausted":
                    escalations.append(outcome)
            if escalations:
                result["autoRetryEscalations"] = escalations
        return result
    if status != "completed":
        return {"status": "ignored", "reason": "non_completed"}
    last: dict[str, Any] = {"status": "ignored"}
    for record in requests:
        if str(record.get("collectionRunStatus") or "").strip().lower() == "cancelled":
            last = {"status": "ignored", "reason": "collection_run_cancelled"}
            continue
        request_id = str(record.get("requestId") or "")
        if not request_id:
            continue
        if str(record.get("status") or "") == "handed_off":
            last = record_collection_handoff(
                normalized_team_id,
                request_id,
                handoff_ref=str(record.get("handoffRef") or f"source_collection_run:{run_id}"),
            )
            last["status"] = "reused"
            continue
        try:
            last = record_collection_handoff(
                normalized_team_id,
                request_id,
                handoff_ref=f"source_collection_run:{run_id}",
            )
            _update_collection_request(
                normalized_team_id,
                request_id,
                collectionRunStatus="completed",
                handoffError={},
            )
            last["request"] = {
                **dict(last.get("request") or {}),
                "collectionRunStatus": "completed",
                "handoffError": {},
            }
        except Exception as exc:
            updated = _update_collection_request(
                normalized_team_id,
                request_id,
                status="handoff_pending",
                collectionRunStatus="completed",
                handoffError={
                    "code": "handoff_failed",
                    "message": str(exc),
                },
            )
            last = {
                "schemaVersion": SCHEMA_VERSION,
                "teamId": normalized_team_id,
                "status": "handoff_pending",
                "request": updated,
                "error": str(exc),
            }
    return last


def _resolve_review_runners(
    meeting_round: Mapping[str, Any],
    meeting_round_id: str,
    meeting_type: str,
    *,
    reflection_runner: Any = None,
    pairwise_runner: Any = None,
    pareto_runner: Any = None,
    metareview_runner: Any = None,
    revision_runner: Any = None,
) -> dict[str, Any]:
    """Resolve the review runners for one meeting (shared close/regenerate).

    When no runner is injected the operator-configured LLM is tried first;
    with no model configured dev/platform scopes fall back to the
    deterministic DEV fixtures.  The meeting's server-owned scope mode is
    the explicit execution fence: a ``mode=formal`` review meeting must
    never slide onto fixture output, so without real receipt-bound runners
    this raises the structured fence error and the caller fails fast.
    """
    if all(
        runner is None
        for runner in (
            reflection_runner,
            pairwise_runner,
            pareto_runner,
            metareview_runner,
            revision_runner,
        )
    ):
        from core.web.services.team_workflow.llm_review_runners import (
            build_hypothesis_review_runners,
        )

        formal_meeting = (
            str(meeting_round.get("mode") or "").strip().lower()
            == HYPOTHESIS_REVIEW_FORMAL_MODE
        )
        real_runners = build_hypothesis_review_runners(
            require_provider_receipts=formal_meeting
        )
        if real_runners:
            return dict(real_runners)
        if formal_meeting and meeting_type == HYPOTHESIS_REVIEW_MEETING_TYPE:
            # Formal fence (fail closed): a formal review meeting must never
            # slide into the deterministic DEV fixtures.  Candidate-generation
            # closures and dev/platform scopes do not consume review runners
            # and keep their previous behaviour.
            raise HypothesisFirstChainError(
                f"Formal review meeting {meeting_round_id} cannot close: "
                "no real receipt-bound review runners resolved from the "
                "Challenge Cup evaluator LLM (see review_llm.resolve."
                "unavailable diagnostics for the missing configuration). "
                "Configure the evaluator agent model and provider "
                "credentials, or close this meeting in a dev/platform scope."
            )
    return {
        "reflection_runner": reflection_runner,
        "pairwise_runner": pairwise_runner,
        "pareto_runner": pareto_runner,
        "metareview_runner": metareview_runner,
        "revision_runner": revision_runner,
    }


def regenerate_hypothesis_round(
    team_id: str,
    meeting_round_id: str,
    *,
    reflection_runner: Any = None,
    pairwise_runner: Any = None,
    pareto_runner: Any = None,
    metareview_runner: Any = None,
    revision_runner: Any = None,
) -> dict[str, Any]:
    """Re-run selection-level HypothesisRound generation for a closed meeting.

    Command-triggered retry path for a persisted round failure trace
    (``hypothesis_round_failures`` ledger): the closed meeting and its
    closure artifacts stay untouched append-only facts; only the fan-in
    projection and the round generation run again.  When generation now
    succeeds, the matching open failure traces are marked resolved; when it
    fails again, a fresh failure trace is appended.  The fan-in
    ``waiting_for_sibling_reviews`` case needs no command: closing the last
    pending sibling review regenerates the round automatically.
    """
    from core.web.services import team_service
    from core.web.services.team_workflow import meeting_rounds

    normalized_team_id = team_service.assert_team_exists(team_id)
    normalized_round_id = str(meeting_round_id or "").strip()
    if not normalized_round_id:
        raise HypothesisFirstChainError("Meeting round id is required.")
    meeting_round = meeting_rounds.get_meeting_round(
        normalized_team_id, normalized_round_id
    )["meetingRound"]
    meeting_type = str(meeting_round.get("meetingType") or "")
    if meeting_type != HYPOTHESIS_REVIEW_MEETING_TYPE:
        raise HypothesisFirstChainError(
            "regenerate_hypothesis_round only handles hypothesis_review rounds."
        )
    if str(meeting_round.get("status") or "").strip().lower() != "closed":
        raise HypothesisFirstChainError(
            f"Review meeting {normalized_round_id} is not closed; close it "
            "before regenerating the hypothesis round."
        )
    resolved_runners = _resolve_review_runners(
        meeting_round,
        normalized_round_id,
        meeting_type,
        reflection_runner=reflection_runner,
        pairwise_runner=pairwise_runner,
        pareto_runner=pareto_runner,
        metareview_runner=metareview_runner,
        revision_runner=revision_runner,
    )
    return _generate_hypothesis_round(
        normalized_team_id,
        meeting_round,
        reflection_runner=resolved_runners["reflection_runner"],
        pairwise_runner=resolved_runners["pairwise_runner"],
        pareto_runner=resolved_runners["pareto_runner"],
        metareview_runner=resolved_runners["metareview_runner"],
        revision_runner=resolved_runners["revision_runner"],
    )


def close_review_meeting(
    team_id: str,
    meeting_round_id: str,
    payload: Mapping[str, Any] | None = None,
    *,
    runtime: Any = None,
    reflection_runner: Any = None,
    pairwise_runner: Any = None,
    pareto_runner: Any = None,
    metareview_runner: Any = None,
    revision_runner: Any = None,
    agent_runner: Any = None,
) -> dict[str, Any]:
    """Approve one hypothesis-review closure, then apply chain effects.

    ``request_new_evidence`` decisions with a valid ``searchEnvelope`` start or
    reuse a stage-1 collection run through the facade; decisions without one
    are reported as skipped and never trigger collection.  A HypothesisRound
    is then generated from the closed meeting through the HF-3 executor
    (idempotent per meeting; failures are reported under ``hypothesisRound``
    without rolling the closure back).  When a runtime is provided the parent
    runs' ``hypothesis_design`` readiness is re-checked outside any writer
    transaction.

    When no review runner is injected the operator-configured LLM is tried
    first; when no model is configured the deterministic DEV fixtures keep
    the previous behaviour for dev/platform scopes.  A ``mode=formal`` review
    meeting is fenced: it must never close onto fixture output, so when no
    real receipt-bound runners resolve the closure fails fast with a
    structured :class:`HypothesisFirstChainError` (the missing configuration
    is named by the ``review_llm.resolve.unavailable`` diagnostics); when
    runners exist but the meeting's server-owned receipt authority is
    missing, the HypothesisRound generation fails closed and is reported
    structurally without rolling the closure back.
    """
    from core.web.services import team_service
    from core.web.services.team_workflow import meeting_rounds

    normalized_team_id = team_service.assert_team_exists(team_id)
    normalized_round_id = str(meeting_round_id or "").strip()
    if not normalized_round_id:
        raise HypothesisFirstChainError("Meeting round id is required.")
    meeting_round = meeting_rounds.get_meeting_round(normalized_team_id, normalized_round_id)[
        "meetingRound"
    ]
    meeting_type = str(meeting_round.get("meetingType") or "")
    # The meeting's server-owned scope mode is the explicit execution fence:
    # formal review meetings require provider-bound receipts from the
    # auto-injected runners; DEV/platform scopes keep the receipt-free path.
    resolved_runners = _resolve_review_runners(
        meeting_round,
        normalized_round_id,
        meeting_type,
        reflection_runner=reflection_runner,
        pairwise_runner=pairwise_runner,
        pareto_runner=pareto_runner,
        metareview_runner=metareview_runner,
        revision_runner=revision_runner,
    )
    reflection_runner = resolved_runners["reflection_runner"]
    pairwise_runner = resolved_runners["pairwise_runner"]
    pareto_runner = resolved_runners["pareto_runner"]
    metareview_runner = resolved_runners["metareview_runner"]
    revision_runner = resolved_runners["revision_runner"]
    request = dict(payload) if isinstance(payload, Mapping) else {}
    if meeting_type == CANDIDATE_GENERATION_MEETING_TYPE:
        return _close_generation_meeting(normalized_team_id, meeting_round, request)
    if meeting_type != HYPOTHESIS_REVIEW_MEETING_TYPE:
        raise HypothesisFirstChainError(
            "close_review_meeting only handles hypothesis_review rounds."
        )
    result = meeting_rounds.approve_meeting_closure(
        normalized_team_id, normalized_round_id, request
    )
    closed_record = result["meetingRound"]
    collection = _process_collection_decisions(
        normalized_team_id, closed_record, result, request
    )
    hypothesis_round = _generate_hypothesis_round(
        normalized_team_id,
        closed_record,
        reflection_runner=reflection_runner,
        pairwise_runner=pairwise_runner,
        pareto_runner=pareto_runner,
        metareview_runner=metareview_runner,
        revision_runner=revision_runner,
    )
    resume = None
    if (
        runtime is not None
        and str(hypothesis_round.get("status") or "")
        != "waiting_for_sibling_reviews"
    ):
        resume = resume_parent_runs(
            normalized_team_id,
            question_id=str(closed_record.get("question") or ""),
            runtime=runtime,
            trigger=f"close:{normalized_round_id}",
        )

    # Shadow decision points after the review closure settled: "meeting_close"
    # (autoCloseMeetingRound) and "converge_question" (autoConvergeQuestion,
    # mirroring the chain_state convergence gates).  Advisory records only —
    # the returned result below is identical with or without shadow policy.
    generated_round = (
        dict(hypothesis_round.get("round"))
        if isinstance(hypothesis_round.get("round"), Mapping)
        else {}
    )
    generated_meta_review = (
        dict(generated_round.get("metaReview"))
        if isinstance(generated_round.get("metaReview"), Mapping)
        else {}
    )
    new_request_count = len(list(collection.get("requests") or []))
    skipped_count = len(list(collection.get("skipped") or []))
    _record_policy_shadow_decisions(
        normalized_team_id,
        closed_record,
        lambda: [
            (
                "meeting_close",
                {
                    "meetingRoundId": normalized_round_id,
                    "meetingType": HYPOTHESIS_REVIEW_MEETING_TYPE,
                    "closureApproved": str(closed_record.get("status") or "") == "closed",
                    "digestConfirmed": bool(list(result.get("decisions") or [])),
                    "decisionsResolved": skipped_count == 0,
                    "unresolvedDecisionCount": skipped_count,
                    "closedBy": str(request.get("closedBy") or "").strip(),
                },
                {
                    "outcome": "review_meeting_closed",
                    "outcomeClass": "acted",
                    "command": "close_review_meeting",
                    "ref": f"meeting_round:{normalized_round_id}",
                },
            ),
            (
                "converge_question",
                {
                    "roundId": str(hypothesis_round.get("roundId") or ""),
                    "latestRoundClosed": str(generated_round.get("status") or "") == "closed",
                    "metaReviewAccepted": generated_meta_review.get("accepted") is True,
                    "newEvidenceRequestCount": new_request_count,
                    "pendingHandoffCount": _pending_handoff_count(
                        normalized_team_id,
                        str(closed_record.get("question") or ""),
                    ),
                },
                {
                    "outcome": (
                        "requested_new_evidence"
                        if new_request_count
                        else "closed_without_new_evidence"
                    ),
                    "outcomeClass": "escalated" if new_request_count else "acted",
                    "command": "close_review_meeting",
                    "ref": f"meeting_round:{normalized_round_id}",
                },
            ),
        ],
    )
    # Active-policy hook (autoConvergeQuestion): gated, audited, quiet.  The
    # executor re-checks the authoritative chain gates (closed round, meta
    # review accepted, no pending handoffs) and always passes through the
    # claim-belief hard gate before recording any adjudication.
    _auto_advance_converge_tick(
        normalized_team_id, str(closed_record.get("question") or "")
    )
    # Budget-exhaustion auto-advance (in-place): when this closure produced a
    # fan-in round at/after the hard limit, adjudicate it accepted and create
    # the formal run without waiting for a human.  Strictly best-effort — the
    # helpers never raise, and this wrapper swallows anything left so the
    # closed fact and the closure result stand regardless.
    auto_adjudication: dict[str, Any] | None = None
    auto_formal_run: dict[str, Any] | None = None
    try:
        auto_adjudication = auto_adjudicate_exhausted_round(
            normalized_team_id,
            question_id=str(closed_record.get("question") or ""),
        )
        if str(auto_adjudication.get("status") or "") in {"created", "reused"}:
            auto_formal_run = auto_create_formal_run_after_convergence(
                normalized_team_id,
                question_id=str(closed_record.get("question") or ""),
            )
    except Exception as exc:  # noqa: BLE001 - closure must never fail on auto-advance
        _record_scene_event(
            "hypothesis_first.auto_advance_failed",
            outcome="failed",
            level="warning",
            fields={
                "teamId": normalized_team_id,
                "meetingRoundId": normalized_round_id,
                "reason": type(exc).__name__,
                "error": str(exc)[:400],
            },
        )
    # The sibling archive gate may have deferred this round's open-next; a
    # first-time archive of the newest logical round's last sibling retries it
    # here.  Replay closures ("reused") never re-trigger, and the gate inside
    # open_next_review_meeting keeps the retry itself idempotent.  Best-effort:
    # the closed fact is append-only, so a failed trigger is reported, never
    # rolled back.
    deferred_next_review = None
    if str(result.get("status") or "") == "created":
        try:
            deferred_next_review = _trigger_deferred_next_review(
                normalized_team_id,
                closed_record,
                agent_runner=agent_runner,
            )
        except Exception as exc:  # noqa: BLE001 - structural report, closure stands
            deferred_next_review = {
                "status": "failed",
                "errorType": type(exc).__name__,
                "error": str(exc)[:400],
            }
            _record_scene_event(
                "hypothesis_first.deferred_next_review_failed",
                outcome="error",
                level="warning",
                fields={
                    "teamId": normalized_team_id,
                    "meetingRoundId": normalized_round_id,
                    "errorType": type(exc).__name__,
                    "error": str(exc)[:400],
                },
            )
    return {
        **result,
        "collection": collection,
        "hypothesisRound": hypothesis_round,
        "deferredNextReview": deferred_next_review,
        "autoAdjudication": auto_adjudication,
        "autoFormalRun": auto_formal_run,
        "resume": resume,
    }


# ---------------------------------------------------------------------------
# handoff -> parent resume + next round


def record_collection_handoff(
    team_id: str,
    request_id: str,
    *,
    handoff_ref: str = "",
    runtime: Any = None,
    agent_runner: Any = None,
    background: bool = True,
    budget: Any = None,
) -> dict[str, Any]:
    """Record one child collection run's knowledge handoff (idempotent).

    Marks the request ``handed_off``, materializes the collected evidence into
    the question-scoped claim ledger (idempotently, before the next round can
    read the claim belief gate), auto-opens the next review meeting
    (budget-gated, sibling-archive gated, lineage-linked), and re-checks the
    parent runs' ``hypothesis_design`` readiness outside any writer
    transaction.

    Replays (an already ``handed_off`` request) re-run the claim
    materialization on purpose: requests handed off before the chain-level
    bridge existed recover their claim rows this way without re-running the
    collection or the review rounds.
    """
    from core.web.services import team_service

    normalized_team_id = team_service.assert_team_exists(team_id)
    normalized_request_id = str(request_id or "").strip()
    if not normalized_request_id:
        raise HypothesisFirstChainError("request_id is required.")
    with _LOCK:
        records = _read_jsonl(_storage_path(normalized_team_id))
        latest = _latest_by_id(
            [item for item in records if item.get("recordKind") == COLLECTION_REQUEST_KIND],
            "requestId",
            normalized_request_id,
        )
        if latest is None:
            raise HypothesisFirstChainNotFoundError(
                f"Collection request {normalized_request_id} not found."
            )
        reused = str(latest.get("status") or "") == "handed_off"
        if not reused:
            latest = {
                **latest,
                "status": "handed_off",
                "handedOffAt": _utc_now(),
                "handoffRef": str(handoff_ref or "").strip(),
            }
            _append_jsonl(_storage_path(normalized_team_id), latest)
    claim_materialization = _materialize_request_collection_claims(
        normalized_team_id, latest
    )
    next_meeting = _handoff_next_review_meeting(
        normalized_team_id,
        latest,
        agent_runner=agent_runner,
        background=background,
        budget=budget,
    )
    resume = None
    if runtime is not None:
        resume = resume_parent_runs(
            normalized_team_id,
            question_id=str(latest.get("questionId") or ""),
            runtime=runtime,
            trigger=f"handoff:{normalized_request_id}",
        )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "status": "reused" if reused else "handed_off",
        "request": latest,
        "claimMaterialization": claim_materialization,
        "nextMeeting": next_meeting,
        "resume": resume,
    }


def _handoff_next_review_meeting(
    team_id: str,
    request: Mapping[str, Any],
    *,
    agent_runner: Any = None,
    background: bool = True,
    budget: Any = None,
) -> dict[str, Any]:
    """Open the post-handoff review round, sibling-archive gated.

    Only a request whose meeting still sits in the selection's newest logical
    round owns the open-next duty: once a newer round exists, a late handoff
    must not stack another round on top of the live one.  While a sibling of
    that newest round still awaits its digest confirmation the open reports
    ``sibling_reviews_pending``; the last sibling close re-triggers it through
    ``_trigger_deferred_next_review``.
    """
    request_meeting_id = str(request.get("meetingRoundId") or "").strip()
    request_link = _newest_link_for_meeting(team_id, request_meeting_id)
    selection_id = str((request_link or {}).get("selectionId") or "").strip()
    if not selection_id:
        return open_next_review_meeting(
            team_id,
            previous_meeting_round_id=request_meeting_id,
            collection_request_id=str(request.get("requestId") or "").strip(),
            agent_runner=agent_runner,
            background=background,
            budget=budget,
            fan_out_selection=True,
        )
    gate = _latest_round_sibling_gate(team_id, selection_id)
    request_round_index = int((request_link or {}).get("roundIndex") or 0)
    already_linked = _request_has_review_round_link(
        team_id, str(request.get("requestId") or "").strip()
    )
    if (
        gate["roundIndex"]
        and request_round_index < gate["roundIndex"]
        and not already_linked
    ):
        return {
            "schemaVersion": SCHEMA_VERSION,
            "teamId": team_id,
            "status": "skipped",
            "reason": "newer_review_round_already_open",
            "selectionId": selection_id,
            "roundIndex": gate["roundIndex"],
            "requestRoundIndex": request_round_index,
        }
    return open_next_review_meeting(
        team_id,
        previous_meeting_round_id=request_meeting_id,
        collection_request_id=str(request.get("requestId") or "").strip(),
        agent_runner=agent_runner,
        background=background,
        budget=budget,
        fan_out_selection=True,
        enforce_sibling_archive_gate=True,
    )


def _newest_link_for_meeting(team_id: str, meeting_round_id: str) -> dict[str, Any] | None:
    """Newest review-round link bound to one meeting round id."""
    normalized_id = str(meeting_round_id or "").strip()
    if not normalized_id:
        return None
    newest: dict[str, Any] | None = None
    for link in list_review_round_links(team_id).get("links") or []:
        if str(link.get("meetingRoundId") or "").strip() != normalized_id:
            continue
        if newest is None or str(link.get("createdAt") or "") >= str(
            newest.get("createdAt") or ""
        ):
            newest = dict(link)
    return newest


def _request_has_review_round_link(team_id: str, request_id: str) -> bool:
    """True when one collection request already produced its follow-up round.

    A replayed handoff whose open-next already committed must resolve through
    the idempotent reuse path instead of the late-handoff skip.
    """
    normalized_id = str(request_id or "").strip()
    if not normalized_id:
        return False
    return any(
        str(link.get("collectionRequestId") or "").strip() == normalized_id
        for link in list_review_round_links(team_id).get("links") or []
    )


def _trigger_deferred_next_review(
    team_id: str,
    closed_meeting: Mapping[str, Any],
    *,
    agent_runner: Any = None,
    background: bool = True,
    budget: Any = None,
) -> dict[str, Any] | None:
    """Re-open the sibling-deferred next round on the last archive of a round.

    The earliest handed-off request still bound to the selection's newest
    logical round owns the deferred open; the sibling gate inside
    ``open_next_review_meeting`` plus that round binding together keep this
    trigger to one round per logical round.  Returns ``None`` when a sibling
    still awaits confirmation or nothing is deferred.
    """
    if str(closed_meeting.get("status") or "").strip().lower() != "closed":
        return None
    selection_id = _selection_id_from_meeting(closed_meeting)
    if not selection_id:
        return None
    gate = _latest_round_sibling_gate(team_id, selection_id)
    if not gate["roundIndex"] or gate["pendingMeetingRoundIds"]:
        return None
    link_by_meeting: dict[str, dict[str, Any]] = {}
    for link in list_review_round_links(team_id).get("links") or []:
        meeting_id = str(link.get("meetingRoundId") or "").strip()
        existing = link_by_meeting.get(meeting_id)
        if existing is None or str(link.get("createdAt") or "") >= str(
            existing.get("createdAt") or ""
        ):
            link_by_meeting[meeting_id] = dict(link)
    deferred = []
    for request in _collection_requests(_records(team_id)):
        if str(request.get("status") or "") != "handed_off":
            continue
        link = link_by_meeting.get(str(request.get("meetingRoundId") or "").strip()) or {}
        if str(link.get("selectionId") or "") != selection_id:
            continue
        if int(link.get("roundIndex") or 0) == gate["roundIndex"]:
            deferred.append(request)
    if not deferred:
        return None
    earliest = min(deferred, key=lambda item: str(item.get("createdAt") or ""))
    return open_next_review_meeting(
        team_id,
        previous_meeting_round_id=str(earliest.get("meetingRoundId") or ""),
        collection_request_id=str(earliest.get("requestId") or "").strip(),
        agent_runner=agent_runner,
        background=background,
        budget=budget,
        fan_out_selection=True,
        enforce_sibling_archive_gate=True,
    )


def _materialize_request_collection_claims(
    team_id: str, request: Mapping[str, Any]
) -> dict[str, Any]:
    """Bridge one collection request's run into the claim ledger (idempotent).

    This is the chain-level claim bridge: chain collections own neither a
    formal workflow run nor an extraction stage task, so the stage-task
    materialization entry points can never fire for them and the claim belief
    gate stayed ``claim_data_missing`` forever (SCI-001).  A failure is
    recorded as a scene event and returned for diagnosis; the handoff itself
    never blocks, and the identical idempotent call retries the bridge (the
    operator handoff endpoint re-invocation is the recovery path).
    """
    collection_run_id = str(request.get("collectionRunId") or "").strip()
    if not collection_run_id:
        return {"status": "skipped", "reason": "collection_run_missing"}
    question_id = str(request.get("questionId") or "").strip()
    if not question_id:
        return {"status": "skipped", "reason": "question_missing"}
    hypothesis_candidate_ids = list(
        dict.fromkeys(_normalized_str_list(request.get("hypothesisCandidateIds")))
    )
    try:
        from .agent_claim_evidence_materializer import (
            materialize_chain_collection_evidence,
        )

        result = materialize_chain_collection_evidence(
            project_root=_project_root(),
            team_id=team_id,
            question_scope=_question_scope_envelope(team_id, question_id),
            collection_run_id=collection_run_id,
            hypothesis_candidate_ids=hypothesis_candidate_ids,
        )
    except Exception as exc:  # noqa: BLE001 - diagnostics only, never a handoff failure
        _record_scene_event(
            "hypothesis_first.chain_collection_claim_materialization_failed",
            outcome="error",
            level="warning",
            fields={
                "requestId": str(request.get("requestId") or ""),
                "collectionRunId": collection_run_id,
                "questionId": question_id,
                "hypothesisCandidateIds": hypothesis_candidate_ids,
                "errorType": type(exc).__name__,
                "error": str(exc)[:400],
            },
        )
        return {"status": "failed", "errorType": type(exc).__name__, "error": str(exc)[:400]}
    if result.get("status") == "materialized":
        _record_scene_event(
            "hypothesis_first.chain_collection_claim_materialized",
            outcome="ok",
            fields={
                "requestId": str(request.get("requestId") or ""),
                "collectionRunId": collection_run_id,
                "questionId": question_id,
                "hypothesisCandidateIds": hypothesis_candidate_ids,
                "factClaimCount": result.get("factClaimCount"),
                "candidateClaimCount": result.get("candidateClaimCount"),
                "evidenceCount": result.get("evidenceCount"),
            },
        )
    return result


# ---------------------------------------------------------------------------
# parent run readiness re-check (writer-transaction-external, T5 discipline)


def _input_snapshot(run: Any) -> dict[str, Any]:
    try:
        snapshot = json.loads(str(getattr(run, "input_snapshot_json", "") or "{}"))
    except (TypeError, ValueError):
        return {}
    return snapshot if isinstance(snapshot, dict) else {}


def is_hypothesis_first_snapshot(snapshot: Mapping[str, Any]) -> bool:
    """The hypothesis-first marker lives inside researchObjectiveContract."""
    objective = snapshot.get("researchObjectiveContract")
    return isinstance(objective, Mapping) and objective.get("hypothesisFirst") is True


def resume_parent_runs(
    team_id: str,
    *,
    question_id: str,
    runtime: Any,
    trigger: str,
) -> dict[str, Any]:
    """Re-evaluate ``hypothesis_design`` for hypothesis-first parent runs.

    Runs entirely outside the writer transaction: readiness is evaluated on
    the caller thread, then a START/RETRY command is submitted with a
    deterministic idempotency key so identical triggers replay instead of
    duplicating attempts.
    """
    normalized_question_id = str(question_id or "").strip().upper()
    normalized_trigger = str(trigger or "").strip() or "manual"
    results: list[dict[str, Any]] = []
    runs = runtime.store.list_runs_for_team(team_id, CHALLENGE_CUP_WORKFLOW_ID)
    for run in runs:
        if str(getattr(run, "status", "") or "") in _TERMINAL_RUN_STATUSES:
            continue
        snapshot = _input_snapshot(run)
        if not is_hypothesis_first_snapshot(snapshot):
            continue
        run_question = str(
            snapshot.get("questionId") or getattr(run, "question_id", "") or ""
        ).upper()
        if normalized_question_id and run_question and run_question != normalized_question_id:
            continue
        results.append(_resume_one_run(runtime, run, normalized_trigger))
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": team_id,
        "questionId": normalized_question_id,
        "trigger": normalized_trigger,
        "runs": results,
    }


def _resume_one_run(runtime: Any, run: Any, trigger: str) -> dict[str, Any]:
    from core.research.workflow.contracts import (
        ActorRef,
        CommandRequest,
        WorkflowCommandKind,
    )

    entry: dict[str, Any] = {"runId": run.run_id}
    idempotency_key = f"hf-chain:{run.run_id}:{HYPOTHESIS_DESIGN_NODE_ID}:{trigger}"
    existing = runtime.store.get_command_by_idempotency(run.run_id, idempotency_key)
    if existing is not None:
        # Identical trigger: replay the original command verbatim (kind and
        # expected version come from the stored record so the request hash
        # matches); the service validates consistency and never re-executes.
        replay = CommandRequest(
            command_id=f"cmd-hf-chain-{_stable_hash({'runId': run.run_id, 'trigger': trigger})[:16]}",
            run_id=run.run_id,
            team_id=run.team_id,
            command=WorkflowCommandKind(str(existing.command_kind)),
            node_id=HYPOTHESIS_DESIGN_NODE_ID,
            expected_run_version=int(existing.expected_run_version),
            idempotency_key=idempotency_key,
            payload={},
            requested_by=ActorRef("system", "hypothesis-first-chain"),
            requested_at_ms=0,
        )
        try:
            receipt = runtime.command_service.submit(replay)
        except Exception as exc:
            entry["action"] = "skipped"
            entry["error"] = str(exc)
            entry["errorType"] = type(exc).__name__
            return entry
        entry["action"] = "replayed"
        entry["commandId"] = receipt.command_id
        entry["receiptStatus"] = receipt.status
        return entry

    latest = runtime.store.latest_attempt(run.run_id, HYPOTHESIS_DESIGN_NODE_ID)
    if latest is not None and str(latest.status) in _ACTIVE_ATTEMPT_STATUSES:
        entry["action"] = "already_active"
        entry["attemptId"] = latest.attempt_id
        return entry
    if latest is not None and str(latest.status) == "succeeded":
        entry["action"] = "already_succeeded"
        entry["attemptId"] = latest.attempt_id
        return entry

    command_kind = (
        WorkflowCommandKind.START_NODE
        if latest is None
        else WorkflowCommandKind.RETRY_NODE
    )
    fresh = runtime.store.get_run(run.run_id)
    expected_version = int(fresh.run_version if fresh is not None else run.run_version)
    request = CommandRequest(
        command_id=f"cmd-hf-chain-{_stable_hash({'runId': run.run_id, 'trigger': trigger})[:16]}",
        run_id=run.run_id,
        team_id=run.team_id,
        command=command_kind,
        node_id=HYPOTHESIS_DESIGN_NODE_ID,
        expected_run_version=expected_version,
        idempotency_key=idempotency_key,
        payload={},
        requested_by=ActorRef("system", "hypothesis-first-chain"),
        requested_at_ms=0,
    )
    readiness = runtime.readiness.evaluate(
        team_id=run.team_id,
        run_id=run.run_id,
        node_id=HYPOTHESIS_DESIGN_NODE_ID,
        context=runtime.readiness_context,
        use_cache=False,
    )
    entry["ready"] = readiness.ready
    entry["blockers"] = [blocker.code for blocker in readiness.blockers]
    if not readiness.ready:
        entry["action"] = "not_ready"
        return entry
    try:
        receipt = runtime.command_service.submit(request)
    except Exception as exc:
        entry["action"] = "skipped"
        entry["error"] = str(exc)
        entry["errorType"] = type(exc).__name__
        return entry
    entry["action"] = (
        "started" if command_kind is WorkflowCommandKind.START_NODE else "retried"
    )
    entry["commandId"] = receipt.command_id
    entry["receiptStatus"] = receipt.status
    return entry


# ---------------------------------------------------------------------------
# chain state read model (readiness evaluators)


def _question_meetings(
    team_id: str,
    question_id: str,
    *,
    workflow_run_id: str = "",
) -> list[dict[str, Any]]:
    from core.web.services.team_workflow import meeting_rounds

    normalized_workflow_run_id = str(workflow_run_id or "").strip()
    meetings = meeting_rounds.list_meeting_rounds(team_id)["meetings"]
    return [
        meeting
        for meeting in meetings
        if str(meeting.get("meetingType") or "") == HYPOTHESIS_REVIEW_MEETING_TYPE
        and str(meeting.get("question") or "").upper() == question_id.upper()
        and (
            not normalized_workflow_run_id
            or _meeting_workflow_run_id(meeting) == normalized_workflow_run_id
        )
    ]


def _question_hypothesis_rounds(team_id: str, question_id: str) -> list[dict[str, Any]]:
    from core.web.services.team_workflow import hypothesis_rounds

    rounds = hypothesis_rounds.list_hypothesis_rounds(team_id)["rounds"]
    return [
        item
        for item in rounds
        if str(item.get("question") or "").upper() == question_id.upper()
    ]


def _question_template_baselines(team_id: str, question_id: str) -> list[dict[str, Any]]:
    from core.web.services.team_workflow import research_templates

    baselines = research_templates.list_template_baselines(team_id)["baselines"]
    return [
        item
        for item in baselines
        if str(item.get("question") or "").upper() == question_id.upper()
        and str(item.get("status") or "") == "frozen"
    ]


def _project_chain_discussion_anchor(
    meeting: Mapping[str, Any],
    *,
    selection_id: str = "",
    candidate_id: str = "",
    team_id: str = "",
    question_id: str = "",
) -> dict[str, Any]:
    """Project one chain meeting through the canonical scoped-room guard.

    The chain ledger owns meeting/candidate lineage, but it does not own room
    identity.  Resolve only the room explicitly bound to this meeting and let
    ``active_discussion_anchor`` validate its v1 scope and room config.  This
    keeps chain state from promoting a sibling candidate's room when a binding
    is absent or malformed.
    """
    from core.web.services import chat_room_service
    from core.web.services.team_workflow.active_discussion_anchor import (
        project_active_discussion_anchor,
    )

    meeting_id = str(meeting.get("meetingRoundId") or "").strip()
    room_id = str(meeting.get("linkedChatRoomId") or "").strip()
    room = None
    if room_id:
        try:
            room = chat_room_service.get_chat_room_compact(room_id)
        except Exception:  # noqa: BLE001 - unreadable room state degrades
            room = None
    projection: dict[str, Any] = {
        "activeMeetingRoundId": meeting_id,
    }
    discussion_scope = meeting.get("discussionScope")
    if isinstance(discussion_scope, Mapping):
        projection["scope"] = dict(discussion_scope)
    else:
        # Selection fan-out can precede formal run creation.  The chain link,
        # meeting binding, and explicitly linked room together provide an
        # exact preformal identity; do not infer one from the question/team
        # alone and do not manufacture a formal workflowRunId.
        from core.research.workflow.contracts.discussion_scope import (
            PREFORMAL_CANDIDATE_REVIEW_SCOPE_KIND,
            PREFORMAL_DISCUSSION_SCOPE_VERSION,
        )

        projection["preformalBinding"] = {
            "version": PREFORMAL_DISCUSSION_SCOPE_VERSION,
            "kind": PREFORMAL_CANDIDATE_REVIEW_SCOPE_KIND,
            "teamId": str(team_id or meeting.get("teamId") or "").strip(),
            "questionId": str(
                question_id or meeting.get("questionId") or meeting.get("question") or ""
            ).strip().upper(),
            "selectionId": selection_id,
            "candidateId": candidate_id,
            "meetingRoundId": meeting_id,
            "roomId": room_id,
        }
    if selection_id:
        projection["activeSelectionId"] = selection_id
    if candidate_id:
        projection["activeCandidateId"] = candidate_id
    return project_active_discussion_anchor(
        projection,
        [meeting],
        [room] if isinstance(room, Mapping) else [],
    )


def _stage_one_r0_collection_ready(
    generation_meeting: Mapping[str, Any] | None,
) -> bool:
    """Treat one closed, actionable R0 digest as the source-finding scope.

    Stage-one catalog runs deliberately persist the first generation round as
    exploratory drafts.  Its validated evidence requests are the bounded
    search scope for ``source_finding``; requiring a later review-round
    collection request here creates a cycle because formal candidates and
    review rounds only exist after the knowledge stages finish.
    """

    meeting = generation_meeting if isinstance(generation_meeting, Mapping) else {}
    if (
        _meeting_candidate_authority(meeting) != EXPLORATORY_DRAFT_AUTHORITY
        or str(meeting.get("status") or "").strip().lower() != "closed"
        or _is_execution_stopped_meeting(meeting)
    ):
        return False
    draft = meeting.get("digestDraft")
    if not isinstance(draft, Mapping):
        return False
    if not _generation_proposals_from_digest(draft):
        return False
    raw_requests = [
        item
        for item in list(draft.get("evidenceRequests") or [])
        if isinstance(item, Mapping)
    ]
    if not raw_requests:
        return False
    source_refs = _normalized_str_list(draft.get("sourceMessageRefs"))
    from core.web.services.team_workflow import meeting_runtime

    for raw in raw_requests:
        try:
            normalized, _errors = meeting_runtime.validate_evidence_request_draft(
                raw,
                meeting,
                source_refs=source_refs,
            )
        except Exception:  # noqa: BLE001 - readiness stays fail-closed
            continue
        if normalized is not None:
            return True
    return False


def chain_state(
    team_id: str,
    question_id: str,
    *,
    workflow_run_id: str = "",
) -> dict[str, Any]:
    """Aggregate one question's hypothesis-first state, optionally by run.

    Read-only; used by the readiness evaluators.  Legacy DEV callers retain
    the team/question projection; formal readiness supplies ``workflowRunId``
    so retained history from another execution cannot advance or block it.
    """
    from core.web.services import team_service
    from core.web.services.team_workflow import hypothesis_selection as selections

    normalized_team_id = team_service.assert_team_exists(team_id)
    normalized_question_id = str(question_id or "").strip().upper()
    normalized_workflow_run_id = str(workflow_run_id or "").strip()
    records = _records(normalized_team_id)
    meetings = (
        _question_meetings(
            normalized_team_id,
            normalized_question_id,
            workflow_run_id=normalized_workflow_run_id,
        )
        if normalized_workflow_run_id
        else _question_meetings(normalized_team_id, normalized_question_id)
    )
    meeting_ids = {
        str(meeting.get("meetingRoundId") or "").strip()
        for meeting in meetings
        if str(meeting.get("meetingRoundId") or "").strip()
    }
    links = [
        link
        for link in _review_round_links(records)
        if str(link.get("questionId") or "").upper() == normalized_question_id
        and (
            not normalized_workflow_run_id
            or str(link.get("meetingRoundId") or "") in meeting_ids
        )
    ]
    requests = [
        request
        for request in _collection_requests(records)
        if str(request.get("questionId") or "").upper() == normalized_question_id
        and (
            not normalized_workflow_run_id
            or str(request.get("meetingRoundId") or "") in meeting_ids
        )
    ]
    meeting_by_id = {
        str(meeting.get("meetingRoundId") or ""): meeting for meeting in meetings
    }
    selection_id = ""
    # links are sorted by roundIndex; the CURRENT selection must come from the
    # newest appended link record, not the max-roundIndex one (a fresh
    # selection's round 1 would otherwise lose to the previous selection's
    # final round).
    question_links_append_order = [
        item
        for item in records
        if str(item.get("recordKind") or "") == REVIEW_ROUND_LINK_KIND
        and str(item.get("questionId") or "").upper() == normalized_question_id
        and (
            not normalized_workflow_run_id
            or str(item.get("meetingRoundId") or "") in meeting_ids
        )
    ]
    if question_links_append_order:
        selection_id = str(question_links_append_order[-1].get("selectionId") or "")
    if not selection_id and not normalized_workflow_run_id:
        try:
            scope = _question_scope_envelope(
                normalized_team_id,
                normalized_question_id,
            )
            scope["scopeHash"] = scope_hash_for(
                **{field: scope[field] for field in _SCOPE_FIELDS},
                agent_id=scope["agentId"],
                mode=scope["mode"],
            )
            latest_selection = selections.get_latest_hypothesis_selection(
                normalized_team_id,
                normalized_question_id,
                scope=scope,
            )
        except selections.ResearchHypothesisSelectionError:
            latest_selection = {}
        selection = latest_selection.get("selection") or {}
        selection_id = str(selection.get("selectionId") or "")

    first_meeting_id = ""
    if links:
        first_link = next(
            (link for link in links if int(link.get("roundIndex") or 0) == 1), links[0]
        )
        first_meeting_id = str(first_link.get("meetingRoundId") or "")
    elif meetings:
        first_meeting_id = str(meetings[0].get("meetingRoundId") or "")
    first_meeting = meeting_by_id.get(first_meeting_id) or {}
    first_meeting_closed = (
        bool(first_meeting)
        and str(first_meeting.get("status") or "") == "closed"
    )
    selection_links = (
        [item for item in links if str(item.get("selectionId") or "") == selection_id]
        if selection_id
        else []
    )
    # Review meetings of superseded selections must not block collection
    # readiness forever.  Within the current selection, the open-next gate
    # defers the next round until every sibling of the newest logical round is
    # archived, so a non-latest open room is stale history for collection
    # readiness (its confirmation entry stays projected) rather than a live
    # wedge; treating those historical rooms as active would wedge the formal
    # source_finding node even though a later closed round supplied the scope.
    current_selection_meeting_ids = {
        str(link.get("meetingRoundId") or "") for link in selection_links
    }
    latest_selection_round_index = max(
        (int(link.get("roundIndex") or 0) for link in selection_links), default=0
    )
    current_round_meeting_ids = {
        str(link.get("meetingRoundId") or "")
        for link in selection_links
        if int(link.get("roundIndex") or 0) == latest_selection_round_index
    }
    open_meeting_ids = [
        str(meeting.get("meetingRoundId") or "")
        for meeting in meetings
        if str(meeting.get("status") or "") != "closed"
        and (
            str(meeting.get("meetingType") or "") != HYPOTHESIS_REVIEW_MEETING_TYPE
            or not current_round_meeting_ids
            or str(meeting.get("meetingRoundId") or "") in current_round_meeting_ids
        )
    ]
    current_selection_requests = [
        request
        for request in requests
        if not current_selection_meeting_ids
        or str(request.get("meetingRoundId") or "")
        in current_selection_meeting_ids
    ]
    current_selection_pending_requests = [
        request
        for request in current_selection_requests
        if str(request.get("status") or "") != "handed_off"
    ]
    active_discussion_anchor: dict[str, Any] | None = None
    active_candidate_links = sorted(
        (
            link
            for link in selection_links
            if str(link.get("candidateId") or "").strip()
            and str(link.get("meetingRoundId") or "").strip() in open_meeting_ids
        ),
        key=lambda item: (
            int(item.get("roundIndex") or 0),
            int(item.get("candidateOrder") or 0),
            str(item.get("createdAt") or ""),
        ),
    )
    if active_candidate_links:
        active_link = active_candidate_links[0]
        active_meeting_id = str(active_link.get("meetingRoundId") or "").strip()
        active_meeting = meeting_by_id.get(active_meeting_id) or {}
        active_discussion_anchor = _project_chain_discussion_anchor(
            active_meeting,
            selection_id=str(active_link.get("selectionId") or "").strip(),
            candidate_id=str(active_link.get("candidateId") or "").strip(),
            team_id=normalized_team_id,
            question_id=normalized_question_id,
        )
    pending_requests = [
        request for request in requests if str(request.get("status") or "") != "handed_off"
    ]

    rounds = _question_hypothesis_rounds(normalized_team_id, normalized_question_id)
    if normalized_workflow_run_id:
        rounds = [
            round_record
            for round_record in rounds
            if any(
                isinstance(ref, Mapping)
                and str(ref.get("kind") or "") == "meeting_round"
                and str(ref.get("id") or "") in meeting_ids
                for ref in list(round_record.get("meetingRefs") or [])
            )
        ]
    latest_round = rounds[-1] if rounds else {}
    latest_round_id = str(latest_round.get("roundId") or "")
    latest_round_closed = str(latest_round.get("status") or "") == "closed"
    meta_review = (
        dict(latest_round.get("metaReview"))
        if isinstance(latest_round.get("metaReview"), Mapping)
        else {}
    )
    latest_meeting_ids = {
        str(ref.get("id") or "")
        for ref in list(latest_round.get("meetingRefs") or [])
        if isinstance(ref, Mapping) and str(ref.get("kind") or "") == "meeting_round"
    }
    new_requests_this_round = [
        request
        for request in requests
        if str(request.get("meetingRoundId") or "") in latest_meeting_ids
    ]
    latest_adjudication = _latest_round_adjudication(
        records,
        question_id=normalized_question_id,
        round_id=latest_round_id,
        meeting_ids=meeting_ids if normalized_workflow_run_id else None,
    )
    adjudication_decision = (
        str((latest_adjudication or {}).get("decision") or "").strip().lower()
    )
    # The appended human adjudication record is the second acceptance
    # authority: an accepted adjudication converges the latest round even
    # when that round produced new evidence requests (they must all be
    # handed off — pending collection still blocks in every case) and even
    # when the meta review itself did not accept.  A rejected adjudication
    # never converges; the v2 projection mirrors these exact clauses.
    adjudication_accepted = adjudication_decision == "accepted"
    adjudication_rejected = adjudication_decision == "rejected"
    converged = bool(
        latest_round
        and latest_round_closed
        and (bool(meta_review.get("accepted")) or adjudication_accepted)
        and not pending_requests
        and (not new_requests_this_round or adjudication_accepted)
    )
    if not latest_round:
        convergence_detail = "尚无闭环的假说评审轮次"
    elif not latest_round_closed:
        convergence_detail = f"最近一轮 {latest_round_id} 尚未 closed"
    elif converged:
        convergence_detail = (
            f"最近一轮 {latest_round_id} 已由人工裁决收敛"
            if adjudication_accepted
            else "converged"
        )
    elif adjudication_rejected:
        convergence_detail = f"最近一轮 {latest_round_id} 已被人工裁决拒绝"
    elif not (bool(meta_review.get("accepted")) or adjudication_accepted):
        convergence_detail = f"最近一轮 {latest_round_id} 的 MetaReview 未 accepted"
    elif pending_requests:
        convergence_detail = "仍有待交接的搜集请求"
    elif new_requests_this_round:
        convergence_detail = (
            f"最近一轮 {latest_round_id} 产生了新的搜集决策，等待人工裁决或下一轮评审"
        )
    else:
        convergence_detail = "converged"

    # Convergence hard gate (R2.2, fail-closed): an accepted recommendation
    # may only converge when its candidate's core claims carry an evaluable,
    # unrefuted five-state belief.  `contradicted`/`disputed` claims, and any
    # missing/unreadable claim data, block convergence instead of silently
    # advancing onto the formal path.  The gate runs only once the structural
    # gates above passed, so the read model pays the claim-ledger I/O only on
    # the otherwise-converged path.
    claim_belief_gate: dict[str, Any] | None = None
    if converged:
        recommended_candidate_id = str(
            meta_review.get("recommendationCandidateId") or ""
        ).strip()
        verdict = evaluate_claim_belief_gate(
            normalized_team_id, normalized_question_id, [recommended_candidate_id]
        ).get(recommended_candidate_id) or _blocked_gate_verdict(
            recommended_candidate_id, "claim_data_missing"
        )
        claim_belief_gate = {
            "decisionPoint": "converge_question",
            "roundId": latest_round_id,
            "candidateId": recommended_candidate_id,
            "status": str(verdict.get("status") or ""),
            "reason": str(verdict.get("reason") or ""),
            "claims": list(verdict.get("claims") or []),
            "blockedClaims": list(verdict.get("blockedClaims") or []),
            "evidenceGaps": list(verdict.get("evidenceGaps") or []),
        }
        if verdict.get("status") != "allowed":
            converged = False
            blocked_claim_ids = [
                str(item.get("claimId") or "")
                for item in claim_belief_gate["blockedClaims"]
                if isinstance(item, Mapping)
            ]
            candidate_label = recommended_candidate_id or "(未给出入选候选)"
            if claim_belief_gate["reason"] == "claim_belief_state_blocked":
                convergence_detail = (
                    f"最近一轮 {latest_round_id} 的入选假说 {candidate_label} "
                    f"存在被反证或争议中的核心 claim"
                    f"（{', '.join(blocked_claim_ids) or '未知'}），"
                    f"claim belief 硬门阻断收敛；请先修订 claim 或证据再重试"
                )
            else:
                convergence_detail = (
                    f"最近一轮 {latest_round_id} 的入选假说 {candidate_label} "
                    f"的 claim 数据无法评估"
                    f"（{claim_belief_gate['reason']}），"
                    f"claim belief 硬门 fail-closed 阻断收敛"
                )

    baselines = _question_template_baselines(normalized_team_id, normalized_question_id)
    # Exhaustion counts only the current selection's rounds. Persisted
    # ``roundBudget`` values are historical replay data, not mutable authority;
    # older runs written with the former default of 3 must inherit the single
    # hard limit instead of blocking before the agent can decide round 4.
    selection_round_index = max(
        (int(item.get("roundIndex") or 0) for item in selection_links), default=0
    )
    budget = HARD_ROUND_LIMIT
    generation_meetings = (
        _question_generation_meetings(
            normalized_team_id,
            normalized_question_id,
            workflow_run_id=normalized_workflow_run_id,
        )
        if normalized_workflow_run_id
        else _question_generation_meetings(
            normalized_team_id, normalized_question_id
        )
    )
    generation_meeting_ids = {
        str(meeting.get("meetingRoundId") or "").strip()
        for meeting in generation_meetings
        if str(meeting.get("meetingRoundId") or "").strip()
    }
    candidates = [
        record
        for record in records
        if str(record.get("recordKind") or "") == CANDIDATE_KIND
        and str(record.get("questionId") or "").upper() == normalized_question_id
        and (
            not normalized_workflow_run_id
            or str(record.get("meetingRoundId") or "") in generation_meeting_ids
        )
    ]
    generation_meeting = generation_meetings[-1] if generation_meetings else {}
    stage_one_r0_collection_ready = _stage_one_r0_collection_ready(
        generation_meeting
    )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "questionId": normalized_question_id,
        "selectionId": selection_id,
        "meetingCount": len(meetings),
        "firstMeetingId": first_meeting_id,
        "firstMeetingClosed": first_meeting_closed,
        "openMeetingIds": open_meeting_ids,
        "collectionRequests": requests,
        "collectionRequestCount": len(requests),
        "pendingCollectionCount": len(pending_requests),
        # A closed, converged review chain that never asked for more
        # evidence is itself a discussion decision: "no additional collection
        # needed". Treating only handed-off requests as ready wedged live
        # flows whose reviews legitimately concluded the anchors suffice. A
        # round that DID request evidence (even with an invalid envelope)
        # keeps blocking — that request must be repaired, not waived.
        "collectionReady": bool(
            current_selection_requests
            and (not open_meeting_ids or not current_selection_pending_requests)
        )
        or stage_one_r0_collection_ready
        or bool(
            converged
            and not open_meeting_ids
            and first_meeting_closed
            and not _question_requested_evidence(
                normalized_team_id,
                normalized_question_id,
                meeting_round_ids=(
                    meeting_ids if normalized_workflow_run_id else None
                ),
            )
        ),
        "hypothesisRoundCount": len(rounds),
        "latestHypothesisRoundId": latest_round_id,
        "hypothesisConverged": converged,
        "convergenceDetail": convergence_detail,
        "claimBeliefGate": claim_belief_gate,
        "roundBudget": budget,
        "budgetExhausted": bool(not converged and selection_round_index >= budget),
        "templateBaselineExists": bool(baselines),
        "templateBaselineIds": [
            str(item.get("baselineId") or "") for item in baselines
        ],
        "candidateCount": len(candidates),
        "generationMeetingId": str(generation_meeting.get("meetingRoundId") or ""),
        "generationMeetingStatus": str(generation_meeting.get("status") or ""),
        "activeDiscussionAnchor": active_discussion_anchor,
    }
