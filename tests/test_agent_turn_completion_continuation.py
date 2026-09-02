"""Bounded agent-turn continuation must respect the stage-task authority.

Incident run-2aac4095762c: a source_finding main turn finished all work (10
sources materialized, completion gate passed, writeback done) but parked as
``needs_continue``; the adapter auto-submitted a "继续" continuation turn whose
LLM call failed with ``payload_protocol_error: duplicate tool call id``
(fail_fast -- deterministic poisoned payload).  The failed continuation then
overwrote the session-level ``last_turn_status`` and the node attempt was
judged ``agent_turn_terminal_failed``, erasing verified work.

Contract under test:

- A parked turn whose stage task already settled ``completed`` (only reachable
  when the completion gate passed) must not trigger a continuation.
- A continuation turn's terminal failure must not poison the attempt when the
  stage task authority confirms the main turn's work: the verdict follows the
  main turn and the failure is exposed as a structured warning.
- Without that authority confirmation the failure still raises (fail-closed).
- A main turn that itself fails terminally after its stage task settled
  ``completed`` (production run-16cfab646d08: writeback passed the gate, then
  a later LLM call died with ``budget_exhausted``) must not deadlock retries:
  the attempt returns the failed turn's snapshot with a structured warning.
- A main turn that itself fails terminally without that settled authority
  (task still ``needs_review``) still fails the attempt (fail-closed).
- ``research_project`` tasks keep their authority-owned, never-continued
  semantics.
"""

from __future__ import annotations

import json

import pytest

from core.research.workflow.contracts import PendingAction
from core.research.workflow.models import ActorKind
from core.web.services.team_workflow.research_runtime.agent_turn_completion import (
    _wait_with_bounded_turn_continuation,
)
from core.web.services.team_workflow.research_runtime.domain_ports import (
    AgentTaskHandle,
)
from core.web.services.team_workflow.research_runtime.task_adapter_registry import (
    AgentTaskAdapterSpec,
)


def _action(node_id: str = "source_finding") -> PendingAction:
    return PendingAction(
        action_id="act-1",
        run_id="run-test",
        node_run_id=f"nr-run-test-{node_id}-a1",
        node_id=node_id,
        attempt=1,
        actor_kind=ActorKind.AGENT,
        action_kind="start_agent_task",
        input_snapshot_hash="a" * 64,
        input_artifact_refs=(),
        binding_snapshot_id=None,
        budget_policy_hash="p-1",
    )


def _handle() -> AgentTaskHandle:
    return AgentTaskHandle(
        session_id="sess-1",
        session_attempt=1,
        task_id="task-1",
        turn_id="turn-main",
    )


def _input_snapshot() -> dict:
    return {"teamId": "team-1", "sourceCollectionRunId": "run-test"}


def _snapshot(status: str, turn_id: str) -> dict:
    return {
        "sessionId": "sess-1",
        "turnId": turn_id,
        "terminal": True,
        "terminalStatus": status,
        "completionSource": "last_turn_status",
        "assistantText": "done" if status not in {"needs_continue"} else "",
    }


def _terminal_failure(
    turn_id: str, status: str, problem_code: str = ""
) -> RuntimeError:
    detail = {
        "code": "agent_turn_terminal_failed",
        "sessionId": "sess-1",
        "turnId": turn_id,
        "terminalStatus": status,
        "completionSource": "last_turn_status",
        "failureClass": "terminal_failure",
    }
    if problem_code:
        detail["terminalProblemCode"] = problem_code
        detail["terminalReason"] = problem_code
    return RuntimeError(json.dumps(detail, ensure_ascii=False))


def _deadline_terminal_failure(turn_id: str = "turn-main") -> RuntimeError:
    return RuntimeError(
        json.dumps(
            {
                "code": "agent_turn_terminal_failed",
                "sessionId": "sess-1",
                "turnId": turn_id,
                "terminalStatus": "cancelled",
                "terminalProblemCode": "challenge_logical_task_deadline_exhausted",
                "terminalReason": "challenge_logical_task_deadline_exhausted",
                "completionSource": "last_turn_status",
                "failureClass": "terminal_failure",
            },
            ensure_ascii=False,
        )
    )


def _wait_waiter(events: list[str], continuations: list[str]):
    """Fake poller: main turn parks needs_continue, each continuation fails."""

    def _wait(session_id, turn_id, *, timeout_ms, poll_ms, reconcilable_terminal_statuses):
        if turn_id == "turn-main":
            return _snapshot("needs_continue", turn_id)
        events.append(f"poll:{turn_id}")
        raise _terminal_failure(turn_id, "failed_provider")

    def _submit(session_id, message, **_kwargs):
        events.append("submit:continue")
        continuations.append(message)
        return {"turnId": f"turn-cont-{len(continuations)}"}

    return _wait, _submit


