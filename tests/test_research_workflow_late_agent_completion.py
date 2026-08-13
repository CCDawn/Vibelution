from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.research.workflow.contracts import PendingAction
from core.research.workflow.models import ActorKind
from core.web.services.team_workflow.research_runtime.domain_ports import (
    BindingResolution,
)
from core.web.services.team_workflow.research_runtime.real_domain_ports import (
    _start_source_collection_agent_task,
)
from core.web.services.team_workflow.research_runtime.source_stage_task_replay import (
    find_reusable_source_stage_task,
)


def _action(*, node_run_id: str, attempt: int) -> PendingAction:
    return PendingAction(
        action_id=f"act-{attempt}",
        run_id="run-retry",
        node_run_id=node_run_id,
        node_id="source_extraction",
        attempt=attempt,
        actor_kind=ActorKind.AGENT,
        action_kind="start_agent_task",
        input_snapshot_hash="a" * 64,
        input_artifact_refs=(),
        binding_snapshot_id="binding-extractor",
        budget_policy_hash="budget-v1",
    )


class _AttemptStore:
    def __init__(self, attempts: dict[str, SimpleNamespace]) -> None:
        self._attempts = attempts

    def read(self, callback):
        attempts = self._attempts

        class _Repository:
            @staticmethod
            def get_attempt(node_run_id: str):
                return attempts.get(node_run_id)

        return callback(_Repository())


def _stage_task(*, task_id: str, status: str = "completed") -> dict:
    return {
        "taskId": task_id,
        "teamId": "research-team",
        "runId": "dprun-source",
        "stageId": "extraction",
        "agentId": "agent-extractor",
        "agentRole": "source_extractor",
        "sessionId": "session-extractor",
        "status": status,
        "turn": {"turnId": "turn-extractor", "accepted": True},
    }


def test_same_node_run_reuses_exact_running_stage_task_before_context_load(
    monkeypatch,
) -> None:
    from core.web.services.team_workflow.source_collection import stage_reconcile

    task = _stage_task(task_id="task-current", status="running")
    requested_keys: list[str] = []

    def find_task(_team_id: str, _run_id: str, *, idempotency_key: str):
        requested_keys.append(idempotency_key)
        return task

    monkeypatch.setattr(
        stage_reconcile,
        "_find_source_collection_stage_session_task",
        find_task,
    )

    replay = find_reusable_source_stage_task(
        store=None,
        action=_action(node_run_id="nr-run-retry-source_extraction-a11", attempt=11),
        team_id="research-team",
        source_run_id="dprun-source",
        stage_id="extraction",
        agent_id="agent-extractor",
        agent_role="source_extractor",
    )

    assert replay is not None
    assert replay["taskId"] == "task-current"
    assert replay["created"] is False
    assert requested_keys == [
        stage_reconcile._source_collection_stage_task_idempotency_key(
            team_id="research-team",
            run_id="dprun-source",
            stage_id="extraction",
            agent_id="agent-extractor",
            agent_role="source_extractor",
            task_id="",
            requested_key="agent-task:nr-run-retry-source_extraction-a11",
        )
    ]


def test_retry_reuses_only_its_exact_completed_parent_node_run(monkeypatch) -> None:
    from core.web.services.team_workflow.source_collection import stage_reconcile

    current_node_run_id = "nr-run-retry-source_extraction-a12"
    parent_node_run_id = "nr-run-retry-source_extraction-a11"
    store = _AttemptStore(
        {
            current_node_run_id: SimpleNamespace(
                node_run_id=current_node_run_id,
                run_id="run-retry",
                node_id="source_extraction",
                retry_of_node_run_id=parent_node_run_id,
            ),
            parent_node_run_id: SimpleNamespace(
                node_run_id=parent_node_run_id,
                run_id="run-retry",
                node_id="source_extraction",
                retry_of_node_run_id=None,
            ),
        }
    )
    parent_key = stage_reconcile._source_collection_stage_task_idempotency_key(
        team_id="research-team",
        run_id="dprun-source",
        stage_id="extraction",
        agent_id="agent-extractor",
        agent_role="source_extractor",
        task_id="",
        requested_key=f"agent-task:{parent_node_run_id}",
    )
    lookups: list[str] = []

    def find_task(_team_id: str, _run_id: str, *, idempotency_key: str):
        lookups.append(idempotency_key)
        if idempotency_key == parent_key:
            return _stage_task(task_id="task-parent", status="completed")
        return None

    monkeypatch.setattr(
        stage_reconcile,
        "_find_source_collection_stage_session_task",
        find_task,
    )

    replay = find_reusable_source_stage_task(
        store=store,
        action=_action(node_run_id=current_node_run_id, attempt=12),
        team_id="research-team",
        source_run_id="dprun-source",
        stage_id="extraction",
        agent_id="agent-extractor",
        agent_role="source_extractor",
    )

    assert replay is not None
    assert replay["taskId"] == "task-parent"
    assert lookups[-1] == parent_key


