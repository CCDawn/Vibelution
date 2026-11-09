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


def _same_second_rows() -> list[dict[str, str]]:
    """Rows sharing second-level timestamps so the tiebreak decides the order."""

    return [
        {"sessionId": "session-old-a", "updatedAt": "2026-01-01T00:00:00"},
        {"sessionId": "session-tie-z", "updatedAt": "2026-01-01T00:00:01"},
        {"sessionId": "session-tie-m", "updatedAt": "2026-01-01T00:00:01"},
        {"sessionId": "session-new", "updatedAt": "2026-01-01T00:00:02"},
        {"sessionId": "session-tie-a", "updatedAt": "2026-01-01T00:00:01"},
        {"sessionId": "session-old-z", "updatedAt": "2026-01-01T00:00:00"},
    ]


_SAME_SECOND_EXPECTED_ORDER = [
    "session-new",
    "session-tie-z",
    "session-tie-m",
    "session-tie-a",
    "session-old-z",
    "session-old-a",
]


def _fake_summary_from_directory_row(row, **_kwargs):
    updated_at = str(row.get("updatedAt") or "")
    return {"id": str(row.get("sessionId") or ""), "updatedAt": updated_at, "lastActive": updated_at}


def _patch_directory_list_paths(monkeypatch, rows):
    """Fake the directory store plumbing around list_session_summaries."""

    store = SimpleNamespace(
        repository=SimpleNamespace(
            list_directory_page=lambda **_kwargs: {"rows": list(rows), "nextCursor": ""},
        ),
    )
    monkeypatch.setattr(
        directory_bridge.directory_runtime,
        "wait_for_directory_startup",
        lambda *, timeout: "ready",
    )
    monkeypatch.setattr(
        directory_bridge.directory_runtime,
        "get_open_directory_store",
        lambda: store,
    )
    monkeypatch.setattr(directory_bridge, "_chat_state_directory_overlay", lambda: ({}, {}))
    monkeypatch.setattr(directory_bridge, "_session_runtime_status_snapshot", lambda: {})
    monkeypatch.setattr(
        directory_bridge, "_summary_from_directory_row", _fake_summary_from_directory_row
    )
    monkeypatch.setattr(
        directory_bridge,
        "_filter_user_directory_summaries",
        lambda summaries, *, include_hidden: summaries,
    )
    monkeypatch.setattr(
        directory_bridge,
        "_merge_agent_directory_stub_summaries",
        lambda summaries, **_kwargs: summaries,
    )
    monkeypatch.setattr(
        directory_bridge, "_with_terminal_states", lambda items, *, store: items
    )
    monkeypatch.setattr(session_service, "_agent_lookup_for_conversations", lambda: {})


def test_list_session_summaries_orders_same_second_rows_by_session_id_desc(monkeypatch):
    """Same-second rows tiebreak on session id DESC (SQL repository direction)."""

    rows = list(reversed(_same_second_rows()))  # input order must not matter
    _patch_directory_list_paths(monkeypatch, rows)

    summaries = directory_bridge.list_session_summaries()

    assert [item["id"] for item in summaries] == _SAME_SECOND_EXPECTED_ORDER


