from __future__ import annotations

import sqlite3
import time

from core.llm.client import LLMClient
from core.llm.usage_ledger import UsageLedgerEvent, build_usage_summary, record_usage_event, usage_ledger_path
from tests.test_llm_client import make_config


def _disable_developer_mode(monkeypatch) -> None:
    monkeypatch.setattr("core.infrastructure.developer_sandbox.is_developer_mode_enabled", lambda **_kwargs: False)


def test_llm_client_usage_ledger_tests_are_isolated(tmp_path, monkeypatch):
    from core.infrastructure import developer_sandbox

    _disable_developer_mode(monkeypatch)
    monkeypatch.setattr(developer_sandbox, "resolve_workspace_home", lambda *args, **kwargs: tmp_path / "workspace")
    monkeypatch.setattr("core.llm.usage_ledger.PROJECT_ROOT", tmp_path)

    client = LLMClient(config=_usage_config(), backend=lambda _payload: _usage_response())
    client.invoke([{"role": "user", "content": "hi"}], metadata={"sessionId": "isolated-session"})

    summary = build_usage_summary(scope="session", session_id="isolated-session", project_root=tmp_path)
    assert summary["diagnostics"]["ledgerPath"].startswith((tmp_path / "workspace").as_posix())
    assert summary["sessionTokenUsage"]["observedCallCount"] == 1


def test_llm_client_invoke_records_one_provider_usage_event(tmp_path, monkeypatch):
    from core.infrastructure import developer_sandbox

    _disable_developer_mode(monkeypatch)
    monkeypatch.setattr(developer_sandbox, "resolve_workspace_home", lambda *args, **kwargs: tmp_path / "workspace")
    monkeypatch.setattr("core.llm.usage_ledger.PROJECT_ROOT", tmp_path)

    def backend(_payload):
        return _usage_response()

    client = LLMClient(config=_usage_config(), backend=backend)
    client.invoke(
        [{"role": "user", "content": "hi"}],
        metadata={"sessionId": "session-1", "turnId": "turn-1", "agentId": "agent-1", "mode": "chat"},
    )

    summary = build_usage_summary(scope="session", session_id="session-1", project_root=tmp_path)
    assert summary["lastTokenUsage"]["source"] == "provider_usage"
    assert summary["lastTokenUsage"]["cachedInputTokens"] == 45
    assert summary["lastTokenUsage"]["reasoningOutputTokens"] == 6
    assert summary["lastTokenUsage"]["contextWindow"] == 128000
    assert summary["sessionTokenUsage"]["observedCallCount"] == 1
    assert summary["sessionTokenUsage"]["estimatedCallCount"] == 0
    assert summary["sessionTokenUsage"]["totalTokens"] == 105


def test_llm_client_stream_records_one_done_event(tmp_path, monkeypatch):
    from core.infrastructure import developer_sandbox

    _disable_developer_mode(monkeypatch)
    monkeypatch.setattr(developer_sandbox, "resolve_workspace_home", lambda *args, **kwargs: tmp_path / "workspace")
    monkeypatch.setattr("core.llm.usage_ledger.PROJECT_ROOT", tmp_path)

    def backend(_payload):
        return iter(
            [
                {"choices": [{"delta": {"content": "hel"}}]},
                {"choices": [{"delta": {"content": "lo"}}]},
                {
                    "choices": [],
                    "usage": {
                        "prompt_tokens": 30,
                        "completion_tokens": 9,
                        "total_tokens": 39,
                        "prompt_tokens_details": {"cached_tokens": 12},
                    },
                },
            ]
        )

    client = LLMClient(config=_usage_config(), backend=backend)
    events = list(
        client.stream_events(
            [{"role": "user", "content": "hi"}],
            metadata={"sessionId": "session-2", "turnId": "turn-2"},
        )
    )

    assert [event.type for event in events] == ["text_delta", "text_delta", "done"]
    summary = build_usage_summary(scope="session", session_id="session-2", project_root=tmp_path)
    assert summary["lastTokenUsage"]["source"] == "provider_usage"
    assert summary["sessionTokenUsage"]["observedCallCount"] == 1
    assert summary["sessionTokenUsage"]["totalTokens"] == 39
    assert summary["sessionTokenUsage"]["cachedInputTokens"] == 12


