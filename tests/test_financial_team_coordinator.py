from __future__ import annotations

import copy
import threading
import time
from typing import Any

import pytest

from core.web.routes.financial_team import FinancialTeamRunResponse
from core.web.services import session_service
from core.web.services.financial_team.coordinator import (
    FinancialTeamCoordinator,
    coordination_task_id,
)
from core.web.services.runtime_task_registry import RuntimeTaskStore


def _run() -> dict[str, Any]:
    roles = ("market", "fundamental", "news", "bull", "bear")
    return {
        "schemaVersion": 2,
        "runId": "run-1",
        "assistantAgentId": "assistant-1",
        "teamId": "team-1",
        "assistantConfigRevision": 7,
        "symbol": "600000",
        "periodDays": 30,
        "researchDate": "2026-10-05",
        "depth": "standard",
        "createdAt": "2026-10-05T00:00:00+00:00",
        "stage": "research",
        "analysts": {
            role: {
                "agentId": f"agent-{role}",
                "sessionId": f"session-{role}",
                "clientSubmissionId": f"submission-{role}",
                "turnId": "",
            }
            for role in roles
        },
        "synthesis": {
            "agentId": "assistant-1",
            "sessionId": "session-synthesis",
            "clientSubmissionId": "submission-synthesis",
            "turnId": "",
        },
    }


class FakeNativeFinancialService:
    """Small native Session stand-in: only exact session/turn finals count."""

    def __init__(self) -> None:
        self.run = _run()
        self.final_answers: dict[tuple[str, str], str] = {}
        self.debate_calls = 0
        self.synthesis_calls = 0
        self.debate_error: Exception | None = None
        self.synthesis_error: Exception | None = None
        self.submission_state = "reserved"
        self.terminal_snapshots: dict[tuple[str, str], dict[str, Any]] = {}
        self.binding_error: Exception | None = None

    def accept_primary_turns(self) -> None:
        for role in ("market", "fundamental", "news"):
            self.run["analysts"][role]["turnId"] = f"turn-{role}"

    def load_run(self, assistant_agent_id: str, run_id: str) -> dict[str, Any]:
        assert assistant_agent_id == self.run["assistantAgentId"]
        assert run_id == self.run["runId"]
        return copy.deepcopy(self.run)

    def update_status(
        self,
        assistant_agent_id: str,
        run_id: str,
        status: str,
        error: str = "",
    ) -> dict[str, Any]:
        assert assistant_agent_id == self.run["assistantAgentId"]
        assert run_id == self.run["runId"]
        current = self.run.get("coordinationStatus")
        if current in {"blocked", "completed"}:
            return copy.deepcopy(self.run)
        self.run["coordinationStatus"] = status
        self.run["coordinationError"] = error[:500]
        return copy.deepcopy(self.run)

    def final_answer_for_turn(self, session_id: str, turn_id: str) -> str:
        return self.final_answers.get((session_id, turn_id), "")

    def completion_snapshot_for_turn(
        self, session_id: str, turn_id: str
    ) -> dict[str, Any]:
        return copy.deepcopy(
            self.terminal_snapshots.get(
                (session_id, turn_id),
                {
                    "sessionId": session_id,
                    "turnId": turn_id,
                    "terminal": False,
                    "terminalStatus": "",
                },
            )
        )

    def validate_current_bindings(self, assistant_agent_id: str, run_id: str) -> None:
        assert assistant_agent_id == self.run["assistantAgentId"]
        assert run_id == self.run["runId"]
        if self.binding_error is not None:
            raise self.binding_error

    def submit_debate(self, assistant_agent_id: str, run_id: str) -> dict[str, Any]:
        assert assistant_agent_id == self.run["assistantAgentId"]
        assert run_id == self.run["runId"]
        self.debate_calls += 1
        self.submission_state = "submitting"
        if self.debate_error is not None:
            raise self.debate_error
        for role in ("bull", "bear"):
            turn_id = f"turn-{role}"
            self.run["analysts"][role]["turnId"] = turn_id
        self.submission_state = "accepted"
        return copy.deepcopy(self.run)

    def submit_synthesis(self, assistant_agent_id: str, run_id: str) -> dict[str, Any]:
        assert assistant_agent_id == self.run["assistantAgentId"]
        assert run_id == self.run["runId"]
        self.synthesis_calls += 1
        if self.synthesis_error is not None:
            raise self.synthesis_error
        self.run["synthesis"]["turnId"] = "turn-synthesis"
        return copy.deepcopy(self.run)


