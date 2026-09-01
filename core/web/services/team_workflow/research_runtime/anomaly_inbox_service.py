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
``retry_exhausted_nodes`` input            ``retry_budget_exhausted``            ``reconcile_run``
                                           (one item per node)
state ``convergence.outcome ==             ``needs_human_gate`` (one item)       none (phase-specific user
``exhausted``)                                                                   decision)
``digest_ttl_overdues`` input (mute state  ``needs_human_gate`` (one item per    none (approval lives on the
from ``meeting_digest_ttl_mute_state``)    meeting round)                        digest surface)
``gate_waits`` input (knowledge_handoff /  ``needs_human_gate`` (one item per    none (gate-specific approval
H1-H4 gate waiting past threshold)         overdue gate)                         surface)
``budget_precheck_blocks`` input (the      ``budget_exhausted`` (one item per    ``retry_node`` (via the
``budget_precheck_blocked`` event payload) blocked stage boundary)              structured extend_budget CTA
                                                                                 ``action``; see
                                                                                 ``attach_inbox_actions``)
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

# Stage-boundary budget admission block (budget_stage_admission is the code
# authority; kept as a literal so this module stays free of runtime-service
# imports and import cycles).  The matching ledger event type is emitted by
# graph_dispatch_worker with the full structured problem in its payload.
BUDGET_PRECHECK_INSUFFICIENT_PROBLEM_CODES = frozenset(
    {"budget_precheck_insufficient"}
)
BUDGET_PRECHECK_BLOCKED_EVENT_TYPE = "budget_precheck_blocked"
BUDGET_PRECHECK_RECOVERY_COMMAND = "extend_budget"
BUDGET_PRECHECK_RECOVERY_FOLLOWUP_COMMAND = "retry_node"

# Default threshold for the human-gate wait escalation (knowledge_handoff /
# H1-H4 pending gates).  Callers may pass an explicit ``gate_wait_threshold_ms``
# (the route resolves the ``VIBELUTION_ANOMALY_GATE_WAIT_THRESHOLD_MS`` env
# override so this module stays a pure function of its inputs); each gate-wait
# entry may also carry its own ``thresholdMs``.
DEFAULT_GATE_WAIT_THRESHOLD_MS = 2 * 60 * 60 * 1000

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


def _as_int(value: Any) -> int | None:
    """Tolerant int read (bools are never ints here); None when unusable."""

    if isinstance(value, bool) or value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _iso_to_ms(value: str) -> int | None:
    """Parse one durable ISO-8601 timestamp into epoch ms; None when unusable."""

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


def _iso_ms(value: Any) -> int | None:
    return _iso_to_ms(str(value or ""))


def _capped_iso(value: str, cap_at: str) -> str:
    """Durable timestamp clamped to the projection instant.

    A future/garbage ``value`` must never make ``firstSeenAt`` follow
    ``lastSeenAt`` (the inbox contract fail-closes on that), so an unusable
    or out-of-range timestamp falls back to the projection instant.
    """

    value_ms = _iso_to_ms(value)
    cap_ms = _iso_to_ms(cap_at)
    if value_ms is None or cap_ms is None or value_ms > cap_ms:
        return cap_at
    return value


def _clean_evidence(*refs: str) -> list[str]:
    cleaned = [str(ref or "").strip() for ref in refs]
    return [ref for ref in cleaned if ref]


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
                # Retry budget exhausted means another retry_node can never
                # succeed (the frozen taxonomy already charged the budget);
                # the only real way forward is a ledger-authority rebuild,
                # so the recommended family is reconcile_run (archive_run
                # as the terminal alternative), not retry_node.
                recommended_action=HumanActionFamily.RECONCILE_RUN.value,
                evidence=[_evidence_ref("node", node_id)],
            )
        )
    return items


