"""Multiple pending interrupts: resume must address one interrupt by id.

Production evidence (run-d02722658d8b): a thread with several historical
heal/goto interrupts rejects a bare ``Command(resume=receipt)`` with
"When there are multiple pending interrupts, you must specify the interrupt
id when resuming".  The worker classified that as transient and burned the
full retry budget before terminal failure.

These tests pin the fixed contract:

- a single pending interrupt keeps the legacy bare-resume behaviour;
- multiple pending interrupts resume through a single-entry resume map
  keyed by the LangGraph interrupt id matched via the action-identity
  formula (nodeId/actionId — the same formula PendingAction and
  ExecutionReceipt use), leaving unrelated interrupts untouched;
- when no interrupt matches the dispatch identity, resuming must fail with
  a diagnostic error (never blindly confirm an unrelated interrupt);
- the worker treats that diagnostic as deterministic and fails the dispatch
  on the first pass instead of requeueing five times.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from core.research.workflow.challenge_cup_runtime import (
    AmbiguousInterruptResumeError,
    ChallengeCupGraphCoordinator,
    GraphDispatch,
)
from core.research.workflow.contracts import ExecutionReceipt
from core.web.services.team_workflow.research_runtime.graph_dispatch_worker import (
    GraphDispatchWorker,
)
from tests._support.command_helpers import CommandHarness
from tests._support.workflow_ledger_helpers import (
    FIXED_NOW_MS,
    build_attempt_record,
    build_command_record,
    build_outbox_record,
    build_run_record,
)

RUN_ID = "run-multi-interrupt"


def _branch_node(node_id: str):
    """Mirror the formal node contract: freeze a PendingAction-shaped value,
    then verify the resumed receipt identity inside the node."""

    def run(state: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "actionId": f"act-{RUN_ID}:{node_id}:1",
            "runId": RUN_ID,
            "nodeRunId": f"nr-{RUN_ID}-{node_id}-a1",
            "nodeId": node_id,
            "attempt": 1,
        }
        answer = interrupt(payload)
        assert answer["actionId"] == payload["actionId"], (
            f"{node_id} received receipt for wrong action: {answer['actionId']!r}"
        )
        # Distinct keys: a plain-dict schema would reject concurrent writes
        # from the three parallel branches into the same channel.
        return {f"done__{node_id}": True}

    return run


def _build_fanout_builder():
    builder = StateGraph(dict)
    builder.add_node("entry", lambda state: {"entered": True})
    builder.add_node("branch_a", _branch_node("branch_a"))
    builder.add_node("branch_b", _branch_node("branch_b"))
    builder.add_node("branch_c", _branch_node("branch_c"))
    builder.add_edge(START, "entry")
    # One superstep runs branch_a/b/c concurrently; each interrupts.
    builder.add_edge("entry", "branch_a")
    builder.add_edge("entry", "branch_b")
    builder.add_edge("entry", "branch_c")
    builder.add_edge("branch_a", END)
    builder.add_edge("branch_b", END)
    builder.add_edge("branch_c", END)
    return builder


def _build_single_builder(target: str):
    builder = StateGraph(dict)
    builder.add_node("entry", lambda state: {"entered": True})
    builder.add_node(target, _branch_node(target))
    builder.add_edge(START, "entry")
    builder.add_edge("entry", target)
    builder.add_edge(target, END)
    return builder


class _RecordingCoordinator(ChallengeCupGraphCoordinator):
    """Compiles a test graph and records every Command handed to invoke."""

    def __init__(self, checkpoint_path: Path, builder: Any) -> None:
        super().__init__(checkpoint_path)
        self._builder = builder
        self.commands: list[Any] = []

    def _compile(self):
        from contextlib import ExitStack

        from core.research.workflow.checkpoint_store import open_sqlite_checkpointer

        stack = ExitStack()
        checkpointer = stack.enter_context(
            open_sqlite_checkpointer(str(self._checkpoint_path))
        )
        graph = self._builder.compile(checkpointer=checkpointer)

        class _Recorder:
            def __init__(self, outer: "_RecordingCoordinator", inner: Any) -> None:
                self._outer = outer
                self._inner = inner

            def invoke(self, command: Any, config: Any) -> Any:
                self._outer.commands.append(command)
                return self._inner.invoke(command, config)

            def __getattr__(self, name: str) -> Any:
                return getattr(self._inner, name)

        return _Recorder(self, graph), stack

    def last_command(self) -> Any | None:
        return self.commands[-1] if self.commands else None


def _receipt(node_id: str) -> ExecutionReceipt:
    return ExecutionReceipt(
        action_id=f"act-{RUN_ID}:{node_id}:1",
        node_run_id=f"nr-{RUN_ID}-{node_id}-a1",
        outcome="succeeded",
        artifact_receipt_ids=(),
        execution_anchor_id=None,
        budget_receipt_id=None,
        problem=None,
        completed_at_ms=FIXED_NOW_MS,
    )


def _resume_dispatch(node_id: str) -> GraphDispatch:
    return GraphDispatch(
        action_id=_receipt(node_id).action_id,
        run_id=RUN_ID,
        node_run_id=f"nr-{RUN_ID}-{node_id}-a1",
        node_id=node_id,
        attempt=1,
        dispatch_kind="resume_action",
        receipt=_receipt(node_id),
    )


def _thread_interrupts(coordinator: _RecordingCoordinator) -> dict[str, str]:
    """Return {nodeId: interruptId} for every task-level pending interrupt."""
    from core.research.workflow.challenge_cup_runtime import _pending_interrupt_items

    graph, stack = coordinator._compile()
    try:
        state = coordinator._read_state(
            graph, coordinator._config(RUN_ID), heal=True
        )
    finally:
        stack.close()
    items: dict[str, str] = {}
    for item in _pending_interrupt_items(state):
        value = getattr(item, "value", None)
        if isinstance(value, dict) and value.get("nodeId"):
            items[str(value["nodeId"])] = str(getattr(item, "id"))
    return items


def _start_multi_interrupt_thread(tmp_path: Path) -> _RecordingCoordinator:
    coordinator = _RecordingCoordinator(
        tmp_path / "checkpoints.sqlite", _build_fanout_builder()
    )
    graph, stack = coordinator._compile()
    try:
        graph.invoke({"run_id": RUN_ID}, coordinator._config(RUN_ID))
    finally:
        stack.close()
    interrupted = _thread_interrupts(coordinator)
    assert set(interrupted) == {"branch_a", "branch_b", "branch_c"}, interrupted
    return coordinator


def test_multiple_interrupts_resume_matched_id_and_leave_others_pending(
    tmp_path: Path,
) -> None:
    coordinator = _start_multi_interrupt_thread(tmp_path)
    interrupts = _thread_interrupts(coordinator)
    command_count_before = len(coordinator.commands)

    result = coordinator.resume_action(_resume_dispatch("branch_a"))

    command = coordinator.last_command()
    assert command is not None
    # Bare resumes raise "multiple pending interrupts"; the fix sends exactly
    # one entry keyed by the matched interrupt's id.
    assert isinstance(command.resume, dict)
    assert list(command.resume.keys()) == [interrupts["branch_a"]]
    assert command.resume[interrupts["branch_a"]]["actionId"] == (
        f"act-{RUN_ID}:branch_a:1"
    )
    after = _thread_interrupts(coordinator)
    assert "branch_a" not in after
    # Unrelated interrupts are NOT confirmed by this resume.
    assert after["branch_b"] == interrupts["branch_b"]
    assert after["branch_c"] == interrupts["branch_c"]
    assert result.completed is False
    assert len(coordinator.commands) == command_count_before + 1


def test_resume_without_matching_interrupt_raises_diagnostic_and_never_invokes(
    tmp_path: Path,
) -> None:
    coordinator = _start_multi_interrupt_thread(tmp_path)
    command_count_before = len(coordinator.commands)

    import pytest

    with pytest.raises(AmbiguousInterruptResumeError) as excinfo:
        coordinator.resume_action(_resume_dispatch("branch_d"))

    message = str(excinfo.value)
    assert "multiple pending interrupts" in message.lower()
    assert "branch_d" in message
    # Blind resume guard: nothing was sent to LangGraph at all.
    assert len(coordinator.commands) == command_count_before
    # Thread untouched: all three interrupts still pending.
    assert set(_thread_interrupts(coordinator)) == {
        "branch_a",
        "branch_b",
        "branch_c",
    }


def test_single_interrupt_keeps_legacy_bare_resume(tmp_path: Path) -> None:
    coordinator = _RecordingCoordinator(
        tmp_path / "checkpoints.sqlite", _build_single_builder("branch_a")
    )
    graph, stack = coordinator._compile()
    try:
        graph.invoke({"run_id": RUN_ID}, coordinator._config(RUN_ID))
    finally:
        stack.close()

    result = coordinator.resume_action(_resume_dispatch("branch_a"))

    command = coordinator.last_command()
    assert command is not None
    # Single-interrupt compatibility: bare payload, no resume map.
    assert isinstance(command.resume, dict)
    assert command.resume.get("actionId") == f"act-{RUN_ID}:branch_a:1"
    assert result.completed is True


class _MultiInterruptCoordinatorStub:
    def __init__(self) -> None:
        self.resume_calls = 0

    def snapshot(self, run_id):
        # Not reached in the failing path; only needed for the worker's
        # pre-resume recovery checks.
        return {"checkpointId": None, "nextNodeIds": [], "values": {}, "pendingAction": None}

    def resume_action(self, dispatch):
        self.resume_calls += 1
        # Exactly what langgraph raised on run-d02722658d8b.
        raise RuntimeError(
            "When there are multiple pending interrupts, you must specify "
            "the interrupt id when resuming. Docs: "
            "https://docs.langchain.com/oss/python/langgraph/add-human-in-the-loop"
            "#resume-multiple-interrupts-with-one-invocation."
        )


def _seed_live_resume_dispatch(commands: CommandHarness) -> None:
    """The ledger shape of run-d02722658d8b right after reconcile revival:
    succeeded attempt + fresh pending resume dispatch for the same node."""
    from dataclasses import replace

    record = build_run_record(run_id="run-test", status="running")
    payload = {
        "commandId": "cmd-driver",
        "runId": "run-test",
        "nodeRunId": "nr-run-test-evidence_relations-a2",
        "nodeId": "evidence_relations",
        "attempt": 2,
        "dispatchKind": "resume_action",
        "teamId": "research-team",
        "workflowVersionId": "challenge-cup-research-v2.1.0",
        "inputSnapshotHash": "a" * 64,
        "budgetPolicyHash": "",
        "receipt": {
            "actionId": "act-5cd0046334264954",
            "nodeRunId": "nr-run-test-evidence_relations-a2",
            "outcome": "succeeded",
            "artifactReceiptIds": [],
            "completedAtMs": FIXED_NOW_MS,
        },
    }
    row = replace(
        build_outbox_record(
            "act-live-multi-interrupt",
            run_id="run-test",
            command_id="cmd-a2",
            idempotency_key="graph:resume:live-multi-interrupt",
        ),
        node_run_id="nr-run-test-evidence_relations-a2",
        payload_json=json.dumps(payload),
    )

    def mutate(uow):
        uow.repository.insert_run(record)
        uow.repository.insert_command(
            build_command_record(
                command_id="cmd-a2",
                run_id="run-test",
                idempotency_key="key:a2",
                node_id="evidence_relations",
            )
        )
        uow.repository.insert_attempt(
            build_attempt_record(
                node_run_id="nr-run-test-evidence_relations-a2",
                run_id="run-test",
                node_id="evidence_relations",
                attempt=2,
                # Terminal attempt: forces the run-level reconciliation
                # translation (the production run-d02722658d8b shape).
                status="succeeded",
                command_id="cmd-a2",
            )
        )
        uow.repository.insert_outbox(row)

    commands.store.submit(mutate, force_flush=True).result(timeout=10)


def test_worker_fails_multi_interrupt_dispatch_on_first_pass(tmp_path: Path) -> None:
    """'multiple pending interrupts' is deterministic: no transient budget."""
    commands = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        _seed_live_resume_dispatch(commands)
        stub = _MultiInterruptCoordinatorStub()
        worker = GraphDispatchWorker(
            store=commands.store,
            coordinator=stub,
            owner_id="graph-worker-test",
            now_provider=lambda: FIXED_NOW_MS + 2000,
        )

        worker.run_once()

        row = commands.store.read(lambda repo: repo.get_outbox("act-live-multi-interrupt"))
        assert row is not None and row.status == "failed"
        # First pass terminal: attempt_count stays at 1 instead of walking to 5.
        assert row.attempt_count == 1
        problem = json.loads(str(row.last_problem_json))
        assert problem["code"] == "graph_dispatch_invalid"
        assert "multiple pending interrupts" in problem["detail"]
        run = commands.store.get_run("run-test")
        assert run.status == "reconciliation_required"
    finally:
        commands.close()


def test_worker_still_requeues_transient_errors(tmp_path: Path) -> None:
    """Non-deterministic errors keep the existing retry budget."""
    commands = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        _seed_live_resume_dispatch(commands)

        class _TransientCoordinatorStub:
            def resume_action(self, dispatch):
                raise RuntimeError("sqlite disk I/O error while reading checkpoint")

        worker = GraphDispatchWorker(
            store=commands.store,
            coordinator=_TransientCoordinatorStub(),
            owner_id="graph-worker-test",
            now_provider=lambda: FIXED_NOW_MS + 2000,
        )

        worker.run_once()

        row = commands.store.read(lambda repo: repo.get_outbox("act-live-multi-interrupt"))
        assert row is not None
        assert row.status == "pending"
        assert row.attempt_count == 1
    finally:
        commands.close()
