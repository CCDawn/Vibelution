"""The Launcher budget adapter stays on its fixed native Agent/Session."""

import threading

import pytest
from fastapi.testclient import TestClient

from core.assistant_runtime import native
from core.assistant_runtime.budget_parameters import AssistantBudgetParameters
from core.assistant_runtime.host import NativeFacade, create_app
from core.web.services import agent_directory_service as directory
from core.web.services import personal_assistant_service as personal
from core.web.services import session_service as sessions
from tests.test_personal_assistant_service import finance_env, personal_env


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


@pytest.fixture
def native_owner(personal_env, monkeypatch):
    assistant = personal.create_personal_assistant()["assistant"]
    monkeypatch.setattr(native, "_STARTED", True)
    monkeypatch.setattr(native, "_AGENT_ID", assistant["agentId"])
    monkeypatch.setattr(native, "_SESSION_ID", assistant["directSessionId"])
    monkeypatch.setattr(native, "_STOP_REQUESTED", threading.Event())
    monkeypatch.setattr(native, "_OFFLINE_MIGRATION", False)
    monkeypatch.setattr(native, "_QUIESCING", False)
    return assistant


def test_native_budget_reuses_owner_and_saves_while_running(native_owner, monkeypatch):
    from core.web.services.session import journal_bridge

    aid, sid = native_owner["agentId"], native_owner["directSessionId"]
    before = directory.get_agent(aid)
    journal = journal_bridge.load_session_conversation_events_snapshot(sid, project_root=sessions.PROJECT_ROOT)
    initial = sessions.get_session_budget_parameters_view(sid)
    calls = []
    real_get = sessions.get_session_budget_parameters_view
    real_update = sessions.update_session_budget_parameters

    def get(session_id):
        assert personal._LOCK._is_owned()
        calls.append(("get", session_id))
        return real_get(session_id)

    def update(session_id, **kwargs):
        assert personal._LOCK._is_owned()
        calls.append(("update", session_id, kwargs))
        return real_update(session_id, **kwargs)

    def forbid_idle(*_args):
        pytest.fail("Saving a future-turn budget must not require an idle Session")

    monkeypatch.setattr(sessions, "get_session_budget_parameters_view", get)
    monkeypatch.setattr(sessions, "update_session_budget_parameters", update)
    monkeypatch.setattr(native, "_assert_session_idle", forbid_idle)
    monkeypatch.setitem(sessions._SESSION_ACTIVE_TURN_IDS, sid, "running-turn")
    assert native.budget_parameters() == initial
    revision = initial["revision"]
    for value in (0, None, 1, 200):
        updated = native.set_budget_parameters(value, revision)
        assert updated == {"revision": revision + 1, "maxCallsPerTurn": value}
        assert native.budget_parameters() == real_get(sid) == updated
        assert calls[-2] == ("update", sid, {"expected_revision": revision, "max_calls_per_turn": value})
        revision = updated["revision"]
    assert all(call[1] == sid for call in calls)
    after = directory.get_agent(aid)
    for field in ("toolPolicy", "permissionPreset", "llmBindings", "personaProfile", "taskProfile"):
        assert after.get(field) == before.get(field), field
    assert sessions._SESSION_ACTIVE_TURN_IDS[sid] == "running-turn"
    assert journal_bridge.load_session_conversation_events_snapshot(sid, project_root=sessions.PROJECT_ROOT) == journal
    with pytest.raises(native.AssistantSessionError, match="^ASSISTANT_BUDGET_CONFLICT$"):
        native.set_budget_parameters(0, initial["revision"])


@pytest.mark.parametrize("value,revision", [(True, 0), (4.0, 0), ("4", 0), (-1, 0), (201, 0),
                                           (None, True), (None, 0.0), (None, -1), (None, "0")])
def test_native_budget_rejects_invalid_values_before_owner_access(monkeypatch, value, revision):
    monkeypatch.setattr(native, "_services", lambda: pytest.fail("Invalid input reached an owner"))
    with pytest.raises(native.AssistantSessionError, match="^ASSISTANT_BUDGET_INVALID$"):
        native.set_budget_parameters(value, revision)