def test_llm_client_records_estimated_usage_when_provider_usage_missing(tmp_path, monkeypatch):
    from core.infrastructure import developer_sandbox

    _disable_developer_mode(monkeypatch)
    monkeypatch.setattr(developer_sandbox, "resolve_workspace_home", lambda *args, **kwargs: tmp_path / "workspace")
    monkeypatch.setattr("core.llm.usage_ledger.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("core.llm.client._estimate_messages_for_usage", lambda _messages: 24)
    monkeypatch.setattr("core.llm.client._estimate_text_for_usage", lambda _text: 8)

    def backend(_payload):
        return {"choices": [{"message": {"role": "assistant", "content": "estimated", "tool_calls": []}}]}

    client = LLMClient(config=_usage_config(), backend=backend)
    client.invoke([{"role": "user", "content": "missing usage"}], metadata={"sessionId": "session-3"})

    summary = build_usage_summary(scope="session", session_id="session-3", project_root=tmp_path)
    assert summary["lastTokenUsage"]["source"] == "estimated"
    assert summary["lastTokenUsage"]["inputTokens"] == 24
    assert summary["lastTokenUsage"]["outputTokens"] == 8
    assert summary["lastTokenUsage"]["totalTokens"] == 32
    assert summary["sessionTokenUsage"]["estimatedCallCount"] == 1


def test_llm_client_usage_ledger_write_failure_does_not_fail_response(monkeypatch):
    recorded = []
    monkeypatch.setattr(
        "core.llm.client.record_usage_event",
        lambda _event: (_ for _ in ()).throw(RuntimeError("ledger locked")),
    )
    monkeypatch.setattr("core.llm.client._record_llm_scene_event", lambda *args, **kwargs: recorded.append((args, kwargs)))

    def backend(_payload):
        return {
            "choices": [{"message": {"role": "assistant", "content": "ok", "tool_calls": []}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
        }

    client = LLMClient(config=_usage_config(), backend=backend)
    message = client.invoke([{"role": "user", "content": "hi"}])

    assert message.content == "ok"
    failure_event = next(item for item in recorded if item[0][1] == "llm.usage_ledger.write_failed")
    assert failure_event[1]["fields"]["errorType"] == "RuntimeError"
    assert "ledger locked" not in str(failure_event)


def test_llm_client_usage_ledger_lock_does_not_slow_success_response(tmp_path, monkeypatch):
    from core.infrastructure import developer_sandbox

    _disable_developer_mode(monkeypatch)
    monkeypatch.setattr(developer_sandbox, "resolve_workspace_home", lambda *args, **kwargs: tmp_path / "workspace")
    monkeypatch.setattr("core.llm.usage_ledger.PROJECT_ROOT", tmp_path)
    recorded = []
    monkeypatch.setattr("core.llm.client._record_llm_scene_event", lambda *args, **kwargs: recorded.append((args, kwargs)))
    record_usage_event(UsageLedgerEvent(source="provider_usage", total_tokens=1), project_root=tmp_path)
    path = usage_ledger_path(tmp_path)

    locked = sqlite3.connect(str(path), timeout=5.0, isolation_level=None)
    try:
        locked.execute("BEGIN EXCLUSIVE")
        locked.execute(
            "INSERT INTO usage_events(event_id, recorded_at, source, scope_kind, provider_usage_keys_json, usage_schema_version) VALUES (?, ?, ?, ?, ?, ?)",
            ("held-lock", "2026-07-05T00:00:00Z", "provider_usage", "unknown", "[]", 1),
        )
        client = LLMClient(config=_usage_config(), backend=lambda _payload: _usage_response())

        started = time.perf_counter()
        message = client.invoke([{"role": "user", "content": "hi"}], metadata={"sessionId": "locked-session"})
        elapsed = time.perf_counter() - started

        assert message.content == "hello"
        assert elapsed < 0.5
        failure_event = next(item for item in recorded if item[0][1] == "llm.usage_ledger.write_failed")
        assert failure_event[1]["fields"]["errorType"] == "OperationalError"
    finally:
        locked.rollback()
        locked.close()


def _usage_config():
    return make_config(
        **{
            "llm.providers.default.kind": "local",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.providers.default.context_window": 128000,
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "custom-ledger-model",
            "llm.profiles.primary.prompt_cache.mode": "disabled",
        }
    )


def _usage_response():
    return {
        "choices": [{"message": {"role": "assistant", "content": "hello", "tool_calls": []}}],
        "usage": {
            "prompt_tokens": 90,
            "completion_tokens": 15,
            "total_tokens": 105,
            "prompt_tokens_details": {"cached_tokens": 45},
            "completion_tokens_details": {"reasoning_tokens": 6},
        },
    }
