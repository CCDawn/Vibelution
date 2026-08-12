"""Fake DomainPorts for T5 adapter tests.

Records the ORDER of calls so tests can assert: read-back before budget,
budget before task creation, verify after execute, no re-execution under a
stable actionId.
"""

from __future__ import annotations

from typing import Any

from core.research.workflow.contracts import PendingAction

from core.web.services.team_workflow.research_runtime.domain_ports import (
    AgentTaskHandle,
    ArtifactReadBack,
    BindingResolution,
    HumanTaskHandle,
    ReadBackVerdict,
)


class FakeDomainPorts:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.read_back_ok = True
        self.read_back_detail = ""
        self.revision_vector: dict[str, str] = {"source_collection": "rev-1"}
        self.input_ok: dict[str, bool] = {}
        self.tasks_by_action: dict[str, AgentTaskHandle] = {}
        self.turn_results_by_action: dict[str, list[dict[str, str]]] = {}
        self.human_tasks_by_action: dict[str, HumanTaskHandle] = {}
        self.system_results: dict[str, tuple[list[dict[str, str]], dict[str, Any]]] = {}
        self.artifact_store: dict[str, ArtifactReadBack] = {}
        self.reservations: list[str] = []
        self.settled: list[str] = []
        self.bindings_by_action: dict[str, dict[str, Any]] = {}
        self.fail_input_readback = False
        self.fail_artifact_hash = False

    # ------------------------------------------------------------- ports

    def read_back_input(self, action: PendingAction) -> ReadBackVerdict:
        self.calls.append("read_back_input")
        if self.fail_input_readback or self.input_ok.get(action.action_id) is False:
            return ReadBackVerdict(ok=False, detail="input changed", revision_vector=self.revision_vector)
        return ReadBackVerdict(ok=self.read_back_ok, detail=self.read_back_detail, revision_vector=self.revision_vector)

    def resolve_binding(self, action: PendingAction) -> BindingResolution:
        self.calls.append("resolve_binding")
        agent_id = str(self.bindings_by_action.get(action.action_id, {}).get("agentId") or f"agent-{action.node_id}")
        role_key = str(self.bindings_by_action.get(action.action_id, {}).get("roleKey") or action.node_id)
        snapshot_id = self.bindings_by_action.get(action.action_id, {}).get("bindingSnapshotId")
        return BindingResolution(
            agent_id=agent_id,
            role_key=role_key,
            binding_snapshot_id=snapshot_id,
        )

    def reserve_budget(self, *, action: PendingAction, estimate_tokens: int) -> dict[str, Any]:
        self.calls.append("reserve_budget")
        self.reservations.append(action.action_id)
        return {
            "reservationId": f"res-{action.action_id}",
            "stageId": "knowledge_collection",
            "reserved": {"estimatedTokens": estimate_tokens},
        }

    def settle_budget(self, *, reservation: dict[str, Any], usage: dict[str, Any]) -> None:
        self.calls.append("settle_budget")
        self.settled.append(str(reservation.get("reservationId") or ""))

    def create_agent_task(self, *, action: PendingAction) -> AgentTaskHandle:
        existing = self.tasks_by_action.get(action.action_id)
        if existing is not None:
            self.calls.append("create_agent_task(cached)")
            return existing
        self.calls.append("create_agent_task")
        handle = AgentTaskHandle(
            session_id=f"session-{action.run_id[:8]}",
            session_attempt=1,
            task_id=f"task-{action.action_id[:8]}",
            turn_id=f"turn-{action.action_id[:8]}",
        )
        self.tasks_by_action[action.action_id] = handle
        return handle

    def execute_agent_turn(self, *, action: PendingAction, handle: AgentTaskHandle) -> list[dict[str, str]]:
        existing = self.turn_results_by_action.get(action.action_id)
        if existing is not None:
            self.calls.append("execute_agent_turn(cached)")
            return existing
        self.calls.append("execute_agent_turn")
        ref = {
            "canonicalRef": f"evidence_card_batch:{action.action_id[:8]}",
            "kind": "evidence_card_batch",
            "sha256": "a" * 64,
        }
        self.turn_results_by_action[action.action_id] = [ref]
        actual_hash = "b" * 64 if self.fail_artifact_hash else "a" * 64
        if "evidence_card_batch:a" not in self.artifact_store:
            self.artifact_store["evidence_card_batch:a"] = ArtifactReadBack(
                canonical_ref=f"evidence_card_batch:{action.action_id[:8]}",
                version="1.0",
                content_hash=actual_hash,
                domain_revision="rev-1",
            )
        return self.turn_results_by_action[action.action_id]

    def read_back_artifact(self, canonical_ref: str) -> ArtifactReadBack | None:
        self.calls.append("read_back_artifact")
        return self.artifact_store.get(canonical_ref) or self.artifact_store.get("evidence_card_batch:a")

    def create_human_task(self, *, action: PendingAction) -> HumanTaskHandle:
        self.calls.append("create_human_task")
        existing = self.human_tasks_by_action.get(action.action_id)
        if existing is not None:
            return existing
        handle = HumanTaskHandle(task_id=f"ht-{action.action_id[:8]}")
        self.human_tasks_by_action[action.action_id] = handle
        return handle

    def execute_system_action(self, *, action: PendingAction) -> tuple[list[dict[str, str]], dict[str, Any]]:
        self.calls.append("execute_system_action")
        existing = self.system_results.get(action.action_id)
        if existing is not None:
            return existing
        result = (
            [{"canonicalRef": f"run_artifacts:{action.action_id[:8]}", "kind": "run_artifacts", "sha256": "c" * 64}],
            {"systemActionId": f"sys-{action.action_id[:8]}", "runnerId": "runner-1"},
        )
        self.system_results[action.action_id] = result
        self.artifact_store[f"run_artifacts:{action.action_id[:8]}"] = ArtifactReadBack(
            canonical_ref=f"run_artifacts:{action.action_id[:8]}",
            version="1.0",
            content_hash="c" * 64,
            domain_revision="rev-1",
        )
        return result

    # -------------------------------------------------------- assertions

    def order(self, *names: str) -> bool:
        positions = [self.calls.index(name) for name in names if name in self.calls]
        return len(positions) == len(names) and positions == sorted(positions)
