from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

from agent import AgentRuntime
from core.web.services import session_service


class _RuntimeAgent:
    def __init__(self, *, failures_before_close: int = 0) -> None:
        self.close_calls = 0
        self.failures_before_close = failures_before_close

    def prepare_for_session_turn_reuse(self) -> None:
        pass

    def close(self) -> None:
        self.close_calls += 1
        if self.failures_before_close:
            self.failures_before_close -= 1
            raise RuntimeError("temporary close failure")


@pytest.fixture
def clean_runtime_cache():
    with session_service._SESSION_AGENT_RUNTIME_CACHE_LOCK:
        session_service._SESSION_AGENT_RUNTIME_CACHE_CLOSED = False
    session_service._invalidate_session_agent_runtime_cache()
    yield
    session_service._invalidate_session_agent_runtime_cache()
    session_service._retry_retired_session_agents()
    with session_service._SESSION_AGENT_RUNTIME_CACHE_LOCK:
        session_service._SESSION_AGENT_RUNTIME_CACHE_CLOSED = False


def _install_agent_factory(monkeypatch, *, failures: int = 0):
    created: list[_RuntimeAgent] = []

    def create(*_args, **_kwargs):
        agent = _RuntimeAgent(failures_before_close=failures)
        created.append(agent)
        return agent

    monkeypatch.setattr(session_service, "_create_chat_agent_for_session", create)
    monkeypatch.setattr(
        session_service,
        "_session_agent_runtime_cache_fingerprint",
        lambda **kwargs: str(kwargs.get("prompt_snapshot_hash") or "fingerprint"),
    )
    return created


def _acquire(session_id: str, workspace, fingerprint: str, *, mode: str = "chat"):
    return session_service._acquire_chat_agent_for_session(
        session_id,
        workspace,
        {"agentId": f"agent-{session_id}"},
        mode=mode,
        prompt_snapshot_hash=fingerprint,
    )


def test_fingerprint_replacement_and_invalidation_wait_for_all_turn_leases(
    tmp_path,
    monkeypatch,
    clean_runtime_cache,
):
    created = _install_agent_factory(monkeypatch)
    first, first_lease = _acquire("session-lease", tmp_path, "v1")
    reused, reused_lease = _acquire("session-lease", tmp_path, "v1")
    replacement, replacement_lease = _acquire("session-lease", tmp_path, "v2")

    assert reused is first
    assert replacement is not first
    assert first.close_calls == 0

    session_service._release_chat_agent_runtime(first_lease)
    assert first.close_calls == 0
    session_service._release_chat_agent_runtime(reused_lease)
    assert first.close_calls == 1
    session_service._release_chat_agent_runtime(first_lease)
    assert first.close_calls == 1

    assert session_service._invalidate_session_agent_runtime_cache("session-lease") == 1
    assert replacement.close_calls == 0
    session_service._release_chat_agent_runtime(replacement_lease)
    assert replacement.close_calls == 1
    assert len(created) == 2


def test_lru_eviction_defers_close_until_evicted_turn_releases(tmp_path, monkeypatch, clean_runtime_cache):
    created = _install_agent_factory(monkeypatch)
    monkeypatch.setattr(session_service, "_SESSION_AGENT_RUNTIME_CACHE_MAX_ENTRIES", 1)
    first, first_lease = _acquire("session-old", tmp_path, "same")
    second, second_lease = _acquire("session-new", tmp_path, "same")

    assert len(session_service._SESSION_AGENT_RUNTIME_CACHE) == 1
    assert first.close_calls == 0
    session_service._release_chat_agent_runtime(first_lease)
    assert first.close_calls == 1
    session_service._release_chat_agent_runtime(second_lease)
    session_service._invalidate_session_agent_runtime_cache()
    assert second.close_calls == 1
    assert len(created) == 2


def test_bypassed_agent_is_retired_after_worker_release(tmp_path, monkeypatch, clean_runtime_cache):
    created = _install_agent_factory(monkeypatch)
    agent, metadata = _acquire("session-bypass", tmp_path, "unused", mode="supervised_evolution")

    assert metadata["status"] == "bypassed"
    assert len(session_service._SESSION_AGENT_RUNTIME_CACHE) == 0
    assert agent.close_calls == 0
    session_service._release_chat_agent_runtime(metadata)
    session_service._release_chat_agent_runtime(metadata)
    assert agent.close_calls == 1
    assert len(created) == 1


def test_failed_agent_close_remains_owned_and_shutdown_retries(tmp_path, monkeypatch, clean_runtime_cache):
    created = _install_agent_factory(monkeypatch, failures=1)
    agent, metadata = _acquire("session-close-retry", tmp_path, "v1")
    session_service._invalidate_session_agent_runtime_cache("session-close-retry")
    assert agent.close_calls == 0

    session_service._release_chat_agent_runtime(metadata)
    assert agent.close_calls == 1
    assert session_service._retired_session_agent_status() == {"pending": 0, "failed": 1}

    assert session_service._retry_retired_session_agents() == {"pending": 0, "failed": 0}
    assert agent.close_calls == 2
    assert created == [agent]


