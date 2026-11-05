"""The private assistant cache view reads only its fixed native usage owner."""

import json

import pytest
from fastapi.testclient import TestClient

from core.assistant_runtime import cache_usage, native
from core.assistant_runtime.host import NativeFacade, create_app
from core.llm import usage_ledger
from core.web.services import session_service as sessions
from core.web.services.session import directory_runtime
from tests.test_assistant_runtime_budget import _private_operator_config, native_owner
from tests.test_assistant_runtime_native import TEST_MODEL_CONFIG, _run
from tests.test_personal_assistant_service import finance_env, personal_env


@pytest.fixture
def usage_owner(native_owner, monkeypatch):
    root = sessions.PROJECT_ROOT
    monkeypatch.setattr(native, "assistant_native_root", lambda: root)
    monkeypatch.setattr(usage_ledger, "PROJECT_ROOT", root)
    monkeypatch.setattr(directory_runtime, "directory_store_project_root", lambda: root)
    return native_owner


def _record(owner, *, tokens=100, cached=0, observed=True, **kwargs):
    usage_ledger.record_usage_event(usage_ledger.UsageLedgerEvent(
        source="provider_usage", session_id=owner["directSessionId"], agent_id=owner["agentId"],
        input_tokens=tokens, cached_input_tokens=cached, cache_read_input_tokens=cached,
        total_tokens=tokens, cache_usage_observed=observed, **kwargs,
    ))


def test_native_summary_reads_cumulative_ledger_without_recent_detail(usage_owner, monkeypatch):
    monkeypatch.setattr(native, "get_detail", lambda *_a: pytest.fail("History is not a usage ledger"))
    empty = native.usage_summary()
    assert set(empty) == {"sessionId", "agentId", "sessionTokenUsage", "lastTokenUsage"}
    assert empty["sessionId"] == usage_owner["directSessionId"]
    assert empty["agentId"] == usage_owner["agentId"]
    assert empty["lastTokenUsage"]["source"] == "not_called"
    assert empty["sessionTokenUsage"]["cacheUsageObserved"] is False

    _record(usage_owner, cached=100)
    _record(usage_owner, tokens=900, cache_creation_input_tokens=450)
    _record({"agentId": "foreign-agent", "directSessionId": "foreign-session"}, tokens=999999, cached=999999)
    result = native.usage_summary()
    rollup = result["sessionTokenUsage"]
    assert rollup["cacheHitRate"] == 0.1  # 100/1000, not the two call rates' average.
    assert rollup["cachedInputTokens"] == 100
    assert rollup["cacheObservedInputTokens"] == 1000
    assert rollup["cacheCreationInputTokens"] == 450  # Writes are never hits.
    assert rollup["cacheObservedCallCount"] == 2
    assert rollup["cacheUsageComplete"] is True
    assert result["lastTokenUsage"]["cacheUsageObserved"] is True
    assert result["lastTokenUsage"]["cacheHitRate"] == 0

    _record(usage_owner, tokens=10000, observed=False,
            cache_usage_missing_reason="PRIVATE_PATH_SENTINEL")
    partial = native.usage_summary()
    assert partial["sessionTokenUsage"]["cacheHitRate"] == 0.1
    assert partial["sessionTokenUsage"]["cacheObservedInputTokens"] == 1000
    assert partial["sessionTokenUsage"]["cacheUnobservedCallCount"] == 1
    assert partial["sessionTokenUsage"]["cacheUsageComplete"] is False
    assert partial["sessionTokenUsage"]["cacheUsageMissingReason"] == "partial_provider_cache_usage"
    assert partial["lastTokenUsage"]["cacheUsageObserved"] is False
    assert partial["lastTokenUsage"]["cacheUsageMissingReason"] == "provider_cache_usage_missing"
    encoded = json.dumps(partial)
    for forbidden in ("globalTokenUsage", "agentTokenUsage", "diagnostics", "ledgerPath",
                      "providerUsageKeys", "runtimeSceneId", "PRIVATE_PATH_SENTINEL", "foreign-session"):
        assert forbidden not in encoded