def test_completion_projects_registered_receipt_without_journal(monkeypatch) -> None:
    import core.web.services.team_workflow.research_runtime.agent_turn_completion as atc
    from core.web.services.team_workflow.research_runtime import (
        model_invocation_receipt_registry as registry,
    )

    receipt = {"receiptId": "receipt-1", "scope": {"turnId": "turn-main"}}
    observed: dict[str, str] = {}

    def read_receipts(team_id: str, **kwargs):
        observed.update({"teamId": team_id, **kwargs})
        return [receipt]

    monkeypatch.setattr(registry, "question_model_invocation_receipts", read_receipts)

    projected = atc._attach_registered_model_invocation_receipts(
        _snapshot("completed", "turn-main"),
        team_id="team-1",
        question_id="SCI-096",
        workflow_run_id="run-test",
        session_id="sess-1",
        turn_id="turn-main",
    )

    assert projected["modelInvocationReceipts"] == [receipt]
    assert projected["modelInvocationReceipt"] == receipt
    assert observed == {
        "teamId": "team-1",
        "question_id": "SCI-096",
        "workflow_run_id": "run-test",
        "session_id": "sess-1",
        "turn_id": "turn-main",
    }


def test_formal_completion_waits_for_durable_receipt_projection() -> None:
    import core.web.services.team_workflow.research_runtime.agent_turn_completion as atc

    snapshot = _snapshot("completed", "turn-main")
    input_snapshot = {
        "questionId": "SCI-096",
        "modelRoutingPolicy": {
            "requiredModelPolicy": {"provider": "relay_autodl"},
            "modelPolicySha256": "a" * 64,
            "routes": {"source_finding": "relay_autodl/GLM-5.3-flash"},
        },
    }

    with pytest.raises(atc.TurnNotReadyError) as raised:
        atc._require_formal_model_invocation_receipt(
            snapshot,
            input_snapshot=input_snapshot,
            task_started_at_ms=123,
        )

    assert raised.value.snapshot["terminal"] is False
    assert raised.value.snapshot["completionSource"] == "receipt_registry_pending"
    assert raised.value.snapshot["turnTerminalStatus"] == "completed"
    assert raised.value.snapshot["challengeTaskStartedAtMs"] == 123


def test_continuation_does_not_submit_after_logical_task_deadline(monkeypatch) -> None:
    import core.web.services.team_workflow.research_runtime.agent_turn_completion as atc
    from core.web.services.team_workflow.research_runtime.challenge_turn_policy import (
        ChallengeTaskDeadlineExceeded,
        challenge_task_deadline_scope,
    )

    events: list[str] = []
    monkeypatch.setattr(atc, "remaining_challenge_task_ms", lambda: 0)
    monkeypatch.setattr(
        atc,
        "_submit_agent_turn_continuation",
        lambda *_args, **_kwargs: events.append("submitted") or "turn-next",
    )

    with (
        challenge_task_deadline_scope(1),
        pytest.raises(ChallengeTaskDeadlineExceeded) as raised,
    ):
        atc._wait_with_bounded_turn_continuation(
            atc.AgentTaskHandle(
                session_id="session-1",
                session_attempt=1,
                task_id="task-1",
                turn_id="turn-main",
            ),
            action=_action(),
            input_snapshot={"teamId": "team-1"},
            adapter_spec=None,
            timeout_ms=1_000,
            poll_ms=1,
        )

    assert raised.value.problem["code"] == "challenge_logical_task_deadline_exhausted"
    assert raised.value.problem["turnChain"] == ["turn-main"]
    assert events == []


def test_deadline_terminal_snapshot_fails_closed_without_continuation(monkeypatch) -> None:
    import core.web.services.team_workflow.research_runtime.agent_turn_completion as atc
    from core.web.services.team_workflow.research_runtime.challenge_turn_policy import (
        ChallengeTaskDeadlineExceeded,
    )

    submitted: list[str] = []

    def wait(*_args, **_kwargs):
        raise _deadline_terminal_failure()

    monkeypatch.setattr(atc, "wait_for_agent_turn_terminal", wait)
    monkeypatch.setattr(
        atc,
        "_submit_agent_turn_continuation",
        lambda *_args, **_kwargs: submitted.append("submitted") or "turn-next",
    )

    with pytest.raises(ChallengeTaskDeadlineExceeded) as raised:
        atc._wait_with_bounded_turn_continuation(
            _handle(),
            action=_action(),
            input_snapshot=_input_snapshot(),
            adapter_spec=AgentTaskAdapterSpec(
                node_id="source_finding",
                family="source_collection",
                task_key="finding",
                role_key="source_finder",
            ),
            timeout_ms=1_000,
            poll_ms=1,
        )

    assert raised.value.problem["code"] == "challenge_logical_task_deadline_exhausted"
    assert raised.value.problem["turnChain"] == ["turn-main"]
    assert submitted == []


