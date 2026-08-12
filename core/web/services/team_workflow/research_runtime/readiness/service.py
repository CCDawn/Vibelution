"""NodeReadinessService — the single executable-ability authority.

Definition node set must exactly equal the evaluator registry key set;
the service fails at construction otherwise (spec 9.3). Evaluation is
read-only; command acceptance re-evaluates without the cache.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable, Mapping
from typing import Any

from core.research.workflow.contracts import NodeReadiness
from core.research.workflow.definition import build_challenge_cup_workflow_definition
from core.research.workflow.models import WorkflowNodeSpec

from .common import (
    CommonReadinessResult,
    DomainReadinessContext,
    DomainVerdict,
    RunSnapshot,
    blocker,
    evaluate_common,
)
from .evidence import evaluate_evidence_relations
from .experiment import (
    evaluate_hypothesis_design,
    evaluate_protocol_design,
    evaluate_protocol_freeze,
    evaluate_protocol_review,
    evaluate_smoke_gate,
)
from .iteration import (
    evaluate_candidate_promotion,
    evaluate_controlled_run,
    evaluate_iteration_decision,
    evaluate_result_evaluation,
    evaluate_result_package,
    evaluate_version_governance,
)
from .knowledge import evaluate_knowledge_handoff, evaluate_knowledge_ingestion
from .source_collection import evaluate_source_extraction, evaluate_source_finding

EvaluatorFn = Callable[
    [RunSnapshot, WorkflowNodeSpec, CommonReadinessResult, DomainReadinessContext],
    DomainVerdict,
]

CACHE_MAX_ENTRIES = 256


class NodeReadinessService:
    def __init__(
        self,
        *,
        run_source: Callable[[str], RunSnapshot | None],
        attempt_count_source: Callable[[str, str], int] | None = None,
        definition: Any | None = None,
    ) -> None:
        self._run_source = run_source
        self._attempt_count_source = attempt_count_source or (lambda run_id, node_id: 0)
        self._definition = definition or build_challenge_cup_workflow_definition()
        self._node_by_id: dict[str, WorkflowNodeSpec] = {
            node.nodeId: node for node in self._definition.nodes
        }
        self._registry: dict[str, EvaluatorFn] = _build_registry()
        self._cache: OrderedDict[tuple[str, ...], NodeReadiness] = OrderedDict()
        self.assert_registry_complete()

    def assert_registry_complete(self) -> None:
        missing = sorted(set(self._node_by_id) - set(self._registry))
        if missing:
            raise AssertionError(f"readiness registry missing evaluators for: {missing}")

    def evaluator_for(self, node_id: str) -> EvaluatorFn | None:
        return self._registry.get(node_id)

    def evaluate(
        self,
        *,
        team_id: str,
        run_id: str,
        node_id: str,
        context: DomainReadinessContext,
        use_cache: bool = True,
        evaluated_at_ms: int | None = None,
    ) -> NodeReadiness:
        now_ms = evaluated_at_ms or int(time.time() * 1000)
        run = self._run_source(run_id)
        if run is None:
            return NodeReadiness(
                run_id=run_id,
                team_id=team_id,
                node_id=node_id,
                run_version=0,
                ready=False,
                evaluated_at_ms=now_ms,
                domain_revision_vector={},
                accepted_handoff_ids=(),
                input_artifact_refs=(),
                actor=_not_ready_actor(),
                budget=_not_ready_budget(""),
                blockers=(
                    blocker("run_not_found", "运行不存在", f"找不到 run {run_id}", category="state"),
                ),
            )
        if run.team_id != team_id:
            return NodeReadiness(
                run_id=run_id,
                team_id=team_id,
                node_id=node_id,
                run_version=run.run_version,
                ready=False,
                evaluated_at_ms=now_ms,
                domain_revision_vector={},
                accepted_handoff_ids=(),
                input_artifact_refs=(),
                actor=_not_ready_actor(),
                budget=_not_ready_budget(run.team_id),
                blockers=(
                    blocker(
                        "team_scope_mismatch",
                        "团队作用域不一致",
                        f"run 属于 {run.team_id}，请求 teamId={team_id}",
                        category="scope",
                    ),
                ),
            )

        node = self._node_by_id.get(node_id)
        if node is None:
            return NodeReadiness(
                run_id=run_id,
                team_id=team_id,
                node_id=node_id,
                run_version=run.run_version,
                ready=False,
                evaluated_at_ms=now_ms,
                domain_revision_vector={},
                accepted_handoff_ids=(),
                input_artifact_refs=(),
                actor=_not_ready_actor(),
                budget=_not_ready_budget(""),
                blockers=(
                    blocker("unknown_node", "未知节点", f"{node_id} 不属于工作流定义", category="state"),
                ),
            )

        cache_key = _cache_key(team_id, run_id, run.run_version, node_id, context)
        if use_cache and cache_key in self._cache:
            hit = self._cache[cache_key]
            self._cache.move_to_end(cache_key)
            return hit

        common = evaluate_common(
            run=run,
            node=node,
            requested_team_id=team_id,
            definition_node_ids=set(self._node_by_id),
            live_attempt_count=self._attempt_count_source(run_id, node_id),
            context=context,
        )
        evaluator = self._registry[node_id]
        verdict = evaluator(run=run, node=node, common=common, context=context)

        readiness = NodeReadiness(
            run_id=run_id,
            team_id=team_id,
            node_id=node_id,
            run_version=run.run_version,
            ready=not common.blockers and not verdict.blockers,
            evaluated_at_ms=now_ms,
            domain_revision_vector=dict(verdict.revision_vector or common.domain_revision_vector),
            accepted_handoff_ids=common.accepted_handoff_ids,
            input_artifact_refs=tuple(common.input_artifact_refs) + tuple(verdict.input_artifact_refs),
            actor=common.actor,
            budget=common.budget,
            blockers=common.blockers + verdict.blockers,
        )
        if use_cache:
            self._remember(cache_key, readiness)
        return readiness

    def _remember(self, key: tuple[str, ...], readiness: NodeReadiness) -> None:
        self._cache[key] = readiness
        self._cache.move_to_end(key)
        while len(self._cache) > CACHE_MAX_ENTRIES:
            self._cache.popitem(last=False)

    def invalidate(self, team_id: str, run_id: str, run_version: int | None = None) -> None:
        for key in list(self._cache):
            if key[0] == team_id and key[1] == run_id:
                if run_version is None or key[2] == run_version:
                    self._cache.pop(key, None)

    @property
    def cache_size(self) -> int:
        return len(self._cache)


def _cache_key(
    team_id: str,
    run_id: str,
    run_version: int,
    node_id: str,
    context: DomainReadinessContext,
) -> tuple[str, ...]:
    vector = context.domain_revision_vector(team_id, run_id)
    encoded = ",".join(f"{key}={value}" for key, value in sorted(vector.items()))
    return (team_id, run_id, run_version, node_id, encoded)


def _build_registry() -> dict[str, EvaluatorFn]:
    return {
        "source_finding": evaluate_source_finding,
        "source_extraction": evaluate_source_extraction,
        "evidence_relations": evaluate_evidence_relations,
        "knowledge_ingestion": evaluate_knowledge_ingestion,
        "knowledge_handoff": evaluate_knowledge_handoff,
        "hypothesis_design": evaluate_hypothesis_design,
        "protocol_design": evaluate_protocol_design,
        "protocol_review": evaluate_protocol_review,
        "protocol_freeze": evaluate_protocol_freeze,
        "smoke_gate": evaluate_smoke_gate,
        "controlled_run": evaluate_controlled_run,
        "result_evaluation": evaluate_result_evaluation,
        "iteration_decision": evaluate_iteration_decision,
        "version_governance": evaluate_version_governance,
        "candidate_promotion": evaluate_candidate_promotion,
        "result_package": evaluate_result_package,
    }


def _not_ready_actor() -> Any:
    from core.research.workflow.contracts import ActorReadiness

    return ActorReadiness(configured=False, resolvable=False, binding_snapshot_id=None)


def _not_ready_budget(policy_hash: str) -> Any:
    from core.research.workflow.contracts import BudgetReadiness

    return BudgetReadiness(policy_hash=policy_hash, available=False, reason="not_evaluated")
