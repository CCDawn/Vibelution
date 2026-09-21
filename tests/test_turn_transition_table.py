"""Turn journal declarative transition table (shadow-first) contracts.

The table borrows ZCode's ``canTransitionTo`` semantics (declarative state ->
allowed next event categories) for the journal-replayed turn state. Covered
here: table integrity, the legal/illegal phase matrix, shadow telemetry on
illegal sequences *without* intercepting the write, the opt-in hard gate that
reuses the post-terminal degrade path, rewrite-aware cache invalidation, and
false-positive replay over the real production turn shapes (normal submit,
proactive, edit/regenerate resubmit, LLM-resilience post-terminal immunity).
"""

from __future__ import annotations

import pytest

from core.chat.turn_journal import (
    EVENT_ASSISTANT_DELTA_COMMITTED,
    EVENT_ASSISTANT_ITEM_COMMITTED,
    EVENT_ASSISTANT_MESSAGE,
    EVENT_ASSISTANT_PARTIAL,
    EVENT_BRANCH_REBASE,
    EVENT_CLI_SESSION_LIFECYCLE,
    EVENT_CLI_TASK_RESULT,
    EVENT_CLI_TASK_SENT,
    EVENT_COMPACTION_CHECKPOINT,
    EVENT_COMPRESSION_ATTEMPT,
    EVENT_LLM_RESILIENCE,
    EVENT_TOOL_CALL_STARTED,
    EVENT_TOOL_RESULT,
    EVENT_TURN_COMPLETED,
    EVENT_TURN_CONTEXT,
    EVENT_TURN_FAILED,
    EVENT_TURN_INTERRUPTED,
    EVENT_TURN_STARTED,
    EVENT_USER_MESSAGE,
    TERMINAL_EVENTS,
    TURN_EVENT_PHASES,
    TURN_EVENT_TRANSITIONS,
    TURN_PHASE_TERMINAL,
    TurnJournalIllegalTransitionError,
    TurnJournalPostTerminalWriteError,
    append_turn_event,
    evaluate_turn_event_transition,
    load_turn_events,
    rewrite_turn_events,
    set_turn_transition_guard_hook,
    turn_transition_guard_mode,
    turn_transition_state_from_event_types,
)
from core.chat.turn_journal import (
    TURN_STATE_OPEN,
    TURN_STATE_PRISTINE,
    TURN_STATE_TERMINAL,
)
from core.chat.turn_journal import (
    TURN_TRANSITION_GUARD_ENFORCE,
    TURN_TRANSITION_GUARD_ENV,
    TURN_TRANSITION_GUARD_SHADOW,
)

_INTERNAL_TURN_TRIGGER = "internal_turn_trigger"

_ALL_EVENT_TYPES = [
    EVENT_TURN_STARTED,
    EVENT_USER_MESSAGE,
    EVENT_TURN_CONTEXT,
    EVENT_ASSISTANT_PARTIAL,
    EVENT_ASSISTANT_DELTA_COMMITTED,
    EVENT_ASSISTANT_ITEM_COMMITTED,
    EVENT_ASSISTANT_MESSAGE,
    EVENT_TOOL_CALL_STARTED,
    EVENT_TOOL_RESULT,
    EVENT_CLI_TASK_SENT,
    EVENT_CLI_TASK_RESULT,
    EVENT_CLI_SESSION_LIFECYCLE,
    EVENT_COMPACTION_CHECKPOINT,
    EVENT_COMPRESSION_ATTEMPT,
    EVENT_TURN_COMPLETED,
    EVENT_TURN_FAILED,
    EVENT_TURN_INTERRUPTED,
    EVENT_LLM_RESILIENCE,
    EVENT_BRANCH_REBASE,
    _INTERNAL_TURN_TRIGGER,
]


@pytest.fixture(autouse=True)
def _isolated_data_home(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path / "operator-data"))


@pytest.fixture(autouse=True)
def _shadow_guard(monkeypatch):
    """Every test starts in shadow mode unless it opts into enforcement."""
    monkeypatch.setenv(TURN_TRANSITION_GUARD_ENV, "")


@pytest.fixture
def violations():
    """Collect guard records through the public hook; unregister on teardown."""
    records: list[dict] = []
    set_turn_transition_guard_hook(records.append)
    yield records
    set_turn_transition_guard_hook(None)


# ---------------------------------------------------------------------------
# Table integrity
# ---------------------------------------------------------------------------


