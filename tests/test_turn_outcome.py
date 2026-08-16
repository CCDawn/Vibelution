"""Focused stop/resume contracts for TurnOutcomeController.

Large protocol tests already cover happy paths. These pin carryover
classification, lifecycle hard-stops, and retry-budget edge cases that
can leave a turn spinning or resuming the wrong identity.
"""

from core.llm.types import CanonicalItemIdentity, TurnOutcome
from core.orchestration.turn_outcome import TurnOutcomeController


def _controller(**kwargs) -> TurnOutcomeController:
    return TurnOutcomeController(
        max_consecutive_failures=kwargs.pop("max_consecutive_failures", 3),
        get_attention_snapshot=lambda: {},
        **kwargs,
    )


def test_classify_turn_carryover_covers_absent_terminal_mismatch_and_accepted():
    assert TurnOutcomeController.classify_turn_carryover(None, expected_turn_identity="t1") == "absent"
    assert TurnOutcomeController.classify_turn_carryover({}, expected_turn_identity="t1") == "absent"
    assert (
        TurnOutcomeController.classify_turn_carryover(
            {"terminal": True, "turnIdentity": "t1", "goal": "g", "messages": [1]},
            expected_turn_identity="t1",
        )
        == "terminal"
    )
    assert (
        TurnOutcomeController.classify_turn_carryover(
            {"turnIdentity": "", "goal": "g", "messages": [1]},
            expected_turn_identity="t1",
        )
        == "missing_identity"
    )
    assert (
        TurnOutcomeController.classify_turn_carryover(
            {"turnIdentity": "old", "goal": "g", "messages": [1]},
            expected_turn_identity="new",
        )
        == "identity_mismatch"
    )
    assert (
        TurnOutcomeController.classify_turn_carryover(
            {"turnIdentity": "t1", "goal": "", "messages": [1]},
            expected_turn_identity="t1",
        )
        == "invalid"
    )
    assert (
        TurnOutcomeController.classify_turn_carryover(
            {"turnIdentity": "t1", "goal": "keep going", "messages": [{"role": "user"}]},
            expected_turn_identity="t1",
        )
        == "accepted"
    )


def test_handle_lifecycle_action_hard_stops_budget_and_restart():
    restart = TurnOutcomeController.handle_lifecycle_action("restart")
    assert restart.continue_main_loop is False
    assert restart.pending_action == "restart"
    assert restart.break_round is False

    budget = TurnOutcomeController.handle_lifecycle_action("tool_budget_exhausted")
    assert budget.break_round is True
    assert budget.continue_main_loop is True
    assert "额度已用尽" in (budget.info_log or "")

    idle = TurnOutcomeController.handle_lifecycle_action(None)
    assert idle.break_round is False
    assert idle.continue_main_loop is True
    assert idle.pending_action is None


def test_should_stop_after_llm_failure_uses_retry_budget_and_coerces_bad_ints():
    controller = _controller(max_consecutive_failures=3)
    assert (
        controller.should_stop_after_llm_failure(
            category="timeout",
            retryable=True,
            consecutive_failures=1,
            iteration=1,
            attempts=2,
            max_attempts=5,
        )
        is None
    )
    timeout_stop = controller.should_stop_after_llm_failure(
        category="timeout",
        retryable=True,
        consecutive_failures=1,
        iteration=1,
        attempts=5,
        max_attempts=5,
    )
    assert timeout_stop and "超时" in timeout_stop

    coerced = controller.should_stop_after_llm_failure(
        category="network_error",
        retryable=True,
        consecutive_failures=1,
        iteration=1,
        attempts="nope",
        max_attempts="also-nope",
    )
    assert coerced is None


def test_decide_llm_iteration_empty_tool_calls_does_not_execute_or_finish():
    identity = CanonicalItemIdentity(
        session_id="s1",
        turn_id="t1",
        invocation_id="i1",
        iteration=1,
        item_id="empty",
    )
    outcome = TurnOutcome(
        kind="tool_calls",
        identity=identity,
        tool_calls=(),
        terminal_event_seen=True,
    )
    decision = TurnOutcomeController.decide_llm_iteration(outcome)
    assert decision.should_execute_tools is False
    assert decision.should_finish is False
    assert decision.should_stop_unsuccessfully is False