def _convergence_exhausted_item(
    state: Any,
    base: AnomalyInboxScope,
    fallback_at: str,
) -> AnomalyInboxItem | None:
    """The convergence review-chain round budget is spent and waiting on a user.

    Read straight from the snapshot's ``convergence`` phase (state v2 projects
    ``outcome == "exhausted"`` with ``actionability == "waiting_user"`` when
    the hard round limit is reached without an accepted verdict): the chain
    cannot advance by itself, so this is a human gate, not a retry.
    """

    convergence = _get(state, "convergence")
    if not isinstance(convergence, Mapping):
        return None
    outcome = _text(convergence, "outcome").lower()
    if outcome != "exhausted":
        return None
    round_index = _as_int(_get(convergence, "roundIndex")) or 0
    round_budget = _as_int(_get(convergence, "roundBudget")) or 0
    updated_at = _capped_iso(
        _first_non_empty(_text(convergence, "updatedAt"), fallback_at),
        fallback_at,
    )
    return AnomalyInboxItem.create(
        kind=ANOMALY_KIND_NEEDS_HUMAN_GATE,
        scope=base,
        first_seen_at=updated_at,
        last_seen_at=fallback_at,
        summary=(
            f"收敛评审轮预算已耗尽（第 {round_index}/{round_budget} 轮），"
            "等待人工决定后续动作（接受结论、分叉修订或重置题目）"
        ),
        recommended_action=None,
        evidence=_clean_evidence(
            "convergence:exhausted",
            f"convergenceRound:{round_index}/{round_budget}",
            _evidence_ref(
                "convergenceRoundId", _text(convergence, "latestHypothesisRoundId")
            ),
        ),
    )


def _digest_ttl_overdue_items(
    entries: list[Any],
    base: AnomalyInboxScope,
    fallback_at: str,
) -> list[AnomalyInboxItem]:
    """One item per meeting whose digest approval waited past the TTL.

    Entries are ``meeting_digest_ttl_mute_state`` results (the meeting
    runtime's own stop-loss verdict — same 判定口径, never re-derived here)
    annotated with ``meetingRoundId`` by the caller.  A mute state without a
    round id is skipped (fail-closed: no unattributable meeting item).
    """

    items: list[AnomalyInboxItem] = []
    for entry in entries:
        round_id = _text(entry, "meetingRoundId")
        if not round_id:
            continue
        overdue_ms = _as_int(_get(entry, "overdueMs"))
        ttl_ms = _as_int(_get(entry, "ttlMs"))
        digest_at = _capped_iso(
            _first_non_empty(_text(entry, "digestAt"), fallback_at), fallback_at
        )
        overdue_minutes = max(overdue_ms or 0, 0) // 60_000
        items.append(
            AnomalyInboxItem.create(
                kind=ANOMALY_KIND_NEEDS_HUMAN_GATE,
                scope=_with_scope_ids(base, meeting_round_id=round_id),
                first_seen_at=digest_at,
                last_seen_at=fallback_at,
                summary=(
                    f"会议纪要审批等待超过 TTL（已超时约 {overdue_minutes} 分钟），"
                    "讨论已自动暂停止损，等待人工审批纪要或恢复讨论"
                ),
                recommended_action=None,
                evidence=_clean_evidence(
                    _evidence_ref("meetingDigestTtlOverdue", round_id),
                    _evidence_ref("digestAtSource", _text(entry, "digestAtSource")),
                    f"ttlMs:{ttl_ms}" if ttl_ms is not None else "",
                    f"overdueMs:{overdue_ms}" if overdue_ms is not None else "",
                ),
            )
        )
    return items


def _gate_wait_items(
    entries: list[Any],
    base: AnomalyInboxScope,
    fallback_at: str,
    default_threshold_ms: int,
) -> list[AnomalyInboxItem]:
    """One item per human gate (knowledge_handoff / H1-H4 / closeout) waiting
    past its threshold.

    Entries carry ``gateKind``, ``gateId``, ``since`` (ISO) and optionally
    ``runId`` / ``requestId`` / ``thresholdMs``.  Entries without a usable
    ``since`` are skipped, and a wait at or under the threshold is not an
    escalation (fail-closed: only provable overdue waits surface).
    """

    fallback_ms = _iso_to_ms(fallback_at)
    items: list[AnomalyInboxItem] = []
    for entry in entries:
        gate_kind = _text(entry, "gateKind") or "unknown_gate"
        gate_id = _text(entry, "gateId") or gate_kind
        since_ms = _iso_ms(_text(entry, "since"))
        if fallback_ms is None or since_ms is None:
            continue
        threshold_ms = _as_int(_get(entry, "thresholdMs"))
        if threshold_ms is None or threshold_ms <= 0:
            threshold_ms = (
                default_threshold_ms
                if default_threshold_ms and default_threshold_ms > 0
                else DEFAULT_GATE_WAIT_THRESHOLD_MS
            )
        waited_ms = fallback_ms - since_ms
        if waited_ms <= threshold_ms:
            continue
        run_id = _text(entry, "runId")
        request_id = _text(entry, "requestId")
        items.append(
            AnomalyInboxItem.create(
                kind=ANOMALY_KIND_NEEDS_HUMAN_GATE,
                scope=_with_scope_ids(base, run_id=run_id),
                first_seen_at=_capped_iso(_text(entry, "since"), fallback_at),
                last_seen_at=fallback_at,
                summary=(
                    f"人工门 {gate_kind} 等待已超过阈值"
                    f"（约 {waited_ms // 60_000} 分钟 ≥ 阈值 "
                    f"{threshold_ms // 60_000} 分钟），需人工处理"
                ),
                recommended_action=None,
                evidence=_clean_evidence(
                    _evidence_ref("humanGateWait", gate_kind, gate_id),
                    f"waitedMs:{waited_ms}",
                    f"thresholdMs:{threshold_ms}",
                    _evidence_ref("gateRequest", request_id),
                ),
            )
        )
    return items


