# -*- coding: utf-8 -*-
"""TTFT batch5 (task B) regression tests: agent/assembly dark-zone caches.

Hard gates under test:
- The seeded-history fingerprint memo must return byte-identical values on
  cache hits and must fall through to a recompute whenever the ledger changed
  in any way the canonical replay can see (other-turn appends, branch markers,
  rewritten event objects).
- The context assembler identity memo must never change assembly output:
  warm-cache and forced-recompute assemblies are byte-identical across turns.
- Message digest telemetry is producer-gated: off by default, and the event
  keeps its complete field set whenever it fires.
- The disk-coherent ledger read cache returns identical event objects for an
  unchanged file and reloads after an append.
"""

from __future__ import annotations

import dataclasses
import json
from types import SimpleNamespace

import pytest

from agent import AgentRuntime
from core.chat import context_assembler
from core.chat.conversation_invariant import (
    canonical_conversation_messages_from_events,
    conversation_layer_fingerprint,
)
from core.chat.conversation_ledger import (
    EVENT_ASSISTANT_MESSAGE,
    EVENT_BRANCH_REBASE,
    EVENT_TOOL_RESULT,
    EVENT_USER_MESSAGE,
    append_conversation_event,
    load_conversation_events,
    load_conversation_events_cached,
)
from core.orchestration import turn_llm_adapter
from core.orchestration.turn_message_assembly import (
    _SEEDED_HISTORY_FINGERPRINT_MEMO,
    ledger_seeded_history_fingerprint,
)


@pytest.fixture(autouse=True)
def _clear_caches():
    _SEEDED_HISTORY_FINGERPRINT_MEMO._entries.clear()
    context_assembler._ASSEMBLY_MEMO._entries.clear()
    core_ledger = pytest.importorskip("core.chat.conversation_ledger")
    core_ledger._CONVERSATION_EVENTS_DISK_CACHE.clear()
    yield
    _SEEDED_HISTORY_FINGERPRINT_MEMO._entries.clear()
    context_assembler._ASSEMBLY_MEMO._entries.clear()
    core_ledger._CONVERSATION_EVENTS_DISK_CACHE.clear()


def _seed_two_turn_history(root, *, session_id: str) -> None:
    append_conversation_event(
        root, session_id, "turn-1", EVENT_USER_MESSAGE,
        status="recorded", payload={"content": "历史请求"},
    )
    append_conversation_event(
        root, session_id, "turn-1", EVENT_ASSISTANT_MESSAGE,
        status="completed", payload={"content": "历史回复"},
    )
    append_conversation_event(
        root, session_id, "turn-2", EVENT_USER_MESSAGE,
        status="recorded", payload={"content": "当前请求"},
    )


class _ProjectionSpy:
    """Count canonical replays driven through turn_message_assembly."""

    def __init__(self, monkeypatch) -> None:
        self.calls = 0
        original = canonical_conversation_messages_from_events

        def counting(events, **kwargs):
            self.calls += 1
            return original(events, **kwargs)

        monkeypatch.setattr(
            "core.chat.conversation_invariant.canonical_conversation_messages_from_events",
            counting,
        )


# ---------------------------------------------------------------------------
# 1. ledger_seeded_history_fingerprint memo
# ---------------------------------------------------------------------------


def test_seeded_history_fingerprint_memo_hits_without_replay(tmp_path, monkeypatch):
    spy = _ProjectionSpy(monkeypatch)
    _seed_two_turn_history(tmp_path, session_id="session-memo-hit")
    events = load_conversation_events(tmp_path, "session-memo-hit")

    first = ledger_seeded_history_fingerprint(events, turn_id="turn-2")
    assert spy.calls == 1

    second = ledger_seeded_history_fingerprint(events, turn_id="turn-2")
    assert second == first
    assert spy.calls == 1, "unchanged ledger must reuse the memoized fingerprint"