def _coordinator(tmp_path, native: FakeNativeFinancialService, **kwargs: Any):
    store = RuntimeTaskStore(
        tmp_path / "runtime_tasks", branch_generation_reader=lambda _session_id: 0
    )
    coordinator = FinancialTeamCoordinator(
        store=store,
        run_loader=native.load_run,
        status_writer=native.update_status,
        final_answer_for_turn=native.final_answer_for_turn,
        completion_snapshot=native.completion_snapshot_for_turn,
        binding_validator=native.validate_current_bindings,
        submit_debate=native.submit_debate,
        submit_synthesis=native.submit_synthesis,
        poll_interval_seconds=0.01,
        **kwargs,
    )
    return coordinator, store


def _accept_all_analyst_finals(native: FakeNativeFinancialService) -> None:
    native.accept_primary_turns()
    for role in ("bull", "bear"):
        native.run["analysts"][role]["turnId"] = f"turn-{role}"
    for role in ("market", "fundamental", "news", "bull", "bear"):
        ref = native.run["analysts"][role]
        native.final_answers[(ref["sessionId"], ref["turnId"])] = f"final-{role}"


def test_primary_coordination_is_registered_only_after_all_primary_turns_are_accepted(
    tmp_path,
):
    native = FakeNativeFinancialService()
    coordinator, store = _coordinator(tmp_path, native)

    assert coordinator.register_after_primary_acceptance("assistant-1", "run-1") is False
    assert store.active_task_ids() == []

    native.accept_primary_turns()
    assert coordinator.register_after_primary_acceptance("assistant-1", "run-1") is True
    assert len(store.active_task_ids()) == 1
    assert native.run["coordinationStatus"] == "waiting"


def test_native_turns_continue_without_page_presence_and_submit_each_stage_once(tmp_path):
    native = FakeNativeFinancialService()
    native.accept_primary_turns()
    coordinator, _store = _coordinator(tmp_path, native)
    assert coordinator.register_after_primary_acceptance("assistant-1", "run-1")

    # The coordinator has no browser/page dependency: it advances native turns
    # from its persisted task even while the primary turns are still running.
    coordinator.process_pending_once()
    assert native.debate_calls == 0
    assert native.synthesis_calls == 0

    for role in ("market", "fundamental", "news"):
        ref = native.run["analysts"][role]
        native.final_answers[(ref["sessionId"], ref["turnId"])] = f"final-{role}"
    coordinator.process_pending_once()
    assert native.debate_calls == 1
    assert native.synthesis_calls == 0

    for role in ("bull", "bear"):
        ref = native.run["analysts"][role]
        native.final_answers[(ref["sessionId"], ref["turnId"])] = f"final-{role}"
    coordinator.process_pending_once()
    assert native.synthesis_calls == 1

    synthesis = native.run["synthesis"]
    native.final_answers[(synthesis["sessionId"], "turn-synthesis")] = "final-synthesis"
    coordinator.process_pending_once()
    coordinator.process_pending_once()

    assert native.debate_calls == 1
    assert native.synthesis_calls == 1
    assert native.run["coordinationStatus"] == "completed"
    assert native.run["coordinationError"] == ""