def _budget_precheck_items(
    entries: list[Any],
    base: AnomalyInboxScope,
    fallback_at: str,
) -> list[AnomalyInboxItem]:
    """One item per stage-boundary budget precheck block.

    Entries are ``budget_precheck_blocked`` payloads (the structured problem
    dict of ``StageBudgetAdmission`` plus run/node context).  Only real
    precheck codes become items; the extend_budget CTA numbers travel in the
    evidence refs and in the structured ``action`` built by
    ``attach_inbox_actions``.
    """

    items: list[AnomalyInboxItem] = []
    for entry in entries:
        code = _text(entry, "code")
        if code not in BUDGET_PRECHECK_INSUFFICIENT_PROBLEM_CODES:
            continue
        stage_id = _text(entry, "stageId")
        node_id = _text(entry, "nodeId")
        run_id = _first_non_empty(
            _text(entry, "runId"), _text(entry, "sourceId")
        )
        detected_at = _capped_iso(
            _first_non_empty(
                _text(entry, "occurredAt"), _text(entry, "detectedAt"), fallback_at
            ),
            fallback_at,
        )
        remaining = _as_int(_get(entry, "remainingTokens"))
        reference = _as_int(_get(entry, "referenceTokens"))
        suggested = _as_int(_get(entry, "suggestedExtensionTokens"))
        summary = _first_non_empty(
            _text(entry, "detail"),
            (
                f"阶段 {stage_id or '?'} 预算预检不足：剩余 "
                f"{remaining if remaining is not None else '?'} tokens 低于参考消耗 "
                f"{reference if reference is not None else '?'} tokens，"
                "需先补预算再重试"
            ),
        )
        items.append(
            AnomalyInboxItem.create(
                kind=ANOMALY_KIND_BUDGET_EXHAUSTED,
                scope=_with_scope_ids(base, run_id=run_id, node_id=node_id),
                first_seen_at=detected_at,
                last_seen_at=detected_at,
                summary=summary,
                # The recovery contract is extend_budget → retry_node; the
                # human action family stays retry_node while the structured
                # CTA action carries the one-click extend authorization.
                recommended_action=HumanActionFamily.RETRY_NODE.value,
                evidence=_clean_evidence(
                    f"problem:{code}",
                    _evidence_ref("stage", stage_id),
                    f"remainingTokens:{remaining}" if remaining is not None else "",
                    f"referenceTokens:{reference}" if reference is not None else "",
                    f"suggestedExtensionTokens:{suggested}"
                    if suggested is not None
                    else "",
                ),
            )
        )
    return items


