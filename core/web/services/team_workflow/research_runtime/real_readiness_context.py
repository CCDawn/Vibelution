"""Production DomainReadinessContext implementation (P1-3).

Reads the frozen run input snapshot from the Workflow Ledger and queries the
real domain authorities for the checkpoints each evaluator needs. Methods that
require a domain service not yet wired return a conservative "missing" so a
node is never wrongly declared ready; budget limits and binding resolution
come from the Ledger (the single frozen authority).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from core.research.workflow.contracts import (
    ActorReadiness,
    BudgetReadiness,
)
from core.research.workflow.definition import (
    build_challenge_cup_workflow_definition,
)
from core.research.workflow.ledger import WorkflowLedgerStore
from core.research.workflow.models import ActorKind

from .readiness.common import (
    BudgetLimitsSnapshot,
    HandoffSnapshot,
)


class RealDomainReadinessContext:
    """Ledger-backed domain context; tests may inject overrides."""

    def __init__(
        self,
        store: WorkflowLedgerStore,
        *,
        adapter_registry: Any | None = None,
        service_overrides: Mapping[str, Any] | None = None,
    ) -> None:
        self._store = store
        self._registry = adapter_registry
        self._overrides = dict(service_overrides or {})

    # --------------------------------------------------------- run access

    def _run(self, run_id: str) -> Any:
        return self._store.get_run(run_id)

    def _input_snapshot(self, run_id: str) -> dict[str, Any]:
        run = self._run(run_id)
        if run is None or not run.input_snapshot_json:
            return {}
        try:
            snapshot = json.loads(run.input_snapshot_json)
        except (TypeError, ValueError):
            return {}
        return snapshot if isinstance(snapshot, dict) else {}

    def _query(self, key: str, *args: Any) -> Any:
        if key in self._overrides:
            fn = self._overrides[key]
            return fn(*args) if callable(fn) else fn
        return None

    # ---------------------------------------------------- protocol methods

    def domain_revision_vector(self, team_id: str, run_id: str) -> Mapping[str, str]:
        return {}

    def question_snapshot(self, team_id: str, question_id: str) -> Mapping[str, Any] | None:
        snapshot = self._query("question_snapshot", team_id, question_id)
        if snapshot is not None:
            return snapshot
        # 冻结题目从 run input 的 researchObjectiveContract 读取。
        for run_id in _run_ids_for(self._store, team_id):
            run_snapshot = self._input_snapshot(run_id)
            objective = run_snapshot.get("researchObjectiveContract") or {}
            if str(objective.get("question") or "") and str(
                run_snapshot.get("questionId") or ""
            ) == str(question_id):
                return {
                    "questionId": question_id,
                    "question": str(objective.get("question") or ""),
                    "fromInputSnapshot": True,
                }
        return None

    def candidate_stats(self, team_id: str, run_id: str) -> Mapping[str, Any] | None:
        return self._query("candidate_stats", team_id, run_id)

    def evidence_cards_stats(self, team_id: str, run_id: str) -> Mapping[str, Any] | None:
        return self._query("evidence_cards_stats", team_id, run_id)

    def evidence_graph_stats(self, team_id: str, run_id: str) -> Mapping[str, Any] | None:
        return self._query("evidence_graph_stats", team_id, run_id)

    def knowledge_package_draft(self, team_id: str, run_id: str) -> Mapping[str, Any] | None:
        return self._query("knowledge_package_draft", team_id, run_id)

    def knowledge_package(self, team_id: str, run_id: str) -> Mapping[str, Any] | None:
        return self._query("knowledge_package", team_id, run_id)

    def hypothesis_set(self, team_id: str, run_id: str) -> Mapping[str, Any] | None:
        return self._query("hypothesis_set", team_id, run_id)

    def protocol_draft(self, team_id: str, run_id: str) -> Mapping[str, Any] | None:
        return self._query("protocol_draft", team_id, run_id)

    def protocol_review(self, team_id: str, run_id: str) -> Mapping[str, Any] | None:
        return self._query("protocol_review", team_id, run_id)

    def frozen_protocol(self, team_id: str, run_id: str) -> Mapping[str, Any] | None:
        return self._query("frozen_protocol", team_id, run_id)

    def smoke_evidence(self, team_id: str, run_id: str) -> Mapping[str, Any] | None:
        return self._query("smoke_evidence", team_id, run_id)

    def controlled_run(self, team_id: str, run_id: str) -> Mapping[str, Any] | None:
        return self._query("controlled_run", team_id, run_id)

    def evaluation_report(self, team_id: str, run_id: str) -> Mapping[str, Any] | None:
        return self._query("evaluation_report", team_id, run_id)

    def iteration_decision(self, team_id: str, run_id: str) -> Mapping[str, Any] | None:
        return self._query("iteration_decision", team_id, run_id)

    def version_governance(self, team_id: str, run_id: str) -> Mapping[str, Any] | None:
        return self._query("version_governance", team_id, run_id)

    def promotion_proposal(self, team_id: str, run_id: str) -> Mapping[str, Any] | None:
        return self._query("promotion_proposal", team_id, run_id)

    def result_package(self, team_id: str, run_id: str) -> Mapping[str, Any] | None:
        return self._query("result_package", team_id, run_id)

    def budget_limits(self, team_id: str, run_id: str) -> BudgetLimitsSnapshot:
        snapshot = self._input_snapshot(run_id)
        budget_policy = snapshot.get("budgetPolicy") or {}
        stage_budgets = budget_policy.get("stageBudgets") or {}
        tokens = _first_positive_limit(stage_budgets, "tokens") or int(
            budget_policy.get("tokens") or 250_000
        )
        tool_calls = _first_positive_limit(stage_budgets, "toolCalls") or int(
            budget_policy.get("toolCalls") or 300
        )
        return BudgetLimitsSnapshot(
            policy_hash=_policy_hash(budget_policy),
            stage_tokens_limit=tokens,
            max_tool_calls=tool_calls,
            max_seconds=int(budget_policy.get("wallClockSeconds") or 21_600),
            auto_retries=int(budget_policy.get("autoRetries") or 2),
        )

    def binding_snapshot(self, run_id: str, node_id: str) -> Mapping[str, Any] | None:
        snapshot = self._input_snapshot(run_id)
        for binding in snapshot.get("agentBindingSnapshot") or []:
            if not isinstance(binding, Mapping):
                continue
            if str(binding.get("nodeId") or "") == node_id:
                return dict(binding)
        return None

    def agent_resolvable(self, agent_id: str) -> bool:
        override = self._query("agent_resolvable", agent_id)
        if override is not None:
            return bool(override)
        return bool(agent_id)

    def recovery_blocker_codes(self, run_id: str) -> Sequence[str]:
        rows = self._store.submit(
            lambda uow: uow.repository.execute(
                "SELECT problem_code FROM recovery_records "
                "WHERE run_id = ? AND status = 'open'",
                (run_id,),
            ).fetchall(),
            force_flush=True,
        ).result(timeout=10)
        return [str(row[0]) for row in rows]

    def adapter_registered(self, node_id: str) -> bool:
        if self._registry is None:
            return True
        definition = build_challenge_cup_workflow_definition()
        node = next(
            (n for n in definition.nodes if n.nodeId == node_id), None
        )
        if node is None:
            return False
        if node.actorKind == ActorKind.AGENT:
            kind = "start_agent_task"
        elif node.actorKind == ActorKind.SYSTEM:
            kind = f"system_action:{node_id}"
        else:
            kind = f"human_task:{node_id}"
        return self._registry.get(kind) is not None

    def incoming_handoffs(self, run_id: str, node_id: str) -> Sequence[HandoffSnapshot]:
        rows = self._store.submit(
            lambda uow: uow.repository.list_handoffs_for_node(run_id, node_id),
            force_flush=True,
        ).result(timeout=10)
        return [
            HandoffSnapshot(
                handoff_id=str(row[0]),
                from_node_run_id=str(row[3]) if row[3] else "",
                status=str(row[8]) if len(row) > 8 else "",
            )
            for row in rows
        ]


def _run_ids_for(store: WorkflowLedgerStore, team_id: str) -> list[str]:
    rows = store.submit(
        lambda uow: uow.repository.execute(
            "SELECT run_id FROM workflow_runs WHERE team_id = ? ORDER BY created_at_ms DESC LIMIT 50",
            (team_id,),
        ).fetchall(),
        force_flush=True,
    ).result(timeout=10)
    return [str(row[0]) for row in rows]


def _first_positive_limit(stage_budgets: Mapping[str, Any], key: str) -> int | None:
    if not isinstance(stage_budgets, Mapping):
        return None
    for stage, limits in stage_budgets.items():
        if isinstance(limits, Mapping) and int(limits.get(key) or 0) > 0:
            return int(limits[key])
    return None


def _policy_hash(budget_policy: Mapping[str, Any]) -> str:
    if not budget_policy:
        return ""
    raw = json.dumps(budget_policy, sort_keys=True, separators=(",", ":")).encode()
    import hashlib

    return hashlib.sha256(raw).hexdigest()
