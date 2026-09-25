"""Startup recovery sweep for chat-room rounds orphaned by a backend restart."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from core.agent_kernel import service as agent_kernel_service
from core.infrastructure import developer_sandbox
from core.runtime_manager import work_run_store
from core.web.services import (
    agent_directory_service,
    chat_room_service,
    chat_room_startup_recovery,
    session_service,
)

# Room ops sync chat_room_service's own (possibly monkeypatched) PROJECT_ROOT
# into sibling service modules with plain assignments, which monkeypatch never
# records (see tests/test_chat_room_service.py for the same containment).
_SERVICE_GLOBAL_ROOT_MODULES = (
    chat_room_service,
    session_service,
    agent_directory_service,
    agent_kernel_service,
)

_STALE_UPDATED_AT = "2026-07-10T02:49:48+00:00"
_ORPHAN_STARTED_AT = "2026-07-10T02:30:52+00:00"


# Captured at collection time, before any test can leak a tmp path into it.
_KERNEL_SERVICE_DEFAULT_PROJECT_ROOT = agent_kernel_service.PROJECT_ROOT


@pytest.fixture(autouse=True)
def _restore_service_project_root_globals():
    """Contain the cross-module PROJECT_ROOT writes room ops perform."""

    if agent_kernel_service.PROJECT_ROOT != _KERNEL_SERVICE_DEFAULT_PROJECT_ROOT:
        agent_kernel_service.PROJECT_ROOT = _KERNEL_SERVICE_DEFAULT_PROJECT_ROOT
    saved = {
        module: getattr(module, "PROJECT_ROOT", None)
        for module in _SERVICE_GLOBAL_ROOT_MODULES
    }
    yield
    for module, value in saved.items():
        if value is not None:
            module.PROJECT_ROOT = value


@pytest.fixture
def room_executor(monkeypatch):
    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="pytest-chat-room-recovery")
    monkeypatch.setattr(chat_room_service, "_CHAT_ROOM_EXECUTOR", executor)
    yield executor
    executor.shutdown(wait=True, cancel_futures=True)


def _isolate_chat_room_kernel(tmp_path, monkeypatch):
    data_home = tmp_path / "operator-data"
    work_runs_root = tmp_path / "work_runs"
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(data_home))
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.meeting_receipt_authority.workflow_run_stop_reason",
        lambda _authority: "",
    )
    monkeypatch.setattr(agent_kernel_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(developer_sandbox, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(developer_sandbox, "resolve_workspace_home", lambda *args, **kwargs: data_home / "workspace")
    monkeypatch.setattr(work_run_store, "WORK_RUNS_DIR", work_runs_root)


def _set_session_recovery_config(monkeypatch, *, enabled=True, max_auto_retries=None):
    section: dict = {"enabled": enabled}
    if max_auto_retries is not None:
        section["maxAutoRetries"] = max_auto_retries
    monkeypatch.setattr(
        "core.session_recovery_flags.load_public_config",
        lambda: {"session_recovery": section},
    )


def _create_agent_room(title, agent_ids):
    return chat_room_service.create_chat_room(title=title, participant_agent_ids=agent_ids)


def _participant_ids_by_agent(room_id):
    detail = chat_room_service.get_chat_room_detail(room_id)
    return {
        str(item.get("agentId") or "").strip(): str(item.get("participantId") or "").strip()
        for item in detail["participants"]
    }


def _orphan_round_payload(
    room_id,
    round_id,
    topic,
    speaker_participant_ids,
    *,
    config=None,
    completed_participant_ids=(),
):
    completed = {str(item) for item in completed_participant_ids}
    return {
        "roundId": round_id,
        "roomId": room_id,
        "topic": topic,
        "mode": "round_robin",
        "purpose": "discussion",
        "config": dict(config or {}),
        "status": "running",
        "speakerOrder": list(speaker_participant_ids),
        "speakerProgress": [
            {
                "participantId": participant_id,
                "sessionId": "",
                "state": "settled" if participant_id in completed else "queued",
                "status": "completed" if participant_id in completed else "",
                "updatedAt": _STALE_UPDATED_AT,
            }
            for participant_id in speaker_participant_ids
        ],
        "messages": [
            {
                "messageId": f"message-{participant_id}",
                "participantId": participant_id,
                "speakerTitle": "",
                "status": "completed",
                "content": "重启前已完成的发言",
                "summary": "已完成",
                "timestamp": _STALE_UPDATED_AT,
            }
            for participant_id in speaker_participant_ids
            if participant_id in completed
        ],
        "autoContinueDeadLetters": [],
        "summary": "",
        "startedAt": _ORPHAN_STARTED_AT,
        "updatedAt": _STALE_UPDATED_AT,
        "finishedAt": "",
    }


def _persist_orphan_round(room, round_payload, *, room_config=None):
    """Leave a durable-running round behind with no process controller."""

    state = chat_room_service._store().load()
    stored_room = next(
        item for item in state["rooms"] if item["roomId"] == room["roomId"]
    )
    stored_room["status"] = "running"
    stored_room["activeRoundId"] = round_payload["roundId"]
    stored_room["rounds"] = [round_payload]
    if room_config is not None:
        stored_room["config"] = dict(room_config)
    chat_room_service._store().save(state)
    chat_room_service._work_run_store().persist_snapshot(
        chat_room_service.RUN_KIND,
        {
            "runId": round_payload["roundId"],
            "runKind": chat_room_service.RUN_KIND,
            "roomId": room["roomId"],
            "roundId": round_payload["roundId"],
            "status": "running",
            "currentPhase": "running",
            "summary": "Interrupted by a backend restart.",
            "startedAt": round_payload["startedAt"],
            "updatedAt": _STALE_UPDATED_AT,
            "finishedAt": "",
        },
        active_run_id=round_payload["roundId"],
    )


def _install_recording_runner(monkeypatch, *, failed_agent_ids=()):
    failed = {str(item) for item in failed_agent_ids}
    calls = []
    lock = threading.Lock()

    def runner(participant, prompt, context):
        agent_id = str(participant.get("agentId") or "").strip()
        with lock:
            calls.append(agent_id)
        if agent_id in failed:
            return {"status": "failed", "raw_output": "boom", "summary": "boom"}
        return {"status": "completed", "raw_output": "ok", "summary": "ok"}

    monkeypatch.setattr(chat_room_service, "_run_participant_agent", runner)
    return calls


def _load_stored_room(room_id):
    state = chat_room_service._store().load()
    return next(
        (item for item in state["rooms"] if item["roomId"] == room_id),
        None,
    )


def _wait_for_room_terminal(room_id, *, timeout=10.0):
    """Wait until the room's active round leaves the running statuses."""

    deadline = time.time() + timeout
    while time.time() < deadline:
        stored_room = _load_stored_room(room_id)
        if stored_room is not None:
            active_round_id = str(stored_room.get("activeRoundId") or "").strip()
            active_round = next(
                (
                    item
                    for item in stored_room.get("rounds") or []
                    if str(item.get("roundId") or "") == active_round_id
                ),
                None,
            )
            if active_round is None or str(active_round.get("status") or "") not in (
                "queued",
                "running",
                "stopping",
            ):
                return stored_room
        time.sleep(0.05)
    raise AssertionError(f"room {room_id} round did not finish in time")