@pytest.mark.parametrize("observed", [False, True])
def test_missing_cache_data_and_observed_zero_stay_distinct(usage_owner, observed):
    _record(usage_owner, observed=observed)
    summary = native.usage_summary()
    rollup, sample = summary["sessionTokenUsage"], summary["lastTokenUsage"]
    assert sample["cacheUsageObserved"] is observed
    assert rollup["cacheObservedCallCount"] == int(observed)
    assert rollup["cacheUnobservedCallCount"] == int(not observed)
    assert rollup["cacheUsageComplete"] is observed
    assert sample["cacheHitRate"] == 0


# Identity drift reports the rebuild code; process-root drift, ledger and
# directory-store failures stay the retryable usage-unavailable fold, and a
# stop already requested surfaces its real lifecycle code.
@pytest.mark.parametrize("binding,code", [
    ("agent", "ASSISTANT_IDENTITY_INVALID"), ("session", "ASSISTANT_IDENTITY_INVALID"),
    ("reverse", "ASSISTANT_IDENTITY_INVALID"), ("root", "ASSISTANT_USAGE_UNAVAILABLE"),
    ("ledger", "ASSISTANT_USAGE_UNAVAILABLE"), ("directory", "ASSISTANT_USAGE_UNAVAILABLE"),
    ("stopping", "ASSISTANT_STOPPING"),
])
def test_identity_drift_never_reaches_the_ledger(usage_owner, monkeypatch, binding, code):
    if binding == "agent":
        monkeypatch.setattr(native, "_AGENT_ID", "foreign-agent")
    elif binding == "session":
        monkeypatch.setattr(native, "_SESSION_ID", "foreign-session")
    elif binding == "reverse":
        monkeypatch.setattr(sessions, "_session_agent_id_snapshot", lambda _sid: "foreign-agent")
    elif binding == "root":
        monkeypatch.setattr(native, "assistant_native_root", lambda: sessions.PROJECT_ROOT / "foreign")
    elif binding == "ledger":
        monkeypatch.setattr(usage_ledger, "PROJECT_ROOT", sessions.PROJECT_ROOT / "foreign")
    elif binding == "directory":
        monkeypatch.setattr(directory_runtime, "directory_store_project_root", lambda: None)
    else:
        native._STOP_REQUESTED.set()
    monkeypatch.setattr(usage_ledger, "build_usage_summary", lambda **_kw: pytest.fail("Foreign ledger read"))
    with pytest.raises(native.AssistantSessionError, match=f"^{code}$"):
        native.usage_summary()


def test_ledger_failure_is_a_safe_error_and_not_an_empty_rollup(usage_owner, monkeypatch):
    def broken(**_kwargs):
        raise RuntimeError("PRIVATE_PATH_SENTINEL")
    monkeypatch.setattr(usage_ledger, "build_usage_summary", broken)
    with pytest.raises(native.AssistantSessionError, match="^ASSISTANT_USAGE_UNAVAILABLE$"):
        native.usage_summary()


def test_native_rechecks_forward_binding_under_owner_locks_before_reading_the_ledger(usage_owner, monkeypatch):
    from core.web.services import agent_directory_service as directory

    projection = native._projection
    agent_id, session_id = usage_owner["agentId"], usage_owner["directSessionId"]

    def snapshot_then_rebind():
        before = projection()
        directory.update_agent_instance(agent_id, direct_session_id="replacement-session")
        assert before["assistant"]["directSessionId"] == session_id
        assert sessions._session_agent_id_snapshot(session_id) == agent_id
        return before

    monkeypatch.setattr(native, "_projection", snapshot_then_rebind)
    monkeypatch.setattr(usage_ledger, "build_usage_summary", lambda **_kw: pytest.fail("Changed Agent binding reached ledger"))
    with pytest.raises(native.AssistantSessionError, match="^ASSISTANT_IDENTITY_INVALID$"):
        native.usage_summary()


def test_native_ledger_views_use_the_session_and_agent_intersection(usage_owner):
    foreign = {"agentId": "foreign-agent", "directSessionId": usage_owner["directSessionId"]}
    _record(foreign, tokens=10000, cached=10000)
    _record(usage_owner, cached=25)
    summary = native.usage_summary()
    assert summary["sessionTokenUsage"]["callCount"] == 1
    assert summary["sessionTokenUsage"]["inputTokens"] == 100
    assert summary["sessionTokenUsage"]["cacheHitRate"] == 0.25
    assert summary["lastTokenUsage"]["cachedInputTokens"] == 25
    _record(foreign, tokens=50, cached=50)
    assert native.usage_summary() == summary


