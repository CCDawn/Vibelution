"""Auditable iteration decision contract (five structured kinds only).

Graph routing and service transitions consume this module; free-form strings are rejected.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Mapping


class IterationDecisionKind(str, Enum):
    RERUN_SAME_PROTOCOL = "rerun_same_protocol"
    REVISE_PROTOCOL = "revise_protocol"
    PROMOTE_CANDIDATE = "promote_candidate"
    ROLLBACK_CANDIDATE = "rollback_candidate"
    STOP = "stop"


class CompletionKind(str, Enum):
    """How a WorkflowRun reached a terminal / branched status."""

    NONE = ""
    BRANCHED_REVISION = "branched_revision"
    STOPPED = "stopped"
    PROMOTED = "promoted"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"


class PromotionOperation(str, Enum):
    PROMOTE = "promote"
    ROLLBACK = "rollback"


# Next graph node id for each kind. revise_protocol has no in-run edge (forks child).
ITERATION_ROUTE_TARGETS: dict[IterationDecisionKind, str | None] = {
    IterationDecisionKind.RERUN_SAME_PROTOCOL: "controlled_run",
    IterationDecisionKind.REVISE_PROTOCOL: None,  # ends parent; service forks child
    IterationDecisionKind.PROMOTE_CANDIDATE: "candidate_promotion",
    IterationDecisionKind.ROLLBACK_CANDIDATE: "candidate_promotion",
    IterationDecisionKind.STOP: "result_package",
}

# Definition edgeIds that must exist for runnable routes (not revise fork).
ITERATION_DEFINITION_EDGE_IDS: dict[IterationDecisionKind, str | None] = {
    IterationDecisionKind.RERUN_SAME_PROTOCOL: "e_decision_rerun",
    IterationDecisionKind.REVISE_PROTOCOL: None,
    IterationDecisionKind.PROMOTE_CANDIDATE: "e_decision_promo",
    IterationDecisionKind.ROLLBACK_CANDIDATE: "e_decision_rollback",
    IterationDecisionKind.STOP: "e_decision_stop",
}

DEFAULT_ITERATION_BUDGET = 3


class IterationDecisionError(ValueError):
    def __init__(self, message: str, *, code: str = "invalid_iteration_decision"):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class IterationDecisionRecord:
    decisionId: str
    decisionKind: IterationDecisionKind
    runId: str
    nodeRunId: str
    iterationAttempt: int
    selectedCandidateRef: str = ""
    baselineRef: str = ""
    frozenProtocolRef: str = ""
    evaluationReportRef: str = ""
    reason: str = ""
    decidedBy: str = ""
    decidedAt: str = ""
    idempotencyKey: str = ""
    parentDecisionId: str = ""
    supersedesDecisionId: str = ""
    terminalReason: str = ""
    promotionOperation: str = ""  # promote | rollback when applicable
    budgetMax: int = DEFAULT_ITERATION_BUDGET

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["decisionKind"] = self.decisionKind.value
        return data

    @staticmethod
    def from_dict(raw: Mapping[str, Any]) -> "IterationDecisionRecord":
        kind_raw = str(raw.get("decisionKind") or "").strip()
        try:
            kind = IterationDecisionKind(kind_raw)
        except ValueError as exc:
            raise IterationDecisionError(
                f"Unknown iteration decisionKind: {kind_raw!r}",
                code="unknown_decision_kind",
            ) from exc
        return IterationDecisionRecord(
            decisionId=str(raw.get("decisionId") or ""),
            decisionKind=kind,
            runId=str(raw.get("runId") or ""),
            nodeRunId=str(raw.get("nodeRunId") or ""),
            iterationAttempt=int(raw.get("iterationAttempt") or 0),
            selectedCandidateRef=str(raw.get("selectedCandidateRef") or ""),
            baselineRef=str(raw.get("baselineRef") or ""),
            frozenProtocolRef=str(raw.get("frozenProtocolRef") or ""),
            evaluationReportRef=str(raw.get("evaluationReportRef") or ""),
            reason=str(raw.get("reason") or ""),
            decidedBy=str(raw.get("decidedBy") or ""),
            decidedAt=str(raw.get("decidedAt") or ""),
            idempotencyKey=str(raw.get("idempotencyKey") or ""),
            parentDecisionId=str(raw.get("parentDecisionId") or ""),
            supersedesDecisionId=str(raw.get("supersedesDecisionId") or ""),
            terminalReason=str(raw.get("terminalReason") or ""),
            promotionOperation=str(raw.get("promotionOperation") or ""),
            budgetMax=int(raw.get("budgetMax") or DEFAULT_ITERATION_BUDGET),
        )


def parse_decision_kind(value: str | IterationDecisionKind | None) -> IterationDecisionKind:
    if isinstance(value, IterationDecisionKind):
        return value
    raw = str(value or "").strip()
    try:
        return IterationDecisionKind(raw)
    except ValueError as exc:
        raise IterationDecisionError(
            f"Unknown iteration decisionKind: {raw!r}",
            code="unknown_decision_kind",
        ) from exc


def route_target_for_decision(kind: IterationDecisionKind | str) -> str | None:
    k = parse_decision_kind(kind)
    return ITERATION_ROUTE_TARGETS[k]


def validate_decision_payload(
    raw: Mapping[str, Any],
    *,
    require_ids: bool = False,
) -> IterationDecisionRecord:
    """Validate and normalize a decision payload (rejects unknown kinds)."""
    record = IterationDecisionRecord.from_dict(raw)
    if require_ids and not record.decisionId:
        raise IterationDecisionError("decisionId is required", code="missing_decision_id")
    if record.decisionKind is IterationDecisionKind.STOP and not (
        record.terminalReason or record.reason
    ):
        raise IterationDecisionError(
            "stop requires terminalReason (or reason)",
            code="missing_terminal_reason",
        )
    if record.decisionKind is IterationDecisionKind.ROLLBACK_CANDIDATE:
        target = record.selectedCandidateRef or record.baselineRef
        if not target:
            raise IterationDecisionError(
                "rollback_candidate requires selectedCandidateRef or baselineRef",
                code="missing_rollback_target",
            )
    return record


def normalize_decision_dict(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Return a mutable validated dict; fixes frozen dataclass mutation issue."""
    kind = parse_decision_kind(raw.get("decisionKind"))
    base = dict(raw)
    base["decisionKind"] = kind.value
    if kind is IterationDecisionKind.PROMOTE_CANDIDATE:
        base["promotionOperation"] = PromotionOperation.PROMOTE.value
    elif kind is IterationDecisionKind.ROLLBACK_CANDIDATE:
        base["promotionOperation"] = PromotionOperation.ROLLBACK.value
        if not (base.get("selectedCandidateRef") or base.get("baselineRef")):
            raise IterationDecisionError(
                "rollback_candidate requires selectedCandidateRef or baselineRef",
                code="missing_rollback_target",
            )
    elif kind is IterationDecisionKind.STOP:
        if not (str(base.get("terminalReason") or "").strip() or str(base.get("reason") or "").strip()):
            raise IterationDecisionError(
                "stop requires terminalReason (or reason)",
                code="missing_terminal_reason",
            )
        if not base.get("terminalReason"):
            base["terminalReason"] = str(base.get("reason") or "")
    # Validate via record
    IterationDecisionRecord.from_dict(base)
    return base


def check_rerun_budget(
    *,
    current_attempt: int,
    budget_max: int = DEFAULT_ITERATION_BUDGET,
) -> None:
    """Raise if another rerun would exceed the frozen protocol budget.

    current_attempt is the last completed controlled_run attempt (1-based).
    A new rerun would become current_attempt + 1.
    """
    max_allowed = max(1, int(budget_max or DEFAULT_ITERATION_BUDGET))
    if int(current_attempt) >= max_allowed:
        raise IterationDecisionError(
            f"iteration budget exhausted: attempt={current_attempt} budgetMax={max_allowed}",
            code="iteration_budget_exhausted",
        )


def promotion_operation_for(kind: IterationDecisionKind | str) -> str | None:
    k = parse_decision_kind(kind)
    if k is IterationDecisionKind.PROMOTE_CANDIDATE:
        return PromotionOperation.PROMOTE.value
    if k is IterationDecisionKind.ROLLBACK_CANDIDATE:
        return PromotionOperation.ROLLBACK.value
    return None
