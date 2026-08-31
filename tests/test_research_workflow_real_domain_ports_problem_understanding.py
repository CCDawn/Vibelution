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
    def result(self, timeout: int):
        return None


class _Repository:
    def __init__(self, store: _FakeStore) -> None:
        self._store = store

    def get_run(self, run_id: str):
        snapshot = self._store.snapshot_json
        return SimpleNamespace(
            input_snapshot_json=snapshot,
            workflow_id=self._store.workflow_id,
        )

    def get_attempt(self, node_run_id: str):
        return self._store.attempts.get(node_run_id)

    def execute(self, _sql: str, params: tuple[str, int, str]):
        self._store.snapshot_json = params[0]


class _UnitOfWork:
    def __init__(self, store: _FakeStore) -> None:
        self.repository = _Repository(store)


class _FakeStore:
    def __init__(
        self,
        snapshot: dict[str, object] | None,
        *,
        workflow_id: str = "",
        attempts: dict[str, object] | None = None,
    ) -> None:
        self.snapshot_json = (
            json.dumps(snapshot, ensure_ascii=False) if snapshot is not None else ""
        )
        self.workflow_id = workflow_id
        self.attempts = dict(attempts or {})

    def submit(self, callback, *, force_flush: bool = False):
        callback(_UnitOfWork(self))
        return _Future()

    def get_run(self, run_id: str):
        return SimpleNamespace(
            input_snapshot_json=self.snapshot_json,
            workflow_id=self.workflow_id,
        )

    def read(self, callback):
        return callback(_Repository(self))


