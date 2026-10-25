"""Focused tests for session stop / interrupt control."""

from __future__ import annotations

import pytest

from core.web.services import session_service
from core.web.services import cli_agent_task_kernel as cli_kernel
from core.web.services.session import control


@pytest.fixture(autouse=True)
def _isolated_cli_store(monkeypatch, tmp_path):
    monkeypatch.setattr(cli_kernel, "TASK_STATE_DIR", tmp_path / "actual-cli-tasks")
    monkeypatch.setattr(cli_kernel, "_ensure_watcher_started", lambda: None)
    monkeypatch.setattr(cli_kernel, "_PENDING_FINALIZATIONS", {})


def _install_running_stop_fixtures(
    monkeypatch,
    *,
    turn_control,
    order: list[str],
    queued_turn_cancelled: bool,
    publish=None,
) -> None:
    original_request_stop = turn_control.request_stop

    def tracked_request_stop(reason: str) -> None:
        order.append("stop")
        original_request_stop(reason)

    turn_control.request_stop = tracked_request_stop  # type: ignore[method-assign]

    monkeypatch.setattr(session_service, "get_web_language", lambda: "zh")
    monkeypatch.setattr(session_service, "text_for", lambda lang, zh="", en="": zh)
    monkeypatch.setattr(session_service, "_is_session_running", lambda session_id: True)
    monkeypatch.setattr(session_service, "_get_session_turn_control", lambda session_id: turn_control)
    monkeypatch.setattr(
        session_service,
        "_cancel_queued_session_turn",
        lambda session_id, turn_id: queued_turn_cancelled,
    )
    monkeypatch.setattr(session_service, "_record_chat_next_state_signal", lambda **kwargs: None)
    if publish is not None:
        monkeypatch.setattr(session_service, "_publish_session_detail_snapshot", publish)


def test_running_stop_fast_ack_skips_detail_rebuild_and_publish(monkeypatch) -> None:
    order: list[str] = []
    turn_control = session_service.SessionTurnControl(session_id="session-live", turn_id="turn-1")

    def forbidden_detail(*args, **kwargs):
        raise AssertionError("running stop fast ack must not rebuild session detail")

    def forbidden_publish(*args, **kwargs):
        raise AssertionError("running stop fast ack must not publish a snapshot")

    _install_running_stop_fixtures(
        monkeypatch,
        turn_control=turn_control,
        order=order,
        queued_turn_cancelled=False,
        publish=forbidden_publish,
    )
    monkeypatch.setattr(session_service, "get_session_detail", forbidden_detail)

    payload = control.request_stop_session_turn(
        "session-live",
        expected_turn_id="turn-1",
        fast_ack=True,
    )

    # The worker owns the stopped snapshot and publishes it once it observes the
    # request; the HTTP path only acknowledges the stop.
    assert order == ["stop"]
    assert payload == {
        "id": "session-live",
        "currentPhase": "stopping",
        "stopRequested": True,
        "stopRequestedAt": turn_control.snapshot().get("stopRequestedAt") or "",
        "activeTurnId": "turn-1",
    }
    assert turn_control.stop_requested is True
    assert turn_control.stop_event.is_set()


def test_running_stop_default_still_returns_hydrated_detail(monkeypatch) -> None:
    order: list[str] = []
    turn_control = session_service.SessionTurnControl(session_id="session-live", turn_id="turn-1")
    detail_calls: list[str] = []

    def tracked_detail(session_id, **kwargs):
        detail_calls.append(session_id)
        return {"id": session_id, "currentPhase": "stopping", "messages": []}

    def tracked_publish(session_id, **kwargs):
        order.append("publish")

    _install_running_stop_fixtures(
        monkeypatch,
        turn_control=turn_control,
        order=order,
        queued_turn_cancelled=False,
        publish=tracked_publish,
    )
    monkeypatch.setattr(session_service, "get_session_detail", tracked_detail)

    payload = control.request_stop_session_turn("session-live", expected_turn_id="turn-1")

    assert order == ["stop", "publish"]
    assert detail_calls == ["session-live"]
    assert payload["messages"] == []
    assert turn_control.stop_requested is True