@pytest.mark.parametrize("binding", ["agent", "session", "reverse"])
def test_native_budget_rejects_identity_changes_without_service_calls(native_owner, monkeypatch, binding):
    if binding == "agent":
        monkeypatch.setattr(native, "_AGENT_ID", "foreign-agent")
    elif binding == "session":
        monkeypatch.setattr(native, "_SESSION_ID", "foreign-session")
    else:
        monkeypatch.setattr(sessions, "_session_agent_id_snapshot", lambda _sid: "foreign-agent")
    monkeypatch.setattr(sessions, "get_session_budget_parameters_view", lambda *_a: pytest.fail("Foreign read"))
    monkeypatch.setattr(sessions, "update_session_budget_parameters", lambda *_a, **_k: pytest.fail("Foreign write"))
    # All three branches are identity breaks; they surface the rebuild code,
    # not the retryable budget-unavailable fold.
    with pytest.raises(native.AssistantSessionError, match="^ASSISTANT_IDENTITY_INVALID$"):
        native.budget_parameters()
    with pytest.raises(native.AssistantSessionError, match="^ASSISTANT_IDENTITY_INVALID$"):
        native.set_budget_parameters(0, 0)


def test_budget_identity_break_and_owner_failure_stay_distinguishable(native_owner, monkeypatch):
    """Regression: an identity break and a generic owner failure used to share
    ASSISTANT_BUDGET_UNAVAILABLE; the desktop must be able to tell rebuild
    (identity) apart from retry-later (owner failure)."""
    monkeypatch.setattr(sessions, "_session_agent_id_snapshot", lambda _sid: "foreign-agent")
    with pytest.raises(native.AssistantSessionError, match="^ASSISTANT_IDENTITY_INVALID$"):
        native.budget_parameters()
    monkeypatch.setattr(sessions, "_session_agent_id_snapshot", lambda _sid: native_owner["agentId"])

    def unavailable(*_args, **_kwargs):
        raise RuntimeError("PRIVATE_CONFIGURATION_SENTINEL")

    monkeypatch.setattr(sessions, "get_session_budget_parameters_view", unavailable)
    with pytest.raises(native.AssistantSessionError, match="^ASSISTANT_BUDGET_UNAVAILABLE$"):
        native.budget_parameters()