def test_source_adapter_reuses_late_parent_before_remediation_context(
    monkeypatch,
) -> None:
    from core.web.services.team_workflow.research_runtime import (
        agent_claim_evidence_materializer,
    )
    from core.web.services.team_workflow.source_collection import (
        stage_reconcile,
        stage_session,
    )

    current_node_run_id = "nr-run-retry-source_extraction-a12"
    parent_node_run_id = "nr-run-retry-source_extraction-a11"
    store = _AttemptStore(
        {
            current_node_run_id: SimpleNamespace(
                node_run_id=current_node_run_id,
                run_id="run-retry",
                node_id="source_extraction",
                retry_of_node_run_id=parent_node_run_id,
            ),
            parent_node_run_id: SimpleNamespace(
                node_run_id=parent_node_run_id,
                run_id="run-retry",
                node_id="source_extraction",
                retry_of_node_run_id=None,
            ),
        }
    )
    parent_key = stage_reconcile._source_collection_stage_task_idempotency_key(
        team_id="research-team",
        run_id="dprun-source",
        stage_id="extraction",
        agent_id="agent-extractor",
        agent_role="source_extractor",
        task_id="",
        requested_key=f"agent-task:{parent_node_run_id}",
    )

    def find_task(_team_id: str, _run_id: str, *, idempotency_key: str):
        if idempotency_key == parent_key:
            return _stage_task(task_id="task-parent", status="completed")
        return None

    monkeypatch.setattr(
        stage_reconcile,
        "_find_source_collection_stage_session_task",
        find_task,
    )
    monkeypatch.setattr(
        agent_claim_evidence_materializer,
        "build_formal_evidence_retry_contract",
        lambda **_kwargs: pytest.fail("remediation context must not load before replay"),
    )
    monkeypatch.setattr(
        stage_session,
        "start_source_collection_stage_session_task",
        lambda *_args, **_kwargs: pytest.fail("must not create a duplicate stage task"),
    )

    replay = _start_source_collection_agent_task(
        team_id="research-team",
        project_id="challenge-sci-096",
        input_snapshot={"sourceCollectionRunId": "dprun-source"},
        action=_action(node_run_id=current_node_run_id, attempt=12),
        binding=BindingResolution(
            agent_id="agent-extractor",
            role_key="source_extractor",
            binding_snapshot_id="binding-extractor",
        ),
        stage_id="extraction",
        role_key="source_extractor",
        idempotency_key=f"agent-task:{current_node_run_id}",
        store=store,  # type: ignore[arg-type]
    )

    assert replay["taskId"] == "task-parent"


def test_retry_does_not_reuse_failed_parent_task(monkeypatch) -> None:
    from core.web.services.team_workflow.source_collection import stage_reconcile

    current_node_run_id = "nr-run-retry-source_extraction-a12"
    parent_node_run_id = "nr-run-retry-source_extraction-a11"
    grandparent_node_run_id = "nr-run-retry-source_extraction-a10"
    store = _AttemptStore(
        {
            current_node_run_id: SimpleNamespace(
                node_run_id=current_node_run_id,
                run_id="run-retry",
                node_id="source_extraction",
                retry_of_node_run_id=parent_node_run_id,
            ),
            parent_node_run_id: SimpleNamespace(
                node_run_id=parent_node_run_id,
                run_id="run-retry",
                node_id="source_extraction",
                retry_of_node_run_id=grandparent_node_run_id,
            ),
            grandparent_node_run_id: SimpleNamespace(
                node_run_id=grandparent_node_run_id,
                run_id="run-retry",
                node_id="source_extraction",
                retry_of_node_run_id=None,
            ),
        }
    )

    parent_key = stage_reconcile._source_collection_stage_task_idempotency_key(
        team_id="research-team",
        run_id="dprun-source",
        stage_id="extraction",
        agent_id="agent-extractor",
        agent_role="source_extractor",
        task_id="",
        requested_key=f"agent-task:{parent_node_run_id}",
    )

    grandparent_key = stage_reconcile._source_collection_stage_task_idempotency_key(
        team_id="research-team",
        run_id="dprun-source",
        stage_id="extraction",
        agent_id="agent-extractor",
        agent_role="source_extractor",
        task_id="",
        requested_key=f"agent-task:{grandparent_node_run_id}",
    )
    lookups: list[str] = []

    def find_task(_team_id: str, _run_id: str, *, idempotency_key: str):
        lookups.append(idempotency_key)
        if idempotency_key == parent_key:
            return _stage_task(task_id="task-failed", status="failed")
        if idempotency_key == grandparent_key:
            return _stage_task(task_id="task-stale-grandparent", status="completed")
        return None

    monkeypatch.setattr(
        stage_reconcile,
        "_find_source_collection_stage_session_task",
        find_task,
    )

    assert (
        find_reusable_source_stage_task(
            store=store,
            action=_action(node_run_id=current_node_run_id, attempt=12),
            team_id="research-team",
            source_run_id="dprun-source",
            stage_id="extraction",
            agent_id="agent-extractor",
            agent_role="source_extractor",
        )
        is None
    )
    assert grandparent_key not in lookups


def test_retry_fails_closed_when_exact_task_identity_does_not_match(monkeypatch) -> None:
    from core.web.services.team_workflow.source_collection import stage_reconcile

    mismatched = {
        **_stage_task(task_id="task-wrong-agent", status="completed"),
        "agentId": "agent-other",
    }
    monkeypatch.setattr(
        stage_reconcile,
        "_find_source_collection_stage_session_task",
        lambda *_args, **_kwargs: mismatched,
    )

    with pytest.raises(RuntimeError, match="stage task identity mismatch"):
        find_reusable_source_stage_task(
            store=None,
            action=_action(node_run_id="nr-run-retry-source_extraction-a11", attempt=11),
            team_id="research-team",
            source_run_id="dprun-source",
            stage_id="extraction",
            agent_id="agent-extractor",
            agent_role="source_extractor",
        )
