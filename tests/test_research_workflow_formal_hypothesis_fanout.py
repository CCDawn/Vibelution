from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

import pytest

from core.research.competition.question_result_package import canonical_model_policy
from core.research.workflow.contracts import PendingAction
from core.research.workflow.models import ActorKind
from core.web.services.team_workflow.research_runtime import (
    formal_hypothesis_fanout,
    hypothesis_fragment_writer,
    workflow_artifact_store,
)
from core.web.services.team_workflow.research_runtime import (
    real_domain_ports as real_ports_module,
)
from core.web.services.team_workflow.research_runtime.domain_ports import (
    AgentTaskHandle,
    BindingResolution,
    ScopedAgentTaskHandle,
)
from core.web.services.team_workflow.research_runtime.adapter_dispatch_worker import (
    AdapterDispatchWorker,
)
from core.web.services.team_workflow.research_runtime.adapters.domain_adapters import (
    register_default_adapters,
)
from core.web.services.team_workflow.research_runtime.action_registry import (
    ActionRegistry,
)
from core.web.services.team_workflow.research_runtime.agent_turn_completion import (
    TurnNotReadyError,
)
from core.web.services.team_workflow.research_runtime.hypothesis_scope_events import (
    HypothesisScopeEventConflict,
    record_hypothesis_scope_event,
)
from core.web.services.team_workflow.research_runtime.real_domain_ports import (
    RealDomainPorts,
)
from tests._support.adapter_fakes import FakeDomainPorts
from tests._support.command_helpers import CommandHarness
from tests._support.workflow_ledger_helpers import (
    FIXED_NOW_MS,
    build_attempt_record,
    build_command_record,
    build_outbox_record,
)


def _action(*, attempt: int = 1, node_run_id: str = "node-1") -> PendingAction:
    return PendingAction(
        action_id="action-1",
        run_id="run-1",
        node_run_id=node_run_id,
        node_id="hypothesis_design",
        attempt=attempt,
        actor_kind=ActorKind.AGENT,
        action_kind="start_agent_task",
        input_snapshot_hash="a" * 64,
        input_artifact_refs=(),
        binding_snapshot_id="binding-1",
        budget_policy_hash="budget-1",
    )


def _formal_required_model_policy() -> dict[str, Any]:
    return canonical_model_policy(
        {
            "family": "qwen",
            "providerIds": ["dashscope_main"],
            "modelIds": ["qwen3.6-plus"],
            "requireOfficialProvider": True,
        }
    )


def _ready_hypothesis_input(
    snapshot_hash: str = "d" * 64,
    *,
    source_collection_run_id: str = "run-1",
) -> dict[str, Any]:
    return {
        "status": "ready",
        "workflowRunId": "run-1",
        "sourceCollectionRunId": source_collection_run_id,
        "allowedEvidenceRefs": ["source:paper:1"],
        "knowledgeSnapshot": {
            "snapshotHash": snapshot_hash,
            "packageCount": 1,
            "packages": [],
            "knowledgeItemIds": ["ki-1"],
        },
        "consumedKnowledgeSnapshotHash": snapshot_hash,
    }


def test_pending_action_rejects_candidate_identity_outside_its_scope() -> None:
    with pytest.raises(ValueError, match="does not match"):
        replace(
            _action(),
            selection_id="selection-1",
            candidate_id="H1",
            scope={
                "kind": "workflow_candidate",
                "selectionId": "selection-1",
                "candidateId": "H2",
            },
        )


def test_pending_action_rejects_candidate_identity_on_root_scope() -> None:
    with pytest.raises(ValueError, match="must not carry candidate identity"):
        replace(
            _action(),
            selection_id="selection-1",
            candidate_id="H1",
            scope={"kind": "workflow_node_root"},
        )


def test_hypothesis_fan_out_wait_uses_one_shared_deadline(monkeypatch) -> None:
    remaining = iter((300_000, 90_000))
    monkeypatch.setattr(
        real_ports_module,
        "remaining_challenge_task_ms",
        lambda: next(remaining),
    )

    assert real_ports_module._hypothesis_fan_out_wait_timeout_ms(
        child_turn_id="turn-1"
    ) == 120_000
    assert real_ports_module._hypothesis_fan_out_wait_timeout_ms(
        child_turn_id="turn-2"
    ) == 90_000


def test_hypothesis_fan_out_deadline_exhaustion_fails_before_child_wait(monkeypatch) -> None:
    from core.web.services.team_workflow.research_runtime.challenge_turn_policy import (
        ChallengeTaskDeadlineExceeded,
    )

    monkeypatch.setattr(real_ports_module, "remaining_challenge_task_ms", lambda: 0)

    with pytest.raises(ChallengeTaskDeadlineExceeded) as raised:
        real_ports_module._hypothesis_fan_out_wait_timeout_ms(child_turn_id="turn-expired")

    assert raised.value.problem["code"] == "challenge_logical_task_deadline_exhausted"


def test_hypothesis_fan_out_wait_preserves_ordinary_default_timeout(monkeypatch) -> None:
    monkeypatch.setattr(real_ports_module, "remaining_challenge_task_ms", lambda: None)

    assert real_ports_module._hypothesis_fan_out_wait_timeout_ms(
        child_turn_id="ordinary-turn"
    ) == 120_000


def test_candidate_action_cannot_join_a_different_frozen_selection() -> None:
    payload = json.dumps(
        {
            "selectionId": "selection-1",
            "selectedCandidateIds": ["H2"],
        }
    )
    anchor = (None,) * 13 + (payload,)

    class _Repository:
        def get_anchor_by_node_run(self, _node_run_id: str):
            return anchor

    class _Store:
        def read(self, callback):
            return callback(_Repository())

    action = replace(
        _action(),
        selection_id="selection-1",
        candidate_id="H1",
        scope={
            "kind": "workflow_candidate",
            "selectionId": "selection-1",
            "candidateId": "H1",
        },
    )

    with pytest.raises(RuntimeError, match="outside the selected candidates"):
        RealDomainPorts(_Store())._bound_hypothesis_selection(action)


def test_formal_selection_prefers_frozen_snapshot_without_legacy_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        formal_hypothesis_fanout,
        "_selection_from_authority",
        lambda _snapshot: pytest.fail("authority must not be consulted"),
    )
    result = formal_hypothesis_fanout.formal_hypothesis_fan_out_input(
        action=_action(),
        snapshot={
            "teamId": "team-1",
            "hypothesisSelection": {
                "selectionId": "selection-1",
                "selectedCandidateIds": ["H1", "H2"],
                "candidateSnapshots": [
                    {"candidateId": "H1", "statement": "claim 1"},
                    {"candidateId": "H2", "statement": "claim 2"},
                ],
            },
        },
    )
    assert result is not None
    assert result["selectionId"] == "selection-1"
    assert result["selectedCandidateIds"] == ["H1", "H2"]


def test_formal_selection_rejects_duplicate_candidates() -> None:
    with pytest.raises(RuntimeError, match="duplicate"):
        formal_hypothesis_fanout.formal_hypothesis_fan_out_input(
            action=_action(),
            snapshot={
                "hypothesisSelection": {
                    "selectionId": "selection-1",
                    "selectedCandidateIds": ["H1", "H1"],
                }
            },
        )


def test_formal_selection_replay_uses_node_run_bound_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[str] = []
    monkeypatch.setattr(
        formal_hypothesis_fanout,
        "_selection_from_snapshot",
        lambda _snapshot: None,
    )

    def authority(_snapshot, *, bound_selection_id: str = ""):
        observed.append(bound_selection_id)
        return {
            "selectionId": bound_selection_id,
            "selectedCandidateIds": ["H1"],
            "candidateSnapshots": [{"candidateId": "H1"}],
        }

    monkeypatch.setattr(
        formal_hypothesis_fanout,
        "_selection_from_authority",
        authority,
    )
    result = formal_hypothesis_fanout.formal_hypothesis_fan_out_input(
        action=_action(),
        snapshot={"teamId": "team-1", "questionId": "SCI-096"},
        bound_selection_id="selection-bound",
    )
    assert result is not None
    assert result["selectionId"] == "selection-bound"
    assert observed == ["selection-bound"]


def test_formal_selection_authority_is_read_from_action_workflow_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        formal_hypothesis_fanout,
        "_selection_from_snapshot",
        lambda _snapshot: None,
    )
    observed: dict[str, str] = {}

    def chain_state(_team_id, _question_id, **kwargs):
        observed["chain_run_id"] = str(kwargs.get("workflow_run_id") or "")
        return {"selectionId": "selection-current"}

    def get_selection(_team_id, _selection_id):
        return {
            "selection": {
                "selectionId": "selection-current",
                "workflowRunId": "run-1",
                "selectedCandidateIds": ["H1"],
            }
        }

    def list_candidates(_team_id, *, question_id, workflow_run_id):
        observed["candidate_run_id"] = workflow_run_id
        assert question_id == "SCI-096"
        return {
            "candidates": [
                {
                    "candidateId": "H1",
                    "workflowRunId": workflow_run_id,
                    "statement": "claim H1",
                }
            ]
        }

    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.hypothesis_first_chain.chain_state",
        chain_state,
    )
    monkeypatch.setattr(
        "core.web.services.team_workflow.hypothesis_selection.get_hypothesis_selection",
        get_selection,
    )
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.hypothesis_first_chain.list_hypothesis_candidates",
        list_candidates,
    )

    result = formal_hypothesis_fanout.formal_hypothesis_fan_out_input(
        action=_action(),
        snapshot={"teamId": "team-1", "questionId": "SCI-096"},
    )

    assert result["selection"]["workflowRunId"] == "run-1"
    assert observed == {"chain_run_id": "run-1", "candidate_run_id": "run-1"}


def test_real_domain_chain_state_uses_snapshot_workflow_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, str] = {}

    def chain_state(_team_id, _question_id, **kwargs):
        observed["workflow_run_id"] = str(kwargs.get("workflow_run_id") or "")
        return {"selectionId": "selection-1"}

    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.hypothesis_first_chain.chain_state",
        chain_state,
    )

    state = RealDomainPorts(object())._hypothesis_chain_state(
        {
            "teamId": "team-1",
            "questionId": "SCI-096",
            "workflowRunId": "run-1",
        }
    )

    assert state["selectionId"] == "selection-1"
    assert observed == {"workflow_run_id": "run-1"}