def test_seeded_history_fingerprint_memo_silent_on_current_turn_appends(tmp_path, monkeypatch):
    spy = _ProjectionSpy(monkeypatch)
    _seed_two_turn_history(tmp_path, session_id="session-memo-grow")
    events = load_conversation_events(tmp_path, "session-memo-grow")
    first = ledger_seeded_history_fingerprint(events, turn_id="turn-2")

    # Mid-turn journal growth (assistant/tool events of the current turn) is
    # excluded by the canonical replay, so the stamped value must not change
    # and the expensive replay must not run again.
    append_conversation_event(
        tmp_path, "session-memo-grow", "turn-2", EVENT_TOOL_RESULT,
        status="completed",
        payload={"content": "工具输出", "tool_call_id": "call-1"},
    )
    grown = load_conversation_events(tmp_path, "session-memo-grow")
    assert ledger_seeded_history_fingerprint(grown, turn_id="turn-2") == first
    assert spy.calls == 1, "current-turn-only growth must hit the prefix-extension memo"


def test_seeded_history_fingerprint_memo_invalidates_on_prior_turn_append(tmp_path, monkeypatch):
    spy = _ProjectionSpy(monkeypatch)
    _seed_two_turn_history(tmp_path, session_id="session-memo-other-turn")
    events = load_conversation_events(tmp_path, "session-memo-other-turn")
    first = ledger_seeded_history_fingerprint(events, turn_id="turn-2")

    append_conversation_event(
        tmp_path, "session-memo-other-turn", "turn-1", EVENT_ASSISTANT_MESSAGE,
        status="completed", payload={"content": "另一条历史回复"},
    )
    changed = load_conversation_events(tmp_path, "session-memo-other-turn")
    second = ledger_seeded_history_fingerprint(changed, turn_id="turn-2")
    assert second != first
    assert spy.calls == 2, "ledger change visible to the replay must recompute"


def test_seeded_history_fingerprint_memo_invalidates_on_branch_marker(tmp_path, monkeypatch):
    spy = _ProjectionSpy(monkeypatch)
    _seed_two_turn_history(tmp_path, session_id="session-memo-rebase")
    events = load_conversation_events(tmp_path, "session-memo-rebase")
    first = ledger_seeded_history_fingerprint(events, turn_id="turn-2")
    user_event = next(
        event for event in events
        if event.event_type == EVENT_USER_MESSAGE
    )

    # A branch marker belonging to the *current* turn still cuts the folded
    # active path, so the memo must not reuse the stale value. Cutting back to
    # the historical user message drops the turn-1 assistant reply from the
    # seeded-history window.
    append_conversation_event(
        tmp_path, "session-memo-rebase", "turn-2", EVENT_BRANCH_REBASE,
        status="recorded",
        payload={"operation": "edit", "fromEventId": user_event.event_id},
        parent_event_id=user_event.event_id,
    )
    rebased = load_conversation_events(tmp_path, "session-memo-rebase")
    second = ledger_seeded_history_fingerprint(rebased, turn_id="turn-2")
    assert spy.calls == 2, "branch markers must bypass the prefix-extension memo"
    assert second != first


def test_seeded_history_fingerprint_memo_identity_mismatch_falls_through(tmp_path, monkeypatch):
    spy = _ProjectionSpy(monkeypatch)
    _seed_two_turn_history(tmp_path, session_id="session-memo-identity")
    events = load_conversation_events(tmp_path, "session-memo-identity")
    ledger_seeded_history_fingerprint(events, turn_id="turn-2")
    assert spy.calls == 1

    tampered = list(events)
    tampered[-1] = dataclasses.replace(events[-1], event_id="tampered-id")
    ledger_seeded_history_fingerprint(tampered, turn_id="turn-2")
    assert spy.calls == 2, "same-length list with a different object must recompute"