def _clear_process_controls():
    with chat_room_service._CHAT_ROOM_ROUND_CONTROLS_LOCK:
        chat_room_service._CHAT_ROOM_ROUND_CONTROLS.clear()


def _reorphan_round(room_id, round_id):
    """Simulate a second backend restart over a finished round."""

    state = chat_room_service._store().load()
    stored_room = next(item for item in state["rooms"] if item["roomId"] == room_id)
    target_round = next(
        item for item in stored_room["rounds"] if item["roundId"] == round_id
    )
    target_round["status"] = "running"
    target_round["finishedAt"] = ""
    target_round["updatedAt"] = _STALE_UPDATED_AT
    stored_room["status"] = "running"
    stored_room["activeRoundId"] = round_id
    stored_room["updatedAt"] = _STALE_UPDATED_AT
    chat_room_service._store().save(state)
    chat_room_service._work_run_store().persist_snapshot(
        chat_room_service.RUN_KIND,
        {
            "runId": round_id,
            "runKind": chat_room_service.RUN_KIND,
            "roomId": room_id,
            "roundId": round_id,
            "status": "running",
            "currentPhase": "running",
            "summary": "Interrupted again by a backend restart.",
            "startedAt": _ORPHAN_STARTED_AT,
            "updatedAt": _STALE_UPDATED_AT,
            "finishedAt": "",
        },
        active_run_id=round_id,
    )
    _clear_process_controls()


