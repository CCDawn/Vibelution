"""Stage-boundary budget admission precheck (challenge chain guardrail).

SCI-091 (2026-09-01): challenge runs died mid-turn with "Challenge
invocation token budget is exhausted" because underfunded stages were only
observable after a real attempt had already burned its reservation. This
module gives the advancement boundary a forward visibility check: before a
new Agent attempt is created, compare the run's current stage remaining
capacity against a conservative reference consumption and refuse to start
the stage when even one typical attempt can no longer fit.

Reference consumption (deliberately conservative-low):

- median settled actual usage of the same question + same node (preferred)
  or the same question + same stage (fallback) across prior runs, read from
  the single budget fact source (``budget_receipts``);
- a small fixed default when no history exists, far below the documented
  real ~300K per-node consumption, so a normally funded run is never killed
  at the boundary (bias: pass and let the next boundary or the invocation
  preflight catch a genuinely underfunded attempt).

Fail-open contract: any evaluation error admits the attempt. Blocking is
only ever a deliberate, evidence-backed decision — never an internal
failure. System/human nodes reserve no invocation budget and are out of
scope. The check mirrors (never diverges from) the admission math of
``reserve_budget_authority``, so anything this module admits can still be
admitted there, and an ``extend_budget`` alone (budget_settled) makes a
blocked run retryable without manual data repair.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Any

from core.logging import debug

from .budget_authority_adapter import (
    _payload,
    _policy_limits,
    _stage_admitted_tokens,
    _usage_payload,
    _usage_tokens,
    stage_for_node,
)

#: Machine-readable failure code distinguishing this pre-flight block from a
#: mid-turn ``budget_exhausted`` or the stage-limit ``budget_safety_limit_reached``.
BUDGET_PRECHECK_INSUFFICIENT_CODE = "budget_precheck_insufficient"

#: No-history fallback. Far below the documented ~300K real formal-node
#: consumption, it only trips when the stage is already nearly empty, so a
#: normally funded run never gets blocked at the boundary.
DEFAULT_CONSERVATIVE_REFERENCE_TOKENS = 100_000

#: Operator-facing recovery contract: extend the budget, then retry the node.
#: Both steps reuse existing commands; no data repair is involved.
RECOVERY_COMMAND = "extend_budget"
RECOVERY_FOLLOWUP_COMMAND = "retry_node"

_EVALUATION_TIMEOUT_SECONDS = 10

_REFERENCE_BASIS_HISTORICAL_NODE = "historical_median_node"
_REFERENCE_BASIS_HISTORICAL_STAGE = "historical_median_stage"
_REFERENCE_BASIS_CONSERVATIVE_DEFAULT = "conservative_default"
_REFERENCE_BASIS_FAIL_OPEN = "evaluation_failed_fail_open"


@dataclass(frozen=True)
class StageBudgetAdmission:
    """Outcome of one stage-boundary budget admission evaluation."""

    run_id: str
    node_id: str
    stage_id: str
    admitted: bool
    stage_limit_tokens: int
    stage_consumed_tokens: int
    remaining_tokens: int
    reference_tokens: int
    reference_basis: str
    history_samples: int

    @property
    def failure_code(self) -> str:
        return BUDGET_PRECHECK_INSUFFICIENT_CODE

    @property
    def suggested_extension_tokens(self) -> int:
        return max(0, self.reference_tokens - self.remaining_tokens)

    def problem(self) -> dict[str, Any]:
        """Structured blocked problem: event payload + run problem projection."""

        return {
            "code": self.failure_code,
            "detail": (
                f"阶段 {self.stage_id} 剩余预算 {self.remaining_tokens} tokens，"
                f"低于一次典型消耗的参考值 {self.reference_tokens} tokens"
                f"（依据 {self.reference_basis}，样本 {self.history_samples}），"
                f"先 extend_budget 补足约 {self.suggested_extension_tokens} tokens 后重试"
            ),
            "stageId": self.stage_id,
            "nodeId": self.node_id,
            "stageLimitTokens": self.stage_limit_tokens,
            "stageConsumedTokens": self.stage_consumed_tokens,
            "remainingTokens": self.remaining_tokens,
            "referenceTokens": self.reference_tokens,
            "referenceBasis": self.reference_basis,
            "historySamples": self.history_samples,
            "suggestedExtensionTokens": self.suggested_extension_tokens,
            "recovery": {
                "command": RECOVERY_COMMAND,
                "then": RECOVERY_FOLLOWUP_COMMAND,
                "hint": (
                    "extend_budget 提高 stageTokens 后对该节点 retry_node，"
                    "无需人工修数据"
                ),
            },
        }


def evaluate_stage_budget_admission(
    store: Any,
    *,
    run_id: str,
    node_id: str,
    actor_kind: str | None = None,
) -> StageBudgetAdmission:
    """Evaluate one stage boundary. Always returns a decision; never raises.

    Non-agent nodes (``actor_kind != "agent"``) reserve no invocation budget
    and are admitted unconditionally (``reference_basis`` marks them out of
    scope via the fail-open basis). Corrupt snapshots, missing runs, ledger
    read failures — every internal problem fails open with a debug record.
    """

    if actor_kind is not None and str(actor_kind) != "agent":
        return _fail_open(run_id, node_id, reason="non_agent_node")
    try:
        return _evaluate(store, run_id=run_id, node_id=node_id)
    except Exception as exc:  # noqa: BLE001 - fail-open is the documented contract
        debug.warning(
            f"budget stage admission failed open run={run_id} node={node_id} "
            f"error={type(exc).__name__}: {exc}"
        )
        return _fail_open(run_id, node_id, reason=type(exc).__name__)


def _fail_open(run_id: str, node_id: str, *, reason: str) -> StageBudgetAdmission:
    return StageBudgetAdmission(
        run_id=run_id,
        node_id=node_id,
        stage_id=stage_for_node(node_id),
        admitted=True,
        stage_limit_tokens=0,
        stage_consumed_tokens=0,
        remaining_tokens=0,
        reference_tokens=0,
        reference_basis=f"{_REFERENCE_BASIS_FAIL_OPEN}:{reason}",
        history_samples=0,
    )


def _evaluate(store: Any, *, run_id: str, node_id: str) -> StageBudgetAdmission:
    stage_id = stage_for_node(node_id)

    def read_run(uow):
        return uow.repository.execute(
            "SELECT input_snapshot_json, safety_limits_json, question_id "
            "FROM workflow_runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()

    run_row = store.submit(read_run, force_flush=True).result(
        timeout=_EVALUATION_TIMEOUT_SECONDS
    )
    if run_row is None:
        # No run row: not this module's decision — the dispatch path will
        # fail structurally on its own. Fail open.
        return _fail_open(run_id, node_id, reason="run_row_missing")

    snapshot = _payload(run_row[0], label="input_snapshot_json")
    operator_limits = _payload(run_row[1], label="safety_limits_json")
    question_id = str(run_row[2] or "").strip()

    limits = _policy_limits(snapshot, stage_id, operator_limits=operator_limits)

    def read_stage_receipts(uow):
        return uow.repository.execute(
            "SELECT status, reserved_json, settled_json FROM budget_receipts "
            "WHERE run_id = ? AND stage_id = ?",
            (run_id, stage_id),
        ).fetchall()

    stage_rows = store.submit(read_stage_receipts, force_flush=True).result(
        timeout=_EVALUATION_TIMEOUT_SECONDS
    )
    # Same admission math as reserve_budget_authority: live reservations
    # occupy their full estimate, settled attempts occupy their real usage.
    consumed = sum(
        _stage_admitted_tokens(
            {
                "status": str(row[0] or ""),
                "reserved_json": row[1],
                "settled_json": row[2],
            }
        )
        for row in stage_rows or []
    )
    remaining = max(0, int(limits["tokens"]) - consumed)

    reference_tokens, reference_basis, samples = _reference_consumption(
        store,
        question_id=question_id,
        exclude_run_id=run_id,
        node_id=node_id,
        stage_id=stage_id,
    )
    return StageBudgetAdmission(
        run_id=run_id,
        node_id=node_id,
        stage_id=stage_id,
        admitted=remaining >= reference_tokens,
        stage_limit_tokens=int(limits["tokens"]),
        stage_consumed_tokens=consumed,
        remaining_tokens=remaining,
        reference_tokens=reference_tokens,
        reference_basis=reference_basis,
        history_samples=samples,
    )


def _reference_consumption(
    store: Any,
    *,
    question_id: str,
    exclude_run_id: str,
    node_id: str,
    stage_id: str,
) -> tuple[int, str, int]:
    """Median historical settled usage for the same question.

    Node-level samples win over stage-level samples so the reference tracks
    the actual node about to start, not the looser stage aggregate. Only
    receipts with a real usage observation count; estimates never become
    history.
    """

    if not question_id:
        return (
            DEFAULT_CONSERVATIVE_REFERENCE_TOKENS,
            _REFERENCE_BASIS_CONSERVATIVE_DEFAULT,
            0,
        )

    def read_history(uow):
        return uow.repository.execute(
            "SELECT na.node_id, br.settled_json FROM budget_receipts br "
            "JOIN workflow_runs wr ON wr.run_id = br.run_id "
            "JOIN node_attempts na ON na.node_run_id = br.node_run_id "
            "WHERE wr.question_id = ? AND br.run_id != ?",
            (question_id, exclude_run_id),
        ).fetchall()

    history_rows = store.submit(read_history, force_flush=True).result(
        timeout=_EVALUATION_TIMEOUT_SECONDS
    )
    node_samples: list[int] = []
    stage_samples: list[int] = []
    for row in history_rows or []:
        history_node_id = str(row[0] or "").strip()
        if not history_node_id:
            continue
        try:
            settled = _payload(row[1], label="settled_json")
        except Exception:  # noqa: BLE001 - a corrupt history row is not evidence
            continue
        usage = _usage_payload(settled)
        if not usage and not settled.get("invocations"):
            continue
        tokens = _usage_tokens(settled)
        if history_node_id == node_id:
            node_samples.append(tokens)
        if stage_for_node(history_node_id) == stage_id:
            stage_samples.append(tokens)

    if node_samples:
        return (
            int(_median(node_samples)),
            _REFERENCE_BASIS_HISTORICAL_NODE,
            len(node_samples),
        )
    if stage_samples:
        return (
            int(_median(stage_samples)),
            _REFERENCE_BASIS_HISTORICAL_STAGE,
            len(stage_samples),
        )
    return (
        DEFAULT_CONSERVATIVE_REFERENCE_TOKENS,
        _REFERENCE_BASIS_CONSERVATIVE_DEFAULT,
        0,
    )


def _median(samples: list[int]) -> float:
    return statistics.median(samples)


__all__ = [
    "BUDGET_PRECHECK_INSUFFICIENT_CODE",
    "DEFAULT_CONSERVATIVE_REFERENCE_TOKENS",
    "RECOVERY_COMMAND",
    "RECOVERY_FOLLOWUP_COMMAND",
    "StageBudgetAdmission",
    "evaluate_stage_budget_admission",
]