def test_deadline_continuation_failure_is_not_rescued_by_settled_task(monkeypatch) -> None:
    import core.web.services.team_workflow.research_runtime.agent_turn_completion as atc
    from core.web.services.team_workflow.research_runtime.challenge_turn_policy import (
        ChallengeTaskDeadlineExceeded,
    )

    submitted: list[str] = []

    def wait(_session_id, turn_id, **_kwargs):
        if turn_id == "turn-main":
            return _snapshot("needs_continue", turn_id)
        raise _deadline_terminal_failure(turn_id)

    monkeypatch.setattr(atc, "wait_for_agent_turn_terminal", wait)
    monkeypatch.setattr(
        atc,
        "_submit_agent_turn_continuation",
        lambda *_args, **_kwargs: submitted.append("submitted") or "turn-cont-1",
    )
    # Even if the domain authority says the main work settled after parking,
    # a deadline problem on the continuation must remain fail-closed.
    authority_reads = iter((False, True))
    monkeypatch.setattr(
        atc,
        "_stage_task_work_already_complete",
        lambda **_kwargs: next(authority_reads, True),
    )

    with pytest.raises(ChallengeTaskDeadlineExceeded) as raised:
        atc._wait_with_bounded_turn_continuation(
            _handle(),
            action=_action(),
            input_snapshot=_input_snapshot(),
            adapter_spec=AgentTaskAdapterSpec(
                node_id="source_finding",
                family="source_collection",
                task_key="finding",
                role_key="source_finder",
            ),
            timeout_ms=1_000,
            poll_ms=1,
        )

    assert raised.value.problem["code"] == "challenge_logical_task_deadline_exhausted"
    assert raised.value.problem["turnChain"] == ["turn-main", "turn-cont-1"]
    assert submitted == ["submitted"]


def test_continuation_wait_requeues_with_persisted_chain(monkeypatch) -> None:
    import core.web.services.team_workflow.research_runtime.agent_turn_completion as atc

    submitted: list[str] = []

    def wait(_session_id, turn_id, **_kwargs):
        if turn_id == "turn-main":
            return _snapshot("needs_continue", turn_id)
        raise atc.TurnNotReadyError(
            "still running",
            snapshot={"terminal": False, "completionSource": "running"},
        )

    monkeypatch.setattr(atc, "wait_for_agent_turn_terminal", wait)
    monkeypatch.setattr(
        atc,
        "_submit_agent_turn_continuation",
        lambda *_args, **_kwargs: submitted.append("turn-cont-1") or "turn-cont-1",
    )
    monkeypatch.setattr(
        atc,
        "_stage_task_work_already_complete",
        lambda **_kwargs: False,
    )

    with pytest.raises(atc.TurnNotReadyError) as raised:
        _wait_with_bounded_turn_continuation(
            _handle(),
            action=_action(),
            input_snapshot=_input_snapshot(),
            adapter_spec=AgentTaskAdapterSpec(
                node_id="source_finding",
                family="source_collection",
                task_key="finding",
                role_key="source_finder",
            ),
            timeout_ms=1_000,
            poll_ms=10,
        )

    assert submitted == ["turn-cont-1"]
    assert raised.value.snapshot["continuationRootTurnId"] == "turn-main"
    assert raised.value.snapshot["continuationTurnId"] == "turn-cont-1"
    assert raised.value.snapshot["continuationTurnChain"] == [
        "turn-main",
        "turn-cont-1",
    ]
    assert raised.value.snapshot["continuationsUsed"] == 1