# ---------------------------------------------------------------------------
# Redrive: orphan closed by reconcile, then re-sent with a narrowed roster
# ---------------------------------------------------------------------------


def test_startup_recovery_redrives_orphan_round_without_completed_speakers(
    tmp_path, monkeypatch, room_executor
):
    _isolate_chat_room_kernel(tmp_path, monkeypatch)
    _set_session_recovery_config(monkeypatch)
    agents = [
        session_service.create_chat_session(title=name)
        for name in ("Alpha Agent", "Beta Agent", "Gamma Agent")
    ]
    agent_ids = [agent["agentId"] for agent in agents]
    room = _create_agent_room("重启恢复群聊", agent_ids)
    participants = _participant_ids_by_agent(room["roomId"])
    _persist_orphan_round(
        room,
        _orphan_round_payload(
            room["roomId"],
            "round-orphan-redrive",
            "恢复中断的讨论",
            [participants[agent_ids[0]], participants[agent_ids[1]], participants[agent_ids[2]]],
            completed_participant_ids=[participants[agent_ids[0]]],
        ),
    )
    calls = _install_recording_runner(monkeypatch)

    result = chat_room_startup_recovery.recover_chat_room_rounds_on_startup()

    assert result["orphanCount"] == 1
    outcome = result["outcomes"][0]
    assert outcome["action"] == "redriven"
    assert outcome["speakerAgentIds"] == [agent_ids[1], agent_ids[2]]

    stored_room = _load_stored_room(room["roomId"])
    assert stored_room["status"] == "running"
    new_round_id = stored_room["activeRoundId"]
    assert new_round_id and new_round_id != "round-orphan-redrive"
    old_round = next(
        item for item in stored_room["rounds"] if item["roundId"] == "round-orphan-redrive"
    )
    assert old_round["status"] == "stopped"
    assert "后端进程已重启" in str(old_round.get("terminalReason") or "")
    new_round = next(item for item in stored_room["rounds"] if item["roundId"] == new_round_id)
    assert new_round["config"]["participantAgentIds"] == [agent_ids[1], agent_ids[2]]
    assert new_round["config"]["startupRecoveryRetries"] == 1
    assert new_round["config"]["startupRecoveryOfRoundId"] == "round-orphan-redrive"
    assert new_round["speakerOrder"] == [participants[agent_ids[1]], participants[agent_ids[2]]]

    _wait_for_room_terminal(room["roomId"])
    assert sorted(calls) == sorted([agent_ids[1], agent_ids[2]])
    assert agent_ids[0] not in calls

    snapshot = chat_room_service._work_run_store().load_snapshot(
        chat_room_service.RUN_KIND, "round-orphan-redrive"
    )
    assert snapshot["runtimeStatus"] == "orphan_reconciled"


def test_startup_recovery_flag_disabled_keeps_current_lazy_behavior(
    tmp_path, monkeypatch
):
    _isolate_chat_room_kernel(tmp_path, monkeypatch)
    _set_session_recovery_config(monkeypatch, enabled=False)
    agents = [
        session_service.create_chat_session(title=name)
        for name in ("Alpha Agent", "Beta Agent")
    ]
    room = _create_agent_room("开关关闭群聊", [agent["agentId"] for agent in agents])
    participants = _participant_ids_by_agent(room["roomId"])
    _persist_orphan_round(
        room,
        _orphan_round_payload(
            room["roomId"],
            "round-orphan-flag-off",
            "开关关闭时的孤儿轮",
            list(participants.values()),
        ),
    )

    result = chat_room_startup_recovery.recover_chat_room_rounds_on_startup()

    assert result == {"enabled": False, "orphanCount": 0, "outcomes": []}
    stored_room = _load_stored_room(room["roomId"])
    assert stored_room["activeRoundId"] == "round-orphan-flag-off"
    assert stored_room["rounds"][0]["status"] == "running"


