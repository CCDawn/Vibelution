from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from core.research.competition.question_result_package import canonical_model_policy
from core.web.services.team_workflow.research_runtime import real_domain_ports
from core.web.services.team_workflow.research_runtime.task_adapter_registry import (
    AgentTaskAdapterSpec,
)


class _Future:
    def result(self, timeout: int):  # noqa: ARG002 - mirrors the Ledger Future API
        return None


class _Repository:
    def __init__(self, store: "_FakeStore") -> None:
        self._store = store

    def get_run(self, run_id: str):  # noqa: ARG002 - the fixture has one run
        snapshot = self._store.snapshot_json
        return SimpleNamespace(
            input_snapshot_json=snapshot,
            workflow_id=self._store.workflow_id,
        )

    def execute(self, _sql: str, params: tuple[str, int, str]):
        self._store.snapshot_json = params[0]
        return None


class _UnitOfWork:
    def __init__(self, store: "_FakeStore") -> None:
        self.repository = _Repository(store)


class _FakeStore:
    def __init__(
        self,
        snapshot: dict[str, object] | None,
        *,
        workflow_id: str = "",
    ) -> None:
        self.snapshot_json = (
            json.dumps(snapshot, ensure_ascii=False) if snapshot is not None else ""
        )
        self.workflow_id = workflow_id

    def submit(self, callback, *, force_flush: bool = False):  # noqa: ARG002
        callback(_UnitOfWork(self))
        return _Future()

    def get_run(self, run_id: str):  # noqa: ARG002
        return SimpleNamespace(
            input_snapshot_json=self.snapshot_json,
            workflow_id=self.workflow_id,
        )


def _action() -> SimpleNamespace:
    return SimpleNamespace(
        action_id="action-problem-1",
        run_id="workflow-run-1",
        node_run_id="node-run-problem-1",
        node_id="problem_understanding",
        attempt=1,
        selection_id="",
        candidate_id="",
        scope={},
    )


def _binding() -> SimpleNamespace:
    return SimpleNamespace(agent_id="agent-search", role_key="challenge_cup_search")


def _snapshot() -> dict[str, object]:
    required_model_policy = canonical_model_policy(
        {
            "family": "qwen",
            "providerIds": ["dashscope_main"],
            "modelIds": ["qwen3.6-plus"],
            "requireOfficialProvider": True,
        }
    )
    return {
        "teamId": "research-team",
        "projectId": "research-project-1",
        "questionId": "SCI-096",
        "researchObjectiveContract": {"question": "如何提高记忆提取的可验证性"},
        "datasetRefs": ["dataset://brief"],
        "modelRoutingPolicy": {"requiredModelPolicy": required_model_policy},
    }


def test_problem_understanding_uses_knowledge_collection_stage() -> None:
    assert real_domain_ports._stage_for("problem_understanding") == "knowledge_collection"


def test_problem_understanding_reuses_existing_source_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _snapshot()
    snapshot["sourceCollectionRunId"] = "source-run-existing"
    store = _FakeStore(snapshot)
    from core.web.services.team_workflow.source_collection import runs as source_runs

    monkeypatch.setattr(
        source_runs,
        "start_source_collection_run",
        lambda *_args, **_kwargs: pytest.fail("existing source run must not be recreated"),
    )

    assert (
        real_domain_ports._ensure_problem_understanding_source_collection_run(
            team_id="research-team",
            project_id="research-project-1",
            input_snapshot=snapshot,
            action=_action(),
            binding=_binding(),
            store=store,
        )
        == "source-run-existing"
    )


def test_problem_understanding_bootstrap_persists_source_run_before_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _FakeStore(_snapshot(), workflow_id="ledger-workflow")
    started_source_runs: list[dict[str, object]] = []
    calls: list[str] = []
    authority_calls: list[dict[str, object]] = []

    from core.web.services.team_workflow.research_runtime import (
        experiment_stage_bootstrap,
        task_adapter_registry,
    )
    from core.web.services.team_workflow.source_collection import runs as source_runs
    from core.web.services.team_workflow import research_project_agent_tasks

    monkeypatch.setattr(
        source_runs,
        "start_source_collection_run",
        lambda team_id, payload: started_source_runs.append(
            {"teamId": team_id, "payload": payload}
        )
        or {"run": {"runId": "source-run-1"}},
    )
    monkeypatch.setattr(
        task_adapter_registry,
        "resolve_agent_task_adapter",
        lambda node_id: AgentTaskAdapterSpec(
            node_id=node_id,
            family="research_project",
            task_key="problem_understanding",
        ),
    )
    monkeypatch.setattr(
        real_domain_ports,
        "_formal_task_authorities",
        lambda **kwargs: authority_calls.append(kwargs)
        or ({"server": "contract"}, {"receipt": "binding"}),
    )
    monkeypatch.setattr(
        experiment_stage_bootstrap,
        "ensure_experiment_stage_round_for_agent_node",
        lambda **_kwargs: calls.append("stage_bootstrap"),
    )

    project_task_payloads: list[dict[str, object]] = []

    def start_project_task(team_id, project_id, payload, **kwargs):
        calls.append("project_task")
        project_task_payloads.append(
            {
                "teamId": team_id,
                "projectId": project_id,
                "payload": payload,
                "kwargs": kwargs,
            }
        )
        return {
            "taskId": "task-problem-1",
            "sessionId": "session-problem-1",
            "task": {"turn": {"turnId": "turn-problem-1"}},
        }

    monkeypatch.setattr(
        research_project_agent_tasks,
        "start_research_project_agent_task",
        start_project_task,
    )

    handle = real_domain_ports._create_real_agent_task(
        _action(),
        _binding(),
        _snapshot(),
        adapter_spec=AgentTaskAdapterSpec(
            node_id="problem_understanding",
            family="research_project",
            task_key="problem_understanding",
        ),
        store=store,
    )

    assert handle.task_id == "task-problem-1"
    assert len(started_source_runs) == 1
    assert calls == ["stage_bootstrap", "project_task"]
    assert authority_calls[0]["workflow_id"] == "ledger-workflow"
    task_record = project_task_payloads[0]
    assert task_record["payload"]["sourceCollectionRunId"] == "source-run-1"
    assert task_record["kwargs"]["_challenge_task_contract"]["sourceCollectionRunId"] == (
        "source-run-1"
    )
    assert json.loads(store.snapshot_json)["sourceCollectionRunId"] == "source-run-1"


def test_problem_understanding_fails_closed_when_snapshot_writeback_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _FakeStore(None)
    from core.web.services.team_workflow.source_collection import runs as source_runs

    monkeypatch.setattr(
        source_runs,
        "start_source_collection_run",
        lambda *_args, **_kwargs: {"run": {"runId": "source-run-1"}},
    )
    with pytest.raises(RuntimeError, match="input snapshot"):
        real_domain_ports._ensure_problem_understanding_source_collection_run(
            team_id="research-team",
            project_id="research-project-1",
            input_snapshot=_snapshot(),
            action=_action(),
            binding=_binding(),
            store=store,
        )
