"""Challenge Cup logical-task deadline scale contract.

The fixed 300s absolute wall clock used to be applied to the whole formal
node turn chain, killing real 6-15 minute nodes, and the 180s no-progress
window killed turns that were mid-flight in one long model call.  The
contract under test:

- The absolute deadline is derived from the node's explicit task-bundle
  ``deadlineAt`` contract first, then the bounded conservative default
  (30 minutes); a missing scope still means unlimited.
- A turn chain that legitimately runs 8+ minutes (simulated clock) never
  trips the deadline.
- A single long in-flight model call (bounded snapshot fingerprint unchanged
  but the session still owns the running turn) is not no-progress.
- A truly silent turn (no fingerprint change AND no in-flight signal) still
  fails closed at the no-progress window.
- Requeues and continuation chains never reset the absolute deadline.
"""

from __future__ import annotations

import json
from dataclasses import replace as _replace
from pathlib import Path

import pytest

from core.research.workflow.contracts import PendingAction
from core.research.workflow.models import ActorKind
from core.web.services.team_workflow.research_runtime.challenge_turn_policy import (
    CHALLENGE_LOGICAL_TASK_TIMEOUT_MS,
    CHALLENGE_NO_PROGRESS_TIMEOUT_MS,
    ChallengeTaskDeadlineExceeded,
    _env_positive_int_ms,
    challenge_task_deadline_scope,
    current_challenge_task_deadline_at_ms,
    decide_live_turn_wait,
    live_turn_progress_fingerprint,
    remaining_challenge_task_ms,
    resolve_challenge_task_deadline_at_ms,
)
from core.web.services.team_workflow.research_runtime.adapter_dispatch_worker import (
    AdapterDispatchWorker,
    _task_bundle_contract_deadline_at_ms,
)
from core.web.services.team_workflow.research_runtime.agent_turn_completion import (
    AgentTaskHandle,
    TurnNotReadyError,
    _wait_with_bounded_turn_continuation,
)
from core.web.services.team_workflow.research_runtime.task_bundle_lifecycle import (
    task_bundle_id,
)
from tests._support.adapter_fakes import FakeDomainPorts
from tests._support.command_helpers import CommandHarness
from tests._support.workflow_ledger_helpers import FIXED_NOW_MS

CREATED_AT_MS = 1_000_000


