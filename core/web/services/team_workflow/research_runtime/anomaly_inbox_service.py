"""Pure anomaly-inbox aggregation service (no persistence, no commands).

R4.3: this projector turns the scattered blocking / risk / drift / needs-human
signals of one hypothesis-first state v2 snapshot (plus optional companion
inputs) into the single sorted :class:`AnomalyInbox` contract.  It is a
deterministic pure function for a fixed ``generated_at``: no storage access,
no threading, no side effects; it never reads the ledger, never emits
workflow commands and never mutates the input snapshot.  No signal at all is
a legal state and yields the empty inbox.

Signal mapping (problems carry the original code verbatim into the item's
evidence refs, so every inbox row stays auditable back to its source):

=========================================  ====================================  ==============================
input signal                               kind                                  recommended action family
=========================================  ====================================  ==============================
``generation_heartbeat_stale`` /           ``heartbeat_stale``                   ``retry_node``
``review_heartbeat_stale`` /
``review_dispatch_heartbeat_stale``
problem with code ``budget_exceeded``      ``budget_exhausted``                  ``reconcile_run``
problem whose code the frozen retry        ``blocked_run``                       the taxonomy entry's first
taxonomy classifies ``human_required``                                           human action family
(e.g. ``collection_run_needs_continue``)
``awaitingHumanCount > 0``                 ``needs_human_gate`` (one item)       none (phase-specific)
``disputed_claims`` input (count)          ``claim_disputed`` (one item)         none (adjudication lives in
                                                                                 the claim ledger)
``review_escalations`` input               ``review_disagreement_escalation``    none (flagged-only marker)
``drift_sentinel_hits`` input              ``drift_sentinel_hit`` (one item)     none (sampling signal)
``retry_exhausted_nodes`` input            ``retry_budget_exhausted``            ``retry_node``
                                           (one item per node)
=========================================  ====================================  ==============================

Problem codes that are neither heartbeat-stale, budget-exhausted nor
taxonomy human-required are informational integrity signals (e.g.
``formal_run_status_unknown``) and are deliberately not inbox items; the
inbox aggregates the blocking/risk/drift/human surface only.  Severity is
never chosen here: :meth:`AnomalyInboxItem.create` derives it from the
frozen ``ANOMALY_KIND_SEVERITY`` table.  Timestamps follow the durable
facts of each source (``detectedAt``/``lastHeartbeatAt``/``computedAt`` /
claim ``lastEvaluatedAt``), falling back to ``generated_at``; unreadable
timestamps fail closed through the contract.

Duck typing: the state snapshot and every companion entry may be a mapping
or an attribute carrier (dataclass / contract instance); the same lookup
path serves both.  Ordering, dedup/merge and integrity enforcement live in
the :class:`AnomalyInbox` / :class:`AnomalyInboxItem` contracts, not here.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from typing import Any

from core.research.workflow.contracts import (
    ANOMALY_KIND_BLOCKED_RUN,
    ANOMALY_KIND_BUDGET_EXHAUSTED,
    ANOMALY_KIND_CLAIM_DISPUTED,
    ANOMALY_KIND_DRIFT_SENTINEL_HIT,
    ANOMALY_KIND_HEARTBEAT_STALE,
    ANOMALY_KIND_NEEDS_HUMAN_GATE,
    ANOMALY_KIND_REVIEW_DISAGREEMENT_ESCALATION,
    ANOMALY_KIND_RETRY_BUDGET_EXHAUSTED,
    AnomalyInbox,
    AnomalyInboxItem,
    AnomalyInboxScope,
    DEFAULT_RETRY_TAXONOMY,
    HumanActionFamily,
    RetryOutcomeClass,
)

HEARTBEAT_STALE_PROBLEM_CODES = frozenset(
    {
        "generation_heartbeat_stale",
        "review_heartbeat_stale",
        "review_dispatch_heartbeat_stale",
    }
)

BUDGET_EXHAUSTED_PROBLEM_CODES = frozenset({"budget_exceeded"})

# Problem source kinds whose sourceId is a run id (scope.runId).
_RUN_SOURCE_KINDS = frozenset({"formal_run", "collection_run"})
# Meeting-scoped heartbeat problems carry the meetingRoundId as sourceId.
_MEETING_SOURCE_KINDS = frozenset({"meeting_round"})

_ESCALATION_FLAGGED_ONLY_STATUS = "flagged_only"
_DISPUTED_BELIEF_STATE = "disputed"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _get(source: Any, key: str) -> Any:
    """Duck-typed field access: mappings and attribute carriers both work."""

    if source is None:
        return None
    if isinstance(source, Mapping):
        return source.get(key)
    return getattr(source, key, None)


def _text(source: Any, key: str) -> str:
    return str(_get(source, key) or "").strip()


def _as_iterable(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (str, bytes, Mapping)):
        return [value]
    if isinstance(value, Iterable):
        return list(value)
    return [value]


def _first_non_empty(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _base_scope(state: Any) -> AnomalyInboxScope:
    return AnomalyInboxScope(
        teamId=_text(state, "teamId"),
        questionId=_text(state, "questionId"),
    )


def _with_scope_ids(
    base: AnomalyInboxScope,
    *,
    run_id: str = "",
    node_id: str = "",
    meeting_round_id: str = "",
) -> AnomalyInboxScope:
    return AnomalyInboxScope(
        teamId=base.teamId,
        questionId=base.questionId,
        runId=run_id,
        nodeId=node_id,
        meetingRoundId=meeting_round_id,
    )


def _evidence_ref(*parts: str) -> str:
    return ":".join(part for part in parts if part)


def _item_for_problem(
    problem: Any,
    base: AnomalyInboxScope,
    fallback_at: str,
) -> AnomalyInboxItem | None:
    """Map one state problem to an inbox item; None for non-inbox codes.

    Kind resolution order is fixed: heartbeat-stale codes first, then the
    budget-exhausted code, then the frozen retry taxonomy (human_required
    codes become blocked_run with the taxonomy's primary human action
    family).  Everything else is not an inbox signal.
    """

    code = _text(problem, "code")
    if not code:
        return None
    source_kind = _text(problem, "sourceKind")
    source_id = _text(problem, "sourceId")
    detected_at = _first_non_empty(_text(problem, "detectedAt"), fallback_at)
    summary = _text(problem, "message") or code
    evidence = [_evidence_ref("problem", code)]
    if source_id:
        evidence.append(_evidence_ref("source", source_kind, source_id))

    if code in HEARTBEAT_STALE_PROBLEM_CODES:
        last_seen = _first_non_empty(_text(problem, "lastHeartbeatAt"), detected_at)
        meeting_round_id = (
            source_id if source_kind in _MEETING_SOURCE_KINDS else ""
        )
        return AnomalyInboxItem.create(
            kind=ANOMALY_KIND_HEARTBEAT_STALE,
            scope=_with_scope_ids(base, meeting_round_id=meeting_round_id),
            first_seen_at=detected_at,
            last_seen_at=last_seen,
            summary=summary,
            # The stale executor's recovery entry is the node-level re-drive
            # (retry / retry_review_dispatch), so the aligned family is
            # retry_node.
            recommended_action=HumanActionFamily.RETRY_NODE.value,
            evidence=evidence,
        )

    if code in BUDGET_EXHAUSTED_PROBLEM_CODES:
        run_id = source_id if source_kind in _RUN_SOURCE_KINDS else ""
        return AnomalyInboxItem.create(
            kind=ANOMALY_KIND_BUDGET_EXHAUSTED,
            scope=_with_scope_ids(base, run_id=run_id),
            first_seen_at=detected_at,
            last_seen_at=detected_at,
            summary=summary,
            # Taxonomy budget_exceeded: reconcile_run/archive_run rebuild is
            # the only way forward; reconcile_run is the primary family.
            recommended_action=HumanActionFamily.RECONCILE_RUN.value,
            evidence=evidence,
        )

    if DEFAULT_RETRY_TAXONOMY.knows(code):
        entry = DEFAULT_RETRY_TAXONOMY.entry(code)
        if entry.outcome_class is RetryOutcomeClass.HUMAN_REQUIRED:
            run_id = source_id if source_kind in _RUN_SOURCE_KINDS else ""
            return AnomalyInboxItem.create(
                kind=ANOMALY_KIND_BLOCKED_RUN,
                scope=_with_scope_ids(base, run_id=run_id),
                first_seen_at=detected_at,
                last_seen_at=detected_at,
                summary=summary,
                recommended_action=entry.human_actions[0].value,
                evidence=evidence,
            )
    return None


def _awaiting_human_item(
    state: Any,
    base: AnomalyInboxScope,
    fallback_at: str,
) -> AnomalyInboxItem | None:
    raw = _get(state, "awaitingHumanCount")
    if isinstance(raw, bool) or not isinstance(raw, int) or raw <= 0:
        return None
    return AnomalyInboxItem.create(
        kind=ANOMALY_KIND_NEEDS_HUMAN_GATE,
        scope=base,
        first_seen_at=fallback_at,
        last_seen_at=fallback_at,
        summary=f"{raw} 处等待人工处理",
        recommended_action=None,
        evidence=[f"awaitingHumanCount:{raw}"],
    )


def _claim_identity(entry: Any) -> tuple[str, str] | None:
    """(claimId, lastEvaluatedAt) for one disputed-claims input entry."""

    if isinstance(entry, str):
        claim_id = entry.strip()
        return (claim_id, "") if claim_id else None
    claim_id = _text(entry, "claimId")
    if not claim_id:
        return None
    belief_state = _text(entry, "beliefState").lower()
    if belief_state and belief_state != _DISPUTED_BELIEF_STATE:
        # A non-disputed entry never becomes a disputed claim (fail-closed).
        return None
    return (claim_id, _text(entry, "lastEvaluatedAt"))


def _disputed_claims_item(
    entries: list[Any],
    base: AnomalyInboxScope,
    fallback_at: str,
) -> AnomalyInboxItem | None:
    claimed: list[tuple[str, str]] = []
    for entry in entries:
        identity = _claim_identity(entry)
        if identity is not None:
            claimed.append(identity)
    if not claimed:
        return None
    claim_ids = sorted({claim_id for claim_id, _ in claimed})
    last_evaluated = max(
        (evaluated for _, evaluated in claimed if evaluated), default=""
    )
    return AnomalyInboxItem.create(
        kind=ANOMALY_KIND_CLAIM_DISPUTED,
        scope=base,
        first_seen_at=_first_non_empty(last_evaluated, fallback_at),
        last_seen_at=_first_non_empty(last_evaluated, fallback_at),
        summary=f"{len(claim_ids)} 条主张支持与反对证据共存，待人工裁决",
        recommended_action=None,
        evidence=[f"disputedClaimCount:{len(claim_ids)}"]
        + [f"claim:{claim_id}" for claim_id in claim_ids],
    )


def _review_escalations_item(
    entries: list[Any],
    base: AnomalyInboxScope,
    fallback_at: str,
) -> AnomalyInboxItem | None:
    flagged = 0
    round_ids: list[str] = []
    for entry in entries:
        status = _text(entry, "status") or _ESCALATION_FLAGGED_ONLY_STATUS
        if status != _ESCALATION_FLAGGED_ONLY_STATUS:
            # The escalation contract is marked-only; other statuses are not
            # inbox signals.
            continue
        flagged += 1
        review_round_id = _text(entry, "reviewRoundId")
        if review_round_id:
            round_ids.append(review_round_id)
    if flagged == 0:
        return None
    return AnomalyInboxItem.create(
        kind=ANOMALY_KIND_REVIEW_DISAGREEMENT_ESCALATION,
        scope=base,
        first_seen_at=fallback_at,
        last_seen_at=fallback_at,
        summary="评审分歧已升级标记（flagged_only），待人工复核",
        recommended_action=None,
        evidence=[f"escalationCount:{flagged}"]
        + sorted({f"reviewRound:{round_id}" for round_id in round_ids}),
    )


def _drift_sentinel_item(
    entries: list[Any],
    base: AnomalyInboxScope,
    fallback_at: str,
) -> AnomalyInboxItem | None:
    run_ids: list[str] = []
    count = 0
    for entry in entries:
        count += 1
        run_id = _text(entry, "runId")
        if run_id:
            run_ids.append(run_id)
    if count == 0:
        return None
    return AnomalyInboxItem.create(
        kind=ANOMALY_KIND_DRIFT_SENTINEL_HIT,
        scope=base,
        first_seen_at=fallback_at,
        last_seen_at=fallback_at,
        summary="审计抽样漂移哨兵命中，抽样质量需人工关注",
        recommended_action=None,
        evidence=[f"driftSentinelHitCount:{count}"]
        + sorted({f"run:{run_id}" for run_id in run_ids}),
    )


def _retry_exhausted_items(
    entries: list[Any],
    base: AnomalyInboxScope,
    fallback_at: str,
) -> list[AnomalyInboxItem]:
    items: list[AnomalyInboxItem] = []
    for entry in entries:
        node_id = _text(entry, "nodeId") or (
            entry.strip() if isinstance(entry, str) else ""
        )
        if not node_id:
            continue
        run_id = _text(entry, "runId")
        items.append(
            AnomalyInboxItem.create(
                kind=ANOMALY_KIND_RETRY_BUDGET_EXHAUSTED,
                scope=_with_scope_ids(base, run_id=run_id, node_id=node_id),
                first_seen_at=fallback_at,
                last_seen_at=fallback_at,
                summary=f"节点 {node_id} 的业务重试预算已耗尽，需人工决定后续动作",
                recommended_action=HumanActionFamily.RETRY_NODE.value,
                evidence=[_evidence_ref("node", node_id)],
            )
        )
    return items


def build_anomaly_inbox(
    state: Any = None,
    *,
    disputed_claims: Any = None,
    review_escalations: Any = None,
    drift_sentinel_hits: Any = None,
    retry_exhausted_nodes: Any = None,
    generated_at: str | None = None,
) -> AnomalyInbox:
    """Project one state-v2 snapshot (plus optional inputs) into the inbox.

    ``state`` may be the snapshot mapping, a snapshot-like object, or None.
    All companion inputs are optional and duck-typed exactly like ``state``.
    The same inputs with the same ``generated_at`` always produce the same
    inbox; with ``generated_at=None`` only the wall-clock fallback differs.
    """

    fallback_at = _first_non_empty(generated_at, _text(state, "computedAt"), _utc_now())
    base = _base_scope(state)

    items: list[AnomalyInboxItem] = []
    for problem in _as_iterable(_get(state, "problems")):
        item = _item_for_problem(problem, base, fallback_at)
        if item is not None:
            items.append(item)

    gate_item = _awaiting_human_item(state, base, fallback_at)
    if gate_item is not None:
        items.append(gate_item)

    disputed_item = _disputed_claims_item(
        _as_iterable(disputed_claims), base, fallback_at
    )
    if disputed_item is not None:
        items.append(disputed_item)

    escalation_item = _review_escalations_item(
        _as_iterable(review_escalations), base, fallback_at
    )
    if escalation_item is not None:
        items.append(escalation_item)

    drift_item = _drift_sentinel_item(
        _as_iterable(drift_sentinel_hits), base, fallback_at
    )
    if drift_item is not None:
        items.append(drift_item)

    items.extend(
        _retry_exhausted_items(
            _as_iterable(retry_exhausted_nodes), base, fallback_at
        )
    )
    return AnomalyInbox.create(items, generated_at=fallback_at)