def test_every_known_event_type_has_a_phase():
    for event_type in _ALL_EVENT_TYPES:
        assert event_type in TURN_EVENT_PHASES, event_type


def test_terminal_events_map_to_the_terminal_phase():
    for event_type in TERMINAL_EVENTS:
        assert TURN_EVENT_PHASES[event_type] == TURN_PHASE_TERMINAL


def test_transitions_only_reference_declared_phases():
    declared = set(TURN_EVENT_PHASES.values())
    for state, phases in TURN_EVENT_TRANSITIONS.items():
        assert state in {TURN_STATE_PRISTINE, TURN_STATE_OPEN, TURN_STATE_TERMINAL}
        assert phases, state
        for phase in phases:
            assert phase in declared, (state, phase)


def test_unknown_event_types_are_out_of_band():
    assert turn_transition_state_from_event_types([]) == TURN_STATE_PRISTINE
    # A future writer's event type must stay forward-compatible: legal everywhere.
    for prior in ([], [EVENT_TURN_STARTED], [EVENT_TURN_STARTED, EVENT_TURN_COMPLETED]):
        state, legal, reason = evaluate_turn_event_transition(prior, "future_schema_event")
        assert legal, (state, reason)


# ---------------------------------------------------------------------------
# Legal / illegal matrix
# ---------------------------------------------------------------------------


_NORMAL_TURN = [
    EVENT_TURN_STARTED,
    EVENT_USER_MESSAGE,
    EVENT_TURN_CONTEXT,
    EVENT_ASSISTANT_PARTIAL,
    EVENT_ASSISTANT_DELTA_COMMITTED,
    EVENT_ASSISTANT_ITEM_COMMITTED,
    EVENT_TOOL_CALL_STARTED,
    EVENT_TOOL_RESULT,
    EVENT_COMPACTION_CHECKPOINT,
    EVENT_COMPRESSION_ATTEMPT,
    EVENT_CLI_TASK_SENT,
    EVENT_CLI_TASK_RESULT,
    EVENT_CLI_SESSION_LIFECYCLE,
    EVENT_ASSISTANT_MESSAGE,
]


@pytest.mark.parametrize(
    "prior,next_event",
    [
        # Pristine: openers, out-of-band markers, and the scaffold-free
        # projection/legacy shapes proven benign by real-journal replay.
        ([], EVENT_TURN_STARTED),
        ([], EVENT_USER_MESSAGE),
        ([], EVENT_LLM_RESILIENCE),
        ([], EVENT_BRANCH_REBASE),
        ([], EVENT_ASSISTANT_MESSAGE),
        ([], EVENT_ASSISTANT_ITEM_COMMITTED),
        ([], EVENT_TURN_CONTEXT),
        ([], EVENT_COMPACTION_CHECKPOINT),
        ([], EVENT_COMPRESSION_ATTEMPT),
        # Open turn: output, tools, maintenance, terminal, markers.
        ([EVENT_TURN_STARTED], EVENT_USER_MESSAGE),
        ([EVENT_TURN_STARTED], EVENT_TURN_CONTEXT),
        ([EVENT_TURN_STARTED], EVENT_ASSISTANT_PARTIAL),
        (_NORMAL_TURN[:6], EVENT_TOOL_CALL_STARTED),
        (_NORMAL_TURN[:8], EVENT_COMPACTION_CHECKPOINT),
        (_NORMAL_TURN[:8], EVENT_COMPRESSION_ATTEMPT),
        (_NORMAL_TURN[:6], EVENT_CLI_TASK_SENT),
        (_NORMAL_TURN, EVENT_TURN_COMPLETED),
        ([EVENT_TURN_STARTED], EVENT_TURN_FAILED),
        ([EVENT_TURN_STARTED, EVENT_USER_MESSAGE], EVENT_TURN_INTERRUPTED),
        (_NORMAL_TURN[:6], EVENT_LLM_RESILIENCE),
        (_NORMAL_TURN[:6], EVENT_BRANCH_REBASE),
        (_NORMAL_TURN[:6], _INTERNAL_TURN_TRIGGER),
        # Edit/regenerate shape: marker first, no turn_started at all.
        ([EVENT_BRANCH_REBASE], EVENT_USER_MESSAGE),
        ([EVENT_BRANCH_REBASE, EVENT_USER_MESSAGE], EVENT_TURN_CONTEXT),
        ([EVENT_BRANCH_REBASE, EVENT_USER_MESSAGE], EVENT_TOOL_RESULT),
        ([EVENT_BRANCH_REBASE, EVENT_USER_MESSAGE], EVENT_TURN_FAILED),
        # Proactive shape: lifecycle then the internal trigger marker.
        ([EVENT_TURN_STARTED], _INTERNAL_TURN_TRIGGER),
        # Out-of-band events are legal at every state, including post-terminal.
        (_NORMAL_TURN + [EVENT_TURN_COMPLETED], EVENT_LLM_RESILIENCE),
        ([EVENT_TURN_STARTED, EVENT_TURN_FAILED], EVENT_BRANCH_REBASE),
    ],
)
def test_legal_transitions(prior, next_event):
    state, legal, reason = evaluate_turn_event_transition(prior, next_event)
    assert legal, (state, prior, next_event, reason)