def test_native_budget_serializes_generic_identity_writers(native_owner, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    aid, sid = native_owner["agentId"], native_owner["directSessionId"]
    revision = sessions.get_session_budget_parameters_view(sid)["revision"]
    attempted, finished = threading.Event(), threading.Event()
    original_settings = native.assistant_settings

    def replace_binding():
        attempted.set()
        directory.update_agent_instance(aid, direct_session_id="replacement-session")
        finished.set()

    with ThreadPoolExecutor(max_workers=1) as pool:
        writers = []

        def settings_then_replace():
            result = original_settings()
            writers.append(pool.submit(replace_binding))
            assert attempted.wait(2)
            assert not finished.wait(0.05), "Identity changed inside the budget owner transaction"
            return result

        monkeypatch.setattr(native, "assistant_settings", settings_then_replace)
        assert native.set_budget_parameters(0, revision) == {"revision": revision + 1, "maxCallsPerTurn": 0}
        writers[0].result(timeout=5)
    assert finished.is_set()
    assert directory.get_agent(aid)["metadata"]["sessionBudgetParameters"] == {"maxCallsPerTurn": 0}
    # The replaced direct Session is an identity break, not a busy endpoint.
    with pytest.raises(native.AssistantSessionError, match="^ASSISTANT_IDENTITY_INVALID$"):
        native.set_budget_parameters(200, revision + 1)


def test_native_budget_sanitizes_owner_failures_and_bad_responses(native_owner, monkeypatch):
    def unavailable(*_args, **_kwargs):
        raise RuntimeError("PRIVATE_CONFIGURATION_SENTINEL")

    monkeypatch.setattr(sessions, "get_session_budget_parameters_view", unavailable)
    monkeypatch.setattr(sessions, "update_session_budget_parameters", unavailable)
    for operation in (native.budget_parameters, lambda: native.set_budget_parameters(None, 0)):
        with pytest.raises(native.AssistantSessionError, match="^ASSISTANT_BUDGET_UNAVAILABLE$"):
            operation()
    monkeypatch.setattr(sessions, "get_session_budget_parameters_view",
                        lambda _sid: {"revision": 0, "maxCallsPerTurn": False, "secret": "PRIVATE_SENTINEL"})
    with pytest.raises(native.AssistantSessionError, match="^ASSISTANT_BUDGET_UNAVAILABLE$"):
        native.budget_parameters()


def test_facade_forwards_budget_without_an_arbitrary_identity(monkeypatch):
    calls = []
    monkeypatch.setattr(native, "budget_parameters", lambda: {"revision": 7, "maxCallsPerTurn": None})
    monkeypatch.setattr(native, "set_budget_parameters",
                        lambda *args: calls.append(args) or {"revision": 8, "maxCallsPerTurn": args[0]})
    facade = NativeFacade.__new__(NativeFacade)
    assert facade.budget_parameters() == {"revision": 7, "maxCallsPerTurn": None}
    assert facade.set_budget_parameters(0, 7) == {"revision": 8, "maxCallsPerTurn": 0}
    assert calls == [(0, 7)]


class _BudgetNative:
    def __init__(self):
        self.value = {"revision": 0, "maxCallsPerTurn": None}
        self.calls = []

    def bootstrap(self):
        return {"assistant": {"agentId": "local-assistant", "directSessionId": "native-session"}}

    def shutdown(self):
        pass

    def budget_parameters(self):
        self.calls.append("get")
        return self.value

    def set_budget_parameters(self, max_calls_per_turn, expected_revision):
        self.calls.append((max_calls_per_turn, expected_revision))
        if expected_revision != self.value["revision"]:
            raise native.AssistantSessionError("ASSISTANT_BUDGET_CONFLICT")
        self.value = {"revision": expected_revision + 1, "maxCallsPerTurn": max_calls_per_turn}
        return self.value


_PATH = "/api/assistant/budget-parameters"
_AUTH = {"Authorization": "Bearer private-test-token"}


def test_host_budget_is_private_closed_and_has_explicit_response_contracts():
    owner = _BudgetNative()
    app = create_app(native=owner, token="private-test-token")
    routes = [route for route in app.routes if getattr(route, "path", None) == _PATH]
    assert len(routes) == 2
    assert all(route.response_model is AssistantBudgetParameters for route in routes)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        payload = {"revision": 0, "maxCallsPerTurn": 0}
        for method in ("GET", "PATCH"):
            args = {"json": payload} if method == "PATCH" else {}
            assert client.request(method, _PATH, **args).status_code == 401
            assert client.request(method, _PATH, headers={**_AUTH, "Origin": "https://evil.invalid"}, **args).status_code == 403
            queried = client.request(method, _PATH + "?sessionId=foreign", headers=_AUTH, **args)
            assert queried.status_code == 422
            assert queried.json()["detail"]["code"] == "ASSISTANT_BUDGET_INVALID"
        invalid = [{}, {"revision": 0}, {"maxCallsPerTurn": 0},
                   {**payload, "revision": True}, {**payload, "revision": 0.0}, {**payload, "revision": -1},
                   {**payload, "maxCallsPerTurn": True}, {**payload, "maxCallsPerTurn": 2.0},
                   {**payload, "maxCallsPerTurn": "2"}, {**payload, "maxCallsPerTurn": -1},
                   {**payload, "maxCallsPerTurn": 201}, {**payload, "sessionId": "foreign"},
                   {**payload, "agentId": "foreign"}, {**payload, "unknown": "PRIVATE_INPUT_SENTINEL"}]
        for body in invalid:
            rejected = client.patch(_PATH, json=body, headers=_AUTH)
            assert rejected.status_code == 422, body
            assert rejected.json()["detail"]["code"] == "ASSISTANT_BUDGET_INVALID"
            assert "PRIVATE_INPUT_SENTINEL" not in rejected.text
        assert not owner.calls
        observed = client.get(_PATH, headers=_AUTH)
        assert observed.json() == owner.value
        assert observed.headers["Cache-Control"] == "no-store"
        for revision, value in enumerate((0, None, 1, 200)):
            saved = client.patch(_PATH, json={"revision": revision, "maxCallsPerTurn": value}, headers=_AUTH)
            assert saved.status_code == 200
            assert saved.json() == {"revision": revision + 1, "maxCallsPerTurn": value}
            assert saved.headers["Cache-Control"] == "no-store"
        conflict = client.patch(_PATH, json=payload, headers=_AUTH)
        assert conflict.status_code == 409
        assert conflict.json()["detail"]["code"] == "ASSISTANT_BUDGET_CONFLICT"


def test_host_budget_reports_unavailable_without_exposing_internal_details():
    owner = _BudgetNative()
    owner.budget_parameters = None
    owner.set_budget_parameters = None
    with TestClient(create_app(native=owner, token="private-test-token"), base_url="http://127.0.0.1", headers=_AUTH) as client:
        for method in ("GET", "PATCH"):
            args = {"json": {"revision": 0, "maxCallsPerTurn": None}} if method == "PATCH" else {}
            result = client.request(method, _PATH, **args)
            assert result.status_code == 503
            assert result.json()["detail"]["code"] == "ASSISTANT_BUDGET_UNAVAILABLE"