def test_seeded_history_fingerprint_memo_is_turn_scoped(tmp_path):
    _seed_two_turn_history(tmp_path, session_id="session-memo-scope")
    events = load_conversation_events(tmp_path, "session-memo-scope")
    as_current = ledger_seeded_history_fingerprint(events, turn_id="turn-2")
    as_observer = ledger_seeded_history_fingerprint(events, turn_id="turn-9")
    assert as_current != as_observer, "exclusion window differs per turn id"


# ---------------------------------------------------------------------------
# 2. context assembler identity memo equivalence
# ---------------------------------------------------------------------------


def _assemble_snapshot(root, *, session_id: str, turn_id: str, events) -> dict:
    assembled = context_assembler.assemble_conversation_context(
        [],
        session_id=session_id,
        current_turn_id=turn_id,
        recent_message_limit=None,
        ledger_events=events,
    )
    return {
        "history": json.dumps(
            assembled.history_messages, ensure_ascii=False, sort_keys=True, default=str
        ),
        "eventIds": [event.event_id for event in assembled.events],
        "patch": json.dumps(
            assembled.to_composition_patch(), ensure_ascii=False, sort_keys=True, default=str
        ),
        "dynamicContextHash": assembled.dynamic_context_hash,
        "cacheablePrefixHash": assembled.cacheable_prefix_hash,
        "historyFingerprint": conversation_layer_fingerprint(assembled.history_messages),
    }


def test_assembly_memo_warm_and_recompute_are_byte_identical(tmp_path, monkeypatch):
    _seed_two_turn_history(tmp_path, session_id="session-memo-equiv")
    events = load_conversation_events(tmp_path, "session-memo-equiv")

    projection_calls = {"count": 0}
    original = context_assembler.conversation_model_messages_from_events

    def counting(events_arg, **kwargs):
        projection_calls["count"] += 1
        return original(events_arg, **kwargs)

    monkeypatch.setattr(
        context_assembler, "conversation_model_messages_from_events", counting
    )

    first = _assemble_snapshot(
        tmp_path, session_id="session-memo-equiv", turn_id="turn-2", events=events
    )
    assert projection_calls["count"] == 1

    # Same events list objects under the same (session,) scope: pure memo hit.
    second = _assemble_snapshot(
        tmp_path, session_id="session-memo-equiv", turn_id="turn-2", events=events
    )
    assert projection_calls["count"] == 1, "unchanged event objects must hit the identity memo"
    assert second == first

    # A different turn id legitimately opens a different exclusion window, so
    # its output differs by design; assert the shared (session,) scope still
    # yields exactly the forced-recompute result for that turn (no stale
    # cross-scope reuse).
    observer = _assemble_snapshot(
        tmp_path, session_id="session-memo-equiv", turn_id="turn-9", events=events
    )
    context_assembler._ASSEMBLY_MEMO._entries.clear()
    observer_reference = _assemble_snapshot(
        tmp_path, session_id="session-memo-equiv", turn_id="turn-9", events=events
    )
    assert observer == observer_reference

    # Forced recompute (empty memo) must reproduce the cached output exactly.
    context_assembler._ASSEMBLY_MEMO._entries.clear()
    recomputed = _assemble_snapshot(
        tmp_path, session_id="session-memo-equiv", turn_id="turn-2", events=events
    )
    assert projection_calls["count"] >= 2
    assert recomputed == first


