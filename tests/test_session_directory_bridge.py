from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.ui.chat_state import save_chat_state
from core.web.services import session_service
from core.web.services.session import directory_bridge
from core.web.services.session import directory_runtime


def test_directory_page_batches_authoritative_terminal_outcomes(monkeypatch):
    from core.web.services.session.session_ops import _terminal_reason_from_conversation
    calls = []
    def terminal_states(ids):
        calls.append(ids)
        return {
            "done": {"last_turn_status": "completed", "last_turn_terminal_reason": "success", "last_turn_terminal_turn_id": "turn-1"},
            "stop": {"last_turn_status": "ready", "last_turn_terminal_reason": "stopped_by_user", "last_turn_terminal_turn_id": "turn-2"},
        }
    store = SimpleNamespace(repository=SimpleNamespace(get_session_terminal_states=terminal_states))
    monkeypatch.setattr(directory_bridge, "_service", lambda: SimpleNamespace(_terminal_reason_from_conversation=_terminal_reason_from_conversation))
    items = [{"id": "done", "status": "ready"}, {"id": "stop", "status": "ready"}, {"id": "continue", "status": "needs_continue"}]
    result = directory_bridge._with_terminal_states(items, store=store)
    assert calls == [["done", "stop", "continue"]]
    assert [item["terminalReason"] for item in result] == ["success", "stopped_by_user", "needs_continue"]
    assert result[0]["lastTurnStatus"] == "completed"
    assert result[1]["lastTurnTerminalTurnId"] == "turn-2"


def test_missing_terminal_metadata_never_guesses_success_from_idle_phase(monkeypatch):
    from core.web.services.session.session_ops import _terminal_reason_from_conversation
    degraded = []
    def fail(_ids):
        raise OSError("metadata read unavailable")
    store = SimpleNamespace(repository=SimpleNamespace(get_session_terminal_states=fail))
    monkeypatch.setattr(directory_bridge, "_service", lambda: SimpleNamespace(_terminal_reason_from_conversation=_terminal_reason_from_conversation))
    monkeypatch.setattr(directory_bridge, "note_session_read_degraded", lambda **values: degraded.append(values))
    result = directory_bridge._with_terminal_states([{"id": "idle", "status": "ready"}], store=store)
    assert result[0]["terminalReason"] == "ready"
    assert degraded == [{"source": "session terminal metadata", "error_type": "OSError"}]


@pytest.mark.parametrize("terminal_status", ["needs_continue", "paused_limit", "failed", "ready"])
def test_directory_sync_preserves_canonical_last_turn_status(monkeypatch, terminal_status):
    writes = []

    def upsert(**values):
        writes.append(values)
        done = Future()
        done.set_result(None)
        return done

    monkeypatch.setattr(directory_bridge.directory_runtime, "get_open_directory_store", lambda: SimpleNamespace(
        repository=SimpleNamespace(
            upsert_directory_session=upsert,
            get_session=lambda *_args, **_kwargs: None,
        ),
    ))
    monkeypatch.setattr(directory_bridge, "_ensure_agent_revision", lambda *_: "revision-a")
    directory_bridge.sync_conversation_record({
        "conversation_id": "session-a", "agent_id": "agent-a", "title": "A",
        "last_turn_status": terminal_status,
    })
    assert writes[0]["status"] == terminal_status


def test_archive_directory_session_safe_can_return_before_archive_finishes(monkeypatch):
    pending_archive = Future()
    archived_session_ids = []

    def schedule_archive(session_id):
        archived_session_ids.append(session_id)
        return pending_archive

    repository = SimpleNamespace(
        archive_directory_session=schedule_archive,
    )
    monkeypatch.setattr(
        directory_bridge.directory_runtime,
        "get_open_directory_store",
        lambda: SimpleNamespace(repository=repository),
    )

    returned = directory_bridge.archive_directory_session_safe("session-live", wait=False)

    assert returned is pending_archive
    assert pending_archive.done() is False
    assert archived_session_ids == ["session-live"]


def test_archive_directory_session_safe_returns_failed_future_when_dispatch_fails(monkeypatch):
    def fail_archive_dispatch(_session_id):
        raise OSError("simulated writer queue failure")

    monkeypatch.setattr(
        directory_bridge.directory_runtime,
        "get_open_directory_store",
        lambda: SimpleNamespace(
            repository=SimpleNamespace(archive_directory_session=fail_archive_dispatch),
        ),
    )

    returned = directory_bridge.archive_directory_session_safe("session-live", wait=False)

    assert returned is not None
    assert isinstance(returned.exception(), OSError)


def test_query_session_summaries_serves_bounded_startup_empty_page(monkeypatch):
    """Mid-startup queries stay non-blocking but never look like real empty data."""

    observed_timeouts: list[float] = []

    def fake_wait(*, timeout):
        observed_timeouts.append(timeout)
        return "starting"

    monkeypatch.setattr(
        directory_bridge.directory_runtime,
        "wait_for_directory_startup",
        fake_wait,
    )

    payload = directory_bridge.query_session_summaries()

    assert payload is not None
    assert payload["items"] == []
    assert payload["nextCursor"] == ""
    # The wait must stay the bounded startup backstop, not the 30s full wait.
    assert observed_timeouts == [directory_bridge.directory_runtime.LIST_QUERY_STARTUP_WAIT_SECONDS]


def test_list_session_summaries_serves_bounded_startup_empty_page(monkeypatch):
    monkeypatch.setattr(
        directory_bridge.directory_runtime,
        "wait_for_directory_startup",
        lambda *, timeout: "starting",
    )

    assert directory_bridge.list_session_summaries() == []