def test_native_process_writer_and_reader_share_the_frozen_ledger_root(tmp_path):
    _run(tmp_path, """
        import os
        from core.infrastructure.native_runtime import assistant_native_root
        root = assistant_native_root()
        os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'] = str(root / 'wrong-project')
        from core.llm import usage_ledger
        from core.llm.client import record_usage_event
        from core.assistant_runtime import native
        assert usage_ledger.PROJECT_ROOT == root
        try:
            owner = native.bootstrap(root)['assistant']
            record_usage_event(usage_ledger.UsageLedgerEvent(source='provider_usage',
                session_id=owner['directSessionId'], agent_id=owner['agentId'], input_tokens=100,
                total_tokens=100, cached_input_tokens=25, cache_usage_observed=True))
            result = native.usage_summary()
            assert result['sessionId'] == owner['directSessionId']
            assert result['agentId'] == owner['agentId']
            assert result['sessionTokenUsage']['cacheHitRate'] == .25
            assert result['sessionTokenUsage']['callCount'] == 1
            assert usage_ledger.usage_ledger_path().is_relative_to(root)
        finally:
            native.shutdown()
    """, config_text=TEST_MODEL_CONFIG)


class _UsageNative:
    def __init__(self, value):
        self.value = value
        self.calls = 0

    def bootstrap(self):
        return {"assistant": {"agentId": self.value["agentId"], "directSessionId": self.value["sessionId"]}}

    def shutdown(self):
        pass

    def usage_summary(self):
        self.calls += 1
        return self.value


_PATH = "/api/assistant/usage-summary"
_AUTH = {"Authorization": "Bearer private-test-token"}


def test_http_usage_is_authenticated_parameterless_bounded_and_declares_its_model(usage_owner):
    owner = _UsageNative(native.usage_summary())
    app = create_app(native=owner, token="private-test-token")
    route = next(route for route in app.routes if getattr(route, "path", None) == _PATH)
    assert route.response_model is cache_usage.AssistantUsageSummary
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.get(_PATH).status_code == 401
        assert client.get(_PATH, headers={**_AUTH, "Origin": "https://evil.invalid"}).status_code == 403
        for suffix in ("?sessionId=foreign", "?agentId=foreign", "?scope=global", "?provider=x&provider=y"):
            response = client.get(_PATH + suffix, headers=_AUTH)
            assert response.status_code == 422
            assert response.json()["detail"]["code"] == "ASSISTANT_USAGE_INVALID"
        assert client.request("GET", _PATH, headers=_AUTH, json={"sessionId": "foreign"}).status_code == 422
        assert client.post(_PATH, headers=_AUTH).status_code == 405
        assert owner.calls == 0
        response = client.get(_PATH, headers=_AUTH)
        assert response.status_code == 200
        assert response.json() == owner.value
        assert response.headers["Cache-Control"] == "no-store"
        assert owner.calls == 1


@pytest.mark.parametrize("failure", ["missing", "throws", "global", "nested", "identity", "numeric"])
def test_http_usage_sanitizes_failures_and_refuses_overbroad_snapshots(usage_owner, failure):
    owner = _UsageNative(native.usage_summary())
    with TestClient(create_app(native=owner, token="private-test-token"),
                    base_url="http://127.0.0.1", headers=_AUTH) as client:
        if failure == "missing":
            owner.usage_summary = None
        elif failure == "throws":
            def broken():
                raise RuntimeError("PRIVATE_PATH_SENTINEL")
            owner.usage_summary = broken
        elif failure == "global":
            owner.value["globalTokenUsage"] = {"PRIVATE_PATH_SENTINEL": True}
        elif failure == "nested":
            owner.value["lastTokenUsage"]["ledgerPath"] = "PRIVATE_PATH_SENTINEL"
        elif failure == "identity":
            owner.value["sessionId"] = "foreign-session"
        else:
            owner.value["sessionTokenUsage"]["cachedInputTokens"] = True
        response = client.get(_PATH)
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "ASSISTANT_USAGE_UNAVAILABLE"
        assert "PRIVATE_PATH_SENTINEL" not in response.text


def test_facade_forwards_only_the_fixed_usage_read(monkeypatch):
    expected = {"fixed": "snapshot"}
    monkeypatch.setattr(native, "usage_summary", lambda: expected)
    assert NativeFacade.__new__(NativeFacade).usage_summary() is expected
