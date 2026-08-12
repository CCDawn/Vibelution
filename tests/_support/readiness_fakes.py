"""Fake DomainReadinessContext + run/definition helpers for T2 readiness tests."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from core.research.workflow.contracts.node_readiness import (
    ActorReadiness,
    BudgetReadiness,
)
from core.research.workflow.definition import build_challenge_cup_workflow_definition
from core.research.workflow.models import ActorKind

from core.web.services.team_workflow.research_runtime.readiness.common import (
    BudgetLimitsSnapshot,
    DomainReadinessContext,
    HandoffSnapshot,
    RunSnapshot,
)

DEFINITION = build_challenge_cup_workflow_definition()
DEFINITION_NODE_IDS = {node.nodeId for node in DEFINITION.nodes}


def make_run(
    run_id: str = "run-test",
    *,
    team_id: str = "research-team",
    status: str = "running",
    run_version: int = 1,
    question_id: str = "SCI-096",
    workflow_version_id: str = "challenge-cup-research-v2.1.0",
) -> RunSnapshot:
    return RunSnapshot(
        run_id=run_id,
        team_id=team_id,
        workflow_id="challenge-cup-research",
        workflow_version_id=workflow_version_id,
        project_id="challenge-sci-096",
        question_id=question_id,
        status=status,
        run_version=run_version,
        input_snapshot_hash="a" * 64,
    )


class FakeDomainContext(DomainReadinessContext):
    """Dict-driven fake; records every call so tests can assert read-only."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self._question: Mapping[str, Any] | None = {
            "questionId": "SCI-096",
            "snapshotHash": "q" * 64,
        }
        self._candidate_stats: Mapping[str, Any] | None = {"record_count": 5}
        self._evidence_cards: Mapping[str, Any] | None = {
            "card_count": 3,
            "missing_minimal_fields": [],
        }
        self._evidence_graph: Mapping[str, Any] | None = {
            "node_count": 4,
            "missing_link_count": 0,
            "waiver_count": 0,
        }
        self._knowledge_draft: Mapping[str, Any] | None = {"reviewable": True}
        self._knowledge_package: Mapping[str, Any] | None = {"accepted": True}
        self._hypothesis_set: Mapping[str, Any] | None = {"hypothesis_count": 2}
        self._protocol_draft: Mapping[str, Any] | None = {
            "dataset": True,
            "baseline": True,
            "metric": True,
            "seed": True,
            "budget": True,
            "stop_condition": True,
        }
        self._protocol_review: Mapping[str, Any] | None = {
            "blocking_issue_count": 0,
            "open_waivers": 0,
        }
        self._frozen_protocol: Mapping[str, Any] | None = {"version": "fp-1"}
        self._smoke_evidence: Mapping[str, Any] | None = {"released": True}
        self._controlled_run: Mapping[str, Any] | None = {
            "terminal": True,
            "logs": True,
            "metrics": True,
            "artifact_hash": True,
        }
        self._evaluation_report: Mapping[str, Any] | None = {
            "baseline_comparison": True,
            "failure_analysis": True,
            "confidence_bounds": True,
        }
        self._iteration_decision: Mapping[str, Any] | None = {
            "kind": "promote_candidate",
            "target_version": "v2",
            "lineage": True,
            "reason": True,
        }
        self._version_governance: Mapping[str, Any] | None = {
            "decision_kind": "promote_candidate",
            "candidate_hash": "h" * 64,
            "proposal": True,
        }
        self._result_package: Mapping[str, Any] | None = {
            "required_artifacts": True,
            "pending_human_tasks": 0,
            "terminal_reason": True,
        }
        self.revision_vector: Mapping[str, str] = {"source_collection": "rev-1"}
        self.budget: BudgetLimitsSnapshot = BudgetLimitsSnapshot(policy_hash="p-1")
        self.bindings: dict[str, Mapping[str, Any] | None] = {
            "source_finding": {"snapshotId": "bs-1", "agentId": "agent-a"},
            "source_extraction": {"snapshotId": "bs-2", "agentId": "agent-a"},
            "evidence_relations": {"snapshotId": "bs-3", "agentId": "agent-a"},
            "knowledge_ingestion": {"snapshotId": "bs-4", "agentId": "agent-a"},
            "hypothesis_design": {"snapshotId": "bs-5", "agentId": "agent-a"},
            "protocol_design": {"snapshotId": "bs-6", "agentId": "agent-a"},
            "protocol_review": {"snapshotId": "bs-7", "agentId": "agent-a"},
            "result_evaluation": {"snapshotId": "bs-8", "agentId": "agent-a"},
            "iteration_decision": {"snapshotId": "bs-9", "agentId": "agent-a"},
            "version_governance": {"snapshotId": "bs-10", "agentId": "agent-a"},
        }
        self.resolvable_agents: set[str] = {"agent-a"}
        self.recovery_codes: list[str] = []
        self.registered_adapters: set[str] = set(DEFINITION_NODE_IDS)
        self.handoffs: dict[str, list[HandoffSnapshot]] = {}

    def _note(self, method: str) -> None:
        self.calls.append(method)

    def domain_revision_vector(self, team_id: str, run_id: str) -> Mapping[str, str]:
        self._note("domain_revision_vector")
        return self.revision_vector

    def question_snapshot(
        self, team_id: str, question_id: str, *, run_id: str | None = None
    ) -> Mapping[str, Any] | None:
        self._note("question_snapshot")
        _ = (team_id, question_id, run_id)
        return self._question

    def candidate_stats(self, team_id: str, run_id: str) -> Mapping[str, Any] | None:
        self._note("candidate_stats")
        return self._candidate_stats

    def evidence_cards_stats(self, team_id: str, run_id: str) -> Mapping[str, Any] | None:
        self._note("evidence_cards_stats")
        return self._evidence_cards

    def evidence_graph_stats(self, team_id: str, run_id: str) -> Mapping[str, Any] | None:
        self._note("evidence_graph_stats")
        return self._evidence_graph

    def knowledge_package_draft(self, team_id: str, run_id: str) -> Mapping[str, Any] | None:
        self._note("knowledge_package_draft")
        return self._knowledge_draft

    def knowledge_package(self, team_id: str, run_id: str) -> Mapping[str, Any] | None:
        self._note("knowledge_package")
        return self._knowledge_package

    def hypothesis_set(self, team_id: str, run_id: str) -> Mapping[str, Any] | None:
        self._note("hypothesis_set")
        return self._hypothesis_set

    def protocol_draft(self, team_id: str, run_id: str) -> Mapping[str, Any] | None:
        self._note("protocol_draft")
        return self._protocol_draft

    def protocol_review(self, team_id: str, run_id: str) -> Mapping[str, Any] | None:
        self._note("protocol_review")
        return self._protocol_review

    def frozen_protocol(self, team_id: str, run_id: str) -> Mapping[str, Any] | None:
        self._note("frozen_protocol")
        return self._frozen_protocol

    def smoke_evidence(self, team_id: str, run_id: str) -> Mapping[str, Any] | None:
        self._note("smoke_evidence")
        return self._smoke_evidence

    def controlled_run(self, team_id: str, run_id: str) -> Mapping[str, Any] | None:
        self._note("controlled_run")
        return self._controlled_run

    def evaluation_report(self, team_id: str, run_id: str) -> Mapping[str, Any] | None:
        self._note("evaluation_report")
        return self._evaluation_report

    def iteration_decision(self, team_id: str, run_id: str) -> Mapping[str, Any] | None:
        self._note("iteration_decision")
        return self._iteration_decision

    def version_governance(self, team_id: str, run_id: str) -> Mapping[str, Any] | None:
        self._note("version_governance")
        return self._version_governance

    def promotion_proposal(self, team_id: str, run_id: str) -> Mapping[str, Any] | None:
        self._note("promotion_proposal")
        return self._version_governance

    def result_package(self, team_id: str, run_id: str) -> Mapping[str, Any] | None:
        self._note("result_package")
        return self._result_package

    def budget_limits(self, team_id: str, run_id: str) -> BudgetLimitsSnapshot:
        self._note("budget_limits")
        return self.budget

    def binding_snapshot(self, run_id: str, node_id: str) -> Mapping[str, Any] | None:
        self._note("binding_snapshot")
        return self.bindings.get(node_id)

    def agent_resolvable(self, agent_id: str) -> bool:
        self._note("agent_resolvable")
        return agent_id in self.resolvable_agents

    def recovery_blocker_codes(self, run_id: str) -> Sequence[str]:
        self._note("recovery_blocker_codes")
        return list(self.recovery_codes)

    def adapter_registered(self, node_id: str) -> bool:
        self._note("adapter_registered")
        return node_id in self.registered_adapters

    def incoming_handoffs(self, run_id: str, node_id: str) -> Sequence[HandoffSnapshot]:
        self._note("incoming_handoffs")
        return self.handoffs.get(node_id, [])


def actor_for_node(node_id: str) -> str:
    for node in DEFINITION.nodes:
        if node.nodeId == node_id:
            return node.actorKind.value
    return ActorKind.HUMAN.value