def test_queued_stop_still_persists_snapshot_and_returns_detail(monkeypatch) -> None:
    order: list[str] = []
    turn_control = session_service.SessionTurnControl(session_id="session-live", turn_id="turn-1")

    def tracked_persist(session_id, snapshot, *, lang):
        order.append("persist")

    def tracked_publish(session_id, **kwargs):
        order.append("publish")

    _install_running_stop_fixtures(
        monkeypatch,
        turn_control=turn_control,
        order=order,
        queued_turn_cancelled=True,
        publish=tracked_publish,
    )
    monkeypatch.setattr(session_service, "_persist_session_interrupted_snapshot", tracked_persist)
    monkeypatch.setattr(
        session_service,
        "_set_session_running",
        lambda session_id, running, turn_id=None: order.append("release"),
    )
    monkeypatch.setattr(
        session_service,
        "get_session_detail",
        lambda session_id, **kwargs: {
            "id": session_id,
            "currentPhase": "stopping",
            "stopRequested": True,
        },
    )

    payload = control.request_stop_session_turn("session-live", expected_turn_id="turn-1")

    assert order[0] == "stop"
    assert order.index("persist") < order.index("publish")
    assert order.index("release") < order.index("publish")
    assert payload["currentPhase"] == "stopping"
    assert turn_control.stop_requested is True


def _cascade_registry(tmp_path, monkeypatch):
    from core.web.services import runtime_task_registry as runtime_tasks

    store = runtime_tasks.store_for(tmp_path / "cascade-runtime-tasks")
    monkeypatch.setattr(runtime_tasks, "default_store", lambda: store)
    monkeypatch.setattr(session_service, "_record_session_turn_lifecycle_event", lambda *args, **kwargs: None)
    return store


def _register_cascade_task(store, task_id, *, parent, kind, status="running"):
    from core.web.services import runtime_task_registry as runtime_tasks

    return store.register_task(
        runtime_tasks.new_snapshot(
            kind=kind,
            task_id=task_id,
            status=status,
            source_session_id="",
            parent_session_id=parent,
        )
    )