@pytest.mark.parametrize(
    "prior,next_event,expected_state",
    [
        # Orphaned live-stream/tool/terminal before any scaffold: no known
        # writer produces these (real-journal replay found zero).
        ([], EVENT_TURN_COMPLETED, TURN_STATE_PRISTINE),
        ([], EVENT_TURN_FAILED, TURN_STATE_PRISTINE),
        ([], EVENT_TURN_INTERRUPTED, TURN_STATE_PRISTINE),
        ([], EVENT_ASSISTANT_PARTIAL, TURN_STATE_PRISTINE),
        ([], EVENT_ASSISTANT_DELTA_COMMITTED, TURN_STATE_PRISTINE),
        ([], EVENT_TOOL_CALL_STARTED, TURN_STATE_PRISTINE),
        ([], EVENT_TOOL_RESULT, TURN_STATE_PRISTINE),
        # Duplicate lifecycle start while the turn is open.
        ([EVENT_TURN_STARTED], EVENT_TURN_STARTED, TURN_STATE_OPEN),
        (
            [EVENT_BRANCH_REBASE, EVENT_USER_MESSAGE],
            EVENT_TURN_STARTED,
            TURN_STATE_OPEN,
        ),
        # Duplicate terminals (the classic double-settle race). The first two
        # are real catches from replaying production journals: a proactive
        # turn that settled turn_interrupted and then also wrote turn_failed,
        # and a completed turn that later received turn_interrupted.
        (
            [EVENT_TURN_STARTED, EVENT_TURN_COMPLETED],
            EVENT_TURN_COMPLETED,
            TURN_STATE_TERMINAL,
        ),
        (
            [EVENT_TURN_STARTED, EVENT_TURN_COMPLETED],
            EVENT_TURN_FAILED,
            TURN_STATE_TERMINAL,
        ),
        (
            [EVENT_TURN_STARTED, EVENT_TURN_FAILED],
            EVENT_TURN_INTERRUPTED,
            TURN_STATE_TERMINAL,
        ),
        (
            [EVENT_TURN_STARTED, EVENT_TURN_INTERRUPTED],
            EVENT_TURN_COMPLETED,
            TURN_STATE_TERMINAL,
        ),
        (
            [EVENT_TURN_STARTED, EVENT_TURN_INTERRUPTED],
            EVENT_TURN_FAILED,
            TURN_STATE_TERMINAL,
        ),
        (
            [EVENT_TURN_STARTED, EVENT_TURN_COMPLETED],
            EVENT_TURN_INTERRUPTED,
            TURN_STATE_TERMINAL,
        ),
        (
            [EVENT_TURN_STARTED, EVENT_TURN_FAILED],
            EVENT_TURN_FAILED,
            TURN_STATE_TERMINAL,
        ),
        # Lifecycle/input/context after the terminal.
        (
            [EVENT_TURN_STARTED, EVENT_TURN_COMPLETED],
            EVENT_TURN_STARTED,
            TURN_STATE_TERMINAL,
        ),
        (
            [EVENT_TURN_STARTED, EVENT_TURN_COMPLETED],
            EVENT_USER_MESSAGE,
            TURN_STATE_TERMINAL,
        ),
        (
            [EVENT_TURN_STARTED, EVENT_TURN_COMPLETED],
            EVENT_TURN_CONTEXT,
            TURN_STATE_TERMINAL,
        ),
        (
            [EVENT_TURN_STARTED, EVENT_TURN_FAILED],
            EVENT_USER_MESSAGE,
            TURN_STATE_TERMINAL,
        ),
        # Output/tools/maintenance after the terminal.
        (
            [EVENT_TURN_STARTED, EVENT_TURN_COMPLETED],
            EVENT_ASSISTANT_PARTIAL,
            TURN_STATE_TERMINAL,
        ),
        (
            [EVENT_TURN_STARTED, EVENT_TURN_COMPLETED],
            EVENT_ASSISTANT_MESSAGE,
            TURN_STATE_TERMINAL,
        ),
        (
            [EVENT_TURN_STARTED, EVENT_TURN_COMPLETED],
            EVENT_TOOL_RESULT,
            TURN_STATE_TERMINAL,
        ),
        (
            [EVENT_TURN_STARTED, EVENT_TURN_COMPLETED],
            EVENT_COMPACTION_CHECKPOINT,
            TURN_STATE_TERMINAL,
        ),
        (
            [EVENT_TURN_STARTED, EVENT_TURN_INTERRUPTED],
            EVENT_CLI_TASK_SENT,
            TURN_STATE_TERMINAL,
        ),
    ],
)
def test_illegal_transitions(prior, next_event, expected_state):
    state, legal, reason = evaluate_turn_event_transition(prior, next_event)
    assert not legal
    assert state == expected_state
    assert reason