def test_reusable_fragment_prefers_prior_anchor_lineage_on_continuous_retry() -> None:
    rows = [
        {
            "recordId": "hypothesis_fragment:selection-1:H1:node-1",
            "payload": {
                "kind": "hypothesis_fragment",
                "workflowRunId": "run-1",
                "nodeRunId": "node-1",
                "selectionId": "selection-1",
                "candidateId": "H1",
                "sessionId": "child-H1",
                "taskId": "task-H1",
                "sessionAttempt": 1,
            },
        },
        {
            "recordId": "hypothesis_fragment:selection-1:H1:node-2",
            "payload": {
                "kind": "hypothesis_fragment",
                "workflowRunId": "run-1",
                "nodeRunId": "node-2",
                "selectionId": "selection-1",
                "candidateId": "H1",
                "sessionId": "child-H1",
                "taskId": "task-H1",
                "sessionAttempt": 1,
            },
        },
    ]

    selected = formal_hypothesis_fanout.load_reusable_formal_hypothesis_fragment(
        rows,
        workflow_run_id="run-1",
        selection_id="selection-1",
        candidate_id="H1",
        session_id="child-H1",
        task_id="task-H1",
        session_attempt=1,
        preferred_fragment_refs=(
            "hypothesis_fragment:selection-1:H1:node-2",
        ),
    )

    assert selected is not None
    assert selected["nodeRunId"] == "node-2"


def test_hypothesis_authority_read_failure_is_not_treated_as_absence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BrokenStore:
        def list_attempts(self, _run_id: str):
            raise OSError("ledger unavailable")

    with pytest.raises(
        formal_hypothesis_fanout.HypothesisAuthorityUnavailable,
        match="ledger unavailable",
    ):
        formal_hypothesis_fanout.previous_hypothesis_anchor(
            BrokenStore(), _action()
        )