# ---------------------------------------------------------------------------
# Skips: rooms with their own recovery owners or unreplayable round entries
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bound_in", ["round_config", "room_config"])
def test_startup_recovery_skips_meeting_bound_orphan_rooms(
    tmp_path, monkeypatch, bound_in
):
    _isolate_chat_room_kernel(tmp_path, monkeypatch)
    meeting_bridges = []
    monkeypatch.setattr(
        "core.web.services.team_workflow.meeting_runtime.finalize_stopped_meeting_after_chat_round",
        lambda room, round_payload: meeting_bridges.append(dict(round_payload)),
    )
    agents = [
        session_service.create_chat_session(title=name)
        for name in ("Alpha Agent", "Beta Agent")
    ]
    room = _create_agent_room("会议绑定群聊", [agent["agentId"] for agent in agents])
    participants = _participant_ids_by_agent(room["roomId"])
    round_config = {"meetingRoundId": "meeting-round-1"} if bound_in == "round_config" else {}
    room_config = {"meetingRoundId": "meeting-round-1"} if bound_in == "room_config" else None
    _persist_orphan_round(
        room,
        _orphan_round_payload(
            room["roomId"],
            "round-orphan-meeting",
            "会议绑定孤儿轮",
            list(participants.values()),
            config=round_config,
        ),
        room_config=room_config,
    )

    result = chat_room_service.recover_orphaned_chat_room_rounds_on_startup()

    assert result["orphanCount"] == 1
    assert result["outcomes"][0]["action"] == "skipped_meeting_bound"
    stored_room = _load_stored_room(room["roomId"])
    assert stored_room["status"] == "ready"
    assert stored_room["activeRoundId"] == ""
    assert len(stored_room["rounds"]) == 1
    assert stored_room["rounds"][0]["status"] == "stopped"
    assert len(meeting_bridges) == 1


def test_startup_recovery_skips_challenge_scoped_orphan_rooms(tmp_path, monkeypatch):
    _isolate_chat_room_kernel(tmp_path, monkeypatch)
    agents = [
        session_service.create_chat_session(title=name)
        for name in ("Alpha Agent", "Beta Agent")
    ]
    room = _create_agent_room("正式阶段群聊", [agent["agentId"] for agent in agents])
    participants = _participant_ids_by_agent(room["roomId"])
    _persist_orphan_round(
        room,
        _orphan_round_payload(
            room["roomId"],
            "round-orphan-scoped",
            "正式阶段孤儿轮",
            list(participants.values()),
        ),
        room_config={
            "scopeAuthority": "workflow_discussion_scope.v1",
            "discussionScope": {"stage": "r1"},
            "scopeHash": "scope-hash-1",
        },
    )

    result = chat_room_service.recover_orphaned_chat_room_rounds_on_startup()

    assert result["outcomes"][0]["action"] == "skipped_challenge_scoped"
    stored_room = _load_stored_room(room["roomId"])
    assert stored_room["activeRoundId"] == ""
    assert stored_room["rounds"][0]["status"] == "stopped"


def test_startup_recovery_skips_operator_rooms(tmp_path, monkeypatch):
    _isolate_chat_room_kernel(tmp_path, monkeypatch)
    agents = [
        session_service.create_chat_session(title=name)
        for name in ("Alpha Agent", "Beta Agent")
    ]
    room = _create_agent_room("运营优化群聊", [agent["agentId"] for agent in agents])
    participants = _participant_ids_by_agent(room["roomId"])
    _persist_orphan_round(
        room,
        _orphan_round_payload(
            room["roomId"],
            "round-orphan-operator",
            "运营优化孤儿轮",
            list(participants.values()),
        ),
        room_config={
            "operatorDiscussionAuthority": {
                "authorityKind": "operator_discussion",
                "workflowRunId": "run-1",
                "nodeRunId": "node-1",
            }
        },
    )

    result = chat_room_service.recover_orphaned_chat_room_rounds_on_startup()

    assert result["outcomes"][0]["action"] == "skipped_operator_room"
    stored_room = _load_stored_room(room["roomId"])
    assert stored_room["activeRoundId"] == ""
    assert len(stored_room["rounds"]) == 1


