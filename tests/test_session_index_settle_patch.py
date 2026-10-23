"""Settled index patches and removal frames on the global session-index stream."""

from core.web.services.session import session_index_stream


def test_index_patch_from_detail_keeps_only_rail_fields():
    detail = {
        "lastActive": "2026-10-23T00:00:00Z",
        "status": "ready",
        "currentPhase": "ready",
        "lastTurnStatus": "completed",
        "lastTurnTerminalTurnId": "turn-1",
        "terminalReason": "success",
        "taskSummary": "done",
        # Heavy payloads must never ride along on an index frame.
        "messages": [{"id": "m"}],
        "toolApprovals": [{"id": "t"}],
    }

    assert session_index_stream.index_patch_from_detail(detail) == {
        "lastActive": "2026-10-23T00:00:00Z",
        "status": "ready",
        "currentPhase": "ready",
        "lastTurnStatus": "completed",
        "lastTurnTerminalTurnId": "turn-1",
        "terminalReason": "success",
        "taskSummary": "done",
    }


def test_index_patch_from_detail_keeps_cleared_terminal_reason():
    # Clearing a terminal reason is a real change; dropping the key would leave
    # the stale value on screen.
    assert session_index_stream.index_patch_from_detail({"terminalReason": ""}) == {
        "terminalReason": ""
    }


def test_index_patch_from_detail_ignores_missing_detail():
    assert session_index_stream.index_patch_from_detail(None) == {}
    assert session_index_stream.index_patch_from_detail({}) == {}


def test_publish_change_safely_swallows_transport_errors(monkeypatch):
    def explode(*_args, **_kwargs):
        raise RuntimeError("no listeners")

    monkeypatch.setattr(session_index_stream, "publish_session_index_delta", explode)

    assert session_index_stream.publish_session_index_change_safely("s1", "remove") == 0


def test_archive_and_delete_normalize_to_removed():
    assert (
        session_index_stream.normalize_session_index_change_type("remove")
        == session_index_stream.SESSION_INDEX_CHANGE_REMOVED
    )
    assert (
        session_index_stream.normalize_session_index_change_type("archive")
        == session_index_stream.SESSION_INDEX_CHANGE_REMOVED
    )
    assert (
        session_index_stream.normalize_session_index_change_type("upsert")
        == session_index_stream.SESSION_INDEX_CHANGE_UPSERTED
    )