def test_consecutive_no_progress_count_does_not_reset_after_requeue(monkeypatch) -> None:
    import core.web.services.team_workflow.research_runtime.agent_turn_completion as atc
    from core.web.services.team_workflow.research_runtime.challenge_turn_policy import (
        challenge_task_deadline_scope,
    )

    polled: list[str] = []

    def wait(_session_id, turn_id, **_kwargs):
        polled.append(turn_id)
        return _snapshot("needs_continue", turn_id)

    monkeypatch.setattr(atc, "wait_for_agent_turn_terminal", wait)
    monkeypatch.setattr(
        atc,
        "_submit_agent_turn_continuation",
        lambda *_args, **_kwargs: pytest.fail("exhausted budget must not submit"),
    )
    monkeypatch.setattr(
        atc,
        "_stage_task_work_already_complete",
        lambda **_kwargs: False,
    )
    monkeypatch.setattr(atc, "remaining_challenge_task_ms", lambda: 1_000)
    resume_problem = {
        "code": "live_turn_wait",
        "continuationRootTurnId": "turn-main",
        "continuationTurnId": "turn-cont-3",
        "continuationTurnChain": [
            "turn-main",
            "turn-cont-1",
            "turn-cont-2",
            "turn-cont-3",
        ],
        "continuationsUsed": 3,
        "continuationNoProgressCount": 2,
    }

    with (
        challenge_task_deadline_scope(1, resume_problem=resume_problem),
        pytest.raises(RuntimeError) as raised,
    ):
        _wait_with_bounded_turn_continuation(
            _handle(),
            action=_action(),
            input_snapshot=_input_snapshot(),
            adapter_spec=AgentTaskAdapterSpec(
                node_id="source_finding",
                family="source_collection",
                task_key="finding",
                role_key="source_finder",
            ),
            timeout_ms=1_000,
            poll_ms=10,
        )

    detail = json.loads(str(raised.value))
    assert polled == ["turn-cont-3"]
    assert detail["code"] == "agent_turn_continuation_exhausted"
    assert detail["continuationsUsed"] == 3
    assert detail["consecutiveNoProgressContinuations"] == 3
    assert detail["turnChain"][-1] == "turn-cont-3"


def test_canonical_progress_resets_external_continuation_limit(monkeypatch) -> None:
    import core.web.services.team_workflow.research_runtime.agent_turn_completion as atc

    submitted: list[str] = []

    def wait(_session_id, turn_id, **_kwargs):
        if turn_id == "turn-cont-4":
            return _snapshot("completed", turn_id)
        snapshot = _snapshot("needs_continue", turn_id)
        snapshot["continuationProgressAdvanced"] = turn_id != "turn-main"
        return snapshot

    def submit(*_args, **_kwargs):
        turn_id = f"turn-cont-{len(submitted) + 1}"
        submitted.append(turn_id)
        return turn_id

    monkeypatch.setattr(atc, "wait_for_agent_turn_terminal", wait)
    monkeypatch.setattr(atc, "_submit_agent_turn_continuation", submit)
    monkeypatch.setattr(
        atc,
        "_stage_task_work_already_complete",
        lambda **_kwargs: False,
    )
    monkeypatch.setattr(atc, "remaining_challenge_task_ms", lambda: 1_000)

    snapshot, final_turn_id, continuations = _wait_with_bounded_turn_continuation(
        _handle(),
        action=_action(),
        input_snapshot=_input_snapshot(),
        adapter_spec=AgentTaskAdapterSpec(
            node_id="source_finding",
            family="source_collection",
            task_key="finding",
            role_key="source_finder",
        ),
        timeout_ms=1_000,
        poll_ms=10,
    )

    assert snapshot["terminalStatus"] == "completed"
    assert final_turn_id == "turn-cont-4"
    assert len(continuations) == 4
    assert submitted == [
        "turn-cont-1",
        "turn-cont-2",
        "turn-cont-3",
        "turn-cont-4",
    ]


def test_challenge_deadline_uses_canonical_task_created_at(monkeypatch) -> None:
    import core.web.services.team_workflow.research_runtime.agent_turn_completion as atc
    from core.web.services.team_workflow.research_runtime.task_adapter_registry import (
        AgentTaskAdapterSpec,
    )

    monkeypatch.setattr(
        "core.web.services.team_workflow.source_collection.stage_task_query.get_source_collection_stage_session_task",
        lambda _team_id, _task_id: {
            "task": {
                "taskId": "task-1",
                "createdAt": "2026-08-29T01:00:00Z",
                "turn": {"acceptedAt": "2026-08-29T01:01:00Z"},
            }
        },
    )
    spec = AgentTaskAdapterSpec(
        node_id="source_finding",
        family="source_collection",
        task_key="finding",
        role_key="source_finder",
    )

    started_at_ms = atc._canonical_agent_task_started_at_ms(
        team_id="team-1",
        task_id="task-1",
        project_id="project-1",
        adapter_spec=spec,
    )

    assert started_at_ms == 1_787_965_200_000


def test_late_project_turn_cannot_reconcile_over_timed_out_task(monkeypatch) -> None:
    import core.web.services.team_workflow.research_runtime.agent_turn_completion as atc
    from core.web.services.team_workflow import research_project_agent_tasks as tasks

    timed_out = {
        "taskId": "task-1",
        "status": "timed_out",
        "failureCode": "challenge_logical_task_deadline_exhausted",
    }
    assert tasks._task_needs_session_reconciliation(timed_out) is False
    monkeypatch.setattr(
        tasks,
        "reconcile_research_project_agent_task_statuses",
        lambda *_args, **_kwargs: {"tasks": [timed_out]},
    )
    monkeypatch.setattr(
        tasks,
        "_read_research_project_agent_task_record",
        lambda *_args, **_kwargs: dict(timed_out),
    )

    with pytest.raises(RuntimeError) as raised:
        atc._require_project_task_terminal(
            team_id="team-1",
            project_id="project-1",
            task_id="task-1",
        )

    detail = json.loads(str(raised.value))
    assert detail["code"] == "project_agent_task_terminal_failed"
    assert detail["status"] == "timed_out"
    assert detail["failureCode"] == "challenge_logical_task_deadline_exhausted"


