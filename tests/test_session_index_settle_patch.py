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


def test_settled_snapshot_without_subscribers_ships_a_patch(monkeypatch):
    """A background session settling must hand the rail the settled row.

    Without the patch every open window has to re-read the whole index just to
    learn that one row finished, so the frame carries the same fields the
    watched path sends.
    """

    from core.web.services import session_service as service
    from core.web.services.session import publish

    session_id = "settled-without-watcher"
    published: list[dict] = []

    monkeypatch.setattr(publish, "_service", lambda: service)
    monkeypatch.setattr(service, "_SESSION_STREAM_SUBSCRIBERS", {})
    monkeypatch.setattr(service, "_is_session_running", lambda _id: False)
    monkeypatch.setattr(service, "_record_session_detail_snapshot_published_event", lambda **kwargs: None)
    monkeypatch.setattr(
        service,
        "get_session_detail",
        lambda _id, **_kwargs: {
            "status": "ready",
            "currentPhase": "ready",
            "lastTurnStatus": "completed",
            "lastTurnTerminalTurnId": "turn-1",
            "terminalReason": "success",
            "messages": [{"id": "m"}],
        },
    )

    def capture(session_id, change_type, *, patch=None):
        published.append(
            {"sessionId": session_id, "changeType": change_type, "patch": dict(patch or {})}
        )
        return 0

    monkeypatch.setattr(session_index_stream, "publish_session_index_delta", capture)

    publish._publish_session_detail_snapshot(session_id)

    assert published == [
        {
            "sessionId": session_id,
            "changeType": "upsert",
            "patch": {
                "status": "ready",
                "currentPhase": "ready",
                "lastTurnStatus": "completed",
                "lastTurnTerminalTurnId": "turn-1",
                "terminalReason": "success",
            },
        }
    ]


def test_settled_snapshot_falls_back_to_a_bare_frame_when_detail_is_gone(monkeypatch):
    """A deleted or unreadable session still tells the rail to drop the row."""

    from core.web.services import session_service as service
    from core.web.services.session import publish

    session_id = "settled-unreadable"
    published: list[dict] = []

    monkeypatch.setattr(publish, "_service", lambda: service)
    monkeypatch.setattr(service, "_SESSION_STREAM_SUBSCRIBERS", {})
    monkeypatch.setattr(service, "_is_session_running", lambda _id: False)
    monkeypatch.setattr(service, "_record_session_detail_snapshot_published_event", lambda **kwargs: None)
    monkeypatch.setattr(service, "get_session_detail", lambda _id, **_kwargs: None)

    def capture(session_id, change_type, *, patch=None):
        published.append({"sessionId": session_id, "patch": None if patch is None else dict(patch)})
        return 0

    monkeypatch.setattr(session_index_stream, "publish_session_index_delta", capture)

    publish._publish_session_detail_snapshot(session_id)

    assert published == [{"sessionId": session_id, "patch": None}]
