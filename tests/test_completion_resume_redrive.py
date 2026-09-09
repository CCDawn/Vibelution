"""Completion-cursor redrive for runs blocked on an undeliverable receipt.

``wake_receipt_completion`` re-arms a deferred completion only when the
original model-invocation receipt is delivered.  When the process that made
the model call died before persisting that receipt (production
run-50d3e53c54de), nothing can ever wake the blocked run again -- even though
the node's business work already settled "completed" on its domain authority
(the source-collection stage completion gate).

The maintenance sweep ``redrive_authority_complete_completions`` closes that
gap fail-closed: only a source-collection cursor whose stage-task authority
reports "completed" and whose turn is already terminal gets its original
failed adapter_dispatch action re-armed, so the ordinary dispatch path
consumes the durable cursor and commits the node through the normal
artifact/handoff chain.  A missing/foreign cursor, a non-completed authority,
a live turn, a consumed attempt, or a non-blocked run is always a no-op.

No real model, network, or research activity is involved.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from core.web.services.team_workflow.research_runtime import agent_turn_completion
from core.web.services.team_workflow.research_runtime.completion_dependency import (
    COMPLETION_PENDING,
    CompletionDependencyPending,
    bind_completion_resume,
    defer_completion,
    redrive_authority_complete_completions,
)
from core.web.services.team_workflow.research_runtime.domain_ports import (
    AgentTaskHandle,
)
from tests._support.adapter_fakes import FakeDomainPorts
from tests._support.command_helpers import CommandHarness
from tests._support.workflow_ledger_helpers import FIXED_NOW_MS
from tests.test_research_workflow_agent_anchor import (
    _agent_action,
    _leased_outbox,
    _outbox_row,
    _project_agent_action,
    _seed,
)

_TEAM_ID = "research-team"


def _error(action) -> CompletionDependencyPending:
    handle = AgentTaskHandle("session-1", 1, "task-1", "turn-1")
    error = CompletionDependencyPending(
        "receipt pending",
        snapshot={"terminal": True, "terminalStatus": "completed"},
        handle=handle,
    )
    bind_completion_resume(error, action, handle, {"reservationId": "res-1"})
    return error


def _defer_to_blocked(h: CommandHarness, action):
    """Drive one real defer into the production blocked-cursor state."""
    h.store.submit(
        lambda u: u.repository.update_attempt_status(
            action.node_run_id, "running", FIXED_NOW_MS
        ),
        force_flush=True,
    ).result()
    outbox = _leased_outbox(h, action, attempt_count=9)
    defer_completion(
        h.store,
        outbox=outbox,
        action=action,
        error=_error(action),
        owner="adapter-worker",
        now_ms=FIXED_NOW_MS + 1,
    )
    assert _outbox_row(h, outbox.action_id).status == "failed"
    assert h.store.get_run(action.run_id).status == "blocked"
    return outbox


def _authority(complete: bool):
    return lambda *, team_id, task_id: (
        bool(complete)
        and team_id == _TEAM_ID
        and task_id == "task-1"
    )


def _settle_cursor_turn(monkeypatch: pytest.MonkeyPatch, *, terminal: bool = True) -> None:
    """Pin the cursor turn's canonical execution state (no live session)."""
    from core.web.services.session import turn_diagnostics

    monkeypatch.setattr(
        turn_diagnostics,
        "get_session_turn_completion_snapshot",
        lambda session_id, turn_id="": {
            "sessionId": session_id,
            "turnId": turn_id,
            "terminal": terminal,
            "terminalStatus": "completed" if terminal else "",
        },
    )


def _completion_resumed_events(h: CommandHarness, run_id: str) -> list[Any]:
    rows = h.store.submit(
        lambda u: u.repository.execute(
            "SELECT event_type, actor_json, payload_json FROM workflow_events "
            "WHERE run_id = ? AND event_type = 'node_completion_resumed'",
            (run_id,),
        ).fetchall(),
        force_flush=True,
    ).result(timeout=10)
    return list(rows or ())


def test_authority_complete_redrive_rearms_cursor_and_unblocks_run(
    tmp_path, monkeypatch
) -> None:
    """Authority-complete blocked cursor: the failed action is re-armed, the
    run unblocked, and one redrive resume event recorded."""
    h = CommandHarness(tmp_path / "ledger.sqlite")
    try:
        h.seed_run(status="running")
        action = _agent_action()
        _seed(h, action, action.node_id)
        outbox = _defer_to_blocked(h, action)
        _settle_cursor_turn(monkeypatch)
        monkeypatch.setattr(
            agent_turn_completion,
            "_stage_task_work_already_complete",
            _authority(True),
        )

        assert (
            redrive_authority_complete_completions(
                h.store, now_ms=FIXED_NOW_MS + 2
            )
            == 1
        )
        row = _outbox_row(h, outbox.action_id)
        assert row.status == "pending"
        assert row.attempt_count == 0
        # The original completion problem (with its cursor) is preserved so
        # the re-leased action re-enters the resume path, not a fresh start.
        problem = json.loads(row.last_problem_json)
        assert problem["code"] == COMPLETION_PENDING
        assert problem["completionResume"]["actionId"] == action.action_id
        assert h.store.get_run(action.run_id).status == "running"
        assert h.store.get_run(action.run_id).blocked_problem_json is None
        assert (
            h.store.latest_attempt(action.run_id, action.node_id).status
            == "running"
        )
        events = _completion_resumed_events(h, action.run_id)
        assert len(events) == 1
        assert json.loads(events[0][1])["actorId"] == "completion-authority-redrive"
        payload = json.loads(events[0][2])
        assert payload["nodeRunId"] == action.node_run_id
        assert payload["redrive"] is True
    finally:
        h.close()