def test_parked_turn_with_settled_stage_task_is_not_continued(monkeypatch):
    """Main turn parked needs_continue, stage task already completed (gate
    passed): no "继续" round-trip; verdict is the parked main snapshot."""
    import core.web.services.session.submit as submit_module
    import core.web.services.team_workflow.research_runtime.agent_turn_completion as atc

    events: list[str] = []
    continuations: list[str] = []
    wait, submit = _wait_waiter(events, continuations)
    monkeypatch.setattr(atc, "wait_for_agent_turn_terminal", wait)
    monkeypatch.setattr(
        atc, "_record_turn_continuation_scene_event", lambda *a, **k: events.append(k.get("event_code") or (a[0] if a else ""))
    )
    monkeypatch.setattr(
        atc,
        "_stage_task_work_already_complete",
        lambda *, team_id, task_id: True,
    )
    monkeypatch.setattr(submit_module, "submit_session_message", submit)

    snapshot, final_turn_id, used = _wait_with_bounded_turn_continuation(
        _handle(),
        action=_action(),
        input_snapshot=_input_snapshot(),
        adapter_spec=AgentTaskAdapterSpec(
            node_id="source_finding",
            family="source_collection",
            task_key="finding",
            role_key="source_finder",
        ),
        timeout_ms=1000,
        poll_ms=10,
    )

    assert final_turn_id == "turn-main"
    assert snapshot["terminalStatus"] == "needs_continue"
    assert used == []
    assert "submit:continue" not in events
    assert "agent_turn.continuation_not_needed_work_complete" in events


def test_continuation_failure_does_not_poison_completed_main_turn(monkeypatch):
    """Main turn parked, continuation submitted, continuation turn failed
    terminally, stage task settled completed: the attempt verdict follows the
    main turn and the failure is surfaced as a structured warning -- not
    raised, not swallowed."""
    import core.web.services.session.submit as submit_module
    import core.web.services.team_workflow.research_runtime.agent_turn_completion as atc

    events: list[str] = []
    continuations: list[str] = []
    wait, submit = _wait_waiter(events, continuations)
    monkeypatch.setattr(atc, "wait_for_agent_turn_terminal", wait)
    recorded: list[tuple] = []

    def _record(event_code, *, outcome, fields, level="info"):
        recorded.append((event_code, level, outcome, fields))
        events.append(event_code)

    monkeypatch.setattr(atc, "_record_turn_continuation_scene_event", _record)
    answers = {"settled": False}

    def _predicate(*, team_id, task_id):
        # False at the submit decision, True once the failure arrives -- the
        # authority confirmed the main turn's work in between.
        return answers["settled"]

    monkeypatch.setattr(atc, "_stage_task_work_already_complete", _predicate)
    monkeypatch.setattr(submit_module, "submit_session_message", submit)

    def _wait_with_late_settlement(session_id, turn_id, **kwargs):
        if turn_id == "turn-main":
            answers["settled"] = False
            return _snapshot("needs_continue", turn_id)
        answers["settled"] = True
        events.append(f"poll:{turn_id}")
        raise _terminal_failure(turn_id, "failed_provider")

    monkeypatch.setattr(atc, "wait_for_agent_turn_terminal", _wait_with_late_settlement)

    snapshot, final_turn_id, used = _wait_with_bounded_turn_continuation(
        _handle(),
        action=_action(),
        input_snapshot=_input_snapshot(),
        adapter_spec=AgentTaskAdapterSpec(
            node_id="source_finding",
            family="source_collection",
            task_key="finding",
            role_key="source_finder",
        ),
        timeout_ms=1000,
        poll_ms=10,
    )

    assert final_turn_id == "turn-main"
    assert snapshot["terminalStatus"] == "needs_continue"
    assert snapshot["turnId"] == "turn-main"
    assert len(used) == 1
    assert used[0]["fromTurnId"] == "turn-main"
    assert used[0]["toTurnId"] == "turn-cont-1"
    assert "submit:continue" in events
    warning = [item for item in recorded if item[0] == "agent_turn.continuation_failed_work_complete"]
    assert len(warning) == 1
    assert warning[0][1] == "warning"
    assert warning[0][3]["failedTurnId"] == "turn-cont-1"
    assert warning[0][3]["failedTurnStatus"] == "failed_provider"
    assert warning[0][3]["mainTurnId"] == "turn-main"