@pytest.mark.parametrize(
    ("terminal_status", "expected_message"),
    [
        ("failed_runtime", "行情分析失败，后续研究已暂停。"),
        ("stopped_by_user", "行情分析已停止，后续研究已暂停。"),
        ("completed", "行情分析缺少最终回答，后续研究已暂停。"),
    ],
)
def test_terminal_native_turn_without_final_blocks_immediately(
    tmp_path, terminal_status: str, expected_message: str
):
    native = FakeNativeFinancialService()
    native.accept_primary_turns()
    ref = native.run["analysts"]["market"]
    native.terminal_snapshots[(ref["sessionId"], ref["turnId"])] = {
        "sessionId": ref["sessionId"],
        "turnId": ref["turnId"],
        "terminal": True,
        "terminalStatus": terminal_status,
        "assistantText": "must never be copied into coordination state",
    }
    coordinator, _store = _coordinator(tmp_path, native)
    coordinator.register_after_primary_acceptance("assistant-1", "run-1")

    coordinator.process_pending_once()

    assert native.run["coordinationStatus"] == "blocked"
    assert native.run["coordinationError"] == expected_message
    assert "must never be copied" not in native.run["coordinationError"]
    assert "final_answer" not in native.run["coordinationError"]
    assert native.debate_calls == 0
    assert native.synthesis_calls == 0


def test_identity_drift_blocks_synthesis_submission(tmp_path):
    native = FakeNativeFinancialService()
    _accept_all_analyst_finals(native)
    native.binding_error = RuntimeError("changed team binding")
    coordinator, _store = _coordinator(tmp_path, native)
    coordinator.register_after_primary_acceptance("assistant-1", "run-1")

    coordinator.process_pending_once()

    assert native.run["coordinationStatus"] == "blocked"
    assert "身份" in native.run["coordinationError"]
    assert native.synthesis_calls == 0


def test_identity_drift_blocks_completion_of_recovered_synthesis(tmp_path):
    native = FakeNativeFinancialService()
    _accept_all_analyst_finals(native)
    native.run["synthesis"]["turnId"] = "turn-synthesis"
    native.final_answers[("session-synthesis", "turn-synthesis")] = "final-synthesis"
    native.binding_error = RuntimeError("changed team binding")
    coordinator, _store = _coordinator(tmp_path, native)
    coordinator.register_after_primary_acceptance("assistant-1", "run-1")

    coordinator.process_pending_once()

    assert native.run["coordinationStatus"] == "blocked"
    assert "身份" in native.run["coordinationError"]
    assert native.run["coordinationStatus"] != "completed"


def test_run_binding_guard_checks_team_revision_roles_and_synthesis_session(monkeypatch):
    from core.web.services.financial_team import runs

    run = _run()
    team = {
        "assistantAgentId": "assistant-1",
        "assistantSessionId": "session-synthesis",
        "teamId": "team-1",
        "status": "ready",
        "assistantConfigRevision": 7,
        "roles": [
            {
                "role": role,
                "agentId": ref["agentId"],
                "sessionId": ref["sessionId"],
                "status": "ready",
            }
            for role, ref in run["analysts"].items()
        ],
    }
    monkeypatch.setattr(runs, "_run_path", lambda *_args: object())
    monkeypatch.setattr(runs, "_load_run", lambda *_args: copy.deepcopy(run))
    monkeypatch.setattr(runs, "get_financial_team", lambda _assistant_id: team)
    monkeypatch.setattr(runs, "_record_financial_team_event", lambda *_args, **_kwargs: None)

    runs.require_current_financial_team_run_bindings("assistant-1", "run-1")

    team["assistantConfigRevision"] = 8
    with pytest.raises(runs.FinancialTeamRunConflictError, match="配置版本"):
        runs.require_current_financial_team_run_bindings("assistant-1", "run-1")

    team["assistantConfigRevision"] = 7
    team["roles"][0]["sessionId"] = "rebound-session"
    with pytest.raises(runs.FinancialTeamRunConflictError, match="原生会话"):
        runs.require_current_financial_team_run_bindings("assistant-1", "run-1")

    team["roles"][0]["sessionId"] = run["analysts"]["market"]["sessionId"]
    team["assistantSessionId"] = "rebound-owner-session"
    with pytest.raises(runs.FinancialTeamRunConflictError, match="主助手原生会话"):
        runs.require_current_financial_team_run_bindings("assistant-1", "run-1")