def test_authority_complete_redrive_finishes_node_through_worker(
    tmp_path, monkeypatch
) -> None:
    """The re-armed cursor is consumed by the ordinary dispatch path: the
    attempt closes succeeded through the normal verify/commit chain, with no
    second budget reservation or task creation."""
    from core.web.services.team_workflow.research_runtime.action_registry import (
        ActionRegistry,
    )
    from core.web.services.team_workflow.research_runtime.adapter_dispatch_worker import (
        AdapterDispatchWorker,
    )
    from core.web.services.team_workflow.research_runtime.adapters.domain_adapters import (
        AgentActionAdapter,
    )

    h = CommandHarness(tmp_path / "ledger.sqlite")
    try:
        h.seed_run(status="running")
        action = _agent_action()
        _seed(h, action, action.node_id)
        outbox = _defer_to_blocked(h, action)
        _settle_cursor_turn(monkeypatch)
        monkeypatch.setattr(
            agent_turn_completion,
            "_stage_task_work_already_complete",
            _authority(True),
        )
        assert (
            redrive_authority_complete_completions(
                h.store, now_ms=FIXED_NOW_MS + 2
            )
            == 1
        )

        ports = FakeDomainPorts()
        registry = ActionRegistry()
        registry.register(AgentActionAdapter(ports))
        worker = AdapterDispatchWorker(
            store=h.store,
            registry=registry,
            ports=ports,
            successor_fn=lambda node: ("source_extraction",),
            now_provider=lambda: FIXED_NOW_MS + 1000,
        )
        worker.run_once()

        attempt = h.store.latest_attempt(action.run_id, action.node_id)
        assert attempt.status == "succeeded"
        assert attempt.attempt == 1
        assert _outbox_row(h, outbox.action_id).status == "succeeded"
        assert h.store.get_run(action.run_id).status != "blocked"
        # The resume path reuses the cursor's handle/reservation: no new
        # budget reservation and no second task was created.
        assert "reserve_budget" not in ports.calls
        assert "create_agent_task" not in ports.calls
    finally:
        h.close()


def test_authority_incomplete_keeps_run_blocked(tmp_path, monkeypatch) -> None:
    """Fail-closed: an authority that has not settled completed never gets
    redriven -- the run stays blocked on its original problem."""
    h = CommandHarness(tmp_path / "ledger.sqlite")
    try:
        h.seed_run(status="running")
        action = _agent_action()
        _seed(h, action, action.node_id)
        outbox = _defer_to_blocked(h, action)
        _settle_cursor_turn(monkeypatch)
        monkeypatch.setattr(
            agent_turn_completion,
            "_stage_task_work_already_complete",
            _authority(False),
        )

        assert (
            redrive_authority_complete_completions(
                h.store, now_ms=FIXED_NOW_MS + 2
            )
            == 0
        )
        assert _outbox_row(h, outbox.action_id).status == "failed"
        assert h.store.get_run(action.run_id).status == "blocked"
        assert (
            _completion_resumed_events(h, action.run_id) == []
        )
    finally:
        h.close()


def test_redrive_skips_non_source_collection_family(tmp_path, monkeypatch) -> None:
    """Families without a completion authority (research_project) keep their
    receipt-wake semantics; no hard-coded sideflow allow-list is consulted."""
    h = CommandHarness(tmp_path / "ledger.sqlite")
    try:
        h.seed_run(status="running")
        action = _project_agent_action()
        _seed(h, action, "problem_understanding")
        outbox = _defer_to_blocked(h, action)
        _settle_cursor_turn(monkeypatch)
        monkeypatch.setattr(
            agent_turn_completion,
            "_stage_task_work_already_complete",
            _authority(True),
        )

        assert (
            redrive_authority_complete_completions(
                h.store, now_ms=FIXED_NOW_MS + 2
            )
            == 0
        )
        assert _outbox_row(h, outbox.action_id).status == "failed"
        assert h.store.get_run(action.run_id).status == "blocked"
    finally:
        h.close()