def test_query_session_summaries_proceeds_past_gate_once_startup_resolves(monkeypatch):
    """A wait that resolves to a terminal phase must reach the store read path."""

    degraded_sources: list[str] = []
    monkeypatch.setattr(
        directory_bridge,
        "note_session_read_degraded",
        lambda *, source, error_type="": degraded_sources.append(source),
    )
    monkeypatch.setattr(
        directory_bridge.directory_runtime,
        "wait_for_directory_startup",
        lambda *, timeout: "ready",
    )
    monkeypatch.setattr(
        directory_bridge.directory_runtime,
        "get_open_directory_store",
        lambda: None,
    )

    # A missing store on the resolved path reports degraded instead of serving
    # the startup empty page, proving the gate no longer holds the query.
    assert directory_bridge.query_session_summaries() is None
    assert degraded_sources == ["session query"]


def test_pure_read_chain_leaves_directory_recency_untouched(tmp_path, monkeypatch):
    """ISS-059 regression: a pure read must not reorder the session list.

    The financial GETs (schedules/batches list, single batch get — including
    the 404 case) all resolve ownership through ``get_financial_team`` →
    ``_native_session_model_is_executable`` → ``get_session_llm_options``.
    That read chain used to re-sync the existing directory row with
    ``touch_recency=True``, bumping ``recency_at_ms`` on every bare GET.
    """

    from core.web.services.session import agent_runtime

    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path / "operator-data"))
    from core.infrastructure import developer_sandbox

    monkeypatch.setattr(developer_sandbox, "is_developer_mode_enabled", lambda: False)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    directory_runtime.shutdown_session_directory_runtime()
    monkeypatch.setattr(directory_runtime, "_import_agent_snapshots", lambda *_args: 0)
    monkeypatch.setattr(
        directory_runtime, "_restore_missing_personal_direct_sessions", lambda *_args: 0
    )
    monkeypatch.setattr(
        directory_runtime, "_migrate_legacy_chat_state_once", lambda *_args: (False, 0, False)
    )
    monkeypatch.setattr(directory_runtime, "_record", lambda *_args, **_kwargs: None)

    agent = {
        "agentId": "agent-a",
        "configRevision": 4,
        "llmBindings": {"dialogue": {"modelId": "provider/model-a"}},
    }

    def fake_model_choice(_session_id):
        return {
            "modelId": "provider/model-a",
            "modelRef": "provider/model-a",
            "reasoningEffortValues": ["low"],
            "defaultReasoningEffort": "low",
        }

    try:
        directory_runtime.begin_directory_startup()
        status = directory_runtime.initialize_session_directory_runtime(
            project_root=tmp_path,
            migrate_legacy_chat_state=False,
        )
        assert status.status == "ready"
        store = directory_runtime.get_open_directory_store()
        assert store is not None
        revision = store.repository.create_agent(
            agent_id="agent-a",
            display_name="Agent agent-a",
            kind="assistant",
            config={"modelId": "provider/model-a"},
            source="test",
        ).result(timeout=3)
        for session_id in ("session-new", "session-old"):
            store.repository.create_session(
                session_id=session_id,
                agent_id="agent-a",
                agent_config_revision_id=str(revision["configRevisionId"]),
                title=session_id,
            ).result(timeout=3)
        writer = store.database.open_writer()
        try:
            writer.execute(
                "UPDATE sessions SET recency_at_ms=? WHERE session_id=?", (2000, "session-new")
            )
            writer.execute(
                "UPDATE sessions SET recency_at_ms=? WHERE session_id=?", (1000, "session-old")
            )
        finally:
            writer.close()
        save_chat_state(
            tmp_path,
            {
                "version": 1,
                "active_conversation_id": "session-new",
                "conversations": [
                    {
                        "conversation_id": "session-new",
                        "agent_id": "agent-a",
                        "title": "session-new",
                    },
                    {
                        "conversation_id": "session-old",
                        "agent_id": "agent-a",
                        "title": "session-old",
                    },
                ],
            },
        )

        def recencies() -> dict[str, int]:
            with store.database.reader() as connection:
                return {
                    str(row[0]): int(row[1])
                    for row in connection.execute(
                        "SELECT session_id, recency_at_ms FROM sessions"
                    )
                }

        def directory_order() -> list[str]:
            page = store.repository.list_directory_page(limit=10)
            return [str(row["sessionId"]) for row in page["rows"]]

        recency_before = recencies()
        assert recency_before == {"session-new": 2000, "session-old": 1000}
        order_before = directory_order()
        assert order_before == ["session-new", "session-old"]

        # The exact probe the financial GET chain runs (config collaborators
        # faked; the ensure/sync path under test stays real).
        monkeypatch.setattr(session_service, "get_agent", lambda *_args, **_kwargs: dict(agent))
        monkeypatch.setattr(
            session_service,
            "_resolve_session_agent_llm",
            lambda *_args, **_kwargs: SimpleNamespace(reasoning_effort_requested=""),
        )
        monkeypatch.setattr(session_service, "_session_llm_model_choices", lambda: [fake_model_choice("")])
        monkeypatch.setattr(session_service, "_session_fixed_model_choice", fake_model_choice)
        monkeypatch.setattr(
            session_service,
            "_conversation_agent_dialogue_context_window_payload",
            lambda *_args, **_kwargs: {"limit": 64000, "maxLimit": 200000},
        )
        options = agent_runtime.get_session_llm_options("session-new")
        assert options["sessionId"] == "session-new"

        # The read changed neither recency nor the recency-ordered list.
        assert recencies() == recency_before
        assert directory_order() == order_before

        # Contrast: the default (mutation-path) ensure still refreshes recency.
        session_service._ensure_session_conversation_record(
            "session-new", source="test.mutation_ensure"
        )
        assert recencies()["session-new"] > 2000
    finally:
        directory_runtime.shutdown_session_directory_runtime()