def test_failed_debate_is_persistently_blocked_and_does_not_advance(tmp_path):
    native = FakeNativeFinancialService()
    native.accept_primary_turns()
    for role in ("market", "fundamental", "news"):
        ref = native.run["analysts"][role]
        native.final_answers[(ref["sessionId"], ref["turnId"])] = f"final-{role}"
    native.debate_error = RuntimeError("native transport failed")
    coordinator, store = _coordinator(tmp_path, native)
    coordinator.register_after_primary_acceptance("assistant-1", "run-1")

    coordinator.process_pending_once()
    coordinator.process_pending_once()

    task = store.load_state(coordination_task_id("run-1"))
    assert native.debate_calls == 1
    assert native.synthesis_calls == 0
    assert native.run["coordinationStatus"] == "blocked"
    assert native.run["coordinationError"]
    assert len(native.run["coordinationError"]) <= 500
    assert task["status"] == "blocked"


def test_unknown_native_submission_is_never_reissued_after_restart(tmp_path):
    native = FakeNativeFinancialService()
    native.accept_primary_turns()
    for role in ("market", "fundamental", "news"):
        ref = native.run["analysts"][role]
        native.final_answers[(ref["sessionId"], ref["turnId"])] = f"final-{role}"
    native.debate_error = RuntimeError("unknown outcome")
    coordinator, store = _coordinator(tmp_path, native)
    coordinator.register_after_primary_acceptance("assistant-1", "run-1")

    coordinator.process_pending_once()
    first_task_id = coordination_task_id("run-1")
    assert native.submission_state == "submitting"

    # A new coordinator instance recovers the durable terminal task without
    # treating the ambiguous submit as permission to send again.
    recovered, _ = _coordinator(tmp_path, native)
    recovered.process_pending_once()

    assert native.debate_calls == 1
    assert native.synthesis_calls == 0
    assert store.load_state(first_task_id)["status"] == "blocked"


def test_synthesis_busy_retries_use_bounded_persisted_backoff(tmp_path):
    native = FakeNativeFinancialService()
    _accept_all_analyst_finals(native)
    native.synthesis_error = session_service.SessionBusyError("assistant session busy")
    clock = [100.0]
    coordinator, store = _coordinator(
        tmp_path,
        native,
        epoch_time=lambda: clock[0],
        synthesis_busy_retry_is_safe=lambda _assistant_id, _run_id: True,
    )
    assert coordinator.register_after_primary_acceptance("assistant-1", "run-1")

    coordinator.process_pending_once()
    state = store.load_state(coordination_task_id("run-1"))
    assert native.synthesis_calls == 1
    assert native.run["coordinationStatus"] == "running"
    assert state["status"] == "running"
    assert state["financialTeamSynthesisBusyRetryCount"] == 1
    assert state["financialTeamSynthesisRetryAtEpoch"] == 101.0

    clock[0] = 100.9
    coordinator.process_pending_once()
    assert native.synthesis_calls == 1

    native.synthesis_error = None
    clock[0] = 101.0
    coordinator.process_pending_once()
    assert native.synthesis_calls == 2
    assert native.run["synthesis"]["turnId"] == "turn-synthesis"
    assert native.run["coordinationStatus"] == "running"


def test_synthesis_busy_retry_exhaustion_blocks_after_three_retries(tmp_path):
    native = FakeNativeFinancialService()
    _accept_all_analyst_finals(native)
    native.synthesis_error = session_service.SessionBusyError("assistant session busy")
    clock = [200.0]
    coordinator, store = _coordinator(
        tmp_path,
        native,
        epoch_time=lambda: clock[0],
        synthesis_busy_retry_is_safe=lambda _assistant_id, _run_id: True,
    )
    assert coordinator.register_after_primary_acceptance("assistant-1", "run-1")

    for retry_number, delay in enumerate((0, 1, 2, 4), start=1):
        if delay:
            clock[0] += delay
        coordinator.process_pending_once()
        assert native.synthesis_calls == retry_number

    state = store.load_state(coordination_task_id("run-1"))
    assert native.run["coordinationStatus"] == "blocked"
    assert "有限自动重试已结束" in native.run["coordinationError"]
    assert state["status"] == "blocked"
    assert state["financialTeamSynthesisBusyRetryCount"] == 3