def test_continuation_failure_still_fails_when_work_not_settled(monkeypatch):
    """Stage task authority does not confirm completed work: the continuation
    failure must keep failing the attempt (fail-closed preserved)."""
    import core.web.services.session.submit as submit_module
    import core.web.services.team_workflow.research_runtime.agent_turn_completion as atc

    events: list[str] = []
    continuations: list[str] = []
    wait, submit = _wait_waiter(events, continuations)
    monkeypatch.setattr(atc, "wait_for_agent_turn_terminal", wait)
    monkeypatch.setattr(atc, "_record_turn_continuation_scene_event", lambda *a, **k: None)
    monkeypatch.setattr(
        atc,
        "_stage_task_work_already_complete",
        lambda *, team_id, task_id: False,
    )
    monkeypatch.setattr(submit_module, "submit_session_message", submit)

    with pytest.raises(RuntimeError) as excinfo:
        _wait_with_bounded_turn_continuation(
            _handle(),
            action=_action(),
            input_snapshot=_input_snapshot(),
            adapter_spec=AgentTaskAdapterSpec(
                node_id="source_finding",
                family="source_collection",
                task_key="finding",
                role_key="source_finder",
            ),
            timeout_ms=1000,
            poll_ms=10,
        )

    detail = json.loads(str(excinfo.value))
    assert detail["code"] == "agent_turn_terminal_failed"
    assert detail["terminalStatus"] == "failed_provider"
    assert "submit:continue" in events


def test_main_turn_failure_rescued_when_stage_task_settled(monkeypatch):
    """Production run-16cfab646d08: the main turn's writeback tool settled the
    stage task ``completed`` (completion gate passed), then a later LLM call
    died with ``budget_exhausted`` so the main turn failed terminally.  The
    stage-task idempotency key omits the node-run attempt, so every retry
    re-anchors to the same failed turn -- the settled authority must rescue
    the attempt (failed snapshot returned, structured warning) instead of
    deadlocking retries, and the failure must stay visible (never swallowed,
    never reclassified as success)."""
    import core.web.services.team_workflow.research_runtime.agent_turn_completion as atc

    recorded: list[tuple] = []

    def _record(event_code, *, outcome, fields, level="info"):
        recorded.append((event_code, level, outcome, fields))

    monkeypatch.setattr(atc, "_record_turn_continuation_scene_event", _record)

    def _wait(session_id, turn_id, *, timeout_ms, poll_ms, reconcilable_terminal_statuses):
        raise _terminal_failure(turn_id, "failed", problem_code="budget_exhausted")

    monkeypatch.setattr(atc, "wait_for_agent_turn_terminal", _wait)
    monkeypatch.setattr(
        atc,
        "_stage_task_work_already_complete",
        lambda *, team_id, task_id: True,
    )

    snapshot, final_turn_id, used = _wait_with_bounded_turn_continuation(
        _handle(),
        action=_action(),
        input_snapshot=_input_snapshot(),
        adapter_spec=AgentTaskAdapterSpec(
            node_id="source_finding",
            family="source_collection",
            task_key="finding",
            role_key="source_finder",
        ),
        timeout_ms=1000,
        poll_ms=10,
    )

    assert final_turn_id == "turn-main"
    assert used == []
    assert snapshot["turnId"] == "turn-main"
    assert snapshot["terminal"] is True
    assert snapshot["terminalStatus"] == "failed"
    assert snapshot["terminalProblemCode"] == "budget_exhausted"
    assert snapshot["failureClass"] == "terminal_failure"
    assert snapshot["rescuedByStageTaskAuthority"] is True
    warnings = [
        item
        for item in recorded
        if item[0] == "agent_turn.main_turn_failed_work_complete"
    ]
    assert len(warnings) == 1
    assert warnings[0][1] == "warning"
    assert warnings[0][2] == "resolved_by_stage_task_authority"
    assert warnings[0][3]["mainTurnId"] == "turn-main"
    assert warnings[0][3]["failedTurnId"] == "turn-main"
    assert warnings[0][3]["failedTurnStatus"] == "failed"