def test_assembly_memo_cross_turn_equivalence(tmp_path):
    session_id = "session-memo-cross-turn"
    _seed_two_turn_history(tmp_path, session_id=session_id)
    turn2_events = load_conversation_events(tmp_path, session_id)
    turn2 = _assemble_snapshot(
        tmp_path, session_id=session_id, turn_id="turn-2", events=turn2_events
    )

    # Complete turn-2 and open turn-3, then reload (new list objects for the
    # grown tail; the parsed prefix objects are reused, as in production).
    append_conversation_event(
        tmp_path, session_id, "turn-2", EVENT_ASSISTANT_MESSAGE,
        status="completed", payload={"content": "当前回复"},
    )
    append_conversation_event(
        tmp_path, session_id, "turn-3", EVENT_USER_MESSAGE,
        status="recorded", payload={"content": "第三轮请求"},
    )
    turn3_events = load_conversation_events(tmp_path, session_id)
    assert turn3_events != turn2_events or len(turn3_events) > len(turn2_events)

    turn3_cached = _assemble_snapshot(
        tmp_path, session_id=session_id, turn_id="turn-3", events=turn3_events
    )
    assert turn3_cached != turn2, "scenario must actually advance the history"

    context_assembler._ASSEMBLY_MEMO._entries.clear()
    turn3_recomputed = _assemble_snapshot(
        tmp_path, session_id=session_id, turn_id="turn-3", events=turn3_events
    )
    assert turn3_recomputed == turn3_cached, (
        "second-turn assembly from a warm memo must be byte-identical to a forced recompute"
    )


def test_assembly_memo_entries_are_bounded():
    memo = context_assembler._IdentityListMemo(max_entries=8)
    sentinel = object()
    items = [sentinel]
    for index in range(32):
        memo.store((f"scope-{index}",), items, index)
    assert len(memo._entries) <= 8
    assert memo.lookup(("scope-31",), items) == 31
    assert memo.lookup(("scope-0",), items) is context_assembler._MISS


# ---------------------------------------------------------------------------
# 3. message digest telemetry gating
# ---------------------------------------------------------------------------


class _DummyContext:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _DummyUI:
    def thinking(self, _label):
        return _DummyContext()


class _DummyLLM:
    profile_id = "primary"

    def effective_route_identity(self):
        return ("primary",)

    def effective_route_id(self):
        return "primary-route"

    def project_outcome_message(self, outcome, **_kwargs):
        from langchain_core.messages import AIMessage

        return AIMessage(content=outcome.final_text)


def _digest_hooks(scene_events):
    from agent import TurnStopRequested
    from core.llm.types import CanonicalItemIdentity, TurnOutcome
    from core.orchestration.turn_llm_adapter import AgentLlmTurnHooks

    identity = CanonicalItemIdentity(
        session_id="session-batch5",
        turn_id="turn-batch5",
        invocation_id="invocation-batch5",
        iteration=0,
        item_id="answer-batch5",
    )

    def fake_invoke(_client, messages, **_kwargs):
        return TurnOutcome.final_answer(identity=identity, text="ok")

    return AgentLlmTurnHooks(
        get_ui=lambda: _DummyUI(),
        llm_cancel_context=lambda _checker: _DummyContext(),
        raise_if_stop=lambda: None,
        current_stop_reason=lambda: "",
        get_llm_for_mode=lambda **_kwargs: _DummyLLM(),
        should_stream=lambda *_args, **_kwargs: False,
        build_invocation_context=lambda **_kwargs: SimpleNamespace(
            to_metadata=lambda client=None: {"invocationId": "inv-1"}
        ),
        invoke_outcome=fake_invoke,
        run_streaming_outcome=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("non-stream path must not stream")
        ),
        canonicalize=lambda outcome: outcome,
        plan_recovery=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("success path must not recover")
        ),
        record_scene_event=lambda phase, event, **kwargs: scene_events.append(
            (phase, event, kwargs)
        ),
        record_route_success=lambda **_kwargs: None,
        request_compression=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("success path must not compress")
        ),
        debug_logger=SimpleNamespace(error=lambda *_args, **_kwargs: None),
        error_logger=SimpleNamespace(log_error=lambda *_args, **_kwargs: None),
        config=None,
        force_disable_tools=False,
        stop_error_cls=TurnStopRequested,
    )