def test_expired_blocked_synthesis_recovery_renews_coordination_deadline(
    tmp_path, monkeypatch
):
    native = FakeNativeFinancialService()
    _accept_all_analyst_finals(native)
    native.run["synthesis"]["submissionState"] = "reserved"
    clock = [time.time()]
    validation_calls: list[tuple[str, str, bool]] = []

    def validate(assistant_id: str, run_id: str, *, allow_waiting: bool = False) -> None:
        validation_calls.append((assistant_id, run_id, allow_waiting))

    def start_recovery(
        assistant_id: str, run_id: str, *, allow_waiting: bool = False
    ) -> dict[str, Any]:
        assert assistant_id == "assistant-1"
        assert run_id == "run-1"
        assert allow_waiting is False
        assert native.run["coordinationStatus"] == "blocked"
        native.run["coordinationStatus"] = "waiting"
        native.run["coordinationError"] = ""
        return copy.deepcopy(native.run)

    monkeypatch.setattr(
        "core.web.services.financial_team.coordinator.runs._run_path",
        lambda *_args: tmp_path / "run.json",
    )
    coordinator, store = _coordinator(
        tmp_path,
        native,
        run_timeout_seconds=60,
        epoch_time=lambda: clock[0],
        synthesis_recovery_validator=validate,
        synthesis_recovery_starter=start_recovery,
    )
    assert coordinator.register_after_primary_acceptance("assistant-1", "run-1")
    original_created_at = "2000-01-01T00:00:00+00:00"
    store.update_task(
        coordination_task_id("run-1"),
        lambda state: {**state, "createdAt": original_created_at},
    )
    native.run["coordinationStatus"] = "blocked"
    store.mark_task_terminal(coordination_task_id("run-1"), status="blocked")

    assert coordinator.synthesis_recovery_status("assistant-1", "run-1") == {
        "available": True,
        "reason": "",
    }
    recovered = coordinator.recover_blocked_synthesis("assistant-1", "run-1")

    state = store.load_state(coordination_task_id("run-1"))
    assert recovered["coordinationStatus"] == "waiting"
    assert state["status"] == "running"
    assert state["financialTeamSynthesisRecoveryPending"] is False
    assert state["createdAt"] == original_created_at
    assert state["financialTeamSynthesisRecoveryStartedAt"]
    assert validation_calls[-1] == ("assistant-1", "run-1", False)

    coordinator.process_pending_once()
    assert native.debate_calls == 0
    assert native.synthesis_calls == 1
    assert native.run["synthesis"]["clientSubmissionId"] == "submission-synthesis"


def test_blocked_synthesis_recovery_refuses_user_stopped_task(tmp_path):
    native = FakeNativeFinancialService()
    _accept_all_analyst_finals(native)
    coordinator, store = _coordinator(
        tmp_path,
        native,
        synthesis_recovery_validator=lambda *_args, **_kwargs: None,
    )
    assert coordinator.register_after_primary_acceptance("assistant-1", "run-1")
    native.run["coordinationStatus"] = "blocked"
    store.update_task(
        coordination_task_id("run-1"),
        lambda state: {**state, "stopInitiator": "user"},
    )
    store.mark_task_terminal(coordination_task_id("run-1"), status="blocked")

    status = coordinator.synthesis_recovery_status("assistant-1", "run-1")

    assert status["available"] is False
    assert "停止请求" in status["reason"]
    assert native.synthesis_calls == 0