def test_main_turn_failure_still_raises_when_work_not_settled(monkeypatch):
    """The main turn itself failed terminally and the stage task is not
    completed (writeback downgrades gate-failed completions to ``needs_review``,
    which the settled predicate treats as not-complete): the failure must
    keep raising -- fail-closed is preserved."""
    import core.web.services.team_workflow.research_runtime.agent_turn_completion as atc

    def _wait(session_id, turn_id, *, timeout_ms, poll_ms, reconcilable_terminal_statuses):
        raise _terminal_failure(turn_id, "failed")

    monkeypatch.setattr(atc, "wait_for_agent_turn_terminal", _wait)
    monkeypatch.setattr(atc, "_record_turn_continuation_scene_event", lambda *a, **k: None)
    monkeypatch.setattr(
        atc,
        "_stage_task_work_already_complete",
        lambda *, team_id, task_id: False,
    )

    with pytest.raises(RuntimeError) as excinfo:
        _wait_with_bounded_turn_continuation(
            _handle(),
            action=_action(),
            input_snapshot=_input_snapshot(),
            adapter_spec=AgentTaskAdapterSpec(
                node_id="source_finding",
                family="source_collection",
                task_key="finding",
                role_key="source_finder",
            ),
            timeout_ms=1000,
            poll_ms=10,
        )

    detail = json.loads(str(excinfo.value))
    assert detail["code"] == "agent_turn_terminal_failed"
    assert detail["turnId"] == "turn-main"
    assert detail["terminalStatus"] == "failed"


def test_settled_predicate_requires_completed_stage_task(monkeypatch):
    """The authority predicate reads canonical task status: only "completed"
    counts (writeback downgrades gate-failed completions to needs_review)."""
    import core.web.services.team_workflow.research_runtime.agent_turn_completion as atc
    from core.web.services.team_workflow.source_collection import stage_task_query

    def _query(status: str | None):
        def _read(team_id, task_id):
            if status is None:
                return None
            return {"runId": "run-test", "task": {"status": status}}

        return _read

    monkeypatch.setattr(
        stage_task_query, "get_source_collection_stage_session_task", _query("completed")
    )
    assert atc._stage_task_work_already_complete(team_id="team-1", task_id="task-1") is True

    monkeypatch.setattr(
        stage_task_query, "get_source_collection_stage_session_task", _query("needs_review")
    )
    assert atc._stage_task_work_already_complete(team_id="team-1", task_id="task-1") is False

    monkeypatch.setattr(
        stage_task_query, "get_source_collection_stage_session_task", _query(None)
    )
    assert atc._stage_task_work_already_complete(team_id="team-1", task_id="task-1") is False

    assert atc._stage_task_work_already_complete(team_id="", task_id="task-1") is False


def test_research_project_parked_turn_is_never_continued(monkeypatch):
    """Project tasks keep their authority-owned verdict: a parked turn returns
    as reconcilable without any continuation or predicate call."""
    import core.web.services.team_workflow.research_runtime.agent_turn_completion as atc

    events: list[str] = []

    def _wait(session_id, turn_id, *, timeout_ms, poll_ms, reconcilable_terminal_statuses):
        events.append(f"poll:{turn_id}")
        return _snapshot("needs_continue", turn_id)

    monkeypatch.setattr(atc, "wait_for_agent_turn_terminal", _wait)
    monkeypatch.setattr(
        atc,
        "_stage_task_work_already_complete",
        lambda *, team_id, task_id: pytest.fail("predicate must not be called for project tasks"),
    )

    snapshot, final_turn_id, used = _wait_with_bounded_turn_continuation(
        _handle(),
        action=_action(node_id="hypothesis_design"),
        input_snapshot={"teamId": "team-1", "projectId": "proj-1"},
        adapter_spec=AgentTaskAdapterSpec(
            node_id="hypothesis_design",
            family="research_project",
            task_key="hypothesis_design",
        ),
        timeout_ms=1000,
        poll_ms=10,
    )

    assert final_turn_id == "turn-main"
    assert snapshot["terminalStatus"] == "needs_continue"
    assert used == []
    assert events == ["poll:turn-main"]


def _stage_task_store(monkeypatch, tasks_by_id):
    """Patch the orchestration-facade stage-task store used by failure propagation."""

    import core.web.services.team_workflow_orchestration_service as facade

    upserts: list[dict] = []
    events: list[tuple] = []

    def _find(team_id, task_id):
        found = tasks_by_id.get(str(task_id))
        return (dict(found), "run-test") if found is not None else (None, "")

    def _upsert(team_id, run_id, task):
        upserts.append(dict(task))
        tasks_by_id[str(task.get("taskId"))] = dict(task)
        return task

    def _record(event_type, team_id, fields=None, **kwargs):
        events.append((event_type, str(team_id), dict(fields or {})))

    monkeypatch.setattr(
        facade, "_find_source_collection_stage_session_task_by_id", _find
    )
    monkeypatch.setattr(
        facade, "_upsert_source_collection_stage_session_task", _upsert
    )
    monkeypatch.setattr(facade, "_record_workflow_event", _record)
    monkeypatch.setattr(facade, "utc_now_iso", lambda: "2026-09-02T00:00:00Z")
    return upserts, events