def derive_gate_waits(state: Any) -> list[dict[str, Any]]:
    """Pure derivation of human-gate wait entries from one state-v2 snapshot.

    Two gate surfaces are read (both read-only projections of facts the
    snapshot already owns; nothing here talks to storage):

    - ``knowledge_handoff`` — one entry per collection request whose handoff
      is ``waiting_human`` (child run finished, human acceptance pending);
    - ``H1_problem_understanding`` / ``H2_hypothesis_selection`` /
      ``H3_research_plan`` / ``H4_external_output`` — one entry per pending
      program-delivery gate while the delivery review is ``waiting_human``.

    Every entry carries ``gateKind`` / ``gateId`` / ``since`` (the phase's
    durable ``updatedAt``) plus ``runId``/``requestId`` when known, so
    ``build_anomaly_inbox`` can threshold them without touching storage.
    """

    waits: list[dict[str, Any]] = []

    collection = _get(state, "collection")
    if isinstance(collection, Mapping):
        for request in _as_iterable(_get(collection, "requests")):
            if not isinstance(request, Mapping):
                continue
            handoff = _get(request, "handoff")
            if not isinstance(handoff, Mapping):
                continue
            if _text(handoff, "lifecycle") != "waiting_human":
                continue
            since = _text(handoff, "updatedAt")
            if not since:
                continue
            request_id = _text(request, "requestId")
            child_run = _get(request, "childRun")
            waits.append(
                {
                    "gateKind": "knowledge_handoff",
                    "gateId": request_id or "knowledge_handoff",
                    "since": since,
                    "runId": _text(child_run, "runId")
                    if isinstance(child_run, Mapping)
                    else "",
                    "requestId": request_id,
                }
            )

    program_delivery = _get(state, "programDelivery")
    if isinstance(program_delivery, Mapping):
        human_gates = _get(program_delivery, "humanGates")
        decisions = (
            _get(human_gates, "decisions")
            if isinstance(human_gates, Mapping)
            else None
        )
        review_waiting = (
            _text(program_delivery, "humanReviewStatus") == "waiting_human"
        )
        if review_waiting and isinstance(decisions, Mapping):
            since = _text(program_delivery, "updatedAt")
            for gate_key in sorted(decisions):
                if str(decisions.get(gate_key) or "").strip().lower() != "pending":
                    continue
                gate_id = str(gate_key or "").strip()
                if not gate_id or not since:
                    continue
                waits.append(
                    {
                        "gateKind": gate_id,
                        "gateId": gate_id,
                        "since": since,
                        "runId": _text(program_delivery, "outputRunId"),
                    }
                )
    return waits


def extend_budget_action(block: Mapping[str, Any]) -> dict[str, Any] | None:
    """Structured one-click extend CTA for one budget-precheck block.

    The command shape mirrors the verified recovery contract
    (``extend_budget`` with a ``limits.stageTokens`` increase, then
    ``retry_node`` on the blocked node): ``limits`` is directly usable as the
    command payload.  ``newStageTokens`` is the *new total* stage limit
    (current limit + suggested extension) because extend_budget only accepts
    increases above the prior value.  ``requiresConfirmation`` is part of the
    contract: the amount is displayed and the execution endpoint refuses any
    call without the explicit ``confirmed`` flag (误触防护), so the extend
    stays a human-authorized action — never an automatic top-up.
    """

    code = _text(block, "code")
    if code not in BUDGET_PRECHECK_INSUFFICIENT_PROBLEM_CODES:
        return None
    stage_id = _text(block, "stageId")
    stage_limit = _as_int(_get(block, "stageLimitTokens"))
    suggested = _as_int(_get(block, "suggestedExtensionTokens"))
    if not stage_id or stage_limit is None or stage_limit <= 0:
        return None
    if suggested is None or suggested <= 0:
        return None
    node_id = _text(block, "nodeId")
    run_id = _first_non_empty(_text(block, "runId"), _text(block, "sourceId"))
    new_stage_tokens = stage_limit + suggested
    return {
        "command": BUDGET_PRECHECK_RECOVERY_COMMAND,
        "params": {
            "runId": run_id,
            "nodeId": node_id,
            "stageId": stage_id,
            "stageLimitTokens": stage_limit,
            "suggestedExtensionTokens": suggested,
            "newStageTokens": new_stage_tokens,
            "limits": {"stageTokens": {stage_id: new_stage_tokens}},
        },
        "then": {
            "command": BUDGET_PRECHECK_RECOVERY_FOLLOWUP_COMMAND,
            "nodeId": node_id,
        },
        "hint": (
            "extend_budget 提高 stageTokens 后对该节点 retry_node，无需人工修数据"
        ),
        "requiresConfirmation": True,
        "confirmHint": (
            f"将阶段 {stage_id} 预算上限从 {stage_limit} 提高到 "
            f"{new_stage_tokens} tokens（+{suggested}）；补预算是人工授权动作，"
            "执行需二次确认"
        ),
    }