# ---------------------------------------------------------------------------
# Shadow mode: telemetry without interception
# ---------------------------------------------------------------------------


def test_shadow_mode_records_violation_and_does_not_intercept_write(tmp_path, violations):
    append_turn_event(tmp_path, "session-a", "turn-1", EVENT_TURN_STARTED, status="running")
    append_turn_event(tmp_path, "session-a", "turn-1", EVENT_TURN_COMPLETED, status="completed")
    assert violations == []

    appended = append_turn_event(
        tmp_path,
        "session-a",
        "turn-1",
        EVENT_TURN_STARTED,  # lifecycle after terminal: table-illegal, audit-only
        status="running",
    )
    assert appended is not None

    # The write landed: shadow never intercepts.
    events = load_turn_events(tmp_path, "session-a")
    assert [event.event_type for event in events] == [
        EVENT_TURN_STARTED,
        EVENT_TURN_COMPLETED,
        EVENT_TURN_STARTED,
    ]

    assert len(violations) == 1
    record = violations[0]
    assert record["schema"] == "turn_transition_guard.v1"
    assert record["mode"] == TURN_TRANSITION_GUARD_SHADOW
    assert record["sessionId"] == "session-a"
    assert record["turnId"] == "turn-1"
    assert record["eventType"] == EVENT_TURN_STARTED
    assert record["phase"] == "lifecycle"
    assert record["priorEventCount"] == 2
    assert record["priorHasTurnStarted"] is True
    assert record["priorTerminalType"] == EVENT_TURN_COMPLETED
    assert "after terminal" in record["reason"]


def test_shadow_mode_reports_duplicate_terminal_and_keeps_it_durable(tmp_path, violations):
    append_turn_event(tmp_path, "session-a", "turn-1", EVENT_TURN_STARTED, status="running")
    append_turn_event(tmp_path, "session-a", "turn-1", EVENT_TURN_COMPLETED, status="completed")
    append_turn_event(tmp_path, "session-a", "turn-1", EVENT_TURN_FAILED, status="failed")

    assert len(violations) == 1
    record = violations[0]
    assert record["eventType"] == EVENT_TURN_FAILED
    assert "duplicate terminal" in record["reason"]
    assert record["priorTerminalType"] == EVENT_TURN_COMPLETED
    events = load_turn_events(tmp_path, "session-a")
    assert len(events) == 3


def test_shadow_mode_default_when_env_missing_or_garbage(monkeypatch):
    monkeypatch.delenv(TURN_TRANSITION_GUARD_ENV, raising=False)
    assert turn_transition_guard_mode() == TURN_TRANSITION_GUARD_SHADOW
    monkeypatch.setenv(TURN_TRANSITION_GUARD_ENV, "observe")
    assert turn_transition_guard_mode() == TURN_TRANSITION_GUARD_SHADOW
    monkeypatch.setenv(TURN_TRANSITION_GUARD_ENV, "ENFORCE")
    assert turn_transition_guard_mode() == TURN_TRANSITION_GUARD_ENFORCE


def test_without_hook_shadow_still_appends(tmp_path):
    """No telemetry sink registered: shadow check stays silent and cheap."""
    append_turn_event(tmp_path, "session-a", "turn-1", EVENT_TURN_COMPLETED, status="completed")
    events = load_turn_events(tmp_path, "session-a")
    assert [event.event_type for event in events] == [EVENT_TURN_COMPLETED]