def test_repeated_shutdown_retries_agent_close_failure_after_cache_is_empty(
    tmp_path,
    monkeypatch,
    clean_runtime_cache,
):
    created = _install_agent_factory(monkeypatch, failures=1)
    agent, metadata = _acquire("session-shutdown-retry", tmp_path, "v1")
    session_service._release_chat_agent_runtime(metadata)
    monkeypatch.setattr(session_service, "stop_session_service_admission", lambda: None)
    monkeypatch.setattr(session_service, "_SESSION_EXECUTOR_DRAIN_THREADS", [])
    monkeypatch.setattr(session_service, "_SESSION_EXECUTOR_DRAIN_ERRORS", set())

    first = session_service.shutdown_session_service(deadline=time.monotonic() + 1)

    assert first["closed"] is False
    assert first["failedRuntimeAgents"] == 1
    assert agent.close_calls == 1
    assert len(session_service._SESSION_AGENT_RUNTIME_CACHE) == 0

    second = session_service.shutdown_session_service(deadline=time.monotonic() + 1)

    assert second["closed"] is True
    assert second["failedRuntimeAgents"] == 0
    assert second["pendingRuntimeAgents"] == 0
    assert agent.close_calls == 2
    assert created == [agent]


def test_shutdown_marks_active_agents_and_release_closes_after_turn(tmp_path, monkeypatch, clean_runtime_cache):
    created = _install_agent_factory(monkeypatch)
    agent, metadata = _acquire("session-shutdown", tmp_path, "v1")
    monkeypatch.setattr(session_service, "stop_session_service_admission", lambda: None)
    monkeypatch.setattr(session_service, "_SESSION_EXECUTOR_DRAIN_THREADS", [])
    monkeypatch.setattr(session_service, "_SESSION_EXECUTOR_DRAIN_ERRORS", set())

    result = session_service.shutdown_session_service(deadline=time.monotonic() + 1)

    assert result["closed"] is False
    assert result["pendingRuntimeAgents"] == 1
    assert agent.close_calls == 0
    session_service._release_chat_agent_runtime(metadata)
    assert agent.close_calls == 1
    assert created == [agent]


def test_shutdown_deadline_leaves_unstarted_retirement_retryable(tmp_path, monkeypatch, clean_runtime_cache):
    created = _install_agent_factory(monkeypatch)
    agent, metadata = _acquire("session-shutdown-deadline", tmp_path, "v1")
    session_service._release_chat_agent_runtime(metadata)
    monkeypatch.setattr(session_service, "stop_session_service_admission", lambda: None)
    monkeypatch.setattr(session_service, "_SESSION_EXECUTOR_DRAIN_THREADS", [])
    monkeypatch.setattr(session_service, "_SESSION_EXECUTOR_DRAIN_ERRORS", set())

    result = session_service.shutdown_session_service(deadline=time.monotonic() - 1)

    assert result["closed"] is False
    assert result["pendingRuntimeAgents"] == 1
    assert agent.close_calls == 0
    assert session_service._retry_retired_session_agents() == {"pending": 0, "failed": 0}
    assert agent.close_calls == 1
    assert created == [agent]


def test_agent_reuses_repeated_slot_clients_and_closes_unique_clients_once():
    runtime = AgentRuntime.__new__(AgentRuntime)
    runtime._owned_llm_clients = {}
    runtime._owned_llm_clients_lock = threading.RLock()
    runtime._llm_close_lock = threading.Lock()
    runtime._agent_llm_client_cache = {}
    runtime._base_llm_client_cache_key = None
    runtime._base_llm = None
    config = SimpleNamespace(llm={"profiles": {"summary": {"model": "model-a"}}})
    created = []

    class Client:
        def __init__(self):
            self.close_calls = 0

        def close(self):
            self.close_calls += 1

    for _ in range(8):
        client = runtime._get_or_create_agent_llm_client(
            role="primary",
            profile_id="summary",
            config=config,
            factory=lambda: created.append(Client()) or created[-1],
        )
    assert len(created) == 1
    assert len(runtime._owned_llm_clients) == 1

    config.llm["profiles"]["summary"]["model"] = "model-b"
    replacement = runtime._get_or_create_agent_llm_client(
        role="primary",
        profile_id="summary",
        config=config,
        factory=lambda: created.append(Client()) or created[-1],
    )
    assert replacement is not client
    assert client.close_calls == 0
    assert len(runtime._owned_llm_clients) == 2

    runtime.close()
    runtime.close()
    assert [item.close_calls for item in created] == [1, 1]


def test_agent_close_failure_preserves_only_failed_client_for_retry():
    runtime = AgentRuntime.__new__(AgentRuntime)
    runtime._owned_llm_clients = {}
    runtime._owned_llm_clients_lock = threading.RLock()
    runtime._llm_close_lock = threading.Lock()
    runtime._agent_llm_client_cache = {}

    class FailOnceClient:
        def __init__(self):
            self.close_calls = 0

        def close(self):
            self.close_calls += 1
            if self.close_calls == 1:
                raise RuntimeError("temporary client close failure")

    class SucceededClient:
        def __init__(self):
            self.close_calls = 0

        def close(self):
            self.close_calls += 1

    failing = FailOnceClient()
    succeeded = SucceededClient()
    runtime._own_llm_client(failing)
    runtime._own_llm_client(failing)
    runtime._own_llm_client(succeeded)

    with pytest.raises(RuntimeError, match="Agent LLM transport close failed"):
        runtime.close()
    assert failing.close_calls == 1
    assert succeeded.close_calls == 1
    assert list(runtime._owned_llm_clients.values()) == [failing]

    runtime.close()
    runtime.close()
    assert failing.close_calls == 2
    assert runtime._owned_llm_clients == {}