def test_startup_recovery_closes_all_spoken_orphan_without_redrive(
    tmp_path, monkeypatch
):
    _isolate_chat_room_kernel(tmp_path, monkeypatch)
    agents = [
        session_service.create_chat_session(title=name)
        for name in ("Alpha Agent", "Beta Agent")
    ]
    room = _create_agent_room("全员已发言群聊", [agent["agentId"] for agent in agents])
    participants = _participant_ids_by_agent(room["roomId"])
    _persist_orphan_round(
        room,
        _orphan_round_payload(
            room["roomId"],
            "round-orphan-all-spoken",
            "全员已发言孤儿轮",
            list(participants.values()),
            completed_participant_ids=list(participants.values()),
        ),
    )
    calls = _install_recording_runner(monkeypatch)

    result = chat_room_service.recover_orphaned_chat_room_rounds_on_startup()

    assert result["orphanCount"] == 1
    assert result["outcomes"][0]["action"] == "skipped_all_spoken"
    stored_room = _load_stored_room(room["roomId"])
    assert stored_room["status"] == "ready"
    assert stored_room["activeRoundId"] == ""
    assert len(stored_room["rounds"]) == 1
    assert stored_room["rounds"][0]["status"] == "stopped"
    assert calls == []


# ---------------------------------------------------------------------------
# Retry chain: round-config counter persists across simulated restarts
# ---------------------------------------------------------------------------


def test_startup_recovery_retry_limit_skips_chain_past_limit(tmp_path, monkeypatch):
    _isolate_chat_room_kernel(tmp_path, monkeypatch)
    agents = [
        session_service.create_chat_session(title=name)
        for name in ("Alpha Agent", "Beta Agent")
    ]
    room = _create_agent_room("超限群聊", [agent["agentId"] for agent in agents])
    participants = _participant_ids_by_agent(room["roomId"])
    _persist_orphan_round(
        room,
        _orphan_round_payload(
            room["roomId"],
            "round-orphan-over-limit",
            "超限孤儿轮",
            list(participants.values()),
            config={"startupRecoveryRetries": 1, "startupRecoveryOfRoundId": "round-root"},
        ),
    )
    calls = _install_recording_runner(monkeypatch)

    result = chat_room_service.recover_orphaned_chat_room_rounds_on_startup(
        max_auto_retries=1
    )

    assert result["outcomes"][0]["action"] == "skipped_retry_limit"
    assert result["outcomes"][0]["retries"] == 1
    stored_room = _load_stored_room(room["roomId"])
    assert stored_room["status"] == "ready"
    assert stored_room["activeRoundId"] == ""
    assert len(stored_room["rounds"]) == 1
    assert calls == []