# ---------------------------------------------------------------------------
# Hard gate (opt-in; off by default)
# ---------------------------------------------------------------------------


def test_enforce_mode_raises_post_terminal_compatible_error_and_drops_write(
    tmp_path, monkeypatch
):
    monkeypatch.setenv(TURN_TRANSITION_GUARD_ENV, "enforce")
    append_turn_event(tmp_path, "session-a", "turn-1", EVENT_TURN_STARTED, status="running")
    append_turn_event(tmp_path, "session-a", "turn-1", EVENT_TURN_COMPLETED, status="completed")

    with pytest.raises(TurnJournalIllegalTransitionError) as excinfo:
        append_turn_event(
            tmp_path,
            "session-a",
            "turn-1",
            EVENT_TURN_STARTED,
            status="running",
        )
    # Existing classifiers keep working: the degrade path catches the
    # post-terminal error, and it is a ValueError.
    assert isinstance(excinfo.value, TurnJournalPostTerminalWriteError)
    assert isinstance(excinfo.value, ValueError)

    events = load_turn_events(tmp_path, "session-a")
    assert [event.event_type for event in events] == [
        EVENT_TURN_STARTED,
        EVENT_TURN_COMPLETED,
    ]


def test_enforce_mode_caller_degrade_path_drops_late_write(tmp_path, monkeypatch):
    """Simulate a caller like stream_capture: catch and degrade, don't crash."""
    monkeypatch.setenv(TURN_TRANSITION_GUARD_ENV, "1")
    append_turn_event(tmp_path, "session-a", "turn-1", EVENT_TURN_STARTED, status="running")
    append_turn_event(tmp_path, "session-a", "turn-1", EVENT_TURN_COMPLETED, status="completed")

    degraded: list[str] = []
    try:
        append_turn_event(tmp_path, "session-a", "turn-1", EVENT_TURN_FAILED, status="failed")
    except TurnJournalPostTerminalWriteError:
        degraded.append("late_terminal_write_dropped")
    assert degraded == ["late_terminal_write_dropped"]
    assert len(load_turn_events(tmp_path, "session-a")) == 2


def test_enforce_mode_blocks_orphaned_output(tmp_path, monkeypatch):
    monkeypatch.setenv(TURN_TRANSITION_GUARD_ENV, "true")
    with pytest.raises(TurnJournalIllegalTransitionError):
        append_turn_event(
            tmp_path,
            "session-a",
            "turn-orphan",
            EVENT_ASSISTANT_PARTIAL,
            status="streaming",
        )
    assert load_turn_events(tmp_path, "session-a") == []


# ---------------------------------------------------------------------------
# Cache invalidation across rewrites
# ---------------------------------------------------------------------------


def test_rewrite_reopens_transition_state_for_truncated_turn(tmp_path, violations):
    append_turn_event(tmp_path, "session-a", "turn-1", EVENT_TURN_STARTED, status="running")
    append_turn_event(tmp_path, "session-a", "turn-1", EVENT_USER_MESSAGE, status="recorded")
    append_turn_event(tmp_path, "session-a", "turn-1", EVENT_TURN_COMPLETED, status="completed")
    events = load_turn_events(tmp_path, "session-a")

    # Edit-resubmit truncation: drop the terminal and the turn is open again.
    rewrite_turn_events(tmp_path, "session-a", events[:-1])
    append_turn_event(
        tmp_path,
        "session-a",
        "turn-1",
        EVENT_USER_MESSAGE,
        status="recorded",
        source="edited_user_message",
    )
    assert violations == []
    tail = [event.event_type for event in load_turn_events(tmp_path, "session-a")]
    assert tail == [EVENT_TURN_STARTED, EVENT_USER_MESSAGE, EVENT_USER_MESSAGE]


# ---------------------------------------------------------------------------
# False-positive replay: production turn shapes must stay silent in shadow
# ---------------------------------------------------------------------------


