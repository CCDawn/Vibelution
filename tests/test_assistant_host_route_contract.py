"""Contract pins for the assistant host narrow copy of the platform session API.

Freezes the drift surface between core/assistant_runtime/host.py (the private
launcher boundary) and the platform source of truth core/web/routes/sessions.py:

1. Request-model field gap: host ``Message`` vs platform ``SessionMessagePayload``
   (forwarded field-for-field in ``session_submit_message``). The frozen gap is
   the literal ``platform_fields - host_fields`` snapshot taken at main=7269e3c68.
   The platform growing a field widens the gap; the host growing one shrinks it;
   both turn red and force a conscious snapshot update instead of silent drift.
   ``message``/``requestId`` on the host are renamed equivalents of
   ``content``/``clientSubmissionId`` on the platform, so they appear in the raw
   gap snapshot alongside the true semantic gaps.
2. Forwarding forks hardcoded in core/assistant_runtime/native.py: ``submit``
   pins ``queue_if_busy=True`` while ``continue_turn`` pins ``content="继续"`` +
   ``queue_if_busy=False``. These pins record the existing divergence from the
   platform payload contract (which honours the caller's ``queueIfBusy``);
   recording is not endorsement.
3. Event-stream single source: host ``NativeFacade.events`` and the platform
   ``GET /sessions/{session_id}/events`` route must resolve to the same
   ``core.web.services.session.publish.stream_session_events_async`` function
   object, with the host pinning ``initial="full"`` and the fixed
   ``assistant["directSessionId"]``, guarded by the private launcher boundary
   (constant-time bearer comparison plus Origin rejection).
"""

import inspect
import threading

import pytest
from fastapi.testclient import TestClient

from core.assistant_runtime.host import Message, NativeFacade, QueuedTurn, SendNowQueuedTurn, UpdateQueuedTurn, create_app

# Frozen snapshot of set(SessionMessagePayload.model_fields) -
# set(Message.model_fields), rebased to the references support already shipped
# in 3b47d0e948. The raw field gap shrank from 12 to 11; forwarding is pinned below.
FROZEN_HOST_FIELD_GAP = frozenset({
    "clientSubmissionId",  # renamed host equivalent: requestId
    "content",  # renamed host equivalent: message
    "contentUtf8Base64",
    "mentalModelEnabled",
    "runtimeStatusEnabled",
    "turnStatusTail",
    "turnMode",
    "writeIntent",
    "queueIfBusy",
    "modelSelection",
    "continuation",
})

HOST_MESSAGE_FIELDS = frozenset({"message", "requestId", "attachmentIds", "references"})

ASSISTANT = {"agentId": "local-assistant", "directSessionId": "native-session"}
AUTH = {"Authorization": "Bearer private-test-token"}


def test_private_queue_models_keep_a_closed_fixed_session_transport():
    assert set(QueuedTurn.model_fields) == {"queuedTurnId"}
    assert set(UpdateQueuedTurn.model_fields) == {"queuedTurnId", "content", "position", "status"}
    assert set(SendNowQueuedTurn.model_fields) == {"queuedTurnId", "expectedTurnId"}
    for model in (QueuedTurn, UpdateQueuedTurn, SendNowQueuedTurn):
        assert model.model_config["extra"] == "forbid"
        assert model.model_config["strict"] is True


def test_private_queue_facade_only_forwards_to_native_adapter(monkeypatch):
    from core.assistant_runtime import native

    calls = []
    for name in ("update_queued_turn", "remove_queued_turn", "send_now_queued_turn"):
        monkeypatch.setattr(native, name, lambda *args, _name=name, **kwargs:
                            calls.append((_name, args, kwargs)) or {"queuedTurns": []})
    facade = NativeFacade.__new__(NativeFacade)
    facade.update_queued_turn("queued-one", content="edited", position=1, status="paused")
    facade.remove_queued_turn("queued-one")
    facade.send_now_queued_turn("queued-one", expected_turn_id="observed-turn")
    assert calls == [("update_queued_turn", ("queued-one",), {"content": "edited", "position": 1, "status": "paused"}),
                     ("remove_queued_turn", ("queued-one",), {}),
                     ("send_now_queued_turn", ("queued-one",), {"expected_turn_id": "observed-turn"})]