def test_message_digest_telemetry_off_by_default(monkeypatch):
    monkeypatch.setattr(turn_llm_adapter, "MESSAGE_DIGEST_TELEMETRY_ENABLED", False)
    digest_calls = {"count": 0}
    original = turn_llm_adapter._message_digest_entries

    def counting(messages):
        digest_calls["count"] += 1
        return original(messages)

    monkeypatch.setattr(turn_llm_adapter, "_message_digest_entries", counting)

    scene_events: list = []
    result = turn_llm_adapter.invoke_agent_llm_turn(
        messages=[{"role": "system", "content": "prefix"}, {"role": "user", "content": "hi"}],
        hooks=_digest_hooks(scene_events),
    )
    assert not [item for item in scene_events if item[1] == "llm_request_messages_digest"]
    assert digest_calls["count"] == 0, "disabled telemetry must not hash message bodies"
    assert isinstance(result.invoke_prep_ms, float)
    assert result.invoke_prep_ms >= 0


def test_message_digest_telemetry_keeps_full_fields_when_enabled(monkeypatch):
    monkeypatch.setattr(turn_llm_adapter, "MESSAGE_DIGEST_TELEMETRY_ENABLED", True)
    scene_events: list = []
    turn_llm_adapter.invoke_agent_llm_turn(
        messages=[{"role": "system", "content": "prefix"}, {"role": "user", "content": "hi"}],
        hooks=_digest_hooks(scene_events),
    )
    digest_events = [item for item in scene_events if item[1] == "llm_request_messages_digest"]
    assert len(digest_events) == 1
    phase, _event, kwargs = digest_events[0]
    assert phase == "llm_route"
    assert kwargs.get("level") == "debug"
    digests = kwargs["fields"]["messageDigests"]
    assert [entry["role"] for entry in digests] == ["system", "user"]
    for entry in digests:
        assert set(entry) == {"index", "role", "sha256", "chars"}
        assert len(entry["sha256"]) == 16 and entry["chars"] > 0


# ---------------------------------------------------------------------------
# 4. disk-coherent ledger read cache
# ---------------------------------------------------------------------------


def test_load_conversation_events_cached_reuses_objects_until_file_changes(tmp_path, monkeypatch):
    from core.chat import conversation_ledger as ledger_module

    _seed_two_turn_history(tmp_path, session_id="session-disk-cache")
    reads = {"count": 0}
    original = ledger_module.load_conversation_events

    def counting(root, session_id):
        reads["count"] += 1
        return original(root, session_id)

    monkeypatch.setattr(ledger_module, "load_conversation_events", counting)

    first = load_conversation_events_cached(tmp_path, "session-disk-cache")
    assert reads["count"] == 1
    second = load_conversation_events_cached(tmp_path, "session-disk-cache")
    assert reads["count"] == 1, "unchanged journal file must not re-read"
    assert [event.event_id for event in second] == [event.event_id for event in first]
    assert all(a is b for a, b in zip(first, second))

    append_conversation_event(
        tmp_path, "session-disk-cache", "turn-2", EVENT_ASSISTANT_MESSAGE,
        status="completed", payload={"content": "当前回复"},
    )
    third = load_conversation_events_cached(tmp_path, "session-disk-cache")
    assert reads["count"] == 2, "appended journal must reload"
    assert len(third) == len(first) + 1
    assert [event.event_id for event in third[: len(first)]] == [
        event.event_id for event in first
    ]


def test_load_conversation_events_cached_missing_file(tmp_path):
    assert load_conversation_events_cached(tmp_path, "session-no-such-file") == []


# ---------------------------------------------------------------------------
# 5. send-path timing anchors
# ---------------------------------------------------------------------------


def test_turn_send_timing_anchor_helper():
    runtime = AgentRuntime.__new__(AgentRuntime)
    runtime._record_turn_send_timing_anchor("todoRestoreMs", 4)
    runtime._record_turn_send_timing_anchor("reconcileMs", 0)
    runtime._record_turn_send_timing_anchor("invokePrepMs", -3)
    assert runtime._turn_send_timing_anchors == {
        "todoRestoreMs": 4,
        "reconcileMs": 0,
        "invokePrepMs": 0,
    }
