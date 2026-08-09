from __future__ import annotations

import json

import pytest

from core.web.services.external_agent.store import (
    ExternalAgentTaskConflictError,
    ExternalAgentTaskStore,
)


def test_task_store_is_atomic_idempotent_and_does_not_persist_prompt(tmp_path) -> None:
    store = ExternalAgentTaskStore(tmp_path)
    task, created = store.create_task(
        owner_id="host-a",
        agent_id="coder",
        task_digest="sha256:abc",
        client_request_id="request-1",
        request_digest="sha256:req",
        permission_profile="read_only",
        lease_seconds=30,
        adapter_connection_id="connection-a",
        runtime_revision="rev-1",
    )
    replay, replay_created = store.create_task(
        owner_id="host-a",
        agent_id="coder",
        task_digest="sha256:abc",
        client_request_id="request-1",
        request_digest="sha256:req",
        permission_profile="read_only",
        lease_seconds=30,
        adapter_connection_id="connection-b",
        runtime_revision="rev-1",
    )

    assert created is True
    assert replay_created is False
    assert replay["taskId"] == task["taskId"]
    persisted = json.loads(store.task_path(task["taskId"]).read_text(encoding="utf-8"))
    assert "prompt" not in persisted
    assert "task" not in persisted
    assert "sha256:abc" in persisted.values()
    assert not list(tmp_path.rglob("*.tmp"))


def test_idempotency_key_cannot_be_reused_for_another_request(tmp_path) -> None:
    store = ExternalAgentTaskStore(tmp_path)
    store.create_task(
        owner_id="host-a",
        agent_id="coder",
        task_digest="sha256:abc",
        client_request_id="request-1",
        request_digest="sha256:req-a",
        permission_profile="read_only",
        lease_seconds=30,
        adapter_connection_id="connection-a",
        runtime_revision="rev-1",
    )

    with pytest.raises(ExternalAgentTaskConflictError, match="idempotency"):
        store.create_task(
            owner_id="host-a",
            agent_id="coder",
            task_digest="sha256:def",
            client_request_id="request-1",
            request_digest="sha256:req-b",
            permission_profile="read_only",
            lease_seconds=30,
            adapter_connection_id="connection-a",
            runtime_revision="rev-1",
        )


def test_task_store_rejects_stale_revision_and_keeps_terminal_state(tmp_path) -> None:
    store = ExternalAgentTaskStore(tmp_path)
    task, _ = store.create_task(
        owner_id="host-a",
        agent_id="coder",
        task_digest="sha256:abc",
        client_request_id="",
        request_digest="sha256:req",
        permission_profile="read_only",
        lease_seconds=30,
        adapter_connection_id="connection-a",
        runtime_revision="rev-1",
    )
    running = store.transition(
        task["taskId"],
        status="running",
        expected_revision=task["revision"],
        fields={"sessionId": "session-1", "turnId": "turn-1"},
    )
    terminal = store.transition(
        task["taskId"],
        status="succeeded",
        expected_revision=running["revision"],
        fields={"resultSummary": "done"},
    )

    with pytest.raises(ExternalAgentTaskConflictError, match="revision"):
        store.transition(
            task["taskId"],
            status="failed",
            expected_revision=running["revision"],
        )
    assert store.get_task(task["taskId"])["status"] == terminal["status"] == "succeeded"