def test_startup_recovery_retry_counter_persists_across_simulated_restarts(
    tmp_path, monkeypatch, room_executor
):
    _isolate_chat_room_kernel(tmp_path, monkeypatch)
    agents = [
        session_service.create_chat_session(title=name)
        for name in ("Alpha Agent", "Beta Agent", "Gamma Agent")
    ]
    agent_ids = [agent["agentId"] for agent in agents]
    room = _create_agent_room("二次重启群聊", agent_ids)
    participants = _participant_ids_by_agent(room["roomId"])
    _persist_orphan_round(
        room,
        _orphan_round_payload(
            room["roomId"],
            "round-orphan-root",
            "跨重启恢复讨论",
            [participants[agent_id] for agent_id in agent_ids],
            completed_participant_ids=[participants[agent_ids[0]]],
        ),
    )
    # Gamma's speaker call fails so the first redrive finishes without her.
    calls = _install_recording_runner(monkeypatch, failed_agent_ids={agent_ids[2]})

    first = chat_room_service.recover_orphaned_chat_room_rounds_on_startup(
        max_auto_retries=2
    )
    assert first["outcomes"][0]["action"] == "redriven"
    assert first["outcomes"][0]["retries"] == 1
    first_room = _wait_for_room_terminal(room["roomId"])
    first_redrive_id = first["outcomes"][0]["newRoundId"]
    first_round = next(
        item for item in first_room["rounds"] if item["roundId"] == first_redrive_id
    )
    assert first_round["config"]["startupRecoveryRetries"] == 1
    assert first_round["config"]["startupRecoveryOfRoundId"] == "round-orphan-root"

    _reorphan_round(room["roomId"], first_redrive_id)

    second = chat_room_service.recover_orphaned_chat_room_rounds_on_startup(
        max_auto_retries=2
    )
    assert second["orphanCount"] == 1
    assert second["outcomes"][0]["action"] == "redriven"
    assert second["outcomes"][0]["retries"] == 2
    assert second["outcomes"][0]["speakerAgentIds"] == [agent_ids[2]]

    second_room = _load_stored_room(room["roomId"])
    second_round = next(
        item
        for item in second_room["rounds"]
        if item["roundId"] == second["outcomes"][0]["newRoundId"]
    )
    assert second_round["config"]["startupRecoveryRetries"] == 2
    assert second_round["config"]["startupRecoveryOfRoundId"] == "round-orphan-root"
    assert second_round["config"]["participantAgentIds"] == [agent_ids[2]]

    _wait_for_room_terminal(room["roomId"])
    # Beta spoke once in the first redrive; gamma failed there and spoke again
    # in the second redrive.
    assert calls.count(agent_ids[1]) == 1
    assert calls.count(agent_ids[2]) == 2
    assert set(calls) == {agent_ids[1], agent_ids[2]}


# ---------------------------------------------------------------------------
# Isolation: one room's failure never blocks the other rooms
# ---------------------------------------------------------------------------


def test_startup_recovery_isolates_per_room_failures(tmp_path, monkeypatch, room_executor):
    _isolate_chat_room_kernel(tmp_path, monkeypatch)
    agents = [
        session_service.create_chat_session(title=name)
        for name in ("Alpha Agent", "Beta Agent", "Gamma Agent")
    ]
    healthy_room = _create_agent_room(
        "健康房间", [agents[0]["agentId"], agents[1]["agentId"]]
    )
    failing_room = _create_agent_room("失败房间", [agents[1]["agentId"], agents[2]["agentId"]])
    rooms = (healthy_room, failing_room)
    # Resolve participant maps for both rooms before seeding any orphan: a
    # detail read in between would run the lazy reconcile and close the first
    # seeded orphan ahead of the sweep.
    participants_by_room = {
        room["roomId"]: _participant_ids_by_agent(room["roomId"]) for room in rooms
    }
    for index, room in enumerate(rooms):
        _persist_orphan_round(
            room,
            _orphan_round_payload(
                room["roomId"],
                f"round-orphan-room-{index}",
                f"隔离测试孤儿轮 {index}",
                list(participants_by_room[room["roomId"]].values()),
            ),
        )

    real_start = chat_room_service.start_chat_room_round

    def flaky_start(room_id, topic, **kwargs):
        if room_id == failing_room["roomId"]:
            raise RuntimeError("boom")
        return real_start(room_id, topic, **kwargs)

    monkeypatch.setattr(chat_room_service, "start_chat_room_round", flaky_start)
    _install_recording_runner(monkeypatch)

    result = chat_room_service.recover_orphaned_chat_room_rounds_on_startup()

    assert result["orphanCount"] == 2
    outcome_by_room = {item["roomId"]: item for item in result["outcomes"]}
    assert outcome_by_room[healthy_room["roomId"]]["action"] == "redriven"
    assert outcome_by_room[failing_room["roomId"]]["action"] == "failed"
    healthy_stored = _load_stored_room(healthy_room["roomId"])
    assert healthy_stored["status"] == "running"
    assert healthy_stored["activeRoundId"] != "round-orphan-room-0"
    failing_stored = _load_stored_room(failing_room["roomId"])
    assert failing_stored["activeRoundId"] == ""
    assert failing_stored["rounds"][0]["status"] == "stopped"