@pytest.fixture(autouse=True)
def _private_operator_config(tmp_path, monkeypatch, reset_singletons):
    config_path = tmp_path / "operator" / "config.toml"
    config_path.parent.mkdir()
    config_path.write_text("", encoding="utf-8")
    monkeypatch.setenv("VIBELUTION_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("VIBELUTION_CONFIG_HOME", str(config_path.parent))
    from config import settings

    monkeypatch.setattr(settings, "_settings", None)
    monkeypatch.setattr(settings, "_config_path", str(config_path))


class _FakeSessionService:
    """Stand-in for core.web.services.session_service as seen by native._services()."""

    SessionNotFoundError = type("SessionNotFoundError", (Exception,), {})
    SessionBusyError = type("SessionBusyError", (Exception,), {})
    SessionValidationError = type("SessionValidationError", (Exception,), {})

    def __init__(self):
        self.lightweight_calls = []

    def submit_session_message_lightweight(self, session_id, message, **kwargs):
        self.lightweight_calls.append((session_id, message, kwargs))
        return {"accepted": True, "sessionId": session_id,
                "clientSubmissionId": kwargs.get("client_submission_id", "")}


@pytest.fixture
def fake_native_state(monkeypatch):
    """Drive the real native.submit/continue_turn path against a captured fake
    session service, so the hardcoded forwarding kwargs become observable
    without booting a real native session."""
    from core.assistant_runtime import native

    fake = _FakeSessionService()
    monkeypatch.setattr(native, "_services", lambda: (None, None, fake, None))
    monkeypatch.setattr(native, "_projection", lambda: {"assistant": dict(ASSISTANT)})
    monkeypatch.setattr(native, "_STARTED", True)
    monkeypatch.setattr(native, "_SESSION_ID", ASSISTANT["directSessionId"])
    monkeypatch.setattr(native, "_AGENT_ID", ASSISTANT["agentId"])
    monkeypatch.setattr(native, "_STOP_REQUESTED", threading.Event())
    monkeypatch.setattr(native, "_QUIESCING", False)
    monkeypatch.setattr(native, "_OFFLINE_MIGRATION", False)
    return fake


def test_host_message_field_gap_matches_frozen_platform_snapshot():
    from core.web.routes import sessions as platform_sessions

    host_fields = set(Message.model_fields)
    platform_fields = set(platform_sessions.SessionMessagePayload.model_fields)
    assert host_fields == set(HOST_MESSAGE_FIELDS)
    assert platform_fields - host_fields == set(FROZEN_HOST_FIELD_GAP)
    # Every platform payload field must actually be forwarded by the platform
    # handler; keeps the "forwarded set" honest instead of model-only.
    handler_source = inspect.getsource(platform_sessions.session_submit_message)
    unforwarded = {name for name in platform_fields if name not in handler_source}
    assert unforwarded == set()


def test_host_submit_pins_queue_if_busy_true_diverging_from_platform_default(fake_native_state):
    # Recorded fork: the platform honours the caller's queueIfBusy (default
    # False) while the launcher host hardcodes queue_if_busy=True. This pin
    # documents current behaviour; it is not an endorsement.
    # TestClient without a context manager skips the lifespan, so no native
    # owner is booted; the route -> facade -> native module -> fake sessions
    # chain under test is fully real.
    client = TestClient(create_app(native=NativeFacade(None), token="private-test-token"),
                        base_url="http://127.0.0.1", headers=AUTH)
    response = client.post("/api/assistant/messages",
                           json={"message": "hello", "requestId": "submit-pin-1"})
    assert response.status_code == 200
    assert fake_native_state.lightweight_calls == [
        ("native-session", "hello",
         {"client_submission_id": "submit-pin-1", "queue_if_busy": True, "attachment_ids": None, "references": None}),
    ]


def test_host_submit_forwards_reference_objects_to_the_native_owner(fake_native_state):
    client = TestClient(create_app(native=NativeFacade(None), token="private-test-token"),
                        base_url="http://127.0.0.1", headers=AUTH)
    references = [{"referenceType": "session", "sessionId": "reference-session"}]
    response = client.post("/api/assistant/messages", json={
        "message": "hello", "requestId": "submit-reference-pin", "references": references,
    })
    assert response.status_code == 200
    assert fake_native_state.lightweight_calls == [
        ("native-session", "hello", {"client_submission_id": "submit-reference-pin", "queue_if_busy": True,
                                      "attachment_ids": None, "references": references}),
    ]


def test_host_continue_pins_literal_content_and_no_queue(fake_native_state):
    # Recorded fork: the platform forwards arbitrary content; the launcher host
    # hardcodes content="继续" and queue_if_busy=False. Documentation, not
    # endorsement.
    continuation = {"turnId": "old-turn", "headId": "old-head", "ledgerSeq": 3, "agentId": "local-assistant"}
    client = TestClient(create_app(native=NativeFacade(None), token="private-test-token"),
                        base_url="http://127.0.0.1", headers=AUTH)
    response = client.post("/api/assistant/continue",
                           json={"requestId": "continue-pin-1", "continuation": continuation})
    assert response.status_code == 202
    assert fake_native_state.lightweight_calls == [
        ("native-session", "继续",
         {"client_submission_id": "continue-pin-1", "queue_if_busy": False,
          "_continuation_expected": continuation}),
    ]


def test_events_stream_function_is_shared_between_host_and_platform():
    from core.web.routes import sessions as platform_sessions
    from core.web.services import session_service
    from core.web.services.session import publish

    # The platform route module, the session_service facade both the route and
    # the host facade resolve through, and publish itself must be one function
    # object, so the host cannot silently fork the event stream implementation.
    assert platform_sessions.stream_session_events_async is publish.stream_session_events_async
    assert session_service.stream_session_events_async is publish.stream_session_events_async
    assert platform_sessions.resolve_session_stream_initial_payload is publish.resolve_session_stream_initial_payload
    assert session_service.parse_session_stream_last_event_id is publish.parse_session_stream_last_event_id
    assert session_service.resolve_session_stream_initial_payload is publish.resolve_session_stream_initial_payload


def test_events_route_enforces_private_launcher_boundary():
    client = TestClient(create_app(native=NativeFacade(None), token="private-test-token"),
                        base_url="http://127.0.0.1")
    assert client.get("/api/assistant/events").status_code == 401
    assert client.get("/api/assistant/events",
                      headers={**AUTH, "Origin": "https://evil.invalid"}).status_code == 403


def test_host_events_stream_pins_full_initial_and_fixed_direct_session(monkeypatch):
    from core.web.services import session_service

    seen = []

    async def spy_stream(session_id, **kwargs):
        seen.append((session_id, kwargs))
        yield "event: ping\ndata: {}\n\n"

    monkeypatch.setattr(session_service, "stream_session_events_async", spy_stream)
    facade = NativeFacade(None)
    facade.assistant = dict(ASSISTANT)
    client = TestClient(create_app(native=facade, token="private-test-token"),
                        base_url="http://127.0.0.1", headers=AUTH)
    response = client.get("/api/assistant/events", headers={"Last-Event-ID": "7"})
    assert response.status_code == 200
    assert "text/event-stream" in response.headers.get("content-type", "")
    assert seen == [("native-session", {"initial": "full", "last_event_id": 7})]