def test_directory_and_legacy_projection_paths_agree_on_same_second_order(monkeypatch):
    """The core regression: both read paths order one same-second batch alike.

    Path switching (cache miss, stale projection, degraded directory) used to
    flip same-second groups because the directory path inherited the SQL
    session_id DESC order while the legacy projection tiebreaked by id ASC.
    """

    from types import SimpleNamespace as Namespace

    from core.web.services.session import projection

    rows = _same_second_rows()

    # Path 1: directory store.
    _patch_directory_list_paths(monkeypatch, rows)
    directory_order = [
        item["id"] for item in (directory_bridge.list_session_summaries() or [])
    ]

    # Path 2: legacy projection rebuild, same rows projected through the
    # lightweight summary builder with the directory read forced unavailable.
    monkeypatch.setattr(
        directory_bridge, "list_session_summaries", lambda **_kwargs: None
    )
    conversations = [
        {"id": row["sessionId"], "updatedAt": row["updatedAt"]} for row in rows
    ]
    fake_service = Namespace(
        _perf_counter=lambda: 0.0,
        _elapsed_ms=lambda _start: 0,
        _agent_lookup_for_conversations=lambda: {},
        _agent_directory_stub_hidden_team_member_ids=lambda: set(),
        _load_conversations=lambda **_kwargs: (None, conversations),
        _append_agent_directory_conversations=lambda conversations, **_kwargs: conversations,
        _build_session_summary=lambda item, **_kwargs: {
            "id": item["id"],
            "updatedAt": item["updatedAt"],
            "lastActive": item["updatedAt"],
        },
        _record_session_agent_missing_index_batch_event=lambda items, **_kwargs: None,
        _timestamp_sort_key=session_service._timestamp_sort_key,
        _session_list_source_signature=lambda: ("test-source",),
    )
    result = projection._build_session_list_data(fake_service, include_hidden_internal=True)
    assert result.source == "legacy_projection"
    legacy_order = [item["id"] for item in result.sessions]

    assert legacy_order == directory_order
    # And the shared order is the canonical SQL tiebreak: same-second id DESC.
    assert legacy_order == _SAME_SECOND_EXPECTED_ORDER


@pytest.mark.parametrize(
    ("sort", "expected_ids"),
    [
        # updatedAt_desc is the canonical direction: ts DESC then id DESC.
        (
            "updatedAt_desc",
            ["session-b", "session-z", "session-m", "session-a"],
        ),
        # The id tiebreak stays DESC regardless of the primary direction (the
        # SQL repository direction), so the catalog mirror and every read path
        # agree on one same-key batch order.
        (
            "updatedAt_asc",
            ["session-z", "session-m", "session-a", "session-b"],
        ),
        (
            "title_asc",
            ["session-m", "session-b", "session-z", "session-a"],
        ),
        (
            "title_desc",
            ["session-z", "session-a", "session-m", "session-b"],
        ),
    ],
)
def test_session_query_sort_key_tiebreaks_equal_keys_by_id(sort, expected_ids):
    """Shared query sort (directory query, body search, canonical fallback)."""

    items = [
        {"id": "session-a", "title": "Beta", "updatedAt": "2026-01-01T00:00:00"},
        {"id": "session-z", "title": "Beta", "updatedAt": "2026-01-01T00:00:00"},
        {"id": "session-m", "title": "Alpha", "updatedAt": "2026-01-01T00:00:00"},
        {"id": "session-b", "title": "Alpha", "updatedAt": "2026-01-01T00:01:00"},
    ]
    key = session_service._session_query_sort_key(sort)

    ordered = sorted(
        # Reversing the input proves the result does not depend on input order.
        list(reversed(items)),
        key=key,
        reverse=sort.endswith("_desc"),
    )

    assert [item["id"] for item in ordered] == expected_ids


def test_list_child_session_summaries_orders_same_second_rows_by_session_id_desc(
    monkeypatch,
):
    """Child session rows share the parent list's same-second tiebreak."""

    rows = list(reversed(_same_second_rows()))
    store = SimpleNamespace(
        repository=SimpleNamespace(
            get_session=lambda *_args, **_kwargs: None,
            list_child_sessions=lambda *_args, **_kwargs: rows,
        ),
    )
    monkeypatch.setattr(
        directory_bridge.directory_runtime,
        "wait_for_directory_startup",
        lambda *, timeout: "ready",
    )
    monkeypatch.setattr(
        directory_bridge.directory_runtime,
        "get_open_directory_store",
        lambda: store,
    )
    monkeypatch.setattr(directory_bridge, "_session_runtime_status_snapshot", lambda: {})
    monkeypatch.setattr(
        directory_bridge, "_summary_from_directory_row", _fake_summary_from_directory_row
    )
    monkeypatch.setattr(
        directory_bridge, "_with_terminal_states", lambda items, *, store: items
    )
    monkeypatch.setattr(session_service, "_agent_lookup_for_conversations", lambda: {})

    payload = directory_bridge.list_child_session_summaries("root-session")

    assert payload is not None
    assert payload["rootSessionId"] == "root-session"
    assert [item["id"] for item in payload["items"]] == _SAME_SECOND_EXPECTED_ORDER