_PRODUCTION_SHAPES: dict[str, list[str]] = {
    "normal_submit": _NORMAL_TURN + [EVENT_TURN_COMPLETED],
    "failed_turn": _NORMAL_TURN[:8] + [EVENT_TURN_FAILED],
    "interrupted_by_reconcile": [EVENT_TURN_STARTED, EVENT_USER_MESSAGE, EVENT_TURN_INTERRUPTED],
    "proactive": [
        EVENT_TURN_STARTED,
        _INTERNAL_TURN_TRIGGER,
        EVENT_TURN_CONTEXT,
        EVENT_ASSISTANT_ITEM_COMMITTED,
        EVENT_TOOL_CALL_STARTED,
        EVENT_TOOL_RESULT,
        EVENT_ASSISTANT_MESSAGE,
        EVENT_TURN_COMPLETED,
    ],
    "proactive_cancelled_open": [
        EVENT_TURN_STARTED,
        _INTERNAL_TURN_TRIGGER,
        EVENT_TURN_INTERRUPTED,
    ],
    "edit_resubmit": [
        EVENT_BRANCH_REBASE,
        EVENT_USER_MESSAGE,
        EVENT_TURN_CONTEXT,
        EVENT_ASSISTANT_PARTIAL,
        EVENT_ASSISTANT_ITEM_COMMITTED,
        EVENT_ASSISTANT_MESSAGE,
        EVENT_TURN_COMPLETED,
    ],
    "regenerate": [
        EVENT_BRANCH_REBASE,
        EVENT_USER_MESSAGE,
        EVENT_TURN_CONTEXT,
        EVENT_TOOL_CALL_STARTED,
        EVENT_TOOL_RESULT,
        EVENT_TURN_FAILED,
    ],
    "resilience_mid_turn": _NORMAL_TURN[:6] + [EVENT_LLM_RESILIENCE, EVENT_TURN_COMPLETED],
    "resilience_post_terminal": _NORMAL_TURN[:6]
    + [EVENT_TURN_COMPLETED, EVENT_LLM_RESILIENCE],
    "head_select_on_settled_turn": [EVENT_TURN_STARTED, EVENT_USER_MESSAGE, EVENT_TURN_COMPLETED]
    + [EVENT_BRANCH_REBASE],
    "llm_resilience_on_pristine_turn": [EVENT_LLM_RESILIENCE],
    # Scaffold-free projection shapes observed in real journals: chat-room
    # round transcript sync, child-session projections, and chat-room rounds
    # journaling compression decisions under synthetic round ids.
    "chat_room_transcript_projection": [EVENT_ASSISTANT_MESSAGE],
    "chat_room_items_projection": [
        EVENT_ASSISTANT_ITEM_COMMITTED,
        EVENT_ASSISTANT_ITEM_COMMITTED,
    ],
    "chat_room_round_maintenance": [
        EVENT_COMPRESSION_ATTEMPT,
        EVENT_ASSISTANT_ITEM_COMMITTED,
        EVENT_COMPACTION_CHECKPOINT,
    ],
    "child_session_projection": [
        EVENT_ASSISTANT_MESSAGE,
        EVENT_TOOL_RESULT,
        EVENT_ASSISTANT_MESSAGE,
    ],
    # Legacy shape: turn_context as a turn's first event (pre-Aug-2025 journals).
    "legacy_context_first": [
        EVENT_TURN_CONTEXT,
        EVENT_ASSISTANT_ITEM_COMMITTED,
        EVENT_TOOL_CALL_STARTED,
        EVENT_TOOL_RESULT,
    ],
}


@pytest.mark.parametrize("shape_name", sorted(_PRODUCTION_SHAPES))
def test_production_shapes_replay_without_false_positives(tmp_path, violations, shape_name):
    sequence = _PRODUCTION_SHAPES[shape_name]
    for event_type in sequence:
        append_turn_event(
            tmp_path,
            f"session-{shape_name}",
            "turn-1",
            event_type,
            status="replay",
            source="transition_replay",
            visible_in_model=False,
        )
    assert violations == [], (shape_name, [record["reason"] for record in violations])
    events = load_turn_events(tmp_path, f"session-{shape_name}")
    assert [event.event_type for event in events] == sequence


def test_multi_turn_session_replay_without_false_positives(tmp_path, violations):
    """One journal, three turns in the three production shapes, interleaved."""
    session_id = "session-multi"
    for turn_id, sequence in (
        ("turn-normal", _PRODUCTION_SHAPES["normal_submit"]),
        ("turn-proactive", _PRODUCTION_SHAPES["proactive"]),
        ("turn-edit", _PRODUCTION_SHAPES["edit_resubmit"]),
    ):
        for event_type in sequence:
            append_turn_event(
                tmp_path,
                session_id,
                turn_id,
                event_type,
                status="replay",
                visible_in_model=False,
            )
    assert violations == []