def _agent_action() -> PendingAction:
    return PendingAction(
        action_id="act-agent",
        run_id="run-test",
        node_run_id="nr-run-test-source_finding-a1",
        node_id="source_finding",
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


# --------------------------------------------------------------- 8-minute scale


def test_formal_node_turn_chain_runs_eight_minutes_without_deadline(monkeypatch) -> None:
    """Five 120s wait windows (10 simulated minutes) stay inside the budget.

    Each window models one durable dispatch of the same logical task (the
    worker requeues a still-running turn and re-enters with the same outbox
    clock).  Under the old flat 300s absolute deadline the chain was killed
    with ChallengeTaskDeadlineExceeded inside the third window.
    """
    import core.web.services.team_workflow.research_runtime.agent_turn_completion as atc

    clock = {"now_ms": CREATED_AT_MS}
    monkeypatch.setattr(
        atc,
        "remaining_challenge_task_ms",
        lambda *, now_ms=None: remaining_challenge_task_ms(
            now_ms=clock["now_ms"] if now_ms is None else now_ms
        ),
    )

    def fake_wait(_session_id, _turn_id, *, timeout_ms, poll_ms, reconcilable_terminal_statuses):
        assert timeout_ms <= 120_000
        clock["now_ms"] += 120_000
        raise TurnNotReadyError("still running after one wait window")

    monkeypatch.setattr(atc, "wait_for_agent_turn_terminal", fake_wait)

    with challenge_task_deadline_scope(CREATED_AT_MS):
        for _window in range(5):
            try:
                _wait_with_bounded_turn_continuation(
                    _handle(),
                    action=_agent_action(),
                    input_snapshot={"teamId": "team-1"},
                    adapter_spec=None,
                    timeout_ms=120_000,
                    poll_ms=1,
                )
            except ChallengeTaskDeadlineExceeded as exc:  # pragma: no cover - guard
                raise AssertionError(
                    "healthy 10-minute chain was killed by the deadline"
                ) from exc
            except TurnNotReadyError:
                pass  # the worker requeues and re-dispatches the same task

    simulated_ms = clock["now_ms"] - CREATED_AT_MS
    assert simulated_ms >= 480_000  # the required 8 real-scale minutes
    assert simulated_ms >= CHALLENGE_LOGICAL_TASK_TIMEOUT_MS / 3


def test_old_flat_window_would_have_failed_the_same_chain(monkeypatch) -> None:
    """Pin the scale regression: 8 minutes must exceed the legacy 300s window."""

    assert 480_000 > 300_000


# ------------------------------------------------------- deadline derivation


def test_deadline_contract_overrides_bounded_default() -> None:
    contract_deadline = CREATED_AT_MS + 600_000
    with challenge_task_deadline_scope(
        CREATED_AT_MS, deadline_at_ms=contract_deadline
    ):
        assert current_challenge_task_deadline_at_ms() == contract_deadline
        # A contract earlier than the default window still wins (fail-closed).
        assert remaining_challenge_task_ms(now_ms=CREATED_AT_MS + 500_000) == 100_000
        assert remaining_challenge_task_ms(now_ms=contract_deadline) == 0


def test_missing_contract_uses_bounded_conservative_default() -> None:
    with challenge_task_deadline_scope(CREATED_AT_MS):
        assert (
            current_challenge_task_deadline_at_ms()
            == CREATED_AT_MS + CHALLENGE_LOGICAL_TASK_TIMEOUT_MS
        )
        assert (
            remaining_challenge_task_ms(now_ms=CREATED_AT_MS + CHALLENGE_LOGICAL_TASK_TIMEOUT_MS - 1)
            == 1
        )
        assert remaining_challenge_task_ms(now_ms=CREATED_AT_MS + CHALLENGE_LOGICAL_TASK_TIMEOUT_MS) == 0


def test_resolve_deadline_helper_priority() -> None:
    assert resolve_challenge_task_deadline_at_ms(
        CREATED_AT_MS, contract_deadline_at_ms=CREATED_AT_MS + 5
    ) == CREATED_AT_MS + 5
    assert resolve_challenge_task_deadline_at_ms(CREATED_AT_MS) == (
        CREATED_AT_MS + CHALLENGE_LOGICAL_TASK_TIMEOUT_MS
    )
    # Invalid/zero contracts fall back to the bounded default.
    assert resolve_challenge_task_deadline_at_ms(
        CREATED_AT_MS, contract_deadline_at_ms=0
    ) == CREATED_AT_MS + CHALLENGE_LOGICAL_TASK_TIMEOUT_MS


def test_no_scope_means_unlimited() -> None:
    assert current_challenge_task_deadline_at_ms() is None
    assert remaining_challenge_task_ms() is None


def test_timeout_constants_are_env_overridable(monkeypatch) -> None:
    monkeypatch.setenv("VIBELUTION_CHALLENGE_LOGICAL_TASK_TIMEOUT_MS", "900000")
    monkeypatch.setenv("VIBELUTION_CHALLENGE_NO_PROGRESS_TIMEOUT_MS", "300000")
    assert _env_positive_int_ms("VIBELUTION_CHALLENGE_LOGICAL_TASK_TIMEOUT_MS", 1) == 900_000
    assert _env_positive_int_ms("VIBELUTION_CHALLENGE_NO_PROGRESS_TIMEOUT_MS", 1) == 300_000
    monkeypatch.setenv("VIBELUTION_CHALLENGE_LOGICAL_TASK_TIMEOUT_MS", "not-a-number")
    monkeypatch.setenv("VIBELUTION_CHALLENGE_NO_PROGRESS_TIMEOUT_MS", "-5")
    assert _env_positive_int_ms("VIBELUTION_CHALLENGE_LOGICAL_TASK_TIMEOUT_MS", 7) == 7
    assert _env_positive_int_ms("VIBELUTION_CHALLENGE_NO_PROGRESS_TIMEOUT_MS", 7) == 7


def test_default_budgets_absorb_real_scale_turns() -> None:
    # Real measured node scale: finding ran 13m42s, a single model call up to
    # 283s.  The bounded default must cover the chain, the no-progress window
    # must outlast one long in-flight call by a wide margin (>= 10 min).
    assert CHALLENGE_LOGICAL_TASK_TIMEOUT_MS >= 822_000
    assert CHALLENGE_NO_PROGRESS_TIMEOUT_MS >= 600_000


# ------------------------------------------------- in-flight model call safety


def _stalled_snapshot(turn_current: bool | None) -> dict:
    snapshot = {
        "terminal": False,
        "completionSource": "running",
        "messageCount": 3,
        "activeTurnId": "turn-main",
    }
    if turn_current is not None:
        snapshot["turnCurrent"] = turn_current
    return snapshot


def test_in_flight_long_call_is_not_no_progress() -> None:
    fingerprint = live_turn_progress_fingerprint(_stalled_snapshot(True))
    decision = decide_live_turn_wait(
        now_ms=CREATED_AT_MS + 300_000,  # 5 minutes of identical snapshots
        created_at_ms=CREATED_AT_MS,
        previous_problem={
            "code": "live_turn_wait",
            "lastProgressAtMs": CREATED_AT_MS,
            "progressFingerprint": fingerprint,
        },
        snapshot=_stalled_snapshot(True),
    )
    assert decision.stop_code == ""
    assert decision.no_progress_ms == 0
    assert decision.last_progress_at_ms == CREATED_AT_MS + 300_000


def test_in_flight_refresh_persists_across_requeues_until_silence() -> None:
    in_flight_fingerprint = live_turn_progress_fingerprint(_stalled_snapshot(True))
    previous = {
        "code": "live_turn_wait",
        "lastProgressAtMs": CREATED_AT_MS + 300_000,
        "progressFingerprint": in_flight_fingerprint,
    }
    # The call is still in flight one window later: still not no-progress.
    alive = decide_live_turn_wait(
        now_ms=CREATED_AT_MS + 420_000,
        created_at_ms=CREATED_AT_MS,
        previous_problem=previous,
        snapshot=_stalled_snapshot(True),
    )
    assert alive.stop_code == ""

    # The session worker went quiet: turnCurrent flipping to False is itself
    # the last observed activity, so the no-progress clock restarts from here.
    quiet_fingerprint = live_turn_progress_fingerprint(_stalled_snapshot(False))
    went_quiet = decide_live_turn_wait(
        now_ms=CREATED_AT_MS + 540_000,
        created_at_ms=CREATED_AT_MS,
        previous_problem={
            "code": "live_turn_wait",
            "lastProgressAtMs": alive.last_progress_at_ms,
            "progressFingerprint": in_flight_fingerprint,
        },
        snapshot=_stalled_snapshot(False),
    )
    assert went_quiet.stop_code == ""
    assert went_quiet.progress_advanced is True

    # No further activity for a full no-progress window: fail closed.
    silent = decide_live_turn_wait(
        now_ms=CREATED_AT_MS + 540_000 + CHALLENGE_NO_PROGRESS_TIMEOUT_MS,
        created_at_ms=CREATED_AT_MS,
        previous_problem={
            "code": "live_turn_wait",
            "lastProgressAtMs": went_quiet.last_progress_at_ms,
            "progressFingerprint": quiet_fingerprint,
        },
        snapshot=_stalled_snapshot(False),
    )
    assert silent.stop_code == "live_turn_no_progress_timeout"


def test_truly_silent_turn_still_fails_closed() -> None:
    fingerprint = live_turn_progress_fingerprint(_stalled_snapshot(False))
    decision = decide_live_turn_wait(
        now_ms=CREATED_AT_MS + CHALLENGE_NO_PROGRESS_TIMEOUT_MS,
        created_at_ms=CREATED_AT_MS,
        previous_problem={
            "code": "live_turn_wait",
            "lastProgressAtMs": CREATED_AT_MS,
            "progressFingerprint": fingerprint,
        },
        snapshot=_stalled_snapshot(False),
    )
    assert decision.stop_code == "live_turn_no_progress_timeout"
    assert decision.no_progress_ms >= CHALLENGE_NO_PROGRESS_TIMEOUT_MS


# ------------------------------------------------------- absolute no-reset


def _seeded_worker(harness: CommandHarness) -> AdapterDispatchWorker:
    from core.web.services.team_workflow.research_runtime.action_registry import ActionRegistry
    from core.web.services.team_workflow.research_runtime.adapters.domain_adapters import (
        AgentActionAdapter,
    )

    ports = FakeDomainPorts()
    registry = ActionRegistry()
    registry.register(AgentActionAdapter(ports))
    return AdapterDispatchWorker(
        store=harness.store,
        registry=registry,
        ports=ports,
        successor_fn=lambda node: (),
        now_provider=lambda: FIXED_NOW_MS + 1_000,
    )


def _seed_agent_outbox(harness: CommandHarness, action: PendingAction) -> None:
    from core.research.workflow.ledger import OutboxRecord
    from tests._support.workflow_ledger_helpers import (
        build_attempt_record,
        build_command_record,
    )

    def mutate(uow):
        if uow.repository.get_command("cmd-driver") is None:
            uow.repository.insert_command(
                build_command_record(
                    command_id="cmd-driver",
                    run_id=action.run_id,
                    idempotency_key="cmd-driver",
                )
            )
        uow.repository.insert_attempt(
            build_attempt_record(
                node_run_id=action.node_run_id,
                run_id=action.run_id,
                node_id=action.node_id,
                attempt=1,
                status="dispatching",
                command_id="cmd-driver",
                started_at_ms=FIXED_NOW_MS,
            )
        )
        uow.repository.insert_outbox(
            OutboxRecord(
                action_id=f"adapter-outbox-{action.action_id}",
                run_id=action.run_id,
                command_id="cmd-driver",
                node_run_id=action.node_run_id,
                action_kind="adapter_dispatch",
                idempotency_key=f"adapter:{action.action_id}",
                payload_json=json.dumps(action.to_dict()),
                status="pending",
                attempt_count=0,
                available_at_ms=FIXED_NOW_MS,
                lease_owner=None,
                lease_expires_at_ms=None,
                last_problem_json=None,
                created_at_ms=FIXED_NOW_MS,
                updated_at_ms=FIXED_NOW_MS,
            )
        )

    harness.store.submit(mutate, force_flush=True).result(timeout=10)


def _leased_outbox(harness: CommandHarness, action: PendingAction):
    from core.research.workflow.ledger.outbox import lease_ready_actions

    leased = lease_ready_actions(
        harness.store, owner="adapter-worker", now_ms=FIXED_NOW_MS, limit=1
    )
    assert leased and leased[0].action_id == f"adapter-outbox-{action.action_id}"
    return leased[0]


def _outbox_row(harness: CommandHarness, action_id: str):
    return harness.store.submit(
        lambda uow: uow.repository.get_outbox(action_id),
        force_flush=True,
    ).result(timeout=10)


def test_requeue_never_resets_absolute_contract_deadline(
    tmp_path: Path, monkeypatch
) -> None:
    """A trap fresh start timestamp cannot move the absolute contract deadline."""

    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        action = _agent_action()
        _seed_agent_outbox(harness, action)
        worker = _seeded_worker(harness)
        outbox = _leased_outbox(harness, action)

        original_started_at_ms = FIXED_NOW_MS - 250_000
        contract_deadline_at_ms = original_started_at_ms + 900_000
        monkeypatch.setattr(
            "core.web.services.team_workflow.research_runtime.adapter_dispatch_worker._task_bundle_contract_deadline_at_ms",
            lambda _action: contract_deadline_at_ms,
        )
        persisted = _replace(
            outbox,
            created_at_ms=FIXED_NOW_MS - 200_000,
            last_problem_json=json.dumps(
                {
                    "code": "live_turn_wait",
                    "logicalTaskStartedAtMs": original_started_at_ms,
                    "lastProgressAtMs": original_started_at_ms,
                    "progressFingerprint": live_turn_progress_fingerprint(
                        _stalled_snapshot(False)
                    ),
                }
            ),
        )

        worker._requeue_live_turn_wait(
            persisted,
            action,
            "turn_not_ready:running",
            snapshot={
                **_stalled_snapshot(False),
                # A missing canonical timestamp used to regenerate the fallback
                # start on every dispatch; it must not move the deadline either.
                "challengeTaskStartedAtMs": FIXED_NOW_MS,
            },
        )

        row = _outbox_row(harness, f"adapter-outbox-{action.action_id}")
        assert row is not None
        assert row.status == "pending"  # far inside the contract budget
        problem = json.loads(row.last_problem_json or "{}")
        assert problem["logicalTaskStartedAtMs"] == original_started_at_ms
        assert problem["deadlineAtMs"] == contract_deadline_at_ms
        assert problem["deadlineSource"] == "task_bundle_contract"
    finally:
        harness.close()


def test_nested_scope_keeps_outer_contract_deadline() -> None:
    """The canonical task clock re-entry must not move the outer deadline."""

    contract_deadline = CREATED_AT_MS + 900_000
    with challenge_task_deadline_scope(
        CREATED_AT_MS, deadline_at_ms=contract_deadline
    ):
        with challenge_task_deadline_scope(CREATED_AT_MS - 60_000):
            assert current_challenge_task_deadline_at_ms() == contract_deadline
            assert (
                remaining_challenge_task_ms(now_ms=CREATED_AT_MS + 500_000)
                == 400_000
            )
        assert current_challenge_task_deadline_at_ms() == contract_deadline


def test_nested_scope_without_contract_keeps_outer_deadline() -> None:
    with challenge_task_deadline_scope(CREATED_AT_MS):
        outer_deadline = current_challenge_task_deadline_at_ms()
        with challenge_task_deadline_scope(CREATED_AT_MS - 60_000):
            assert current_challenge_task_deadline_at_ms() == outer_deadline
        assert current_challenge_task_deadline_at_ms() == outer_deadline


# ------------------------------------------------------- contract resolution


def _write_run_with_bundle(
    root: Path,
    *,
    run_id: str,
    node_run_id: str,
    deadline_at: str,
    selection_id: str = "",
    candidate_id: str = "",
) -> None:
    from core.web.services.team_workflow.research_runtime.store import WorkflowRunStore

    scope: dict = {"kind": "workflow_node_root", "nodeRunId": node_run_id}
    if selection_id and candidate_id:
        scope = {
            "kind": "workflow_candidate",
            "selectionId": selection_id,
            "candidateId": candidate_id,
        }
    store = WorkflowRunStore(root=root)
    store.create_run(
        {
            "runId": run_id,
            "taskBundles": [
                {
                    "bundleId": task_bundle_id(node_run_id),
                    "parentNodeRunId": node_run_id,
                    "subtasks": [
                        {
                            "subtaskId": f"subtask-{node_run_id}",
                            "scope": scope,
                            "status": "running",
                            "deadlineAt": deadline_at,
                        }
                    ],
                }
            ],
        }
    )


def test_contract_resolver_reads_task_bundle_deadline(tmp_path, monkeypatch) -> None:
    from datetime import datetime, timezone

    deadline_iso = (
        datetime.fromtimestamp((FIXED_NOW_MS + 900_000) / 1000, tz=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )
    _write_run_with_bundle(
        tmp_path,
        run_id="run-test",
        node_run_id="nr-run-test-source_finding-a1",
        deadline_at=deadline_iso,
    )
    monkeypatch.setenv("VIBELUTION_RESEARCH_WORKFLOW_RUN_STORE", str(tmp_path))
    action = _agent_action()

    resolved = _task_bundle_contract_deadline_at_ms(action)
    assert resolved == FIXED_NOW_MS + 900_000

    # A single-subtask bundle (v2 default shape) still resolves for a scoped
    # action whose candidate key does not match the subtask scope.
    scoped = _replace(action, selection_id="sel-1", candidate_id="cand-1")
    assert _task_bundle_contract_deadline_at_ms(scoped) == FIXED_NOW_MS + 900_000


def test_contract_resolver_multi_subtask_requires_scope_match(
    tmp_path, monkeypatch
) -> None:
    from core.web.services.team_workflow.research_runtime.store import WorkflowRunStore

    node_run_id = "nr-run-test-source_finding-a1"
    store = WorkflowRunStore(root=tmp_path)
    store.create_run(
        {
            "runId": "run-test",
            "taskBundles": [
                {
                    "bundleId": task_bundle_id(node_run_id),
                    "parentNodeRunId": node_run_id,
                    "subtasks": [
                        {
                            "subtaskId": "s1",
                            "scope": {
                                "kind": "workflow_candidate",
                                "selectionId": "sel-1",
                                "candidateId": "cand-1",
                            },
                            "status": "running",
                            "deadlineAt": "2099-01-01T00:00:00Z",
                        },
                        {
                            "subtaskId": "s2",
                            "scope": {
                                "kind": "workflow_candidate",
                                "selectionId": "sel-1",
                                "candidateId": "cand-2",
                            },
                            "status": "running",
                            "deadlineAt": "2099-01-02T00:00:00Z",
                        },
                    ],
                }
            ],
        }
    )
    monkeypatch.setenv("VIBELUTION_RESEARCH_WORKFLOW_RUN_STORE", str(tmp_path))
    action = _agent_action()
    # No scope on the action and several subtasks: ambiguous, use the default.
    assert _task_bundle_contract_deadline_at_ms(action) is None
    # Exact scope match resolves that subtask's contract.
    scoped = _replace(action, selection_id="sel-1", candidate_id="cand-2")
    assert _task_bundle_contract_deadline_at_ms(scoped) is not None


def test_contract_resolver_missing_or_broken_falls_back_to_default(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("VIBELUTION_RESEARCH_WORKFLOW_RUN_STORE", str(tmp_path))
    action = _agent_action()
    # No run record at all.
    assert _task_bundle_contract_deadline_at_ms(action) is None

    # Malformed deadlineAt.
    _write_run_with_bundle(
        tmp_path,
        run_id="run-test",
        node_run_id="nr-run-test-source_finding-a1",
        deadline_at="not-a-timestamp",
    )
    assert _task_bundle_contract_deadline_at_ms(action) is None


def test_execute_scope_carries_contract_deadline(tmp_path: Path, monkeypatch) -> None:
    """The dispatcher's deadline scope uses the resolved contract deadline."""

    import core.web.services.team_workflow.research_runtime.adapter_dispatch_worker as adw

    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        action = _agent_action()
        _seed_agent_outbox(harness, action)
        worker = _seeded_worker(harness)
        outbox = _leased_outbox(harness, action)

        contract_deadline_at_ms = FIXED_NOW_MS + 600_000
        monkeypatch.setattr(
            adw,
            "_task_bundle_contract_deadline_at_ms",
            lambda _action: contract_deadline_at_ms,
        )
        captured: dict = {}

        class FakeAdapter:
            def execute(self, _action):
                captured["deadline"] = current_challenge_task_deadline_at_ms()
                captured["remaining_at_500s"] = remaining_challenge_task_ms(
                    now_ms=FIXED_NOW_MS + 500_000
                )
                return {"outcome": "succeeded"}

        worker._execute_with_lease_heartbeat(FakeAdapter(), action, outbox)

        assert captured["deadline"] == contract_deadline_at_ms
        # Contract (10 min) wins over the bounded default (30 min).
        assert captured["remaining_at_500s"] == 100_000
    finally:
        harness.close()