def test_main_turn_failure_marks_stage_task_failed(monkeypatch):
    """A formal stage turn that ends ``failed_runtime`` must mirror the failure
    onto its stage task (status=failed + structured failureCode/failureMessage)
    so the replay can pick a recovery path instead of reusing the poisoned
    session forever.  Existing task data (result/writeback) stays untouched."""
    import core.web.services.team_workflow.research_runtime.agent_turn_completion as atc

    tasks = {
        "task-1": {
            "taskId": "task-1",
            "sessionId": "sess-1",
            "status": "needs_review",
            "writeback": {"status": "needs_review"},
            "result": {"keep": "me"},
            "turn": {"turnId": "turn-main", "status": "needs_review"},
        }
    }
    upserts, events = _stage_task_store(monkeypatch, tasks)

    def _wait(session_id, turn_id, *, timeout_ms, poll_ms, reconcilable_terminal_statuses):
        raise _terminal_failure(
            turn_id, "failed_runtime", problem_code="context_budget_exhausted"
        )

    monkeypatch.setattr(atc, "wait_for_agent_turn_terminal", _wait)
    monkeypatch.setattr(atc, "_record_turn_continuation_scene_event", lambda *a, **k: None)
    monkeypatch.setattr(
        atc,
        "_stage_task_work_already_complete",
        lambda *, team_id, task_id: False,
    )

    with pytest.raises(RuntimeError) as excinfo:
        _wait_with_bounded_turn_continuation(
            _handle(),
            action=_action(),
            input_snapshot=_input_snapshot(),
            adapter_spec=AgentTaskAdapterSpec(
                node_id="source_finding",
                family="source_collection",
                task_key="finding",
                role_key="source_finder",
            ),
            timeout_ms=1000,
            poll_ms=10,
        )

    assert json.loads(str(excinfo.value))["code"] == "agent_turn_terminal_failed"
    assert len(upserts) == 1
    failed = upserts[0]
    assert failed["status"] == "failed"
    assert failed["failureCode"] == "context_budget_exhausted"
    assert "failed_runtime" in failed["failureMessage"]
    assert "context_budget_exhausted" in failed["failureMessage"]
    assert failed["result"] == {"keep": "me"}
    assert failed["writeback"] == {"status": "needs_review"}
    assert failed["failedAt"] == "2026-09-02T00:00:00Z"
    assert any(
        event_type == "source_collection.stage_session_task_turn_terminal_failed"
        for event_type, _team, _fields in events
    )


def test_stage_task_failure_propagation_idempotent_and_completed_guard(monkeypatch):
    """Repeated callbacks must not rewrite an identical failure, and a settled
    ``completed`` task must never be retroactively failed."""
    from core.web.services.team_workflow.research_runtime.agent_turn_completion import (
        _propagate_turn_terminal_failure_to_stage_task,
    )

    detail = {
        "code": "agent_turn_terminal_failed",
        "sessionId": "sess-1",
        "turnId": "turn-main",
        "terminalStatus": "failed_runtime",
        "terminalProblemCode": "context_budget_exhausted",
        "terminalReason": "context_budget_exhausted",
    }

    # Completed tasks are settled work: never overwritten.
    completed = {"taskId": "task-done", "status": "completed", "result": {"ok": True}}
    upserts, _events = _stage_task_store(monkeypatch, {"task-done": completed})
    _propagate_turn_terminal_failure_to_stage_task(
        team_id="team-1", task_id="task-done", failure_detail=detail
    )
    assert upserts == []

    # Identical failure already recorded: no rewrite (original timestamps win).
    failed_once = {
        "taskId": "task-failed",
        "status": "failed",
        "failureCode": "context_budget_exhausted",
        "failureMessage": (
            "Agent turn ended in terminal status 'failed_runtime'. "
            "Reason: context_budget_exhausted. Stage task marked failed so the "
            "formal replay can pick a recovery path."
        ),
        "failedAt": "2026-01-01T00:00:00Z",
        "updatedAt": "2026-01-01T00:00:00Z",
    }
    tasks = {"task-failed": failed_once}
    upserts, _events = _stage_task_store(monkeypatch, tasks)
    _propagate_turn_terminal_failure_to_stage_task(
        team_id="team-1", task_id="task-failed", failure_detail=detail
    )
    assert upserts == []
    assert tasks["task-failed"]["failedAt"] == "2026-01-01T00:00:00Z"

    # A new failure reason on the same task does overwrite the failure record.
    _propagate_turn_terminal_failure_to_stage_task(
        team_id="team-1",
        task_id="task-failed",
        failure_detail={
            **detail,
            "terminalStatus": "failed_provider",
            "terminalProblemCode": "provider_timeout",
            "terminalReason": "provider_timeout",
        },
    )
    assert len(upserts) == 1
    assert upserts[0]["failureCode"] == "provider_timeout"
    assert "failed_provider" in upserts[0]["failureMessage"]
