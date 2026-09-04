"""Review prompt-cache keepalive probe tests.

Covers the DashScope explicit-cache keepalive for active meetings:

* scheduling guards: disabled via env, one probe per (meeting, closed round),
  fire-time skip for closed meetings;
* global probe concurrency is 1 (a busy slot skips instead of queueing);
* the probe rides the review LLM channel with the marked shared prefix and a
  minimal output budget, and failures stay quiet bounded scene events.

No real model or network is involved.
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any

import pytest

from core.web.services import runtime_scene_service
from core.web.services.team_workflow import meeting_rounds, review_cache_keepalive

_PROBE_MARKER = "cache_control"


@pytest.fixture(autouse=True)
def _reset_keepalive_state():
    review_cache_keepalive.reset_meeting_cache_keepalive_for_tests()
    yield
    review_cache_keepalive.reset_meeting_cache_keepalive_for_tests()


@pytest.fixture()
def keepalive_events(monkeypatch):
    events: list[dict[str, Any]] = []

    def _capture(*args, **kwargs):
        events.append({"args": args, "kwargs": kwargs})
        return {"accepted": True}

    monkeypatch.setattr(
        runtime_scene_service,
        "record_runtime_scene_event_quietly",
        _capture,
    )
    return events


def _resolved_llm(**overrides):
    resolved = {
        "client": object(),
        "profileId": "primary",
        "modelId": "qwen3.8-flash",
        "providerId": "dashscope_main",
        "agentId": "agent-evaluator",
        "modelRef": "dashscope_main/qwen3.8-flash",
    }
    resolved.update(overrides)
    return resolved


def _open_meeting_round(monkeypatch, *, status: str = "open") -> None:
    monkeypatch.setattr(
        meeting_rounds,
        "get_meeting_round",
        lambda team_id, meeting_round_id: {"meetingRound": {"status": status}},
    )


def _probe_outcomes(events):
    return [
        event
        for event in events
        if event["args"][2].startswith("review_cache_keepalive.probe.")
    ]


def _wait_for_condition(condition, *, timeout_s: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.02)
    return False


def test_disabled_env_never_schedules_or_fires(keepalive_events, monkeypatch):
    monkeypatch.setenv("VIBELUTION_MEETING_CACHE_KEEPALIVE_DELAY_MS", "0")

    result = review_cache_keepalive.schedule_meeting_cache_keepalive(
        "team-1",
        "meeting-1",
        dedupe_key="round-1",
    )

    assert result["status"] == "disabled"
    assert keepalive_events == []


def test_duplicate_round_key_schedules_only_once(monkeypatch, keepalive_events):
    monkeypatch.setenv("VIBELUTION_MEETING_CACHE_KEEPALIVE_DELAY_MS", "60000")

    first = review_cache_keepalive.schedule_meeting_cache_keepalive(
        "team-1",
        "meeting-1",
        dedupe_key="round-1",
        system_prompt="shared-prefix",
    )
    second = review_cache_keepalive.schedule_meeting_cache_keepalive(
        "team-1",
        "meeting-1",
        dedupe_key="round-1",
        system_prompt="shared-prefix",
    )

    assert first["status"] == "scheduled"
    assert second["status"] == "duplicate"
    scheduled = [
        event
        for event in keepalive_events
        if event["args"][2] == "review_cache_keepalive.scheduled"
    ]
    assert len(scheduled) == 1


def test_probe_reuses_marked_prefix_with_minimal_budget(monkeypatch, keepalive_events):
    monkeypatch.setenv("VIBELUTION_MEETING_CACHE_KEEPALIVE_DELAY_MS", "10")
    _open_meeting_round(monkeypatch)
    calls: list[dict[str, Any]] = []

    def fake_invoke_llm(client, messages, tools=None, context=None, **kwargs):
        calls.append(
            {
                "client": client,
                "messages": messages,
                "context": context,
                "metadata": dict(kwargs.get("metadata") or {}),
            }
        )
        return SimpleNamespace(content=".", response_metadata={})

    monkeypatch.setattr(review_cache_keepalive, "invoke_llm", fake_invoke_llm)
    resolved = _resolved_llm()

    result = review_cache_keepalive.schedule_meeting_cache_keepalive(
        "team-1",
        "meeting-1",
        dedupe_key="round-1",
        system_prompt="shared-review-prefix",
        resolve=lambda: resolved,
    )
    assert result["status"] == "scheduled"
    assert _wait_for_condition(lambda: bool(calls))

    call = calls[0]
    system_message = call["messages"][0]
    assert system_message["role"] == "system"
    assert system_message["content"][0]["text"] == "shared-review-prefix"
    assert system_message["content"][0][_PROBE_MARKER] == {"type": "ephemeral"}
    assert call["messages"][1] == {"role": "user", "content": "."}
    assert str(getattr(call["context"], "prompt_purpose", "")) == (
        "review_cache_keepalive"
    )
    from core.llm.client import MAX_OUTPUT_TOKENS_OVERRIDE_METADATA_KEY

    assert call["metadata"][MAX_OUTPUT_TOKENS_OVERRIDE_METADATA_KEY] == (
        review_cache_keepalive.probe_max_output_tokens()
    )
    # Ledger attribution rides the invocation context metadata (invoke_llm
    # merges it into the effective client metadata).
    assert getattr(call["context"], "metadata", {}).get("teamId") == "team-1"
    succeeded = [
        event
        for event in _probe_outcomes(keepalive_events)
        if event["args"][2] == "review_cache_keepalive.probe.succeeded"
    ]
    assert len(succeeded) == 1
    assert succeeded[0]["kwargs"]["fields"]["modelRef"] == (
        "dashscope_main/qwen3.8-flash"
    )


def test_probe_skipped_when_meeting_already_closed(monkeypatch, keepalive_events):
    monkeypatch.setattr(
        meeting_rounds,
        "get_meeting_round",
        lambda team_id, meeting_round_id: {
            "meetingRound": {"status": "closed"}
        },
    )
    probe_calls: list[dict[str, Any]] = []

    def fake_invoke_llm(client, messages, tools=None, context=None, **kwargs):
        probe_calls.append({"messages": messages})
        return SimpleNamespace(content=".", response_metadata={})

    monkeypatch.setattr(review_cache_keepalive, "invoke_llm", fake_invoke_llm)

    review_cache_keepalive._run_probe(
        "team-1",
        "meeting-1",
        system_prompt="shared-review-prefix",
        resolve=lambda: _resolved_llm(),
    )

    assert probe_calls == []
    skipped = [
        event
        for event in _probe_outcomes(keepalive_events)
        if event["args"][2] == "review_cache_keepalive.probe.skipped"
    ]
    assert len(skipped) == 1
    assert (
        skipped[0]["kwargs"]["fields"]["reason"]
        == "meeting_closed_or_unreadable"
    )


def test_probe_skipped_while_another_probe_holds_the_global_slot(
    monkeypatch, keepalive_events
):
    _open_meeting_round(monkeypatch)
    review_cache_keepalive._probe_slot.acquire(blocking=False)
    probe_calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        review_cache_keepalive,
        "invoke_llm",
        lambda *args, **kwargs: probe_calls.append(args),
    )

    review_cache_keepalive._run_probe(
        "team-1",
        "meeting-1",
        system_prompt="shared-review-prefix",
        resolve=lambda: _resolved_llm(),
    )

    assert probe_calls == []
    skipped = [
        event
        for event in _probe_outcomes(keepalive_events)
        if event["args"][2] == "review_cache_keepalive.probe.skipped"
    ]
    assert len(skipped) == 1
    assert skipped[0]["kwargs"]["fields"]["reason"] == "probe_busy"


def test_probe_failure_is_quiet_bounded_scene_event(monkeypatch, keepalive_events):
    from core.web.services.team_workflow import llm_review_runners

    _open_meeting_round(monkeypatch)
    probe_attempts: list[int] = []

    def fake_invoke_llm(client, messages, tools=None, context=None, **kwargs):
        probe_attempts.append(1)
        raise RuntimeError("provider exploded")

    monkeypatch.setattr(review_cache_keepalive, "invoke_llm", fake_invoke_llm)
    monkeypatch.setattr(
        llm_review_runners,
        "resolve_review_llm",
        lambda: _resolved_llm(),
    )

    review_cache_keepalive._run_probe(
        "team-1",
        "meeting-1",
        system_prompt="shared-review-prefix",
        resolve=lambda: _resolved_llm(),
    )
    # The global slot must be released again: a later probe can acquire it.
    assert review_cache_keepalive._probe_slot.acquire(blocking=False)
    review_cache_keepalive._probe_slot.release()

    assert len(probe_attempts) == 1
    failed = [
        event
        for event in _probe_outcomes(keepalive_events)
        if event["args"][2] == "review_cache_keepalive.probe.failed"
    ]
    assert len(failed) == 1
    assert failed[0]["kwargs"]["fields"]["errorType"] == "RuntimeError"
    assert failed[0]["kwargs"]["level"] == "warning"


def test_probe_without_resolvable_review_llm_fails_quietly(
    monkeypatch, keepalive_events
):
    from core.web.services.team_workflow import llm_review_runners

    _open_meeting_round(monkeypatch)
    monkeypatch.setattr(llm_review_runners, "resolve_review_llm", lambda: None)
    probe_calls: list[Any] = []
    monkeypatch.setattr(
        review_cache_keepalive,
        "invoke_llm",
        lambda *args, **kwargs: probe_calls.append(args),
    )

    review_cache_keepalive._run_probe(
        "team-1",
        "meeting-1",
        system_prompt="shared-review-prefix",
        resolve=None,
    )

    assert probe_calls == []
    failed = [
        event
        for event in _probe_outcomes(keepalive_events)
        if event["args"][2] == "review_cache_keepalive.probe.failed"
    ]
    assert len(failed) == 1
    assert failed[0]["kwargs"]["fields"]["reason"] == "review_llm_unavailable"


def test_default_probe_uses_the_shared_reflection_prefix(monkeypatch):
    from core.web.services.team_workflow.llm_review_runners import (
        _REFLECTION_SYSTEM_PROMPT,
    )

    captured: dict[str, Any] = {}

    def fake_timer(delay, fn, args=None, kwargs=None):
        captured["delay"] = delay
        captured["kwargs"] = dict(kwargs or {})

        class _FakeTimer:
            daemon = False

            def start(self):
                captured["started"] = True

            def cancel(self):
                captured["cancelled"] = True

        return _FakeTimer()

    monkeypatch.setenv("VIBELUTION_MEETING_CACHE_KEEPALIVE_DELAY_MS", "240000")
    monkeypatch.setattr(review_cache_keepalive.threading, "Timer", fake_timer)

    result = review_cache_keepalive.schedule_meeting_cache_keepalive(
        "team-1",
        "meeting-1",
        dedupe_key="round-1",
    )

    assert result["status"] == "scheduled"
    assert captured["delay"] == 240.0
    assert captured["kwargs"]["system_prompt"] == _REFLECTION_SYSTEM_PROMPT
    assert captured["started"] is True


def test_probe_timer_never_blocks_interpreter_exit(monkeypatch, keepalive_events):
    monkeypatch.setenv("VIBELUTION_MEETING_CACHE_KEEPALIVE_DELAY_MS", "3600000")

    result = review_cache_keepalive.schedule_meeting_cache_keepalive(
        "team-1",
        "meeting-1",
        dedupe_key="round-1",
        system_prompt="shared-prefix",
        resolve=lambda: _resolved_llm(),
    )

    assert result["status"] == "scheduled"
    with review_cache_keepalive._pending_timers_lock:
        assert len(review_cache_keepalive._pending_timers) == 1
        assert review_cache_keepalive._pending_timers[0].daemon is True


def test_reset_cancels_pending_timers(monkeypatch, keepalive_events):
    monkeypatch.setenv("VIBELUTION_MEETING_CACHE_KEEPALIVE_DELAY_MS", "3600000")

    review_cache_keepalive.schedule_meeting_cache_keepalive(
        "team-1",
        "meeting-1",
        dedupe_key="round-1",
        system_prompt="shared-prefix",
        resolve=lambda: _resolved_llm(),
    )
    review_cache_keepalive.reset_meeting_cache_keepalive_for_tests()

    with review_cache_keepalive._pending_timers_lock:
        assert review_cache_keepalive._pending_timers == []
    with review_cache_keepalive._scheduled_keys_lock:
        assert review_cache_keepalive._scheduled_keys == set()
