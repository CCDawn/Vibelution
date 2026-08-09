from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from core.web.services.external_agent.service import (
    ExternalAgentAccessError,
    ExternalAgentConflictError,
    ExternalAgentTaskService,
    ExternalAgentTaskServiceDependencies,
)
from core.web.services.external_agent.store import ExternalAgentTaskStore


def _agent(agent_id: str = "coder", **extra: Any) -> dict[str, Any]:
    value = {
        "agentId": agent_id,
        "agentCode": agent_id,
        "displayName": "Coder",
        "status": "active",
        "conversationIndexKind": "personal_agent",
        "externalMaximumPermissionProfile": "workspace_write",
    }
    value.update(extra)
    return value


@dataclass
class FakeRuntime:
    agents: list[dict[str, Any]] = field(default_factory=lambda: [_agent()])
    details: dict[str, dict[str, Any]] = field(default_factory=dict)
    approvals: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    create_calls: list[dict[str, Any]] = field(default_factory=list)
    submit_calls: list[dict[str, Any]] = field(default_factory=list)
    resolve_calls: list[tuple[str, str, str]] = field(default_factory=list)
    stop_calls: list[tuple[str, str]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    active_teams: dict[str, dict[str, Any]] = field(default_factory=dict)

    def list_agents(self, **_kwargs: Any) -> list[dict[str, Any]]:
        return list(self.agents)

    def get_agent(self, agent_id: str, **_kwargs: Any) -> dict[str, Any] | None:
        return next((item for item in self.agents if item["agentId"] == agent_id), None)

    def active_team(self, agent_id: str) -> dict[str, Any] | None:
        return self.active_teams.get(agent_id)

    def create_session(self, **kwargs: Any) -> dict[str, Any]:
        self.create_calls.append(kwargs)
        session_id = f"session-{len(self.create_calls)}"
        self.details[session_id] = {
            "sessionId": session_id,
            "phase": "running",
            "messages": [],
        }
        return {"sessionId": session_id}

    def submit_message(
        self, session_id: str, content: str, **kwargs: Any
    ) -> dict[str, Any]:
        self.submit_calls.append(
            {"sessionId": session_id, "content": content, **kwargs}
        )
        return {"turnId": f"turn-{len(self.submit_calls)}"}

    def get_detail(self, session_id: str, **_kwargs: Any) -> dict[str, Any] | None:
        return self.details.get(session_id)

    def list_approvals(self, session_id: str, **_kwargs: Any) -> list[dict[str, Any]]:
        return list(self.approvals.get(session_id, []))

    def resolve_approval(
        self, session_id: str, approval_id: str, *, decision: str
    ) -> dict[str, Any]:
        self.resolve_calls.append((session_id, approval_id, decision))
        for approval in self.approvals.get(session_id, []):
            if approval["requestId"] == approval_id:
                approval["status"] = (
                    "accepted" if decision.startswith("accept") else "declined"
                )
                approval["decision"] = decision
                return dict(approval)
        raise ValueError("missing approval")

    def stop_turn(
        self, session_id: str, *, expected_turn_id: str = ""
    ) -> dict[str, Any]:
        self.stop_calls.append((session_id, expected_turn_id))
        return dict(self.details[session_id])

    def record_event(self, *args: Any, **kwargs: Any) -> None:
        self.events.append({"args": args, "kwargs": kwargs})


def _service(tmp_path, runtime: FakeRuntime) -> ExternalAgentTaskService:
    dependencies = ExternalAgentTaskServiceDependencies(
        list_agents=runtime.list_agents,
        get_agent=runtime.get_agent,
        active_team_lookup=runtime.active_team,
        create_session=runtime.create_session,
        submit_message=runtime.submit_message,
        get_session_detail=runtime.get_detail,
        list_approvals=runtime.list_approvals,
        resolve_approval=runtime.resolve_approval,
        stop_turn=runtime.stop_turn,
        record_event=runtime.record_event,
    )
    return ExternalAgentTaskService(
        ExternalAgentTaskStore(tmp_path),
        dependencies=dependencies,
        operator_permission_ceiling="workspace_write",
        runtime_permission_ceiling="workspace_write",
        lease_seconds=30,
        approval_persist_enabled=True,
    )


def test_start_is_hidden_async_and_does_not_persist_prompt(tmp_path) -> None:
    runtime = FakeRuntime()
    service = _service(tmp_path, runtime)

    result = service.start_task(
        owner_id="host-a",
        adapter_connection_id="connection-a",
        capabilities=set(),
        agent_id="coder",
        task="secret prompt body",
        permission_profile="full_access",
        client_request_id="request-1",
        title="review",
        runtime_revision="rev-1",
    )

    assert result["status"] == "running"
    assert result["effectivePermissionProfile"] == "workspace_write"
    assert result["pollAfterMs"] > 0
    assert runtime.create_calls[0]["activate"] is False
    assert runtime.create_calls[0]["conversation_index_kind"] == "hidden"
    assert (
        runtime.create_calls[0]["session_metadata"]["source"] == "external_agent_task"
    )
    assert runtime.submit_calls[0]["message_metadata"]["allowInternalAutoContinue"] is True
    assert runtime.submit_calls[0]["content"] == "secret prompt body"
    assert "secret prompt body" not in service.store.task_path(
        result["taskId"]
    ).read_text(encoding="utf-8")


def test_missing_agent_permission_ceiling_matches_public_workspace_write_default(
    tmp_path,
) -> None:
    agent = _agent()
    agent.pop("externalMaximumPermissionProfile")
    runtime = FakeRuntime(agents=[agent])
    service = _service(tmp_path, runtime)

    result = service.start_task(
        owner_id="host-a",
        adapter_connection_id="connection-a",
        capabilities=set(),
        agent_id="coder",
        task="run a bounded quality check",
        permission_profile="workspace_write",
        client_request_id="request-default-agent-ceiling",
        title="",
        runtime_revision="rev-1",
    )

    assert result["effectivePermissionProfile"] == "workspace_write"


def test_concurrent_idempotent_start_does_not_create_a_second_session(tmp_path) -> None:
    runtime = FakeRuntime()
    nested_result: dict[str, Any] = {}
    nested_started = False
    original_create = runtime.create_session
    service: ExternalAgentTaskService

    def reentrant_create(**kwargs: Any) -> dict[str, Any]:
        nonlocal nested_started
        if not nested_started:
            nested_started = True
            nested_result.update(
                service.start_task(
                    owner_id="host-a",
                    adapter_connection_id="connection-a",
                    capabilities=set(),
                    agent_id="coder",
                    task="do work",
                    permission_profile="read_only",
                    client_request_id="request-reentrant",
                    title="",
                    runtime_revision="rev-1",
                )
            )
        return original_create(**kwargs)

    runtime.create_session = reentrant_create  # type: ignore[method-assign]
    service = _service(tmp_path, runtime)

    result = service.start_task(
        owner_id="host-a",
        adapter_connection_id="connection-a",
        capabilities=set(),
        agent_id="coder",
        task="do work",
        permission_profile="read_only",
        client_request_id="request-reentrant",
        title="",
        runtime_revision="rev-1",
    )

    assert nested_result["taskId"] == result["taskId"]
    assert nested_result["status"] == "queued"
    assert result["status"] == "running"
    assert len(runtime.create_calls) == 1
    assert len(runtime.submit_calls) == 1


def test_start_failure_projection_does_not_persist_internal_exception_text(
    tmp_path,
) -> None:
    runtime = FakeRuntime()

    def fail_submit(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("secret prompt body C:\\private\\runtime.txt")

    runtime.submit_message = fail_submit  # type: ignore[method-assign]
    service = _service(tmp_path, runtime)

    with pytest.raises(RuntimeError, match="secret prompt body"):
        service.start_task(
            owner_id="host-a",
            adapter_connection_id="connection-a",
            capabilities=set(),
            agent_id="coder",
            task="do work",
            permission_profile="read_only",
            client_request_id="request-failed",
            title="",
            runtime_revision="rev-1",
        )

    record_path = next((tmp_path / "tasks").glob("eat-*.json"))
    persisted = record_path.read_text(encoding="utf-8")
    assert "secret prompt body" not in persisted
    assert "C:\\\\private" not in persisted
    assert "RuntimeError" not in persisted


def test_start_rechecks_team_membership_and_creates_nothing(tmp_path) -> None:
    runtime = FakeRuntime(active_teams={"coder": {"teamId": "team-1"}})
    service = _service(tmp_path, runtime)

    with pytest.raises(ExternalAgentAccessError, match="not available"):
        service.start_task(
            owner_id="host-a",
            adapter_connection_id="connection-a",
            capabilities=set(),
            agent_id="coder",
            task="do work",
            permission_profile="read_only",
            client_request_id="",
            title="",
            runtime_revision="rev-1",
        )

    assert runtime.create_calls == []
    assert list(tmp_path.rglob("*.json")) == []


def test_get_sanitizes_approvals_and_enforces_owner(tmp_path) -> None:
    runtime = FakeRuntime()
    service = _service(tmp_path, runtime)
    started = service.start_task(
        owner_id="host-a",
        adapter_connection_id="connection-a",
        capabilities=set(),
        agent_id="coder",
        task="do work",
        permission_profile="read_only",
        client_request_id="",
        title="",
        runtime_revision="rev-1",
    )
    session_id = service.store.get_task(started["taskId"])["sessionId"]
    runtime.approvals[session_id] = [
        {
            "requestId": "approval-1",
            "turnId": "turn-1",
            "toolName": "write_file_tool",
            "risk": "write",
            "argumentSummary": {"paths": ["README.md"]},
            "arguments": {"secret": "never expose"},
            "configRevision": 7,
            "decisionFingerprint": "fp-1",
            "status": "pending",
        }
    ]

    result = service.get_task(owner_id="host-a", task_id=started["taskId"])

    assert result["status"] == "awaiting_approval"
    assert result["pendingApprovals"] == [
        {
            "approvalId": "approval-1",
            "toolName": "write_file_tool",
            "risk": "write",
            "targetSummary": {"paths": ["README.md"]},
            "configRevision": 7,
            "revision": "fp-1",
            "availableDecisions": [
                "accept",
                "acceptForSession",
                "acceptAlways",
                "decline",
                "cancel",
            ],
        }
    ]
    assert "sessionId" not in result
    with pytest.raises(ExternalAgentAccessError, match="not found"):
        service.get_task(owner_id="host-b", task_id=started["taskId"])


@pytest.mark.parametrize("resumable_status", ["needs_continue", "paused_limit"])
def test_get_continues_resumable_session_phase_before_succeeding(
    tmp_path, resumable_status: str
) -> None:
    runtime = FakeRuntime()
    service = _service(tmp_path, runtime)
    started = service.start_task(
        owner_id="host-a",
        adapter_connection_id="connection-a",
        capabilities=set(),
        agent_id="coder",
        task="finish the managed task",
        permission_profile="read_only",
        client_request_id="",
        title="",
        runtime_revision="rev-1",
    )
    task = service.store.get_task(started["taskId"])
    runtime.details[task["sessionId"]] = {
        "sessionId": task["sessionId"],
        "status": resumable_status,
        "messages": [
            {"role": "assistant", "content": "已取得进展，但还需要继续。"}
        ],
    }

    continued = service.get_task(owner_id="host-a", task_id=task["taskId"])

    assert continued["status"] == "running"
    assert len(runtime.submit_calls) == 2
    assert runtime.submit_calls[1]["content"] == (
        "继续完成当前外部 Agent 任务；复用已有上下文，完成剩余工作并给出最终结果。"
    )
    assert runtime.submit_calls[1]["message_source"] == "external_agent_task"
    assert runtime.submit_calls[1]["message_metadata"] == {
        "source": "external_agent_task",
        "taskId": task["taskId"],
        "effectivePermissionProfile": "read_only",
        "allowInternalAutoContinue": True,
        "runtimeRevision": "rev-1",
        "continuationIndex": 1,
    }
    continued_record = service.store.get_task(task["taskId"])
    assert continued_record["turnId"] == "turn-2"
    assert continued_record["continuationCount"] == 1

    runtime.details[task["sessionId"]] = {
        "sessionId": task["sessionId"],
        "status": "ready",
        "messages": [{"role": "assistant", "content": "任务完成。"}],
    }
    completed = service.get_task(owner_id="host-a", task_id=task["taskId"])

    assert completed["status"] == "succeeded"
    assert completed["resultSummary"] == "任务完成。"


def test_resumable_session_phase_fails_after_bounded_continuations(tmp_path) -> None:
    runtime = FakeRuntime()
    service = _service(tmp_path, runtime)
    started = service.start_task(
        owner_id="host-a",
        adapter_connection_id="connection-a",
        capabilities=set(),
        agent_id="coder",
        task="finish the managed task",
        permission_profile="read_only",
        client_request_id="",
        title="",
        runtime_revision="rev-1",
    )
    task = service.store.get_task(started["taskId"])
    runtime.details[task["sessionId"]] = {
        "sessionId": task["sessionId"],
        "status": "needs_continue",
        "messages": [{"role": "assistant", "content": "仍需继续。"}],
    }

    for _ in range(3):
        result = service.get_task(owner_id="host-a", task_id=task["taskId"])
        assert result["status"] == "running"

    failed = service.get_task(owner_id="host-a", task_id=task["taskId"])

    assert failed["status"] == "failed"
    assert failed["error"] == {
        "code": "TURN_CONTINUATION_LIMIT",
        "message": "Agent task reached the managed continuation limit.",
    }
    assert failed["resultSummary"] == "仍需继续。"
    assert len(runtime.submit_calls) == 4


def test_succeeded_task_uses_canonical_final_answer_as_result_summary(
    tmp_path,
) -> None:
    runtime = FakeRuntime()
    service = _service(tmp_path, runtime)
    started = service.start_task(
        owner_id="host-a",
        adapter_connection_id="connection-a",
        capabilities=set(),
        agent_id="coder",
        task="echo a bounded result",
        permission_profile="read_only",
        client_request_id="",
        title="",
        runtime_revision="rev-1",
    )
    task = service.store.get_task(started["taskId"])
    runtime.details[task["sessionId"]] = {
        "sessionId": task["sessionId"],
        "status": "ready",
        "messages": [
            {
                "role": "assistant",
                "status": "completed",
                "turnItems": [
                    {
                        "type": "reasoning",
                        "status": "completed",
                        "text": "internal reasoning must not be projected",
                    },
                    {
                        "type": "agent_message",
                        "phase": "final_answer",
                        "status": "completed",
                        "terminal": True,
                        "text": "MCP echo result.",
                    },
                ],
            }
        ],
    }

    completed = service.get_task(owner_id="host-a", task_id=task["taskId"])

    assert completed["status"] == "succeeded"
    assert completed["resultSummary"] == "MCP echo result."


def test_approval_is_explicit_idempotent_and_accept_always_is_capability_gated(
    tmp_path,
) -> None:
    runtime = FakeRuntime()
    service = _service(tmp_path, runtime)
    started = service.start_task(
        owner_id="host-a",
        adapter_connection_id="connection-a",
        capabilities=set(),
        agent_id="coder",
        task="do work",
        permission_profile="read_only",
        client_request_id="",
        title="",
        runtime_revision="rev-1",
    )
    session_id = service.store.get_task(started["taskId"])["sessionId"]
    runtime.approvals[session_id] = [
        {
            "requestId": "approval-1",
            "turnId": "turn-1",
            "toolName": "write_file_tool",
            "risk": "write",
            "argumentSummary": {"paths": ["README.md"]},
            "configRevision": 7,
            "decisionFingerprint": "fp-1",
            "status": "pending",
        }
    ]

    with pytest.raises(ExternalAgentAccessError, match="approval.persist"):
        service.resolve_approval(
            owner_id="host-a",
            capabilities=set(),
            task_id=started["taskId"],
            approval_id="approval-1",
            decision="acceptAlways",
            expected_revision="fp-1",
            reason="",
        )
    first = service.resolve_approval(
        owner_id="host-a",
        capabilities=set(),
        task_id=started["taskId"],
        approval_id="approval-1",
        decision="accept",
        expected_revision="fp-1",
        reason="reviewed",
    )
    replay = service.resolve_approval(
        owner_id="host-a",
        capabilities=set(),
        task_id=started["taskId"],
        approval_id="approval-1",
        decision="accept",
        expected_revision="fp-1",
        reason="reviewed",
    )

    assert first["decision"] == replay["decision"] == "accept"
    assert runtime.resolve_calls == [(session_id, "approval-1", "accept")]


def test_cancel_waits_for_real_stop_confirmation_and_is_idempotent(tmp_path) -> None:
    runtime = FakeRuntime()
    service = _service(tmp_path, runtime)
    started = service.start_task(
        owner_id="host-a",
        adapter_connection_id="connection-a",
        capabilities=set(),
        agent_id="coder",
        task="do work",
        permission_profile="read_only",
        client_request_id="",
        title="",
        runtime_revision="rev-1",
    )
    task = service.store.get_task(started["taskId"])

    first = service.cancel_task(owner_id="host-a", task_id=started["taskId"])
    assert first["status"] == "stop_unconfirmed"
    runtime.details[task["sessionId"]]["phase"] = "stopped"
    confirmed = service.get_task(owner_id="host-a", task_id=started["taskId"])
    replay = service.cancel_task(owner_id="host-a", task_id=started["taskId"])

    assert confirmed["status"] == replay["status"] == "cancelled"
    assert runtime.stop_calls == [(task["sessionId"], "turn-1")]


def test_expired_lease_uses_cancel_path_and_only_times_out_after_stop(tmp_path) -> None:
    runtime = FakeRuntime()
    service = _service(tmp_path, runtime)
    started = service.start_task(
        owner_id="host-a",
        adapter_connection_id="connection-a",
        capabilities=set(),
        agent_id="coder",
        task="do work",
        permission_profile="read_only",
        client_request_id="",
        title="",
        runtime_revision="rev-1",
    )
    task = service.store.get_task(started["taskId"])
    service.store.transition(
        task["taskId"],
        status="running",
        fields={"leaseExpiresAt": "2000-01-01T00:00:00Z"},
    )

    service.reconcile(now_iso="2026-08-09T00:00:00Z")
    assert (
        service.get_task(owner_id="host-a", task_id=task["taskId"])["status"]
        == "stop_unconfirmed"
    )
    runtime.details[task["sessionId"]]["phase"] = "stopped"
    service.reconcile(now_iso="2026-08-09T00:00:01Z")

    assert (
        service.get_task(owner_id="host-a", task_id=task["taskId"])["status"]
        == "timed_out"
    )


def test_running_task_is_stopped_when_agent_joins_active_team(tmp_path) -> None:
    runtime = FakeRuntime()
    service = _service(tmp_path, runtime)
    started = service.start_task(
        owner_id="host-a",
        adapter_connection_id="connection-a",
        capabilities=set(),
        agent_id="coder",
        task="do work",
        permission_profile="read_only",
        client_request_id="",
        title="",
        runtime_revision="rev-1",
    )
    task = service.store.get_task(started["taskId"])
    runtime.active_teams["coder"] = {"teamId": "team-1", "status": "active"}

    result = service.get_task(owner_id="host-a", task_id=task["taskId"])

    assert result["status"] == "stop_unconfirmed"
    assert runtime.stop_calls == [(task["sessionId"], "turn-1")]


def test_agent_concurrency_limit_rejects_second_task_without_session(tmp_path) -> None:
    runtime = FakeRuntime()
    service = _service(tmp_path, runtime)
    service.start_task(
        owner_id="host-a",
        adapter_connection_id="connection-a",
        capabilities=set(),
        agent_id="coder",
        task="first",
        permission_profile="read_only",
        client_request_id="request-1",
        title="",
        runtime_revision="rev-1",
    )

    with pytest.raises(ExternalAgentConflictError, match="concurrency limit"):
        service.start_task(
            owner_id="host-b",
            adapter_connection_id="connection-b",
            capabilities=set(),
            agent_id="coder",
            task="second",
            permission_profile="read_only",
            client_request_id="request-2",
            title="",
            runtime_revision="rev-1",
        )

    assert len(runtime.create_calls) == 1


def test_accept_always_requires_agent_policy_and_current_config_revision(
    tmp_path,
) -> None:
    runtime = FakeRuntime(agents=[_agent(configRevision=8)])
    service = _service(tmp_path, runtime)
    started = service.start_task(
        owner_id="host-a",
        adapter_connection_id="connection-a",
        capabilities=set(),
        agent_id="coder",
        task="do work",
        permission_profile="read_only",
        client_request_id="",
        title="",
        runtime_revision="rev-1",
    )
    session_id = service.store.get_task(started["taskId"])["sessionId"]
    runtime.approvals[session_id] = [
        {
            "requestId": "approval-1",
            "turnId": "turn-1",
            "toolName": "write_file_tool",
            "risk": "write",
            "argumentSummary": {},
            "configRevision": 7,
            "decisionFingerprint": "fp-1",
            "status": "pending",
        }
    ]

    with pytest.raises(ExternalAgentAccessError, match="Agent policy"):
        service.resolve_approval(
            owner_id="host-a",
            capabilities={"approval.persist"},
            task_id=started["taskId"],
            approval_id="approval-1",
            decision="acceptAlways",
            expected_revision="fp-1",
            reason="",
        )
    runtime.agents[0]["externalApprovalPersistAllowed"] = True
    with pytest.raises(ExternalAgentConflictError, match="config revision"):
        service.resolve_approval(
            owner_id="host-a",
            capabilities={"approval.persist"},
            task_id=started["taskId"],
            approval_id="approval-1",
            decision="acceptAlways",
            expected_revision="fp-1",
            reason="",
        )


def test_task_deadline_uses_stop_path_before_timed_out_terminal_state(tmp_path) -> None:
    runtime = FakeRuntime()
    service = _service(tmp_path, runtime)
    started = service.start_task(
        owner_id="host-a",
        adapter_connection_id="connection-a",
        capabilities=set(),
        agent_id="coder",
        task="do work",
        permission_profile="read_only",
        client_request_id="",
        title="",
        runtime_revision="rev-1",
    )
    task = service.store.get_task(started["taskId"])
    service.store.transition(
        task["taskId"],
        status="running",
        fields={"deadlineAt": "2000-01-01T00:00:00Z"},
    )

    service.reconcile(now_iso="2026-08-09T00:00:00Z")
    assert (
        service.get_task(owner_id="host-a", task_id=task["taskId"])["status"]
        == "stop_unconfirmed"
    )
    assert runtime.stop_calls == [(task["sessionId"], "turn-1")]

    runtime.details[task["sessionId"]]["phase"] = "stopped"
    service.reconcile(now_iso="2026-08-09T00:00:01Z")
    assert (
        service.get_task(owner_id="host-a", task_id=task["taskId"])["status"]
        == "timed_out"
    )


@pytest.mark.parametrize("decision", ["accept", "acceptForSession", "decline"])
def test_nonpersistent_approval_decisions_use_existing_approval_service(
    tmp_path, decision: str
) -> None:
    runtime = FakeRuntime()
    service = _service(tmp_path, runtime)
    started = service.start_task(
        owner_id="host-a",
        adapter_connection_id="connection-a",
        capabilities=set(),
        agent_id="coder",
        task="do work",
        permission_profile="read_only",
        client_request_id="",
        title="",
        runtime_revision="rev-1",
    )
    session_id = service.store.get_task(started["taskId"])["sessionId"]
    runtime.approvals[session_id] = [
        {
            "requestId": "approval-1",
            "turnId": "turn-1",
            "toolName": "write_file_tool",
            "risk": "write",
            "argumentSummary": {},
            "configRevision": 7,
            "decisionFingerprint": "fp-1",
            "status": "pending",
        }
    ]

    result = service.resolve_approval(
        owner_id="host-a",
        capabilities=set(),
        task_id=started["taskId"],
        approval_id="approval-1",
        decision=decision,
        expected_revision="fp-1",
        reason="",
    )

    assert result["decision"] == decision
    assert runtime.resolve_calls == [(session_id, "approval-1", decision)]


def test_accept_always_succeeds_only_with_all_three_authorities(tmp_path) -> None:
    runtime = FakeRuntime(
        agents=[
            _agent(
                configRevision=7,
                externalApprovalPersistAllowed=True,
            )
        ]
    )
    service = _service(tmp_path, runtime)
    started = service.start_task(
        owner_id="host-a",
        adapter_connection_id="connection-a",
        capabilities=set(),
        agent_id="coder",
        task="do work",
        permission_profile="read_only",
        client_request_id="",
        title="",
        runtime_revision="rev-1",
    )
    session_id = service.store.get_task(started["taskId"])["sessionId"]
    runtime.approvals[session_id] = [
        {
            "requestId": "approval-1",
            "turnId": "turn-1",
            "toolName": "write_file_tool",
            "risk": "write",
            "argumentSummary": {},
            "configRevision": 7,
            "decisionFingerprint": "fp-1",
            "status": "pending",
        }
    ]

    result = service.resolve_approval(
        owner_id="host-a",
        capabilities={"approval.persist"},
        task_id=started["taskId"],
        approval_id="approval-1",
        decision="acceptAlways",
        expected_revision="fp-1",
        reason="",
    )

    assert result["decision"] == "acceptAlways"
    assert runtime.resolve_calls == [(session_id, "approval-1", "acceptAlways")]


def test_cancel_approval_enters_real_turn_stop_path(tmp_path) -> None:
    runtime = FakeRuntime()
    service = _service(tmp_path, runtime)
    started = service.start_task(
        owner_id="host-a",
        adapter_connection_id="connection-a",
        capabilities=set(),
        agent_id="coder",
        task="do work",
        permission_profile="read_only",
        client_request_id="",
        title="",
        runtime_revision="rev-1",
    )
    task = service.store.get_task(started["taskId"])
    runtime.approvals[task["sessionId"]] = [
        {
            "requestId": "approval-1",
            "turnId": "turn-1",
            "toolName": "write_file_tool",
            "risk": "write",
            "argumentSummary": {},
            "configRevision": 7,
            "decisionFingerprint": "fp-1",
            "status": "pending",
        }
    ]

    result = service.resolve_approval(
        owner_id="host-a",
        capabilities=set(),
        task_id=started["taskId"],
        approval_id="approval-1",
        decision="cancel",
        expected_revision="fp-1",
        reason="",
    )

    assert result["taskStatus"] == "stop_unconfirmed"
    assert runtime.stop_calls == [(task["sessionId"], "turn-1")]


def test_other_owner_cannot_resolve_task_approval(tmp_path) -> None:
    runtime = FakeRuntime()
    service = _service(tmp_path, runtime)
    started = service.start_task(
        owner_id="host-a",
        adapter_connection_id="connection-a",
        capabilities=set(),
        agent_id="coder",
        task="do work",
        permission_profile="read_only",
        client_request_id="",
        title="",
        runtime_revision="rev-1",
    )

    with pytest.raises(ExternalAgentAccessError, match="not found"):
        service.resolve_approval(
            owner_id="host-b",
            capabilities=set(),
            task_id=started["taskId"],
            approval_id="approval-1",
            decision="accept",
            expected_revision="",
            reason="",
        )


def test_runtime_scene_events_never_include_prompt_approval_reason_or_arguments(
    tmp_path,
) -> None:
    runtime = FakeRuntime()
    service = _service(tmp_path, runtime)
    started = service.start_task(
        owner_id="host-a",
        adapter_connection_id="connection-a",
        capabilities=set(),
        agent_id="coder",
        task="secret prompt body",
        permission_profile="read_only",
        client_request_id="",
        title="",
        runtime_revision="rev-1",
    )
    session_id = service.store.get_task(started["taskId"])["sessionId"]
    runtime.approvals[session_id] = [
        {
            "requestId": "approval-1",
            "turnId": "turn-1",
            "toolName": "write_file_tool",
            "risk": "write",
            "argumentSummary": {"secret": "approval arguments"},
            "configRevision": 7,
            "decisionFingerprint": "fp-1",
            "status": "pending",
        }
    ]
    service.resolve_approval(
        owner_id="host-a",
        capabilities=set(),
        task_id=started["taskId"],
        approval_id="approval-1",
        decision="decline",
        expected_revision="fp-1",
        reason="private approval reason",
    )

    serialized = repr(runtime.events)
    assert "secret prompt body" not in serialized
    assert "approval arguments" not in serialized
    assert "private approval reason" not in serialized