def test_running_stop_cascades_two_level_descendants_and_seals(monkeypatch, tmp_path) -> None:
    order: list[str] = []
    turn_control = session_service.SessionTurnControl(session_id="session-root", turn_id="turn-1")
    _install_running_stop_fixtures(
        monkeypatch,
        turn_control=turn_control,
        order=order,
        queued_turn_cancelled=False,
        publish=lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(session_service, "get_session_detail", lambda session_id, **kwargs: {"id": session_id})
    store = _cascade_registry(tmp_path, monkeypatch)
    _register_cascade_task(store, "child-1", parent="session-root", kind="child_session")
    _register_cascade_task(store, "cli-1", parent="session-root", kind="cli_agent")
    _register_cascade_task(store, "cli-2", parent="child-1", kind="cli_agent")

    # Intercept only the descendant stop primitive: the root call keeps the
    # real function, whose internal recursion resolves the patched name.
    real_stop = control.request_stop_session_turn
    descendant_stops: list[tuple[str, bool]] = []

    def tracked_descendant_stop(session_id, **kwargs):
        descendant_stops.append((session_id, bool(kwargs.get("cascade"))))
        return {"id": session_id}

    monkeypatch.setattr(control, "request_stop_session_turn", tracked_descendant_stop)

    payload = real_stop("session-root", expected_turn_id="turn-1")

    assert turn_control.stop_requested is True
    assert descendant_stops == [("child-1", False)]
    assert payload["id"] == "session-root"

    for task_id in ("child-1", "cli-1", "cli-2"):
        state = store.load_state(task_id)
        assert state["notificationSealed"] is True, task_id
        assert state["notificationSealedReason"] == "parent_turn_cancelled"
        assert state["notificationSealedByTurnId"] == "turn-1"
        assert state["stopInitiator"] == "user"
        assert state["cascadeStop"]["cascadedFrom"] == "session-root"


def test_running_stop_without_descendants_is_registry_neutral(monkeypatch, tmp_path) -> None:
    order: list[str] = []
    turn_control = session_service.SessionTurnControl(session_id="session-live", turn_id="turn-1")
    _install_running_stop_fixtures(
        monkeypatch,
        turn_control=turn_control,
        order=order,
        queued_turn_cancelled=False,
        publish=lambda *_args, **_kwargs: order.append("publish"),
    )
    monkeypatch.setattr(session_service, "get_session_detail", lambda session_id, **kwargs: {"id": session_id})
    store = _cascade_registry(tmp_path, monkeypatch)

    def forbidden_seal(*args, **kwargs):
        raise AssertionError("a session without descendants must not touch the registry")

    monkeypatch.setattr(store, "seal_and_request_stop", forbidden_seal)

    payload = control.request_stop_session_turn("session-live", expected_turn_id="turn-1")

    assert payload["id"] == "session-live"
    assert store.active_task_ids() == []
    assert turn_control.stop_requested is True


def test_cascade_stop_isolates_per_target_failures(monkeypatch, tmp_path) -> None:
    turn_control = session_service.SessionTurnControl(session_id="session-root", turn_id="turn-1")
    _install_running_stop_fixtures(
        monkeypatch,
        turn_control=turn_control,
        order=[],
        queued_turn_cancelled=False,
        publish=lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(session_service, "get_session_detail", lambda session_id, **kwargs: {"id": session_id})
    store = _cascade_registry(tmp_path, monkeypatch)
    _register_cascade_task(store, "child-broken", parent="session-root", kind="child_session")
    _register_cascade_task(store, "cli-healthy", parent="session-root", kind="cli_agent")

    real_seal = store.seal_and_request_stop

    def flaky_seal(task_id, **kwargs):
        if task_id == "child-broken":
            raise RuntimeError("registry write failed")
        return real_seal(task_id, **kwargs)

    monkeypatch.setattr(store, "seal_and_request_stop", flaky_seal)
    real_stop = control.request_stop_session_turn
    monkeypatch.setattr(
        control,
        "request_stop_session_turn",
        lambda session_id, **kwargs: (_ for _ in ()).throw(AssertionError("broken child must not be stopped")),
    )

    real_stop("session-root", expected_turn_id="turn-1")

    assert store.load_state("cli-healthy")["notificationSealed"] is True
    assert store.load_state("cli-healthy")["stopInitiator"] == "user"
    assert store.load_state("child-broken")["notificationSealed"] is False


@pytest.mark.parametrize("child_owner", [False, True])
def test_cascade_seals_the_actual_cli_store_and_drops_late_marker(monkeypatch, tmp_path, child_owner):
    from core.web.services import cli_agent_service, cli_agent_terminal_service, runtime_task_registry as registry

    native = _cascade_registry(tmp_path, monkeypatch)
    if child_owner:
        _register_cascade_task(native, "child-owner", parent="session-root", kind="child_session")
    owner = "child-owner" if child_owner else "session-root"
    monkeypatch.setattr(control, "request_stop_session_turn", lambda *args, **kwargs: {})
    monkeypatch.setattr(cli_agent_terminal_service, "write_cli_agent_terminal_input", lambda *args: {})
    monkeypatch.setattr(cli_agent_terminal_service, "stop_cli_agent_terminal_session", lambda *args: pytest.fail("notification sealing must not stop a terminal"))
    delivered = []
    events = []
    monkeypatch.setattr(session_service, "append_cli_agent_task_result_event", lambda *args, **kwargs: delivered.append(args))
    monkeypatch.setattr(cli_agent_service, "_record_event", lambda event, **kwargs: events.append((event, kwargs)))
    terminal = {
        "terminalSessionId": "cli-real-store", "adapterId": "codex_code", "alive": True,
        "status": "running", "sourceSessionId": owner, "sourceRunId": "origin-turn",
    }
    submitted = cli_kernel.submit_cli_agent_task(
        terminal_session=terminal, task="Inspect", timeout_seconds=60, output_limit=2000,
    )
    cli_store = cli_kernel._task_store()
    task_id = submitted["taskId"]
    before = cli_store.load_state(task_id)
    assert before["parentSessionId"] == ""
    untouched = {}
    for name, source, status, kind in [
        ("cli-neighbor", "session-root-neighbor", "running", registry.KIND_CLI_AGENT),
        ("cli-unknown", "", "running", registry.KIND_CLI_AGENT),
        ("cli-finished", owner, "completed", registry.KIND_CLI_AGENT),
        ("other-kind", owner, "running", registry.KIND_RESEARCH_TASK),
    ]:
        untouched[name] = cli_store.register_task(registry.new_snapshot(
            kind=kind, task_id=name, status=status, source_session_id=source,
        ))

    report = control._cascade_stop_descendant_runtime_tasks("session-root", turn_id="stopped-turn")

    actual = cli_store.load_state(task_id)
    assert actual["notificationSealed"] is True
    assert actual["notificationSealedByTurnId"] == "stopped-turn"
    assert actual["cascadeStop"]["cascadedFrom"] == "session-root"
    assert actual["stopInitiator"] == "user"
    assert actual["status"] == before["status"]
    assert native.load_state(task_id) == {}
    row = next(row for row in report if row["taskId"] == task_id)
    assert row["cascadeDepth"] == (1 if child_owner else 0)
    assert row["sealed"] is True
    assert row["stopResult"] == "stop_intent_recorded"
    for name, snapshot in untouched.items():
        assert cli_store.load_state(name) == snapshot

    cli_kernel.ingest_terminal_output(terminal, before["completionMarker"])

    settled = cli_store.load_state(task_id)
    assert settled["status"] == "completed"
    assert settled["notificationDropReason"] == "sealed"
    assert delivered == []
    assert any(event == "cli_agent.task.result_fenced" and data["outcome"] == "sealed_dropped" for event, data in events)