def test_formal_shadow_validates_scope_and_keeps_legacy_task_execution(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run(run_id="run-1")
        harness.service.submit(
            harness.request(run_id="run-1", idempotency_key="start-shadow")
        )
        latest = harness.store.latest_attempt("run-1", "source_finding")
        assert latest is not None
        action = _action(node_run_id=latest.node_run_id)
        fallback = AgentTaskHandle(
            session_id="legacy-session",
            session_attempt=1,
            task_id="legacy-task",
            turn_id="legacy-turn",
        )
        ports = RealDomainPorts(
            harness.store,
            agent_task_factory=lambda **_kwargs: fallback,
        )
        monkeypatch.setattr(
            ports,
            "_run_input_snapshot",
            lambda _run_id: {
                "teamId": "team-1",
                "projectId": "project-1",
                "workflowSessionScopeV3": {"hypothesis_design": "shadow"},
                "budgetPolicy": {"maxParallelTasks": 2},
                "agentBindingSnapshot": [
                    {
                        "nodeId": "hypothesis_design",
                        "agentId": "agent-1",
                        "roleKey": "hypothesis_designer",
                    }
                ],
            },
        )
        monkeypatch.setattr(
            real_ports_module,
            "_formal_hypothesis_fan_out_input",
            lambda **_kwargs: {
                "selectionId": "selection-1",
                "selectedCandidateIds": ["H1", "H2"],
            },
        )
        monkeypatch.setattr(
            ports,
            "_create_hypothesis_fan_out",
            lambda **_kwargs: pytest.fail("shadow must not create child tasks"),
        )
        monkeypatch.setattr(
            real_ports_module,
            "_bounded_agent_node_can_complete",
            lambda *_args, **_kwargs: False,
        )

        shadow_handle = ports.create_agent_task(action=action)
        assert shadow_handle == fallback
        assert shadow_handle.observation_only is False
        assert shadow_handle.session_id == "legacy-session"
        events = harness.store.list_events("run-1")
        scope_events = [
            item
            for item in events
            if item.event_type == "workflow.session_scope.resolved"
        ]
        assert len(scope_events) == 1
        payload = json.loads(scope_events[0].payload_json)
        assert payload["mode"] == "shadow"
        assert payload["candidateCount"] == 2
        assert len(payload["scopeHash"]) == 64
    finally:
        harness.close()


def test_formal_non_hypothesis_first_without_selection_uses_bounded_compatibility(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run(run_id="run-1")
        harness.service.submit(
            harness.request(run_id="run-1", idempotency_key="start-compatibility")
        )
        latest = harness.store.latest_attempt("run-1", "source_finding")
        assert latest is not None
        action = _action(node_run_id=latest.node_run_id)
        fallback = AgentTaskHandle(
            session_id="legacy-session",
            session_attempt=1,
            task_id="legacy-task",
            turn_id="legacy-turn",
        )
        ports = RealDomainPorts(
            harness.store,
            agent_task_factory=lambda **_kwargs: fallback,
        )
        snapshot = {
            "teamId": "team-1",
            "projectId": "project-1",
            "questionId": "SCI-096",
            "workflowId": "challenge-cup-research",
            "workflowVersionId": "v2.1",
            "workflowSessionScopeV3": {"hypothesis_design": "on"},
            "researchObjectiveContract": {"hypothesisFirst": False},
        }
        monkeypatch.setattr(ports, "_run_input_snapshot", lambda _run_id: snapshot)
        monkeypatch.setattr(ports, "_hypothesis_chain_state", lambda _snapshot: {})
        monkeypatch.setattr(
            ports,
            "resolve_binding",
            lambda _action: BindingResolution(
                agent_id="agent-1", role_key="hypothesis_designer"
            ),
        )
        monkeypatch.setattr(
            real_ports_module,
            "_bounded_agent_node_can_complete",
            lambda *_args, **_kwargs: False,
        )
        monkeypatch.setattr(
            real_ports_module,
            "_formal_hypothesis_fan_out_input",
            lambda **_kwargs: (_ for _ in ()).throw(
                RuntimeError(
                    "hypothesis_design requires a current hypothesis selection"
                )
            ),
        )

        handle = ports.create_agent_task(action=action)

        assert handle == fallback
        events = harness.store.list_events("run-1")
        scope_events = [
            item
            for item in events
            if item.event_type == "workflow.session_scope.resolved"
        ]
        assert len(scope_events) == 1
        payload = json.loads(scope_events[0].payload_json)
        assert payload["mode"] == "on"
        assert payload["candidateCount"] == 0
        assert (
            payload["fallbackReason"]
            == "legacy_non_hypothesis_first_without_authoritative_selection"
        )
    finally:
        harness.close()


def test_formal_hypothesis_first_without_selection_fails_closed(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run(run_id="run-1")
        harness.service.submit(
            harness.request(run_id="run-1", idempotency_key="start-hypothesis-missing")
        )
        latest = harness.store.latest_attempt("run-1", "source_finding")
        assert latest is not None
        action = _action(node_run_id=latest.node_run_id)
        ports = RealDomainPorts(harness.store)
        snapshot = {
            "teamId": "team-1",
            "projectId": "project-1",
            "questionId": "SCI-096",
            "workflowId": "challenge-cup-research",
            "workflowVersionId": "v2.1",
            "workflowSessionScopeV3": {"hypothesis_design": "on"},
            "researchObjectiveContract": {"hypothesisFirst": True},
        }
        monkeypatch.setattr(ports, "_run_input_snapshot", lambda _run_id: snapshot)
        monkeypatch.setattr(ports, "_hypothesis_chain_state", lambda _snapshot: {})
        monkeypatch.setattr(
            ports,
            "resolve_binding",
            lambda _action: BindingResolution(
                agent_id="agent-1", role_key="hypothesis_designer"
            ),
        )
        monkeypatch.setattr(
            real_ports_module,
            "_bounded_agent_node_can_complete",
            lambda *_args, **_kwargs: False,
        )
        monkeypatch.setattr(
            real_ports_module,
            "_formal_hypothesis_fan_out_input",
            lambda **_kwargs: (_ for _ in ()).throw(
                RuntimeError(
                    "hypothesis_design requires a current hypothesis selection"
                )
            ),
        )

        with pytest.raises(
            RuntimeError,
            match="hypothesis_design requires a current hypothesis selection",
        ):
            ports.create_agent_task(action=action)
    finally:
        harness.close()


def test_formal_live_selection_enables_fan_out_when_snapshot_is_missing_selection(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run(run_id="run-1")
        harness.service.submit(
            harness.request(run_id="run-1", idempotency_key="start-live-selection")
        )
        latest = harness.store.latest_attempt("run-1", "source_finding")
        assert latest is not None
        action = _action(node_run_id=latest.node_run_id)
        ports = RealDomainPorts(harness.store)
        required_model_policy = _formal_required_model_policy()
        snapshot = {
            "teamId": "team-1",
            "projectId": "project-1",
            "questionId": "SCI-096",
            "workflowVersionId": "v2.1",
            "workflowSessionScopeV3": {"hypothesis_design": "on"},
            "researchObjectiveContract": {"hypothesisFirst": False},
            "modelRoutingPolicy": {
                "requiredModelPolicy": required_model_policy,
                "modelPolicySha256": required_model_policy["policySha256"],
                "routes": {
                    "reasoning": {
                        "byProductRole": {
                            "challenge_cup_experiment_revision": {
                                "agentId": "agent-1",
                                "productRoleId": "challenge_cup_experiment_revision",
                                "modelRef": "dashscope_main/qwen3.6-plus",
                                "providerId": "dashscope_main",
                                "modelId": "qwen3.6-plus",
                            }
                        }
                    }
                },
            },
        }
        fan_out = {
            "selection": {
                "selectionId": "selection-live",
                "selectedCandidateIds": ["H1"],
            },
            "selectionId": "selection-live",
            "selectedCandidateIds": ["H1"],
            "candidateSnapshots": [{"candidateId": "H1", "statement": "claim"}],
        }
        monkeypatch.setattr(ports, "_run_input_snapshot", lambda _run_id: snapshot)
        monkeypatch.setattr(
            ports,
            "_hypothesis_chain_state",
            lambda _snapshot: {"selectionId": "selection-live"},
        )
        monkeypatch.setattr(
            ports,
            "resolve_binding",
            lambda _action: BindingResolution(
                agent_id="agent-1", role_key="hypothesis_designer"
            ),
        )
        monkeypatch.setattr(
            real_ports_module,
            "_bounded_agent_node_can_complete",
            lambda *_args, **_kwargs: False,
        )
        monkeypatch.setattr(
            real_ports_module,
            "_formal_hypothesis_fan_out_input",
            lambda **_kwargs: fan_out,
        )
        observed: list[dict[str, Any]] = []
        authority_ids: list[tuple[str, str]] = []

        def create_fan_out(**kwargs):
            observed.append(dict(kwargs["fan_out"]))
            authority_ids.append(
                (
                    kwargs["challenge_task_contract"]["workflowId"],
                    kwargs["model_invocation_receipt_binding"]["workflowId"],
                )
            )
            return AgentTaskHandle(
                session_id="root-live",
                session_attempt=1,
                task_id="task-live",
                turn_id="turn-live",
            )

        monkeypatch.setattr(ports, "_create_hypothesis_fan_out", create_fan_out)

        handle = ports.create_agent_task(action=action)

        assert handle.task_id == "task-live"
        assert observed and observed[0]["selectionId"] == "selection-live"
        assert authority_ids == [
            ("challenge-cup-research", "challenge-cup-research")
        ]
        payload = json.loads(
            next(
                item
                for item in harness.store.list_events("run-1")
                if item.event_type == "workflow.session_scope.resolved"
            ).payload_json
        )
        assert payload["selectionId"] == "selection-live"
        assert payload["candidateCount"] == 1
        assert payload["fallbackReason"] == ""
    finally:
        harness.close()


def test_parallel_limit_is_frozen_and_fail_closed() -> None:
    assert formal_hypothesis_fanout.hypothesis_max_parallel(
        {"budgetPolicy": {"maxParallelTasks": 2}}, 3
    ) == 2
    with pytest.raises(RuntimeError, match="positive integer"):
        formal_hypothesis_fanout.hypothesis_max_parallel(
            {"budgetPolicy": {"maxParallelTasks": "2"}}, 3
        )


def test_resolve_candidate_reuses_success_and_retries_only_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot_hash = "b" * 64
    statuses = {
        "H1": {
            "taskId": "task-H1",
            "workflowRunId": "run-1",
            "workflowNodeId": "hypothesis_design",
            "nodeRunId": "node-2",
            "selectionId": "selection-1",
            "candidateId": "H1",
            "sessionId": "child-H1",
            "sessionAttempt": 1,
            "status": "completed",
            "consumedKnowledgeSnapshotHash": snapshot_hash,
            "turn": {"turnId": "turn-H1"},
        },
        "H2": {
            "taskId": "task-H2",
            "workflowRunId": "run-1",
            "workflowNodeId": "hypothesis_design",
            "nodeRunId": "node-2",
            "selectionId": "selection-1",
            "candidateId": "H2",
            "sessionId": "child-H2",
            "sessionAttempt": 1,
            "status": "failed",
            "consumedKnowledgeSnapshotHash": snapshot_hash,
            "turn": {"turnId": "turn-H2"},
        },
    }
    starts: list[dict] = []

    monkeypatch.setattr(
        "core.web.services.team_workflow.research_project_agent_tasks.get_research_project_agent_task_status",
        lambda *_args, **_kwargs: {"tasks": list(statuses.values())},
    )

    authorities: list[dict] = []

    def start(_team: str, _project: str, payload: dict, **kwargs) -> dict:
        starts.append(dict(payload))
        authorities.append(dict(kwargs))
        return {
            "task": {
                "taskId": "task-H2-retry",
                "sessionId": "child-H2-retry",
                "sessionAttempt": 2,
                "status": "running",
                "turn": {"turnId": "turn-H2-retry"},
            },
            "taskId": "task-H2-retry",
            "sessionId": "child-H2-retry",
            "sessionAttempt": 2,
            "startedTurnId": "turn-H2-retry",
        }

    monkeypatch.setattr(
        "core.web.services.team_workflow.research_project_agent_tasks.start_research_project_agent_task",
        start,
    )
    common = {
        "team_id": "team-1",
        "project_id": "project-1",
        "action": _action(attempt=2, node_run_id="node-2"),
        "agent_id": "agent-1",
        "source_collection_run_id": "source-1",
        "selection_id": "selection-1",
        "selected_candidate_ids": ["H1", "H2"],
        "candidate_context": {"candidateId": "H2"},
        "subtask_id": "node-2:selection-1:H2",
        "previous": {},
        "challenge_task_contract": {
            "questionId": "SCI-096",
            "workflowId": "challenge-cup-research",
            "workflowVersionId": "v2.1",
            "workflowRunId": "run-1",
            "workflowNodeId": "hypothesis_design",
            "nodeRunId": "node-2",
            "nodeAttempt": 2,
            "agentId": "agent-1",
            "modelPolicySha256": "a" * 64,
            "requiredModelPolicy": {"providerIds": ["dashscope"]},
        },
        "model_invocation_receipt_binding": {
            "questionId": "SCI-096",
            "questionRunId": "run-1",
            "workflowRunId": "run-1",
            "workflowId": "challenge-cup-research",
            "workflowVersionId": "v2.1",
            "formalNodeId": "hypothesis_design",
            "formalNodeRunId": "node-2",
            "formalNodeAttempt": 2,
            "questionStage": "generation",
            "outcomeKinds": ["candidate"],
            "modelPolicySha256": "a" * 64,
        },
        "hypothesis_input_binding": {
            "status": "ready",
            "workflowRunId": "run-1",
            "sourceCollectionRunId": "source-1",
            "allowedEvidenceRefs": ["source:paper:1"],
            "knowledgeSnapshot": {"snapshotHash": snapshot_hash},
            "consumedKnowledgeSnapshotHash": snapshot_hash,
        },
    }
    reused = formal_hypothesis_fanout.resolve_formal_candidate_task(
        **{**common, "candidate_id": "H1"}
    )
    retried = formal_hypothesis_fanout.resolve_formal_candidate_task(
        **{**common, "candidate_id": "H2"}
    )
    assert reused["sessionId"] == "child-H1"
    assert retried["sessionId"] == "child-H2-retry"
    assert starts[0]["formalRetry"] is True
    assert starts[0]["retryTaskId"] == "task-H2"
    assert authorities[0]["_challenge_task_contract"]["nodeRunId"] == "node-2"
    assert authorities[0]["_model_invocation_receipt_binding"]["outcomeKinds"] == [
        "candidate"
    ]
    assert (
        authorities[0]["_hypothesis_input_binding"]["knowledgeSnapshot"][
            "snapshotHash"
        ]
        == snapshot_hash
    )
    reused_previous = formal_hypothesis_fanout.resolve_formal_candidate_task(
        **{
            **common,
            "action": _action(attempt=3, node_run_id="node-3"),
            "candidate_id": "H1",
            "previous": statuses["H1"],
        }
    )
    assert reused_previous["sessionId"] == "child-H1"
    assert len(starts) == 1

    statuses["H1"]["consumedKnowledgeSnapshotHash"] = "c" * 64
    revised = formal_hypothesis_fanout.resolve_formal_candidate_task(
        **{
            **common,
            "action": _action(attempt=4, node_run_id="node-4"),
            "candidate_id": "H1",
            "previous": statuses["H1"],
            "challenge_task_contract": {
                **common["challenge_task_contract"],
                "nodeRunId": "node-4",
                "nodeAttempt": 4,
            },
            "model_invocation_receipt_binding": {
                **common["model_invocation_receipt_binding"],
                "formalNodeRunId": "node-4",
                "formalNodeAttempt": 4,
            },
        }
    )
    assert revised["sessionId"] == "child-H2-retry"
    assert starts[-1]["formalRetry"] is True
    assert starts[-1]["retryTaskId"] == "task-H1"
    assert snapshot_hash[:16] in starts[-1]["idempotencyKey"]


def test_knowledge_snapshot_consumption_is_idempotent(tmp_path) -> None:
    from core.web.services.team_workflow.research_runtime.knowledge_snapshot_consumption import (
        record_knowledge_snapshot_consumed,
    )

    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run(run_id="run-1")
        first = record_knowledge_snapshot_consumed(
            harness.store,
            run_id="run-1",
            node_run_id="node-1",
            selection_id="selection-1",
            snapshot_hash="d" * 64,
            now_ms=1_750_000_001_000,
        )
        replay = record_knowledge_snapshot_consumed(
            harness.store,
            run_id="run-1",
            node_run_id="node-1",
            selection_id="selection-1",
            snapshot_hash="d" * 64,
            now_ms=1_750_000_001_001,
        )

        assert first is True
        assert replay is False
        events = [
            event
            for event in harness.store.list_events("run-1")
            if event.event_type == "knowledge_snapshot_consumed"
        ]
        assert len(events) == 1
        payload = json.loads(events[0].payload_json)
        assert payload == {
            "nodeRunId": "node-1",
            "selectionId": "selection-1",
            "snapshotHash": "d" * 64,
        }
    finally:
        harness.close()


def test_fragment_readback_requires_exact_formal_scope() -> None:
    payload = {
        "kind": "hypothesis_fragment",
        "workflowRunId": "run-1",
        "workflowNodeId": "hypothesis_design",
        "nodeRunId": "node-1",
        "selectionId": "selection-1",
        "candidateId": "H1",
        "sessionId": "child-H1",
        "sessionAttempt": 1,
        "taskId": "task-H1",
    }
    row = {"recordId": "hypothesis_fragment:selection-1:H1", "payload": payload}
    assert formal_hypothesis_fanout.load_formal_hypothesis_fragment(
        [row],
        node_run_id="node-1",
        selection_id="selection-1",
        candidate_id="H1",
        session_id="child-H1",
        task_id="task-H1",
        session_attempt=1,
    ) == payload
    assert formal_hypothesis_fanout.load_formal_hypothesis_fragment(
        [row],
        node_run_id="node-2",
        selection_id="selection-1",
        candidate_id="H1",
        session_id="child-H1",
        task_id="task-H1",
        session_attempt=1,
    ) is None
    assert formal_hypothesis_fanout.load_reusable_formal_hypothesis_fragment(
        [row],
        workflow_run_id="run-1",
        selection_id="selection-1",
        candidate_id="H1",
        session_id="child-H1",
        task_id="task-H1",
        session_attempt=1,
    ) == payload


def test_scoped_handle_reads_and_requires_canonical_session_lineage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = {
        "task": {
            "taskId": "task-H1",
            "sessionId": "child-H1",
            "sessionAttempt": 1,
            "status": "running",
            "turn": {"turnId": "turn-H1"},
        }
    }
    monkeypatch.setattr(
        "core.web.services.session_service.get_session_detail",
        lambda *_args, **_kwargs: {
            "id": "child-H1",
            "parentSessionId": "root-1",
            "rootSessionId": "root-1",
        },
    )
    handle = formal_hypothesis_fanout.scoped_handle_from_started(
        started,
        selection_id="selection-1",
        candidate_id="H1",
        subtask_id="node-1:selection-1:H1",
        expected_root_session_id="root-1",
    )
    assert handle.parent_session_id == "root-1"
    assert handle.root_session_id == "root-1"

    with pytest.raises(RuntimeError, match="does not match"):
        formal_hypothesis_fanout.scoped_handle_from_started(
            started,
            selection_id="selection-1",
            candidate_id="H1",
            subtask_id="node-1:selection-1:H1",
            expected_root_session_id="root-other",
        )


def test_formal_live_anchor_is_incremental_and_keeps_failed_placeholder(
    tmp_path,
) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run(run_id="run-1")
        harness.service.submit(
            harness.request(run_id="run-1", idempotency_key="start-live-anchor")
        )
        latest = harness.store.latest_attempt("run-1", "source_finding")
        assert latest is not None
        action = _action(node_run_id=latest.node_run_id)
        ports = RealDomainPorts(harness.store)
        binding = BindingResolution(agent_id="agent-1", role_key="hypothesis_designer")
        child = ScopedAgentTaskHandle(
            selection_id="selection-1",
            candidate_id="H1",
            session_id="child-H1",
            session_attempt=1,
            task_id="task-H1",
            turn_id="turn-H1",
            parent_session_id="root-1",
            root_session_id="root-1",
        )
        ports._persist_hypothesis_anchor_draft(
            action=action,
            binding=binding,
            root_session_id="root-1",
            root_session_attempt=1,
            selection_id="selection-1",
            selected_candidate_ids=["H1", "H2"],
            handles=[child],
            candidate_statuses={"H2": "failed"},
        )
        row = harness.store.read(
            lambda repo: repo.get_anchor_by_node_run(latest.node_run_id)
        )
        assert row is not None
        payload = json.loads(row[13])
        assert payload["rootSession"]["sessionId"] == "root-1"
        assert [item["candidateId"] for item in payload["scopedSessions"]] == [
            "H1",
            "H2",
        ]
        assert payload["scopedSessions"][0]["sessionId"] == "child-H1"
        assert payload["scopedSessions"][1]["sessionId"] is None
        assert payload["scopedSessions"][1]["status"] == "failed"
    finally:
        harness.close()


def test_hypothesis_scope_events_are_bounded_and_idempotent(tmp_path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run(run_id="run-1")
        harness.service.submit(
            harness.request(run_id="run-1", idempotency_key="start-events")
        )
        latest = harness.store.latest_attempt("run-1", "source_finding")
        assert latest is not None
        action = _action(node_run_id=latest.node_run_id)
        fields = {
            "mode": "on",
            "selectionId": "selection-1",
            "candidateId": "H1",
            "sessionId": "child-H1",
            "status": "running",
            "prompt": "must-not-be-recorded",
        }
        first = record_hypothesis_scope_event(
            harness.store,
            action=action,
            event_type="workflow.child_session.created",
            fields=fields,
            discriminator="H1:1",
        )
        second = record_hypothesis_scope_event(
            harness.store,
            action=action,
            event_type="workflow.child_session.created",
            fields=fields,
            discriminator="H1:1",
        )

        assert first == second
        matching = [
            item
            for item in harness.store.list_events("run-1")
            if item.event_id == first
        ]
        assert len(matching) == 1
        payload = json.loads(matching[0].payload_json)
        assert payload["candidateId"] == "H1"
        assert "prompt" not in payload
    finally:
        harness.close()


def test_hypothesis_scope_event_id_conflict_is_fail_closed_without_sequence_gap(
    tmp_path,
) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run(run_id="run-1")
        harness.service.submit(
            harness.request(run_id="run-1", idempotency_key="start-event-conflict")
        )
        latest = harness.store.latest_attempt("run-1", "source_finding")
        assert latest is not None
        action = _action(node_run_id=latest.node_run_id)
        first = record_hypothesis_scope_event(
            harness.store,
            action=action,
            event_type="workflow.child_session.created",
            fields={"candidateId": "H1", "status": "running"},
            discriminator="H1:1",
        )
        sequence_after_first = harness.store.latest_event_sequence("run-1")

        with pytest.raises(HypothesisScopeEventConflict, match=first):
            record_hypothesis_scope_event(
                harness.store,
                action=action,
                event_type="workflow.child_session.created",
                fields={"candidateId": "H2", "status": "running"},
                discriminator="H1:1",
            )

        matching = [
            item
            for item in harness.store.list_events("run-1")
            if item.event_id == first
        ]
        assert len(matching) == 1
        assert harness.store.latest_event_sequence("run-1") == sequence_after_first
    finally:
        harness.close()


def test_hypothesis_scope_event_replay_compares_correlation_identity(
    tmp_path,
) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run(run_id="run-1")
        harness.service.submit(
            harness.request(run_id="run-1", idempotency_key="start-event-correlation")
        )
        latest = harness.store.latest_attempt("run-1", "source_finding")
        assert latest is not None
        action = _action(node_run_id=latest.node_run_id)
        first = record_hypothesis_scope_event(
            harness.store,
            action=action,
            event_type="workflow.child_session.created",
            fields={"candidateId": "H1", "status": "running"},
            discriminator="H1:correlation",
        )
        conflicting_action = replace(action, action_id="action-different")

        with pytest.raises(HypothesisScopeEventConflict, match=first):
            record_hypothesis_scope_event(
                harness.store,
                action=conflicting_action,
                event_type="workflow.child_session.created",
                fields={"candidateId": "H1", "status": "running"},
                discriminator="H1:correlation",
            )
    finally:
        harness.close()


def test_formal_child_turn_failure_closes_live_anchor_and_emits_blocked_event(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Legacy blocking semantics (flag=true): a failed child fails the node."""

    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run(run_id="run-1")
        harness.service.submit(
            harness.request(run_id="run-1", idempotency_key="start-turn-failure")
        )
        latest = harness.store.latest_attempt("run-1", "source_finding")
        assert latest is not None
        action = _action(node_run_id=latest.node_run_id)
        child = ScopedAgentTaskHandle(
            selection_id="selection-1",
            candidate_id="H1",
            session_id="child-H1",
            session_attempt=1,
            task_id="task-H1",
            turn_id="turn-H1",
            parent_session_id="root-1",
            root_session_id="root-1",
        )
        handle = AgentTaskHandle(
            session_id="root-1",
            session_attempt=1,
            task_id="",
            turn_id="",
            root_session_id="root-1",
            root_session_attempt=1,
            scoped_handles=(child,),
        )
        binding = BindingResolution(
            agent_id="agent-1", role_key="hypothesis_designer"
        )
        ports = RealDomainPorts(harness.store)
        monkeypatch.setattr(ports, "resolve_binding", lambda _action: binding)
        monkeypatch.setattr(
            real_ports_module,
            "_blocking_hypothesis_fan_out_wait_enabled",
            lambda: True,
        )
        ports._persist_hypothesis_anchor_draft(
            action=action,
            binding=binding,
            root_session_id="root-1",
            root_session_attempt=1,
            selection_id="selection-1",
            selected_candidate_ids=["H1"],
            handles=[child],
        )
        monkeypatch.setattr(
            real_ports_module,
            "_formal_hypothesis_fan_out_input",
            lambda **_kwargs: {
                "selection": {
                    "selectionId": "selection-1",
                    "selectedCandidateIds": ["H1"],
                },
                "selectionId": "selection-1",
                "selectedCandidateIds": ["H1"],
            },
        )
        monkeypatch.setattr(
            "core.web.services.team_workflow.research_runtime.agent_turn_completion.wait_for_agent_turn_terminal",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                RuntimeError("terminal failed")
            ),
        )

        with pytest.raises(RuntimeError, match="terminal failed"):
            ports._execute_hypothesis_fan_out(
                action=action,
                handle=handle,
                snapshot={"teamId": "team-1", "projectId": "project-1"},
            )

        row = harness.store.read(
            lambda repo: repo.get_anchor_by_node_run(latest.node_run_id)
        )
        payload = json.loads(row[13])
        assert payload["rootSession"]["status"] == "failed"
        assert payload["scopedSessions"][0]["status"] == "failed"
        assert any(
            item.event_type == "workflow.hypothesis_aggregation.blocked"
            and json.loads(item.payload_json).get("errorCode")
            == "candidate_turn_failed"
            for item in harness.store.list_events("run-1")
        )
    finally:
        harness.close()


def test_formal_execute_rejects_candidate_list_drift_after_anchor_freeze(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run(run_id="run-1")
        harness.service.submit(
            harness.request(run_id="run-1", idempotency_key="start-selection-drift")
        )
        latest = harness.store.latest_attempt("run-1", "source_finding")
        assert latest is not None
        action = _action(node_run_id=latest.node_run_id)
        binding = BindingResolution(
            agent_id="agent-1", role_key="hypothesis_designer"
        )
        child = ScopedAgentTaskHandle(
            selection_id="selection-1",
            candidate_id="H1",
            session_id="child-H1",
            session_attempt=1,
            task_id="task-H1",
            turn_id="turn-H1",
            parent_session_id="root-1",
            root_session_id="root-1",
        )
        handle = AgentTaskHandle(
            session_id="root-1",
            session_attempt=1,
            task_id="",
            turn_id="",
            root_session_id="root-1",
            root_session_attempt=1,
            scoped_handles=(child,),
        )
        ports = RealDomainPorts(harness.store)
        monkeypatch.setattr(ports, "resolve_binding", lambda _action: binding)
        ports._persist_hypothesis_anchor_draft(
            action=action,
            binding=binding,
            root_session_id="root-1",
            root_session_attempt=1,
            selection_id="selection-1",
            selected_candidate_ids=["H1"],
            handles=[child],
        )
        monkeypatch.setattr(
            real_ports_module,
            "_formal_hypothesis_fan_out_input",
            lambda **_kwargs: {
                "selection": {
                    "selectionId": "selection-1",
                    "selectedCandidateIds": ["H1", "H2"],
                },
                "selectionId": "selection-1",
                "selectedCandidateIds": ["H1", "H2"],
            },
        )

        with pytest.raises(RuntimeError, match="scope was frozen"):
            ports._execute_hypothesis_fan_out(
                action=action,
                handle=handle,
                snapshot={"teamId": "team-1", "projectId": "project-1"},
            )
        row = harness.store.read(
            lambda repo: repo.get_anchor_by_node_run(latest.node_run_id)
        )
        assert json.loads(row[13])["rootSession"]["status"] == "failed"
    finally:
        harness.close()


def test_formal_create_continues_after_one_candidate_start_failure(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run(run_id="run-1")
        harness.service.submit(
            harness.request(run_id="run-1", idempotency_key="start-partial")
        )
        latest = harness.store.latest_attempt("run-1", "source_finding")
        assert latest is not None
        action = _action(node_run_id=latest.node_run_id)
        started_candidates: list[str] = []
        binding_hashes: list[str] = []
        build_calls: list[str] = []
        monkeypatch.setattr(
            "core.web.services.team_workflow.research_project_hypothesis_context.build_hypothesis_input_context",
            lambda _team_id, task, **_kwargs: (
                build_calls.append(str(task.get("workflowRunId") or ""))
                or _ready_hypothesis_input()
            ),
        )
        monkeypatch.setattr(
            real_ports_module,
            "_resolve_formal_node_root_session",
            lambda **_kwargs: {"sessionId": "root-1", "sessionAttempt": 1},
        )
        monkeypatch.setattr(
            real_ports_module,
            "_verify_node_root_session",
            lambda *_args, **_kwargs: None,
        )

        def start_candidate(**kwargs):
            candidate_id = kwargs["candidate_id"]
            started_candidates.append(candidate_id)
            binding_hashes.append(
                kwargs["hypothesis_input_binding"]["knowledgeSnapshot"][
                    "snapshotHash"
                ]
            )
            if candidate_id == "H2":
                raise RuntimeError("H2 unavailable")
            return {"candidateId": candidate_id}

        monkeypatch.setattr(
            real_ports_module,
            "_resolve_or_start_formal_candidate_task",
            start_candidate,
        )
        monkeypatch.setattr(
            real_ports_module,
            "_scoped_handle_from_started",
            lambda started, **kwargs: ScopedAgentTaskHandle(
                selection_id=kwargs["selection_id"],
                candidate_id=kwargs["candidate_id"],
                session_id=f"child-{started['candidateId']}",
                session_attempt=1,
                task_id=f"task-{started['candidateId']}",
                turn_id=f"turn-{started['candidateId']}",
                parent_session_id="root-1",
                root_session_id="root-1",
            ),
        )
        ports = RealDomainPorts(harness.store)
        required_model_policy = _formal_required_model_policy()
        handle = ports._create_hypothesis_fan_out(
            action=action,
            binding=BindingResolution(
                agent_id="agent-1", role_key="hypothesis_designer"
            ),
            snapshot={
                "teamId": "research-team",
                "projectId": "project-1",
            },
            fan_out={
                "selectionId": "selection-1",
                "selectedCandidateIds": ["H1", "H2", "H3"],
                "candidateSnapshots": [
                    {"candidateId": "H1"},
                    {"candidateId": "H2"},
                    {"candidateId": "H3"},
                ],
            },
            challenge_task_contract={
                "questionId": "SCI-096",
                "workflowId": "challenge-cup-research",
                "workflowVersionId": "v2.1",
                "workflowRunId": action.run_id,
                "workflowNodeId": action.node_id,
                "nodeRunId": action.node_run_id,
                "nodeAttempt": action.attempt,
                "agentId": "agent-1",
                "modelPolicySha256": required_model_policy["policySha256"],
                "requiredModelPolicy": required_model_policy,
            },
            model_invocation_receipt_binding={
                "questionId": "SCI-096",
                "questionRunId": action.run_id,
                "workflowRunId": action.run_id,
                "workflowId": "challenge-cup-research",
                "workflowVersionId": "v2.1",
                "formalNodeId": action.node_id,
                "formalNodeRunId": action.node_run_id,
                "formalNodeAttempt": action.attempt,
                "questionStage": "generation",
                "outcomeKinds": ["candidate"],
                "modelPolicySha256": required_model_policy["policySha256"],
            },
        )
        assert started_candidates == ["H1", "H2", "H3"]
        assert build_calls == ["run-1"]
        assert binding_hashes == ["d" * 64] * 3
        assert [item.candidate_id for item in handle.scoped_handles] == ["H1", "H3"]
        consumed = [
            event
            for event in harness.store.list_events("run-1")
            if event.event_type == "knowledge_snapshot_consumed"
        ]
        assert len(consumed) == 1
        assert json.loads(consumed[0].payload_json)["snapshotHash"] == "d" * 64
        row = harness.store.read(
            lambda repo: repo.get_anchor_by_node_run(latest.node_run_id)
        )
        payload = json.loads(row[13])
        assert [item["status"] for item in payload["scopedSessions"]] == [
            "running",
            "failed",
            "running",
        ]
    finally:
        harness.close()


def test_formal_retry_reuses_successful_children_and_rebinds_replayed_fragments(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A partial retry opens only the failed child and rebinds sibling output."""

    monkeypatch.setattr(workflow_artifact_store, "PROJECT_ROOT", tmp_path)
    # Legacy blocking semantics regression anchor (flag=true).
    monkeypatch.setattr(
        real_ports_module,
        "_blocking_hypothesis_fan_out_wait_enabled",
        lambda: True,
    )
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run(run_id="run-1")
        monkeypatch.setattr(
            "core.web.services.team_workflow.research_project_hypothesis_context.build_hypothesis_input_context",
            lambda *_args, **_kwargs: _ready_hypothesis_input(
                source_collection_run_id="source-1"
            ),
        )

        def seed_attempts(uow) -> None:
            for command_id, node_run_id, attempt, status in (
                ("cmd-node-1", "node-1", 1, "failed"),
                ("cmd-node-2", "node-2", 2, "running"),
            ):
                uow.repository.insert_command(
                    build_command_record(
                        command_id=command_id,
                        run_id="run-1",
                        node_id="hypothesis_design",
                        idempotency_key=command_id,
                    )
                )
                uow.repository.insert_attempt(
                    build_attempt_record(
                        node_run_id=node_run_id,
                        run_id="run-1",
                        node_id="hypothesis_design",
                        attempt=attempt,
                        status=status,
                        command_id=command_id,
                    )
                )

        harness.store.submit(seed_attempts, force_flush=True).result(timeout=10)

        def child_handle(
            candidate_id: str,
            *,
            node_run_id: str,
            session_attempt: int = 1,
            status: str = "succeeded",
            suffix: str = "",
        ) -> ScopedAgentTaskHandle:
            token = suffix or candidate_id
            return ScopedAgentTaskHandle(
                selection_id="selection-1",
                candidate_id=candidate_id,
                session_id=f"child-{token}",
                session_attempt=session_attempt,
                task_id=f"task-{token}",
                turn_id=f"turn-{token}",
                subtask_id=f"{node_run_id}:selection-1:{candidate_id}",
                status=status,
                parent_session_id="root-1",
                root_session_id="root-1",
            )

        def fragment_context(child: ScopedAgentTaskHandle, node_run_id: str) -> dict:
            return {
                "task": {
                    "taskKind": "hypothesis_design",
                    "workflowRunId": "run-1",
                    "workflowNodeId": "hypothesis_design",
                    "nodeRunId": node_run_id,
                    "sourceCollectionRunId": "source-1",
                    "selectionId": child.selection_id,
                    "candidateId": child.candidate_id,
                    "sessionId": child.session_id,
                    "sessionAttempt": child.session_attempt,
                    "taskId": child.task_id,
                    "turn": {"turnId": child.turn_id},
                },
                "hypothesisInput": {
                    "status": "ready",
                    "allowedEvidenceRefs": ["counter-1"],
                },
            }

        def fragment_payload(candidate_id: str) -> dict:
            return {
                "statement": f"statement-{candidate_id}",
                "mechanism": f"mechanism-{candidate_id}",
                "novelty_basis": f"novelty basis-{candidate_id}",
                "predictions": [f"prediction-{candidate_id}"],
                "falsificationCriteria": [f"falsify-{candidate_id}"],
                "evidenceRefs": ["counter-1"],
                "counterEvidenceRefs": ["counter-1"],
                "boundary_conditions": [f"boundary-{candidate_id}"],
                "scores": {
                    "novelty": 0.8,
                    "competitionFit": 0.7,
                    "falsifiability": 0.9,
                    "evidenceSupport": 0.6,
                    "feasibility": 0.75,
                },
            }

        binding = BindingResolution(
            agent_id="agent-1",
            role_key="hypothesis_designer",
        )
        old_children = [
            child_handle("H1", node_run_id="node-1"),
            child_handle("H2", node_run_id="node-1", status="failed"),
            child_handle("H3", node_run_id="node-1"),
        ]
        ports = RealDomainPorts(harness.store)
        first_action = _action(attempt=1, node_run_id="node-1")
        ports._persist_hypothesis_anchor_draft(
            action=first_action,
            binding=binding,
            root_session_id="root-1",
            root_session_attempt=1,
            selection_id="selection-1",
            selected_candidate_ids=["H1", "H2", "H3"],
            handles=old_children,
            candidate_statuses={"H2": "failed"},
            root_status="failed",
        )
        for child in (old_children[0], old_children[2]):
            hypothesis_fragment_writer.record_hypothesis_fragment(
                team_id="team-1",
                task_context=fragment_context(child, "node-1"),
                payload=fragment_payload(child.candidate_id),
                persist=True,
                artifact_sink=workflow_artifact_store.put_workflow_artifact,
            )

        old_tasks = {
            child.candidate_id: {
                "taskId": child.task_id,
                "sessionId": child.session_id,
                "sessionAttempt": child.session_attempt,
                "status": "completed" if child.candidate_id != "H2" else "failed",
                "consumedKnowledgeSnapshotHash": "d" * 64,
                "turn": {"turnId": child.turn_id},
            }
            for child in old_children
        }
        monkeypatch.setattr(
            formal_hypothesis_fanout,
            "_task_from_status",
            lambda **kwargs: dict(old_tasks[kwargs["candidate_id"]]),
        )
        starts: list[dict] = []

        def start_retry(
            team_id: str, project_id: str, payload: dict, **_kwargs: Any
        ) -> dict:
            _ = team_id, project_id
            starts.append(dict(payload))
            return {
                "task": {
                    "taskId": "task-H2-retry",
                    "sessionId": "child-H2-retry",
                    "sessionAttempt": 2,
                    "status": "running",
                    "turn": {"turnId": "turn-H2-retry"},
                },
                "taskId": "task-H2-retry",
                "sessionId": "child-H2-retry",
                "sessionAttempt": 2,
                "startedTurnId": "turn-H2-retry",
            }

        monkeypatch.setattr(
            "core.web.services.team_workflow.research_project_agent_tasks.start_research_project_agent_task",
            start_retry,
        )
        monkeypatch.setattr(
            "core.web.services.session_service.get_session_detail",
            lambda session_id, **_kwargs: {
                "id": session_id,
                "parentSessionId": "root-1",
                "rootSessionId": "root-1",
                "agentId": "agent-1",
            },
        )
        monkeypatch.setattr(
            real_ports_module,
            "_resolve_formal_node_root_session",
            lambda **_kwargs: {"sessionId": "root-1", "sessionAttempt": 1},
        )
        monkeypatch.setattr(
            real_ports_module,
            "_verify_node_root_session",
            lambda *_args, **_kwargs: None,
        )
        monkeypatch.setattr(ports, "resolve_binding", lambda _action: binding)
        monkeypatch.setattr(
            real_ports_module,
            "_candidate_hypothesis_task_context",
            lambda **kwargs: fragment_context(kwargs["child"], "node-2"),
        )
        completed: list[dict] = []
        monkeypatch.setattr(
            real_ports_module,
            "_mark_candidate_task_completed",
            lambda **kwargs: completed.append(dict(kwargs)),
        )
        monkeypatch.setattr(
            "core.web.services.team_workflow.research_runtime.agent_turn_completion.wait_for_agent_turn_terminal",
            lambda *_args, **_kwargs: {"terminal": True, "terminalStatus": "completed"},
        )

        second_action = _action(attempt=2, node_run_id="node-2")
        snapshot = {
            "teamId": "team-1",
            "projectId": "project-1",
            "sourceCollectionRunId": "source-1",
            "hypothesisSelection": {
                "selectionId": "selection-1",
                "selectedCandidateIds": ["H1", "H2", "H3"],
                "candidateSnapshots": [
                    {"candidateId": "H1"},
                    {"candidateId": "H2"},
                    {"candidateId": "H3"},
                ],
            },
        }
        required_model_policy = _formal_required_model_policy()
        handle = ports._create_hypothesis_fan_out(
            action=second_action,
            binding=binding,
            snapshot=snapshot,
            fan_out=snapshot["hypothesisSelection"],
            challenge_task_contract={
                "questionId": "SCI-096",
                "workflowId": "challenge-cup-research",
                "workflowVersionId": "v2.1",
                "workflowRunId": "run-1",
                "workflowNodeId": "hypothesis_design",
                "nodeRunId": "node-2",
                "nodeAttempt": 2,
                "agentId": "agent-1",
                "modelPolicySha256": required_model_policy["policySha256"],
                "requiredModelPolicy": required_model_policy,
            },
            model_invocation_receipt_binding={
                "questionId": "SCI-096",
                "questionRunId": "run-1",
                "workflowRunId": "run-1",
                "workflowId": "challenge-cup-research",
                "workflowVersionId": "v2.1",
                "formalNodeId": "hypothesis_design",
                "formalNodeRunId": "node-2",
                "formalNodeAttempt": 2,
                "questionStage": "generation",
                "outcomeKinds": ["candidate"],
                "modelPolicySha256": required_model_policy["policySha256"],
            },
        )
        retry_child = next(
            item for item in handle.scoped_handles if item.candidate_id == "H2"
        )
        hypothesis_fragment_writer.record_hypothesis_fragment(
            team_id="team-1",
            task_context=fragment_context(retry_child, "node-2"),
            payload=fragment_payload("H2"),
            persist=True,
            artifact_sink=workflow_artifact_store.put_workflow_artifact,
        )

        result = ports._execute_hypothesis_fan_out(
            action=second_action,
            handle=handle,
            snapshot=snapshot,
        )

        by_candidate = {
            item.candidate_id: item for item in result.handle.scoped_handles
        }
        assert (by_candidate["H1"].session_id, by_candidate["H1"].task_id, by_candidate["H1"].turn_id) == (
            "child-H1",
            "task-H1",
            "turn-H1",
        )
        assert (by_candidate["H3"].session_id, by_candidate["H3"].task_id, by_candidate["H3"].turn_id) == (
            "child-H3",
            "task-H3",
            "turn-H3",
        )
        assert (by_candidate["H2"].session_id, by_candidate["H2"].task_id, by_candidate["H2"].turn_id) == (
            "child-H2-retry",
            "task-H2-retry",
            "turn-H2-retry",
        )
        assert len(starts) == 1
        assert starts[0]["candidateId"] == "H2"
        assert starts[0]["formalRetry"] is True
        assert starts[0]["retryTaskId"] == "task-H2"
        assert {item["task_id"] for item in completed} == {
            "task-H1",
            "task-H2-retry",
            "task-H3",
        }

        fragment_rows = workflow_artifact_store.list_workflow_artifacts(
            "team-1",
            kind="hypothesis_fragment",
            workflow_run_id="run-1",
        )
        current_fragments = {
            str((row.get("payload") or {}).get("candidateId")): row
            for row in fragment_rows
            if isinstance(row.get("payload"), dict)
            and row["payload"].get("nodeRunId") == "node-2"
        }
        assert set(current_fragments) == {"H1", "H2", "H3"}
        for candidate_id in ("H1", "H3"):
            provenance = current_fragments[candidate_id]["payload"]["provenance"]
            assert provenance["nodeRunId"] == "node-2"
            assert provenance["replayedFromNodeRunId"] == "node-1"
            assert provenance["replayedFromTaskId"] == f"task-{candidate_id}"
            assert provenance["replayedFromFragmentRef"].endswith(
                f":{candidate_id}:node-1:1"
            )

        hypothesis_sets = workflow_artifact_store.list_workflow_artifacts(
            "team-1", kind="hypothesis_set", workflow_run_id="run-1"
        )
        assert len(hypothesis_sets) == 1
        assert [
            item["candidateId"] for item in hypothesis_sets[0]["payload"]["candidates"]
        ] == ["H1", "H2", "H3"]

        anchor = harness.store.read(
            lambda repo: repo.get_anchor_by_node_run("node-2")
        )
        assert anchor is not None
        anchor_payload = json.loads(anchor[13])
        assert anchor_payload["rootSession"]["status"] == "succeeded"
        assert anchor_payload["scopedSessions"][0]["fragmentRefs"]
        assert anchor_payload["scopedSessions"][1]["sessionAttempt"] == 2
        anchor_count = harness.store.read(
            lambda repo: repo.execute(
                "SELECT COUNT(*) FROM execution_anchors WHERE node_run_id = ?",
                ("node-2",),
            ).fetchone()[0]
        )
        assert anchor_count == 1
    finally:
        harness.close()


# ---------------------------------------------------------------------------
# Non-blocking candidate fan-out (default; [research] blocking_fanout_wait=false)
# ---------------------------------------------------------------------------


def _nonblocking_child(candidate_id: str) -> ScopedAgentTaskHandle:
    return ScopedAgentTaskHandle(
        selection_id="selection-1",
        candidate_id=candidate_id,
        session_id=f"child-{candidate_id}",
        session_attempt=1,
        task_id=f"task-{candidate_id}",
        turn_id=f"turn-{candidate_id}",
        parent_session_id="root-1",
        root_session_id="root-1",
    )


def _fragment_context(child: ScopedAgentTaskHandle, node_run_id: str) -> dict:
    return {
        "task": {
            "taskKind": "hypothesis_design",
            "workflowRunId": "run-1",
            "workflowNodeId": "hypothesis_design",
            "nodeRunId": node_run_id,
            "sourceCollectionRunId": "source-1",
            "selectionId": child.selection_id,
            "candidateId": child.candidate_id,
            "sessionId": child.session_id,
            "sessionAttempt": child.session_attempt,
            "taskId": child.task_id,
            "turn": {"turnId": child.turn_id},
        },
        "hypothesisInput": {
            "status": "ready",
            "allowedEvidenceRefs": ["counter-1"],
        },
    }


def _fragment_payload(candidate_id: str) -> dict:
    return {
        "statement": f"statement-{candidate_id}",
        "mechanism": f"mechanism-{candidate_id}",
        "novelty_basis": f"novelty basis-{candidate_id}",
        "predictions": [f"prediction-{candidate_id}"],
        "falsificationCriteria": [f"falsify-{candidate_id}"],
        "evidenceRefs": ["counter-1"],
        "counterEvidenceRefs": ["counter-1"],
        "boundary_conditions": [f"boundary-{candidate_id}"],
        "scores": {
            "novelty": 0.8,
            "competitionFit": 0.7,
            "falsifiability": 0.9,
            "evidenceSupport": 0.6,
            "feasibility": 0.75,
        },
    }


def _seed_nonblocking_fan_out(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    candidate_ids: list[str],
    *,
    idempotency_key: str,
):
    """Shared stubs: frozen selection, live anchor, terminal-state probe map."""

    monkeypatch.setattr(workflow_artifact_store, "PROJECT_ROOT", tmp_path)
    harness = CommandHarness(tmp_path / f"ledger-{idempotency_key}.sqlite3")
    monkeypatch.setattr(
        real_ports_module,
        "_blocking_hypothesis_fan_out_wait_enabled",
        lambda: False,
    )
    harness.seed_run(run_id="run-1")
    harness.service.submit(
        harness.request(run_id="run-1", idempotency_key=idempotency_key)
    )
    latest = harness.store.latest_attempt("run-1", "source_finding")
    assert latest is not None
    action = _action(node_run_id=latest.node_run_id)
    children = [_nonblocking_child(item) for item in candidate_ids]
    handle = AgentTaskHandle(
        session_id="root-1",
        session_attempt=1,
        task_id="",
        turn_id="",
        root_session_id="root-1",
        root_session_attempt=1,
        scoped_handles=tuple(children),
    )
    binding = BindingResolution(agent_id="agent-1", role_key="hypothesis_designer")
    ports = RealDomainPorts(harness.store)
    monkeypatch.setattr(ports, "resolve_binding", lambda _action: binding)
    monkeypatch.setattr(
        real_ports_module,
        "_formal_hypothesis_fan_out_input",
        lambda **_kwargs: {
            "selection": {
                "selectionId": "selection-1",
                "selectedCandidateIds": list(candidate_ids),
            },
            "selectionId": "selection-1",
            "selectedCandidateIds": list(candidate_ids),
        },
    )
    ports._persist_hypothesis_anchor_draft(
        action=action,
        binding=binding,
        root_session_id="root-1",
        root_session_attempt=1,
        selection_id="selection-1",
        selected_candidate_ids=list(candidate_ids),
        handles=children,
    )
    monkeypatch.setattr(
        real_ports_module,
        "_candidate_hypothesis_task_context",
        lambda **kwargs: _fragment_context(kwargs["child"], latest.node_run_id),
    )
    completed: list[dict] = []
    monkeypatch.setattr(
        real_ports_module,
        "_mark_candidate_task_completed",
        lambda **kwargs: completed.append(dict(kwargs)),
    )
    turn_state: dict[str, str] = {
        child.turn_id: "running" for child in children
    }
    probes: list[str] = []

    def probe(session_id: str, turn_id: str) -> dict:
        probes.append(turn_id)
        state = turn_state[turn_id]
        if state == "failed":
            raise RuntimeError(
                json.dumps(
                    {
                        "code": "agent_turn_terminal_failed",
                        "sessionId": session_id,
                        "turnId": turn_id,
                        "terminalStatus": "failed",
                        "failureClass": "terminal_failure",
                    },
                    ensure_ascii=False,
                )
            )
        if state == "completed":
            return {
                "terminal": True,
                "terminalStatus": "completed",
                "completionSource": "turn_terminal",
            }
        return {
            "terminal": False,
            "completionSource": "running",
            "turnCurrent": True,
            "messageCount": 3,
        }

    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.agent_turn_completion.probe_agent_turn_terminal",
        probe,
    )

    def unexpected_block(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("blocking wait_for_agent_turn_terminal must not run")

    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.agent_turn_completion.wait_for_agent_turn_terminal",
        unexpected_block,
    )
    return (
        harness,
        latest,
        action,
        handle,
        ports,
        turn_state,
        probes,
        completed,
        latest.node_run_id,
    )


def test_nonblocking_fan_out_returns_pending_until_last_candidate_fans_in_once(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default path: probe, requeue pending, and fan in exactly once at the end."""

    harness, latest, action, handle, ports, turn_state, probes, completed, node_run_id = (
        _seed_nonblocking_fan_out(
            tmp_path, monkeypatch, ["H1", "H2", "H3"], idempotency_key="nb-fan-out"
        )
    )
    try:
        snapshot = {
            "teamId": "team-1",
            "projectId": "project-1",
            "sourceCollectionRunId": "source-1",
        }

        def execute() -> Any:
            return ports._execute_hypothesis_fan_out(
                action=action, handle=handle, snapshot=snapshot
            )

        # Pass 1: only H1 is terminal. The call must return promptly with a
        # durable pending signal (no wait primitive, no aggregation yet).
        # Its fragment arrived through the single-shot fan-in writeback when
        # the candidate's turn went terminal.
        hypothesis_fragment_writer.record_hypothesis_fragment(
            team_id="team-1",
            task_context=_fragment_context(handle.scoped_handles[0], node_run_id),
            payload=_fragment_payload("H1"),
            persist=True,
            artifact_sink=workflow_artifact_store.put_workflow_artifact,
        )
        turn_state["turn-H1"] = "completed"
        with pytest.raises(TurnNotReadyError) as pending1:
            execute()
        detail1 = json.loads(str(pending1.value))
        assert detail1["code"] == "hypothesis_fan_out_pending"
        assert detail1["selectionId"] == "selection-1"
        assert detail1["pendingCandidateIds"] == ["H2", "H3"]
        assert pending1.value.snapshot["terminal"] is False
        assert pending1.value.snapshot["completionSource"] == "running"
        assert pending1.value.snapshot["turnCurrent"] is True
        assert probes == ["turn-H1", "turn-H2", "turn-H3"]
        assert workflow_artifact_store.list_workflow_artifacts(
            "team-1", kind="hypothesis_set", workflow_run_id="run-1"
        ) == []

        # H3 finishes out of order (its fragment arrived through the
        # single-shot fan-in writeback before H2's).
        hypothesis_fragment_writer.record_hypothesis_fragment(
            team_id="team-1",
            task_context=_fragment_context(handle.scoped_handles[2], node_run_id),
            payload=_fragment_payload("H3"),
            persist=True,
            artifact_sink=workflow_artifact_store.put_workflow_artifact,
        )
        turn_state["turn-H3"] = "completed"

        # Pass 2: H1 reprocessed idempotently, H3 closed, H2 still pending.
        with pytest.raises(TurnNotReadyError) as pending2:
            execute()
        assert json.loads(str(pending2.value))["pendingCandidateIds"] == ["H2"]
        assert probes[-3:] == ["turn-H1", "turn-H2", "turn-H3"]

        hypothesis_fragment_writer.record_hypothesis_fragment(
            team_id="team-1",
            task_context=_fragment_context(handle.scoped_handles[1], node_run_id),
            payload=_fragment_payload("H2"),
            persist=True,
            artifact_sink=workflow_artifact_store.put_workflow_artifact,
        )
        turn_state["turn-H2"] = "completed"

        # Final pass: all terminal -> deterministic fan-in exactly once.
        result = execute()
        assert result.materialized_refs
        assert result.handle.root_status == "succeeded"
        by_candidate = {
            item.candidate_id: item for item in result.handle.scoped_handles
        }
        assert {item.status for item in by_candidate.values()} == {"succeeded"}
        assert by_candidate["H2"].fragment_refs

        hypothesis_sets = workflow_artifact_store.list_workflow_artifacts(
            "team-1", kind="hypothesis_set", workflow_run_id="run-1"
        )
        assert len(hypothesis_sets) == 1
        assert [
            item["candidateId"]
            for item in hypothesis_sets[0]["payload"]["candidates"]
        ] == ["H1", "H2", "H3"]

        fragment_rows = workflow_artifact_store.list_workflow_artifacts(
            "team-1", kind="hypothesis_fragment", workflow_run_id="run-1"
        )
        assert sorted(
            str(row["payload"]["candidateId"]) for row in fragment_rows
        ) == ["H1", "H2", "H3"]
        assert {item["task_id"] for item in completed} == {
            "task-H1",
            "task-H2",
            "task-H3",
        }

        anchor = harness.store.read(
            lambda repo: repo.get_anchor_by_node_run(latest.node_run_id)
        )
        anchor_payload = json.loads(anchor[13])
        assert anchor_payload["rootSession"]["status"] == "succeeded"
        assert any(
            item.event_type == "workflow.hypothesis_aggregation.completed"
            for item in harness.store.list_events("run-1")
        )
    finally:
        harness.close()


def test_nonblocking_fan_out_candidate_failure_keeps_running_sibling_unchanged(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A terminal-failed candidate fails the node without rewriting the sibling."""

    harness, latest, action, handle, ports, turn_state, probes, _completed, node_run_id = (
        _seed_nonblocking_fan_out(
            tmp_path, monkeypatch, ["H1", "H2"], idempotency_key="nb-failure"
        )
    )
    try:
        turn_state["turn-H1"] = "failed"
        with pytest.raises(RuntimeError, match="agent_turn_terminal_failed"):
            ports._execute_hypothesis_fan_out(
                action=action,
                handle=handle,
                snapshot={
                    "teamId": "team-1",
                    "projectId": "project-1",
                    "sourceCollectionRunId": "source-1",
                },
            )

        anchor = harness.store.read(
            lambda repo: repo.get_anchor_by_node_run(latest.node_run_id)
        )
        anchor_payload = json.loads(anchor[13])
        assert anchor_payload["rootSession"]["status"] == "failed"
        by_candidate = {
            item["candidateId"]: item
            for item in anchor_payload["scopedSessions"]
        }
        assert by_candidate["H1"]["status"] == "failed"
        assert by_candidate["H2"]["status"] == "running"
        assert any(
            item.event_type == "workflow.hypothesis_aggregation.blocked"
            and json.loads(item.payload_json).get("errorCode")
            == "candidate_turn_failed"
            and json.loads(item.payload_json).get("candidateId") == "H1"
            for item in harness.store.list_events("run-1")
        )
    finally:
        harness.close()


def test_blocking_flag_restores_in_thread_child_wait(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``[research] blocking_fanout_wait=true`` keeps the legacy wait semantics."""

    monkeypatch.setattr(workflow_artifact_store, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        real_ports_module,
        "_blocking_hypothesis_fan_out_wait_enabled",
        lambda: True,
    )
    harness = CommandHarness(tmp_path / "ledger-blocking-flag.sqlite3")
    try:
        harness.seed_run(run_id="run-1")
        harness.service.submit(
            harness.request(run_id="run-1", idempotency_key="blocking-flag")
        )
        latest = harness.store.latest_attempt("run-1", "source_finding")
        assert latest is not None
        action = _action(node_run_id=latest.node_run_id)
        children = [_nonblocking_child(item) for item in ("H1", "H2")]
        handle = AgentTaskHandle(
            session_id="root-1",
            session_attempt=1,
            task_id="",
            turn_id="",
            root_session_id="root-1",
            root_session_attempt=1,
            scoped_handles=tuple(children),
        )
        binding = BindingResolution(agent_id="agent-1", role_key="hypothesis_designer")
        ports = RealDomainPorts(harness.store)
        monkeypatch.setattr(ports, "resolve_binding", lambda _action: binding)
        monkeypatch.setattr(
            real_ports_module,
            "_formal_hypothesis_fan_out_input",
            lambda **_kwargs: {
                "selection": {
                    "selectionId": "selection-1",
                    "selectedCandidateIds": ["H1", "H2"],
                },
                "selectionId": "selection-1",
                "selectedCandidateIds": ["H1", "H2"],
            },
        )
        ports._persist_hypothesis_anchor_draft(
            action=action,
            binding=binding,
            root_session_id="root-1",
            root_session_attempt=1,
            selection_id="selection-1",
            selected_candidate_ids=["H1", "H2"],
            handles=children,
        )
        monkeypatch.setattr(
            real_ports_module,
            "_candidate_hypothesis_task_context",
            lambda **kwargs: _fragment_context(kwargs["child"], latest.node_run_id),
        )
        monkeypatch.setattr(
            real_ports_module,
            "_mark_candidate_task_completed",
            lambda **kwargs: None,
        )
        waited_turns: list[str] = []

        def wait(session_id: str, turn_id: str, **_kwargs: Any) -> dict:
            waited_turns.append(turn_id)
            return {
                "terminal": True,
                "terminalStatus": "completed",
                "completionSource": "turn_terminal",
            }

        monkeypatch.setattr(
            "core.web.services.team_workflow.research_runtime.agent_turn_completion.wait_for_agent_turn_terminal",
            wait,
        )

        def unexpected_probe(*_args: Any, **_kwargs: Any) -> dict:
            raise AssertionError("blocking flag must use wait_for_agent_turn_terminal")

        monkeypatch.setattr(
            "core.web.services.team_workflow.research_runtime.agent_turn_completion.probe_agent_turn_terminal",
            unexpected_probe,
        )
        for child in children:
            hypothesis_fragment_writer.record_hypothesis_fragment(
                team_id="team-1",
                task_context=_fragment_context(child, latest.node_run_id),
                payload=_fragment_payload(child.candidate_id),
                persist=True,
                artifact_sink=workflow_artifact_store.put_workflow_artifact,
            )

        result = ports._execute_hypothesis_fan_out(
            action=action,
            handle=handle,
            snapshot={
                "teamId": "team-1",
                "projectId": "project-1",
                "sourceCollectionRunId": "source-1",
            },
        )

        assert waited_turns == ["turn-H1", "turn-H2"]
        assert result.handle.root_status == "succeeded"
    finally:
        harness.close()


def test_nonblocking_fan_out_config_flag_defaults_and_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from config.models import ResearchConfig

    assert ResearchConfig().blocking_fanout_wait is False
    assert ResearchConfig(blocking_fanout_wait=True).blocking_fanout_wait is True
    # Invalid values never block startup and never enable the legacy wait.
    assert ResearchConfig(blocking_fanout_wait="yes").blocking_fanout_wait is False
    assert ResearchConfig(blocking_fanout_wait=1).blocking_fanout_wait is False
    assert ResearchConfig(blocking_fanout_wait=None).blocking_fanout_wait is False

    class _BrokenConfig:
        def __getattr__(self, _name: str) -> Any:
            raise RuntimeError("config authority unavailable")

    monkeypatch.setattr(
        "config.settings.get_config", lambda **_kwargs: _BrokenConfig()
    )
    assert real_ports_module._blocking_hypothesis_fan_out_wait_enabled() is False

    class _LegacyConfig:
        research = ResearchConfig(blocking_fanout_wait=True)

    monkeypatch.setattr(
        "config.settings.get_config", lambda **_kwargs: _LegacyConfig()
    )
    assert real_ports_module._blocking_hypothesis_fan_out_wait_enabled() is True


def _seed_pending_worker_action(
    harness: CommandHarness,
    *,
    outbox_id: str,
    created_at_ms: int = FIXED_NOW_MS,
) -> None:
    action = PendingAction(
        action_id=outbox_id,
        run_id="run-test",
        node_run_id="nr-run-test-hypothesis_design-a1",
        node_id="hypothesis_design",
        attempt=1,
        actor_kind=ActorKind.AGENT,
        action_kind="start_agent_task",
        input_snapshot_hash="a" * 64,
        input_artifact_refs=(),
        binding_snapshot_id=None,
        budget_policy_hash="policy-1",
    )

    def mutate(uow) -> None:
        uow.repository.insert_command(
            build_command_record(
                command_id=f"cmd-{outbox_id}",
                run_id=action.run_id,
                node_id=action.node_id,
            )
        )
        uow.repository.insert_attempt(
            build_attempt_record(
                node_run_id=action.node_run_id,
                run_id=action.run_id,
                node_id=action.node_id,
                attempt=1,
                status="running",
                command_id=f"cmd-{outbox_id}",
                started_at_ms=FIXED_NOW_MS,
            )
        )
        uow.repository.insert_outbox(
            replace(
                build_outbox_record(
                    outbox_id,
                    run_id=action.run_id,
                    command_id=f"cmd-{outbox_id}",
                    action_kind="adapter_dispatch",
                    available_at_ms=FIXED_NOW_MS,
                ),
                node_run_id=action.node_run_id,
                payload_json=json.dumps(action.to_dict()),
                created_at_ms=created_at_ms,
            )
        )

    harness.store.submit(mutate, force_flush=True).result(timeout=10)


def _pending_fan_out_error() -> TurnNotReadyError:
    return real_ports_module._hypothesis_fan_out_pending_error(
        fan_out={"selectionId": "selection-1"},
        pending_children=[
            (
                _nonblocking_child("H1"),
                {
                    "terminal": False,
                    "completionSource": "running",
                    "turnCurrent": True,
                    "messageCount": 3,
                },
            )
        ],
    )


def test_pending_fan_out_requeues_action_without_consuming_failure_budget(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The pump stays free: a pending fan-out becomes a durable live-wait requeue."""

    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.challenge_turn_policy.CHALLENGE_LOGICAL_TASK_TIMEOUT_MS",
        1_800_000,
    )
    harness = CommandHarness(tmp_path / "ledger-requeue.sqlite3")
    try:
        harness.seed_run(status="running")
        _seed_pending_worker_action(harness, outbox_id="act-pending-fanout")
        ports = FakeDomainPorts()
        error = _pending_fan_out_error()

        def raise_pending(*, action, handle):
            raise error

        monkeypatch.setattr(ports, "execute_agent_turn", raise_pending)
        registry = ActionRegistry()
        register_default_adapters(registry, ports)
        worker = AdapterDispatchWorker(
            store=harness.store,
            registry=registry,
            ports=ports,
            owner_id="adapter-worker-test",
            now_provider=lambda: FIXED_NOW_MS + 1_000,
        )

        assert worker.run_once() == 1

        outbox = harness.store.read(lambda repo: repo.get_outbox("act-pending-fanout"))
        assert outbox is not None and outbox.status == "pending"
        problem = json.loads(str(outbox.last_problem_json))
        assert problem["code"] == "live_turn_wait"
        assert outbox.available_at_ms == FIXED_NOW_MS + 1_000 + 5_000
        # The requeue must not consume the transient-failure budget.
        assert outbox.attempt_count == 0
        attempt = harness.store.latest_attempt("run-test", "hypothesis_design")
        assert attempt is not None and attempt.status == "running"
        assert harness.store.get_run("run-test").status == "running"
        # The park is durable: an immediate second tick must not busy-loop it.
        assert worker.run_once() == 0
    finally:
        harness.close()


def test_pending_fan_out_deadline_exhaustion_fails_the_node(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Timeout fallback: an exhausted wall-clock cap fails the pending fan-out."""

    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.challenge_turn_policy.CHALLENGE_LOGICAL_TASK_TIMEOUT_MS",
        1_800_000,
    )
    harness = CommandHarness(tmp_path / "ledger-expired.sqlite3")
    try:
        harness.seed_run(status="running")
        _seed_pending_worker_action(
            harness,
            outbox_id="act-expired-fanout",
            created_at_ms=FIXED_NOW_MS - 2_000_000,
        )
        ports = FakeDomainPorts()
        monkeypatch.setattr(
            ports, "execute_agent_turn", lambda *, action, handle: (_ for _ in ()).throw(
                _pending_fan_out_error()
            )
        )
        registry = ActionRegistry()
        register_default_adapters(registry, ports)
        worker = AdapterDispatchWorker(
            store=harness.store,
            registry=registry,
            ports=ports,
            owner_id="adapter-worker-test",
            now_provider=lambda: FIXED_NOW_MS + 1_000,
        )

        assert worker.run_once() == 1

        outbox = harness.store.read(lambda repo: repo.get_outbox("act-expired-fanout"))
        assert outbox is not None and outbox.status == "failed"
        problem = json.loads(str(outbox.last_problem_json))
        assert problem["code"] == "live_turn_wait_timeout"
        attempt = harness.store.latest_attempt("run-test", "hypothesis_design")
        assert attempt is not None and attempt.status == "failed"
        run = harness.store.get_run("run-test")
        assert run.status == "blocked"
    finally:
        harness.close()