def test_startup_recovers_active_coordination_task_and_continues_next_phase(tmp_path):
    native = FakeNativeFinancialService()
    native.accept_primary_turns()
    for role in ("market", "fundamental", "news"):
        ref = native.run["analysts"][role]
        native.final_answers[(ref["sessionId"], ref["turnId"])] = f"final-{role}"
    first, store = _coordinator(tmp_path, native)
    first.register_after_primary_acceptance("assistant-1", "run-1")
    first.process_pending_once()
    assert native.debate_calls == 1
    assert store.load_state(coordination_task_id("run-1"))["status"] == "running"

    for role in ("bull", "bear"):
        ref = native.run["analysts"][role]
        native.final_answers[(ref["sessionId"], ref["turnId"])] = f"final-{role}"
    recovered, same_store = _coordinator(tmp_path, native)
    assert same_store.root == store.root
    recovered.process_pending_once()

    assert native.debate_calls == 1
    assert native.synthesis_calls == 1
    assert native.run["synthesis"]["turnId"] == "turn-synthesis"


def test_stop_request_prevents_any_later_stage_submission(tmp_path):
    native = FakeNativeFinancialService()
    native.accept_primary_turns()
    for role in ("market", "fundamental", "news"):
        ref = native.run["analysts"][role]
        native.final_answers[(ref["sessionId"], ref["turnId"])] = f"final-{role}"
    coordinator, store = _coordinator(tmp_path, native)
    coordinator.register_after_primary_acceptance("assistant-1", "run-1")
    assert store.request_stop(coordination_task_id("run-1"), "user")

    coordinator.process_pending_once()

    assert native.debate_calls == 0
    assert native.synthesis_calls == 0
    assert native.run["coordinationStatus"] == "blocked"


def test_expired_coordination_times_out_without_submitting_next_stage(tmp_path):
    native = FakeNativeFinancialService()
    native.accept_primary_turns()
    for role in ("market", "fundamental", "news"):
        ref = native.run["analysts"][role]
        native.final_answers[(ref["sessionId"], ref["turnId"])] = f"final-{role}"
    coordinator, store = _coordinator(tmp_path, native, run_timeout_seconds=1)
    coordinator.register_after_primary_acceptance("assistant-1", "run-1")
    store.update_task(
        coordination_task_id("run-1"),
        lambda task: {**task, "createdAt": "2000-01-01T00:00:00+00:00"},
    )

    coordinator.process_pending_once()

    assert native.debate_calls == 0
    assert native.synthesis_calls == 0
    assert native.run["coordinationStatus"] == "blocked"
    assert "超时" in native.run["coordinationError"]


def test_coordinator_stop_signal_terminates_its_worker(tmp_path):
    native = FakeNativeFinancialService()
    coordinator, _store = _coordinator(tmp_path, native)
    stop = threading.Event()
    ready = threading.Event()

    def run() -> None:
        ready.set()
        coordinator.run_forever(stop_requested=stop.is_set)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    assert ready.wait(timeout=1)
    stop.set()
    thread.join(timeout=1)
    assert not thread.is_alive()


def test_financial_team_response_model_accepts_optional_coordination_projection():
    payload = {
        "schemaVersion": 2,
        "runId": "run-1",
        "assistantAgentId": "assistant-1",
        "teamId": "team-1",
        "symbol": "600000",
        "periodDays": 30,
        "researchDate": "2026-10-05",
        "depth": "standard",
        "createdAt": "2026-10-05T00:00:00+00:00",
        "stage": "research",
        "analysts": {
            role: {
                "agentId": f"agent-{role}",
                "sessionId": f"session-{role}",
                "clientSubmissionId": f"submission-{role}",
                "turnId": "",
            }
            for role in ("market", "fundamental", "news", "bull", "bear")
        },
        "synthesis": {
            "agentId": "assistant-1",
            "sessionId": "session-synthesis",
            "clientSubmissionId": "submission-synthesis",
            "turnId": "",
        },
        "coordinationStatus": "blocked",
        "coordinationError": "原生 Turn 结果未知，已停止自动推进。",
    }

    response = FinancialTeamRunResponse.model_validate(payload)

    assert response.model_dump(exclude_none=True) == payload