def attach_inbox_actions(
    inbox_payload: Mapping[str, Any],
    *,
    blocks: Any = None,
) -> dict[str, Any]:
    """Decorate the serialized inbox with the extend CTA ``action`` fields.

    Pure pass-through decorator: items are copied verbatim and only
    ``budget_precheck`` items gain an ``action`` (when a matching block with
    a computable extend contract exists).  Blocks are matched by
    ``(runId, nodeId)`` scope; the latest ``occurredAt`` wins when several
    blocks share a scope.
    """

    latest_by_scope: dict[tuple[str, str], Mapping[str, Any]] = {}

    def _scope_of(block: Mapping[str, Any]) -> tuple[str, str]:
        return (
            _first_non_empty(_text(block, "runId"), _text(block, "sourceId")),
            _text(block, "nodeId"),
        )

    def _occurred_at(block: Mapping[str, Any]) -> str:
        return _first_non_empty(_text(block, "occurredAt"), _text(block, "detectedAt"))

    for block in _as_iterable(blocks):
        if not isinstance(block, Mapping):
            continue
        if _text(block, "code") not in BUDGET_PRECHECK_INSUFFICIENT_PROBLEM_CODES:
            continue
        key = _scope_of(block)
        existing = latest_by_scope.get(key)
        if existing is None or _occurred_at(block) >= _occurred_at(existing):
            latest_by_scope[key] = block

    payload = dict(inbox_payload)
    items: list[dict[str, Any]] = []
    for raw_item in payload.get("items") or []:
        item = dict(raw_item) if isinstance(raw_item, Mapping) else raw_item
        if isinstance(item, dict):
            evidence = " ".join(str(ref) for ref in (item.get("evidence") or []))
            scope = item.get("scope") if isinstance(item.get("scope"), Mapping) else {}
            key = (str(scope.get("runId") or ""), str(scope.get("nodeId") or ""))
            if (
                item.get("kind") == ANOMALY_KIND_BUDGET_EXHAUSTED
                and "problem:budget_precheck_insufficient" in evidence
            ):
                block = latest_by_scope.get(key)
                action = extend_budget_action(block) if block else None
                if action is not None:
                    item["action"] = action
        items.append(item)
    payload["items"] = items
    return payload


class InboxActionConfirmationError(ValueError):
    """A CTA execution was refused (missing/invalid explicit confirmation)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def assert_extend_budget_confirmation(
    *,
    confirmed: Any,
    run_id: Any,
    stage_id: Any,
    stage_limit_tokens: Any,
    suggested_extension_tokens: Any,
) -> None:
    """误触防护 gate for the one-click extend CTA execution.

    The extend is a human-authorized budget decision: the execution endpoint
    MUST call this before submitting the command and refuse the request when
    the explicit ``confirmed`` flag is missing/false — displaying the amount
    alone is never consent.  The numeric inputs must be a concrete, positive
    extension against a known stage limit so the server computes the new
    stage total itself instead of trusting a pre-merged payload.
    """

    if confirmed is not True:
        raise InboxActionConfirmationError(
            "inbox_action_confirmation_required",
            "补预算是人工授权动作：缺少显式确认（confirmed=true），已拒绝执行",
        )
    if not str(run_id or "").strip():
        raise InboxActionConfirmationError(
            "inbox_action_run_required", "缺少目标运行 runId，已拒绝执行"
        )
    if not str(stage_id or "").strip():
        raise InboxActionConfirmationError(
            "inbox_action_stage_required", "缺少目标预算阶段 stageId，已拒绝执行"
        )
    stage_limit = _as_int(stage_limit_tokens)
    suggested = _as_int(suggested_extension_tokens)
    if stage_limit is None or stage_limit <= 0:
        raise InboxActionConfirmationError(
            "inbox_action_stage_limit_invalid",
            "stageLimitTokens 必须是正整数，已拒绝执行",
        )
    if suggested is None or suggested <= 0:
        raise InboxActionConfirmationError(
            "inbox_action_extension_invalid",
            "suggestedExtensionTokens 必须是正整数，已拒绝执行",
        )


def build_anomaly_inbox(
    state: Any = None,
    *,
    disputed_claims: Any = None,
    review_escalations: Any = None,
    drift_sentinel_hits: Any = None,
    retry_exhausted_nodes: Any = None,
    digest_ttl_overdues: Any = None,
    gate_waits: Any = None,
    budget_precheck_blocks: Any = None,
    gate_wait_threshold_ms: int = DEFAULT_GATE_WAIT_THRESHOLD_MS,
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

    convergence_item = _convergence_exhausted_item(state, base, fallback_at)
    if convergence_item is not None:
        items.append(convergence_item)

    items.extend(
        _digest_ttl_overdue_items(
            _as_iterable(digest_ttl_overdues), base, fallback_at
        )
    )
    items.extend(
        _gate_wait_items(
            _as_iterable(gate_waits), base, fallback_at, gate_wait_threshold_ms
        )
    )
    items.extend(
        _budget_precheck_items(
            _as_iterable(budget_precheck_blocks), base, fallback_at
        )
    )

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
