"""Async hypothesis-first command window tests (SCI-049).

Covers the accepted-and-poll contract for the three long V2 command paths:

- ``submit_v2_command_async`` returns an ``accepted`` envelope with a
  ``commandAttemptId`` fast while the real command body runs on the
  background worker inside the per-question scope lock;
- duplicate submits of the same idempotency key are deduplicated against the
  attempt ledger (same acceptance while running, stored response after
  success, a fresh attempt after failure);
- a second distinct command for the same question is rejected with the stable
  ``command_attempt_in_progress`` conflict while one attempt is live;
- startup recovery fences attempts orphaned by a dead process and never
  touches same-boot running leases;
- short commands are not intercepted (the route keeps its sync fallback).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from core.web.services import team_service
from core.web.services.team_workflow.research_runtime import (
    hypothesis_command_attempts as attempts,
)
from core.web.services.team_workflow.research_runtime import (
    hypothesis_first_chain as chain,
)
from core.web.services.team_workflow.research_runtime import hypothesis_first_state_v2


@pytest.fixture(autouse=True)
def _isolated_attempt_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Chain storage resolves through the workspace home when the project root
    # has no project identity, so the data home env (not PROJECT_ROOT) is the
    # authoritative isolation seam here — same as _use_tmp_project_root.
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(team_service, "assert_team_exists", lambda value: value)
    attempts.reset_for_tests()
    yield tmp_path
    attempts.reset_for_tests()


_TEAM_ID = "team-1"
_QUESTION_ID = "SCI-001"


def _selection_request(*, key: str = "hf2:record-selection:k1") -> dict[str, Any]:
    return {
        "actionId": "record-selection",
        "idempotencyKey": key,
        "expectedStateVersion": "hf2-action:pending:pending",
        "payload": {"questionId": _QUESTION_ID},
        "input": {"candidateIds": ["hyp-a", "hyp-b"]},
    }


def _patch_selection_offer(monkeypatch: pytest.MonkeyPatch) -> None:
    snapshot = {
        "stateVersion": "hf2-action:pending:pending",
        "allowedActions": [
            {
                "kind": "command",
                "actionId": "record-selection",
                "command": "record_selection",
                "payload": {"questionId": _QUESTION_ID},
                "enabled": True,
                "idempotencyKey": "hf2:record-selection:k1",
            }
        ],
    }
    monkeypatch.setattr(
        hypothesis_first_state_v2,
        "project_hypothesis_first_state_v2",
        lambda *_args, **_kwargs: snapshot,
    )


class _BlockingImpl:
    """Fake command body: runs under the scope lock like the real impl."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.started = threading.Event()
        self.release = threading.Event()
        self._lock = threading.Lock()
        self._fail_first = False

    def fail_first_call(self) -> None:
        self._fail_first = True

    def __call__(self, team_id: str, request: Mapping, **kwargs: Any) -> dict[str, Any]:
        with self._lock:
            call_index = len(self.calls)
            self.calls.append({"team_id": team_id, "request": dict(request)})
        # The real impl acquires the per-question scope lock; the fake must
        # prove the worker executes outside the gate's lock window.
        with chain.hypothesis_first_scope_lock(team_id, _QUESTION_ID):
            self.started.set()
            assert self.release.wait(timeout=10), "test release event never set"
            if self._fail_first and call_index == 0:
                raise chain.HypothesisFirstChainError("模拟执行失败")
            return {
                "schemaVersion": 2,
                "teamId": team_id,
                "command": "record_selection",
                "result": {"status": "created", "call": call_index},
            }