def test_redrive_skips_when_cursor_missing_from_row_problem(
    tmp_path, monkeypatch
) -> None:
    h = CommandHarness(tmp_path / "ledger.sqlite")
    try:
        h.seed_run(status="running")
        action = _agent_action()
        _seed(h, action, action.node_id)
        outbox = _defer_to_blocked(h, action)
        _settle_cursor_turn(monkeypatch)
        current = _outbox_row(h, outbox.action_id)
        stripped = json.dumps(
            {k: v for k, v in json.loads(current.last_problem_json).items()
             if k != "completionResume"},
            ensure_ascii=False,
        )
        h.store.submit(
            lambda u: u.repository.execute(
                "UPDATE outbox_actions SET last_problem_json=? WHERE action_id=?",
                (stripped, outbox.action_id),
            ),
            force_flush=True,
        ).result()
        monkeypatch.setattr(
            agent_turn_completion,
            "_stage_task_work_already_complete",
            _authority(True),
        )

        assert (
            redrive_authority_complete_completions(
                h.store, now_ms=FIXED_NOW_MS + 2
            )
            == 0
        )
        assert _outbox_row(h, outbox.action_id).status == "failed"
        assert h.store.get_run(action.run_id).status == "blocked"
    finally:
        h.close()


def test_redrive_skips_consumed_attempt_and_non_blocked_run(
    tmp_path, monkeypatch
) -> None:
    """A superseded/terminal attempt and a non-blocked run are both no-ops."""
    h = CommandHarness(tmp_path / "ledger.sqlite")
    monkeypatch.setattr(
        agent_turn_completion,
        "_stage_task_work_already_complete",
        _authority(True),
    )
    try:
        h.seed_run(status="running")
        action = _agent_action()
        _seed(h, action, action.node_id)
        outbox = _defer_to_blocked(h, action)
        _settle_cursor_turn(monkeypatch)

        # Attempt no longer running: the cursor's execution window is closed.
        h.store.submit(
            lambda u: u.repository.update_attempt_status(
                action.node_run_id, "failed", FIXED_NOW_MS + 2
            ),
            force_flush=True,
        ).result()
        assert (
            redrive_authority_complete_completions(
                h.store, now_ms=FIXED_NOW_MS + 3
            )
            == 0
        )
        assert _outbox_row(h, outbox.action_id).status == "failed"
        assert h.store.get_run(action.run_id).status == "blocked"

        # Run no longer blocked (terminal): never resurrected by the sweep
        # (the SQL scan only sees blocked runs).
        h.store.submit(
            lambda u: u.repository.update_run_status(
                action.run_id, _TEAM_ID, "cancelled", FIXED_NOW_MS + 4
            ),
            force_flush=True,
        ).result()
        assert (
            redrive_authority_complete_completions(
                h.store, now_ms=FIXED_NOW_MS + 5
            )
            == 0
        )
        assert _outbox_row(h, outbox.action_id).status == "failed"
        assert h.store.get_run(action.run_id).status == "cancelled"
    finally:
        h.close()


def test_redrive_is_idempotent_under_replays(tmp_path, monkeypatch) -> None:
    """A second sweep pass after a successful redrive is a no-op: the row is
    no longer failed, the run no longer blocked, and exactly one resume event
    exists."""
    h = CommandHarness(tmp_path / "ledger.sqlite")
    try:
        h.seed_run(status="running")
        action = _agent_action()
        _seed(h, action, action.node_id)
        _defer_to_blocked(h, action)
        _settle_cursor_turn(monkeypatch)
        monkeypatch.setattr(
            agent_turn_completion,
            "_stage_task_work_already_complete",
            _authority(True),
        )

        assert (
            redrive_authority_complete_completions(
                h.store, now_ms=FIXED_NOW_MS + 2
            )
            == 1
        )
        assert (
            redrive_authority_complete_completions(
                h.store, now_ms=FIXED_NOW_MS + 3
            )
            == 0
        )
        assert (
            len(_completion_resumed_events(h, action.run_id)) == 1
        )
        assert h.store.get_run(action.run_id).status == "running"
    finally:
        h.close()


def test_formal_receipt_gate_only_relaxes_for_authority_complete() -> None:
    """The receipt gate keeps its strict raise everywhere; the durable-cursor
    resume onto gate-verified completed work is the single relaxation."""
    routing = {
        "requiredModelPolicy": {"providerIds": ["p"]},
        "modelPolicySha256": "h" * 64,
        "routes": {"generation": {}},
    }
    snapshot = {"terminal": True, "terminalStatus": "completed"}
    with pytest.raises(CompletionDependencyPending):
        agent_turn_completion._require_formal_model_invocation_receipt(
            snapshot,
            input_snapshot={"modelRoutingPolicy": routing},
            task_started_at_ms=1,
        )
    # Durable-cursor resume onto authority-complete work: no re-defer.
    agent_turn_completion._require_formal_model_invocation_receipt(
        snapshot,
        input_snapshot={"modelRoutingPolicy": routing},
        task_started_at_ms=1,
        stage_authority_complete=True,
        identity={"sessionId": "session-1", "turnId": "turn-1", "taskId": "task-1"},
    )
    # No routing requirement: never raises, relaxation or not.
    agent_turn_completion._require_formal_model_invocation_receipt(
        snapshot,
        input_snapshot={},
        task_started_at_ms=1,
    )
    # A visible formal receipt still satisfies the gate on every path.
    agent_turn_completion._require_formal_model_invocation_receipt(
        snapshot,
        input_snapshot={"modelRoutingPolicy": routing},
        task_started_at_ms=1,
        formal_receipt={"scope": {"stageId": "generation"}},
    )