def _action(
    *,
    node_run_id: str = "node-run-problem-1",
    attempt: int = 1,
) -> SimpleNamespace:
    return SimpleNamespace(
        action_id="action-problem-1",
        run_id="workflow-run-1",
        node_run_id=node_run_id,
        node_id="problem_understanding",
        attempt=attempt,
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

    from core.web.services.team_workflow import research_project_agent_tasks
    from core.web.services.team_workflow.research_runtime import (
        experiment_stage_bootstrap,
        task_adapter_registry,
    )
    from core.web.services.team_workflow.source_collection import runs as source_runs

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


def _ledger_attempt(
    node_run_id: str,
    *,
    retry_of_node_run_id: str | None,
    attempt: int,
    run_id: str = "workflow-run-1",
    node_id: str = "problem_understanding",
) -> SimpleNamespace:
    return SimpleNamespace(
        node_run_id=node_run_id,
        run_id=run_id,
        node_id=node_id,
        attempt=attempt,
        retry_of_node_run_id=retry_of_node_run_id,
    )


def _retry_store(attempts: dict[str, SimpleNamespace]) -> _FakeStore:
    snapshot = _snapshot()
    snapshot["sourceCollectionRunId"] = "source-run-existing"
    return _FakeStore(snapshot, workflow_id="ledger-workflow", attempts=attempts)


def _patch_retry_collaborators(
    monkeypatch: pytest.MonkeyPatch,
    *,
    tasks: list[dict[str, object]],
) -> None:
    from core.web.services.team_workflow import research_project_agent_tasks
    from core.web.services.team_workflow.research_runtime import (
        experiment_stage_bootstrap,
    )

    monkeypatch.setattr(
        real_domain_ports,
        "_formal_task_authorities",
        lambda **_kwargs: ({"server": "contract"}, {"receipt": "binding"}),
    )
    monkeypatch.setattr(
        experiment_stage_bootstrap,
        "ensure_experiment_stage_round_for_agent_node",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        research_project_agent_tasks,
        "get_research_project_agent_task_status",
        lambda *_args: {"tasks": tasks},
    )


def _project_task(
    task_id: str,
    node_run_id: str,
    *,
    status: str = "failed",
) -> dict[str, object]:
    return {
        "taskId": task_id,
        "workflowRunId": "workflow-run-1",
        "nodeRunId": node_run_id,
        "agentId": "agent-search",
        "taskKind": "problem_understanding",
        "status": status,
    }


def test_problem_understanding_retry_uses_exact_parent_project_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _snapshot()
    snapshot["sourceCollectionRunId"] = "source-run-existing"
    store = _FakeStore(
        snapshot,
        workflow_id="ledger-workflow",
        attempts={
            "node-run-problem-1": SimpleNamespace(
                run_id="workflow-run-1",
                node_id="problem_understanding",
                retry_of_node_run_id=None,
            ),
            "node-run-problem-2": SimpleNamespace(
                run_id="workflow-run-1",
                node_id="problem_understanding",
                retry_of_node_run_id="node-run-problem-1",
            ),
        },
    )
    from core.web.services.team_workflow import research_project_agent_tasks
    from core.web.services.team_workflow.research_runtime import (
        experiment_stage_bootstrap,
    )

    monkeypatch.setattr(
        real_domain_ports,
        "_formal_task_authorities",
        lambda **_kwargs: ({"server": "contract"}, {"receipt": "binding"}),
    )
    monkeypatch.setattr(
        experiment_stage_bootstrap,
        "ensure_experiment_stage_round_for_agent_node",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        research_project_agent_tasks,
        "get_research_project_agent_task_status",
        lambda *_args: {
            "tasks": [
                {
                    "taskId": "task-unrelated",
                    "workflowRunId": "workflow-run-1",
                    "nodeRunId": "node-run-other",
                    "agentId": "agent-search",
                    "taskKind": "problem_understanding",
                },
                {
                    "taskId": "task-problem-parent",
                    "workflowRunId": "workflow-run-1",
                    "nodeRunId": "node-run-problem-1",
                    "agentId": "agent-search",
                    "taskKind": "problem_understanding",
                    "status": "failed",
                },
            ]
        },
    )
    payloads: list[dict[str, object]] = []

    def start_project_task(_team_id, _project_id, payload, **_kwargs):
        payloads.append(dict(payload))
        return {
            "taskId": "task-problem-retry",
            "sessionId": "session-problem-retry",
            "sessionAttempt": 2,
            "task": {"turn": {"turnId": "turn-problem-retry"}},
        }

    monkeypatch.setattr(
        research_project_agent_tasks,
        "start_research_project_agent_task",
        start_project_task,
    )

    handle = real_domain_ports._create_real_agent_task(
        _action(node_run_id="node-run-problem-2", attempt=2),
        _binding(),
        snapshot,
        adapter_spec=AgentTaskAdapterSpec(
            node_id="problem_understanding",
            family="research_project",
            task_key="problem_understanding",
        ),
        store=store,
    )

    assert handle.task_id == "task-problem-retry"
    assert payloads[0]["formalRetry"] is True
    assert payloads[0]["retryTaskId"] == "task-problem-parent"


def test_problem_understanding_retry_fails_closed_on_ambiguous_parent_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A retry must never attach to an ambiguous parent project task."""
    snapshot = _snapshot()
    snapshot["sourceCollectionRunId"] = "source-run-existing"
    store = _FakeStore(
        snapshot,
        workflow_id="ledger-workflow",
        attempts={
            "node-run-problem-1": SimpleNamespace(
                run_id="workflow-run-1",
                node_id="problem_understanding",
                retry_of_node_run_id=None,
            ),
            "node-run-problem-2": SimpleNamespace(
                run_id="workflow-run-1",
                node_id="problem_understanding",
                retry_of_node_run_id="node-run-problem-1",
            ),
        },
    )
    from core.web.services.team_workflow import research_project_agent_tasks
    from core.web.services.team_workflow.research_runtime import (
        experiment_stage_bootstrap,
    )

    monkeypatch.setattr(
        real_domain_ports,
        "_formal_task_authorities",
        lambda **_kwargs: ({"server": "contract"}, {"receipt": "binding"}),
    )
    monkeypatch.setattr(
        experiment_stage_bootstrap,
        "ensure_experiment_stage_round_for_agent_node",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        research_project_agent_tasks,
        "get_research_project_agent_task_status",
        lambda *_args: {
            "tasks": [
                {
                    "taskId": "task-parent-duplicate-a",
                    "workflowRunId": "workflow-run-1",
                    "nodeRunId": "node-run-problem-1",
                    "agentId": "agent-search",
                    "taskKind": "problem_understanding",
                },
                {
                    "taskId": "task-parent-duplicate-b",
                    "workflowRunId": "workflow-run-1",
                    "nodeRunId": "node-run-problem-1",
                    "agentId": "agent-search",
                    "taskKind": "problem_understanding",
                },
            ]
        },
    )

    def start_project_task(*_args, **_kwargs):
        pytest.fail("ambiguous retry lineage must fail closed before task creation")

    monkeypatch.setattr(
        research_project_agent_tasks,
        "start_research_project_agent_task",
        start_project_task,
    )

    with pytest.raises(RuntimeError, match="missing or ambiguous"):
        real_domain_ports._create_real_agent_task(
            _action(node_run_id="node-run-problem-2", attempt=2),
            _binding(),
            snapshot,
            adapter_spec=AgentTaskAdapterSpec(
                node_id="problem_understanding",
                family="research_project",
                task_key="problem_understanding",
            ),
            store=store,
        )


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


def test_problem_understanding_retry_resolves_nearest_tasked_ancestor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A retry whose direct parent owns no project task still resolves.

    Regression: a retry rejected before task creation (for example the
    ``previous task is still active`` guard) leaves a task-less Ledger
    attempt.  Later retries must walk past it to the nearest tasked
    ancestor instead of failing forever.
    """
    store = _retry_store(
        {
            "node-run-problem-1": _ledger_attempt(
                "node-run-problem-1",
                retry_of_node_run_id=None,
                attempt=1,
            ),
            "node-run-problem-2": _ledger_attempt(
                "node-run-problem-2",
                retry_of_node_run_id="node-run-problem-1",
                attempt=2,
            ),
            "node-run-problem-3": _ledger_attempt(
                "node-run-problem-3",
                retry_of_node_run_id="node-run-problem-2",
                attempt=3,
            ),
        }
    )
    _patch_retry_collaborators(
        monkeypatch,
        tasks=[
            {
                "taskId": "task-unrelated",
                "workflowRunId": "workflow-run-1",
                "nodeRunId": "node-run-other",
                "agentId": "agent-search",
                "taskKind": "problem_understanding",
            },
            _project_task("task-problem-root", "node-run-problem-1"),
        ],
    )
    payloads: list[dict[str, object]] = []

    def start_project_task(_team_id, _project_id, payload, **_kwargs):
        payloads.append(dict(payload))
        return {
            "taskId": "task-problem-retry",
            "sessionId": "session-problem-retry",
            "sessionAttempt": 3,
            "task": {"turn": {"turnId": "turn-problem-retry"}},
        }

    from core.web.services.team_workflow import research_project_agent_tasks

    monkeypatch.setattr(
        research_project_agent_tasks,
        "start_research_project_agent_task",
        start_project_task,
    )

    handle = real_domain_ports._create_real_agent_task(
        _action(node_run_id="node-run-problem-3", attempt=3),
        _binding(),
        _snapshot() | {"sourceCollectionRunId": "source-run-existing"},
        adapter_spec=AgentTaskAdapterSpec(
            node_id="problem_understanding",
            family="research_project",
            task_key="problem_understanding",
        ),
        store=store,
    )

    assert handle.task_id == "task-problem-retry"
    assert payloads[0]["formalRetry"] is True
    assert payloads[0]["retryTaskId"] == "task-problem-root"


def test_problem_understanding_retry_without_lineage_task_starts_fresh_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _retry_store(
        {
            "node-run-problem-1": _ledger_attempt(
                "node-run-problem-1",
                retry_of_node_run_id=None,
                attempt=1,
            ),
            "node-run-problem-2": _ledger_attempt(
                "node-run-problem-2",
                retry_of_node_run_id="node-run-problem-1",
                attempt=2,
            ),
            "node-run-problem-3": _ledger_attempt(
                "node-run-problem-3",
                retry_of_node_run_id="node-run-problem-2",
                attempt=3,
            ),
        }
    )
    _patch_retry_collaborators(
        monkeypatch,
        tasks=[
            {
                "taskId": "task-unrelated",
                "workflowRunId": "workflow-run-1",
                "nodeRunId": "node-run-other",
                "agentId": "agent-search",
                "taskKind": "problem_understanding",
            }
        ],
    )

    payloads: list[dict[str, object]] = []

    def start_project_task(_team_id, _project_id, payload, **_kwargs):
        payloads.append(dict(payload))
        return {
            "taskId": "task-problem-first-dispatch",
            "sessionId": "session-problem-first-dispatch",
            "sessionAttempt": 1,
            "task": {"turn": {"turnId": "turn-problem-first-dispatch"}},
        }

    from core.web.services.team_workflow import research_project_agent_tasks

    monkeypatch.setattr(
        research_project_agent_tasks,
        "start_research_project_agent_task",
        start_project_task,
    )

    handle = real_domain_ports._create_real_agent_task(
        _action(node_run_id="node-run-problem-3", attempt=3),
        _binding(),
        _snapshot() | {"sourceCollectionRunId": "source-run-existing"},
        adapter_spec=AgentTaskAdapterSpec(
            node_id="problem_understanding",
            family="research_project",
            task_key="problem_understanding",
        ),
        store=store,
    )

    assert handle.task_id == "task-problem-first-dispatch"
    assert "formalRetry" not in payloads[0]
    assert "retryTaskId" not in payloads[0]


def test_problem_understanding_retry_fails_closed_on_cross_run_lineage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _retry_store(
        {
            "node-run-problem-1": _ledger_attempt(
                "node-run-problem-1",
                retry_of_node_run_id=None,
                attempt=1,
                run_id="workflow-run-other",
            ),
            "node-run-problem-2": _ledger_attempt(
                "node-run-problem-2",
                retry_of_node_run_id="node-run-problem-1",
                attempt=2,
            ),
        }
    )
    _patch_retry_collaborators(
        monkeypatch,
        tasks=[_project_task("task-foreign-run", "node-run-problem-1")],
    )

    def start_project_task(*_args, **_kwargs):
        pytest.fail("cross-run lineage must fail closed before task creation")

    from core.web.services.team_workflow import research_project_agent_tasks

    monkeypatch.setattr(
        research_project_agent_tasks,
        "start_research_project_agent_task",
        start_project_task,
    )

    with pytest.raises(RuntimeError, match="lineage identity mismatch"):
        real_domain_ports._create_real_agent_task(
            _action(node_run_id="node-run-problem-2", attempt=2),
            _binding(),
            _snapshot() | {"sourceCollectionRunId": "source-run-existing"},
            adapter_spec=AgentTaskAdapterSpec(
                node_id="problem_understanding",
                family="research_project",
                task_key="problem_understanding",
            ),
            store=store,
        )


def test_problem_understanding_retry_fails_closed_on_ambiguous_lineage_ancestor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ambiguity deeper in the lineage must still fail closed."""
    store = _retry_store(
        {
            "node-run-problem-1": _ledger_attempt(
                "node-run-problem-1",
                retry_of_node_run_id=None,
                attempt=1,
            ),
            "node-run-problem-2": _ledger_attempt(
                "node-run-problem-2",
                retry_of_node_run_id="node-run-problem-1",
                attempt=2,
            ),
            "node-run-problem-3": _ledger_attempt(
                "node-run-problem-3",
                retry_of_node_run_id="node-run-problem-2",
                attempt=3,
            ),
        }
    )
    _patch_retry_collaborators(
        monkeypatch,
        tasks=[
            _project_task(
                "task-root-duplicate-a",
                "node-run-problem-1",
                status="failed",
            ),
            _project_task(
                "task-root-duplicate-b",
                "node-run-problem-1",
                status="cancelled",
            ),
        ],
    )

    def start_project_task(*_args, **_kwargs):
        pytest.fail("ambiguous lineage must fail closed before task creation")

    from core.web.services.team_workflow import research_project_agent_tasks

    monkeypatch.setattr(
        research_project_agent_tasks,
        "start_research_project_agent_task",
        start_project_task,
    )

    with pytest.raises(RuntimeError, match="missing or ambiguous"):
        real_domain_ports._create_real_agent_task(
            _action(node_run_id="node-run-problem-3", attempt=3),
            _binding(),
            _snapshot() | {"sourceCollectionRunId": "source-run-existing"},
            adapter_spec=AgentTaskAdapterSpec(
                node_id="problem_understanding",
                family="research_project",
                task_key="problem_understanding",
            ),
            store=store,
        )