def _wait_for_terminal(attempt_id: str, *, timeout_s: float = 10.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        status = attempts.get_attempt(_TEAM_ID, attempt_id) or {}
        if str(status.get("status") or "") in attempts._TERMINAL_STATUSES:
            return status
        time.sleep(0.01)
    raise AssertionError(f"attempt {attempt_id} never reached a terminal state")


# ---------------------------------------------------------------------------
# Inference
# ---------------------------------------------------------------------------


def test_infer_async_command_covers_projection_action_id_prefixes() -> None:
    assert attempts.infer_async_command("record-selection") == "record_selection"
    assert (
        attempts.infer_async_command("reselect-after-rejection:hsel-1")
        == "record_selection"
    )
    assert attempts.infer_async_command("open-generation") == "open_generation"
    assert (
        attempts.infer_async_command("open-stage-one-generation")
        == "open_generation"
    )
    assert attempts.infer_async_command("retry-generation") == "retry_generation"
    assert (
        attempts.infer_async_command("approve-summary:hyp-a") == "approve_summary"
    )
    assert (
        attempts.infer_async_command("approve-generation-summary:meeting-1")
        == "approve_summary"
    )
    # Short commands keep the synchronous route fallback.
    assert attempts.infer_async_command("stop-discussion:meeting-1") == ""
    assert attempts.infer_async_command("resume-discussion:meeting-1") == ""
    assert attempts.infer_async_command("retry-formal-node:run-1:node") == ""
    assert attempts.infer_async_command("record-selection", "stop_discussion") == ""


# ---------------------------------------------------------------------------
# Accept -> poll -> terminal contract
# ---------------------------------------------------------------------------


def test_submit_async_accepts_fast_and_completes_on_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_selection_offer(monkeypatch)
    impl = _BlockingImpl()
    monkeypatch.setattr(chain, "_execute_v2_command_impl", impl)

    started_at = time.monotonic()
    accepted = chain.submit_v2_command_async(_TEAM_ID, _selection_request())
    accepted_ms = (time.monotonic() - started_at) * 1000

    assert accepted is not None
    assert accepted["status"] == "accepted"
    assert accepted["commandAttemptId"]
    assert accepted["command"] == "record_selection"
    assert accepted["idempotencyKey"] == "hf2:record-selection:k1"
    # The HTTP window must not wait for the command body.
    assert accepted_ms < 5_000

    attempt_id = str(accepted["commandAttemptId"])
    assert impl.started.wait(timeout=10), "worker never started the command body"
    running = attempts.get_attempt(_TEAM_ID, attempt_id)
    assert running is not None
    assert running["status"] == "running"

    impl.release.set()
    terminal = _wait_for_terminal(attempt_id)
    assert terminal["status"] == "succeeded", terminal.get("error")
    assert terminal["result"]["result"] == {"status": "created", "call": 0}
    assert len(impl.calls) == 1


def test_submit_async_duplicate_key_while_running_replays_same_acceptance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_selection_offer(monkeypatch)
    impl = _BlockingImpl()
    monkeypatch.setattr(chain, "_execute_v2_command_impl", impl)

    first = chain.submit_v2_command_async(_TEAM_ID, _selection_request())
    assert first is not None and first["status"] == "accepted"
    assert impl.started.wait(timeout=10)

    duplicate = chain.submit_v2_command_async(_TEAM_ID, _selection_request())
    assert duplicate is not None
    assert duplicate["status"] == "accepted"
    assert (
        duplicate["commandAttemptId"] == first["commandAttemptId"]
    ), "a duplicate key must never mint a second live attempt"

    impl.release.set()
    _wait_for_terminal(str(first["commandAttemptId"]))
    assert len(impl.calls) == 1


def test_submit_async_after_success_replays_stored_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_selection_offer(monkeypatch)
    impl = _BlockingImpl()
    monkeypatch.setattr(chain, "_execute_v2_command_impl", impl)

    first = chain.submit_v2_command_async(_TEAM_ID, _selection_request())
    assert first is not None
    impl.started.wait(timeout=10)
    impl.release.set()
    _wait_for_terminal(str(first["commandAttemptId"]))

    replay = chain.submit_v2_command_async(_TEAM_ID, _selection_request())
    assert replay is not None
    # The stored terminal response is replayed verbatim, not an acceptance.
    assert replay.get("status") != "accepted"
    assert replay["result"] == {"status": "created", "call": 0}
    assert "commandAttemptId" not in replay
    assert len(impl.calls) == 1


def test_submit_async_after_failure_mints_fresh_retry_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_selection_offer(monkeypatch)
    impl = _BlockingImpl()
    impl.fail_first_call()
    monkeypatch.setattr(chain, "_execute_v2_command_impl", impl)

    first = chain.submit_v2_command_async(_TEAM_ID, _selection_request())
    assert first is not None
    impl.started.wait(timeout=10)
    impl.release.set()
    failed = _wait_for_terminal(str(first["commandAttemptId"]))
    assert failed["status"] == "failed"
    assert failed["error"]["code"] == "HypothesisFirstChainError"

    retry = chain.submit_v2_command_async(_TEAM_ID, _selection_request())
    assert retry is not None
    assert retry["status"] == "accepted"
    assert retry["commandAttemptId"] != first["commandAttemptId"], (
        "a failed attempt must not poison the operator's retry with the same key"
    )
    impl.started.wait(timeout=10)
    impl.release.set()
    succeeded = _wait_for_terminal(str(retry["commandAttemptId"]))
    assert succeeded["status"] == "succeeded"
    assert len(impl.calls) == 2


def test_submit_async_rejects_second_command_while_one_is_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_selection_offer(monkeypatch)
    impl = _BlockingImpl()
    monkeypatch.setattr(chain, "_execute_v2_command_impl", impl)

    first = chain.submit_v2_command_async(_TEAM_ID, _selection_request())
    assert first is not None
    assert impl.started.wait(timeout=10)

    other = _selection_request(key="hf2:record-selection:k2")
    other["actionId"] = "reselect-after-rejection:hsel-1"
    with pytest.raises(chain.CommandAttemptInProgressError) as excinfo:
        chain.submit_v2_command_async(_TEAM_ID, other)
    assert excinfo.value.code == "command_attempt_in_progress"

    impl.release.set()
    _wait_for_terminal(str(first["commandAttemptId"]))


# ---------------------------------------------------------------------------
# Crash recovery
# ---------------------------------------------------------------------------


def test_recover_fences_foreign_boot_attempts_and_keeps_same_boot_lease() -> None:
    identity = attempts._attempt_identity(
        team_id=_TEAM_ID,
        question_id=_QUESTION_ID,
        action_id="record-selection",
        idempotency_key="hf2:record-selection:k1",
        workflow_run_id="",
    )
    queued = attempts.register_attempt(
        identity, command="record_selection", accepted_state_version="hf2-action:x"
    )

    # Same-boot running lease is alive: the sweep must not touch it.
    running = attempts.mark_attempt_running(queued)
    summary = attempts.recover_interrupted_command_attempts()
    assert summary["fenced"] == 0
    assert (
        attempts.get_attempt(_TEAM_ID, str(running["attemptId"])) or {}
    ).get("status") == "running"

    # A foreign boot id (process died) proves the attempt is orphaned.
    attempts.reset_for_tests()
    summary = attempts.recover_interrupted_command_attempts()
    assert summary["fenced"] == 1
    fenced = attempts.get_attempt(_TEAM_ID, str(running["attemptId"]))
    assert fenced is not None
    assert fenced["status"] == "failed"
    assert fenced["error"]["code"] == "attempt_interrupted"

    # Idempotent: a second sweep finds nothing active.
    again = attempts.recover_interrupted_command_attempts()
    assert again["fenced"] == 0


def test_get_attempt_unknown_id_returns_none() -> None:
    assert attempts.get_attempt(_TEAM_ID, "hf2-attempt-missing") is None
    with pytest.raises(chain.HypothesisFirstChainNotFoundError):
        chain.get_v2_command_attempt(_TEAM_ID, "hf2-attempt-missing")


# ---------------------------------------------------------------------------
# Sync fallback
# ---------------------------------------------------------------------------


def test_submit_async_returns_none_for_short_commands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = {
        "actionId": "stop-discussion:meeting-1",
        "idempotencyKey": "hf2:stop-discussion:meeting-1:k1",
        "expectedStateVersion": "hf2-action:pending:pending",
        "payload": {"meetingRoundId": "meeting-1"},
    }
    assert chain.submit_v2_command_async(_TEAM_ID, request) is None
