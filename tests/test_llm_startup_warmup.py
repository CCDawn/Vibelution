"""Startup LLM warmup: deferred scheduling, idempotence, ledger exclusion, switches."""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

from fastapi import FastAPI

from core.llm import warmup
from core.web import lifecycle
from core.web.startup_jobs import StartupJobGroup

from tests.test_llm_client import make_config


def _disable_developer_mode(monkeypatch) -> None:
    monkeypatch.setattr(
        "core.infrastructure.developer_sandbox.is_developer_mode_enabled", lambda **_kwargs: False
    )


def _relay_config(**extra):
    options = {
        "llm.providers.default.kind": "relay",
        "llm.providers.default.api_key": "test-key",
        "llm.providers.default.base_url": "https://relay.example.test/v1",
        "llm.profiles.primary.provider_id": "default",
        "llm.profiles.primary.model": "chat-model",
    }
    options.update(extra)
    return make_config(**options)


class _FakeWarmupClient:
    instances: list["_FakeWarmupClient"] = []

    def __init__(self, *, config, profile_id) -> None:
        self.config = config
        self.profile_id = profile_id
        self.invocations: list[dict] = []
        self.closed = False
        _FakeWarmupClient.instances.append(self)

    def invoke(self, messages, metadata=None):
        self.invocations.append({"messages": messages, "metadata": dict(metadata or {})})
        return SimpleNamespace(content="ok")

    def close(self):
        self.closed = True


def _install_fake_client(monkeypatch) -> list[_FakeWarmupClient]:
    _FakeWarmupClient.instances = []
    monkeypatch.setattr("core.llm.client.LLMClient", _FakeWarmupClient)
    return _FakeWarmupClient.instances


def _stub_preload(monkeypatch) -> list[str]:
    labels: list[str] = []
    monkeypatch.setattr(
        warmup, "prewarm_llm_imports", lambda: {label: {"ok": True, "ms": 0, "error": ""} for label in labels}
    )
    return labels


# ---------------------------------------------------------------------------
# Lifecycle scheduling: the delayed channel receives the warmup worker.
# ---------------------------------------------------------------------------


def test_llm_warmup_waits_for_routes_ready_and_runs_off_loop(monkeypatch):
    monkeypatch.setenv("VIBELUTION_STARTUP_PREWARM_STAGGER_SECONDS", "0")
    monkeypatch.delenv("VIBELUTION_DEFER_STARTUP_CACHE_PREWARM", raising=False)
    monkeypatch.delenv("VIBELUTION_LLM_STARTUP_WARMUP", raising=False)
    monkeypatch.setattr(
        "core.web.services.session.directory_runtime.should_skip_directory_runtime_for_pytest",
        lambda: False,
    )
    calls: list[tuple[int, dict]] = []

    def fake_worker(gate_timings=None):
        calls.append((threading.get_ident(), dict(gate_timings or {})))
        return {"enabled": True}

    monkeypatch.setattr(lifecycle, "_llm_startup_warmup_worker", fake_worker)
    app = FastAPI()

    async def exercise():
        app.state.web_routes_ready_event = asyncio.Event()
        jobs = StartupJobGroup()
        worker = jobs.start_async(
            "llm-warmup-test", lifecycle._run_llm_warmup_after_routes_ready(app, startup_jobs=jobs)
        )
        await asyncio.sleep(0.02)
        assert calls == []  # gate holds the warmup until routes are ready
        app.state.web_routes_ready_event.set()
        await asyncio.wait_for(worker, timeout=5)

    loop_thread = threading.get_ident()
    asyncio.run(exercise())
    assert len(calls) == 1
    assert calls[0][0] != loop_thread  # imports/probes never run on the event loop
    assert calls[0][1]["waitedForRoutesMs"] >= 0
    assert calls[0][1]["staggerMs"] == 0


def test_llm_warmup_never_probes_under_pytest(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(lifecycle, "_llm_startup_warmup_worker", lambda *_a, **_k: calls.append("ran"))

    async def exercise():
        return await lifecycle._run_llm_warmup_after_routes_ready(None)

    assert asyncio.run(exercise()) == {"skipped": "pytest"}
    assert calls == []


def test_cancelled_route_wait_never_starts_llm_warmup(monkeypatch):
    monkeypatch.setenv("VIBELUTION_STARTUP_PREWARM_STAGGER_SECONDS", "0")
    monkeypatch.delenv("VIBELUTION_DEFER_STARTUP_CACHE_PREWARM", raising=False)
    monkeypatch.setattr(
        "core.web.services.session.directory_runtime.should_skip_directory_runtime_for_pytest",
        lambda: False,
    )
    calls: list[str] = []
    monkeypatch.setattr(lifecycle, "_llm_startup_warmup_worker", lambda *_a, **_k: calls.append("ran"))
    app = FastAPI()

    async def exercise():
        app.state.web_routes_ready_event = asyncio.Event()
        worker = asyncio.create_task(lifecycle._run_llm_warmup_after_routes_ready(app))
        await asyncio.sleep(0)
        worker.cancel()
        try:
            await worker
        except asyncio.CancelledError:
            pass

    asyncio.run(exercise())
    assert calls == []


# ---------------------------------------------------------------------------
# Import preload targets.
# ---------------------------------------------------------------------------


def test_prewarm_llm_imports_covers_call_path_modules_without_heavy_import(monkeypatch):
    requested: list[str] = []

    def fake_import_module(name):
        requested.append(name)
        return SimpleNamespace(completion=object(), responses=object(), HTTPHandler=object)

    monkeypatch.setattr(warmup.importlib, "import_module", fake_import_module)

    results = warmup.prewarm_llm_imports()

    assert requested == [entry[1] for entry in warmup._LLM_CALL_PATH_IMPORTS]
    assert set(results) == {
        "httpx",
        "openai",
        "litellm.completion",
        "litellm.responses",
        "litellm.HTTPHandler",
        "core.chat.conversation_invariant",
        "core.chat.model_messages",
        "tools.token_manager",
        "core.llm.usage_ledger",
    }
    assert all(entry["ok"] and entry["ms"] >= 0 for entry in results.values())


def test_prewarm_llm_imports_swallows_individual_failures(monkeypatch):
    def fake_import_module(name):
        if name == "litellm":
            raise ImportError("no litellm in this environment")
        return SimpleNamespace()

    monkeypatch.setattr(warmup.importlib, "import_module", fake_import_module)

    results = warmup.prewarm_llm_imports()

    assert results["litellm.completion"]["ok"] is False
    assert results["litellm.completion"]["error"] == "ImportError"
    assert results["httpx"]["ok"] is True


# ---------------------------------------------------------------------------
# Provider probes: idempotence, selection, bounded payloads.
# ---------------------------------------------------------------------------


def test_warmup_provider_is_idempotent_per_process(monkeypatch):
    warmup.reset_warmup_state_for_tests()
    instances = _install_fake_client(monkeypatch)
    config = _relay_config()

    first = warmup.warmup_provider("default", "primary", config=config)
    second = warmup.warmup_provider("default", "primary", config=config)

    assert first["outcome"] == "succeeded" and first["errorType"] == ""
    assert second["skipped"] == "already_warmed"
    assert len(instances) == 1
    assert len(instances[0].invocations) == 1
    assert instances[0].closed
    metadata = instances[0].invocations[0]["metadata"]
    assert metadata["llmWarmup"] is True
    assert metadata["disableAutomaticRetries"] is True
    assert metadata["llmMaxOutputTokensOverride"] == 1
    assert instances[0].invocations[0]["messages"] == [{"role": "user", "content": "hi"}]


def test_warmup_provider_caps_timeouts_and_disables_prompt_cache(monkeypatch):
    warmup.reset_warmup_state_for_tests()
    instances = _install_fake_client(monkeypatch)
    config = _relay_config(
        **{
            "llm.profiles.primary.timeout": 120,
            "llm.profiles.primary.connect_timeout": 60,
            "llm.profiles.primary.prompt_cache.mode": "automatic",
        }
    )

    warmup.warmup_provider("default", "primary", config=config, timeout_seconds=15)

    profile = instances[0].config.llm.profiles["primary"]
    assert profile.timeout == 15
    assert profile.connect_timeout == 15
    assert profile.prompt_cache.mode == "disabled"
    # The operator config object itself stays untouched.
    assert config.llm.profiles["primary"].timeout == 120


def test_only_enabled_credentialed_referenced_providers_are_warmed(monkeypatch):
    """Schema v2 is the operator shape: provider identity, enabled flag and
    credential requirements survive intact (v1 test kwargs get inlined per
    profile and drop ``enabled``)."""

    from config.models import AppConfig, LLMConfig, LLMProfile, ProviderConfig

    warmup.reset_warmup_state_for_tests()
    _stub_preload(monkeypatch)
    instances = _install_fake_client(monkeypatch)
    # Machine env (e.g. a real OPENAI_API_KEY) would make "keyless" credentialed
    # through the canonical relay alias; pin resolution to the declared fields.
    monkeypatch.setattr("config.models.get_provider_api_key_env", lambda _kind: None)
    config = AppConfig(
        llm=LLMConfig(
            schema_version=2,
            providers={
                "default": ProviderConfig(
                    provider_id="default",
                    kind="relay",
                    api_key="test-key",
                    base_url="https://relay.example.test/v1",
                ),
                # Referenced but disabled: hidden from warmup like from the picker.
                "ghost": ProviderConfig(
                    provider_id="ghost",
                    kind="relay",
                    api_key="ghost-key",
                    base_url="https://ghost.example.test/v1",
                    enabled=False,
                ),
                # Requires a key that is not resolvable: credentials not ready.
                "keyless": ProviderConfig(
                    provider_id="keyless",
                    kind="relay",
                    base_url="https://keyless.example.test/v1",
                ),
            },
            profiles={
                "primary": LLMProfile(profile_id="primary", provider_id="default", model="chat-model"),
                "aux": LLMProfile(profile_id="aux", provider_id="ghost", model="ghost-model"),
                "keyless": LLMProfile(profile_id="keyless", provider_id="keyless", model="keyless-model"),
            },
        )
    )

    summary = warmup.run_llm_startup_warmup(config=config)

    assert summary["enabled"] is True
    assert [provider["provider"] for provider in summary["providers"]] == ["default"]
    assert len(instances) == 1
    assert instances[0].profile_id == "primary"


def test_run_llm_startup_warmup_is_idempotent_across_runs(monkeypatch):
    warmup.reset_warmup_state_for_tests()
    _stub_preload(monkeypatch)
    instances = _install_fake_client(monkeypatch)
    config = _relay_config()

    warmup.run_llm_startup_warmup(config=config)
    warmup.run_llm_startup_warmup(config=config)

    assert len(instances) == 1


# ---------------------------------------------------------------------------
# Switches: env kill switch and operator config item.
# ---------------------------------------------------------------------------


def test_env_kill_switch_disables_warmup_entirely(monkeypatch):
    warmup.reset_warmup_state_for_tests()
    monkeypatch.setenv("VIBELUTION_LLM_STARTUP_WARMUP", "0")
    instances = _install_fake_client(monkeypatch)
    preloaded: list[str] = []
    monkeypatch.setattr(warmup, "prewarm_llm_imports", lambda: preloaded.append("ran") or {})

    summary = warmup.run_llm_startup_warmup(config=_relay_config())

    assert summary["enabled"] is False
    assert summary["skipped"] == "disabled"
    assert instances == []
    assert preloaded == []


def test_config_item_disables_warmup(monkeypatch):
    warmup.reset_warmup_state_for_tests()
    monkeypatch.delenv("VIBELUTION_LLM_STARTUP_WARMUP", raising=False)
    instances = _install_fake_client(monkeypatch)
    monkeypatch.setattr(warmup, "prewarm_llm_imports", lambda: {})

    config = _relay_config(**{"llm.startup_warmup": False})
    summary = warmup.run_llm_startup_warmup(config=config)

    assert summary["enabled"] is False
    assert instances == []


def test_config_item_disables_warmup_via_default_config_resolution(monkeypatch):
    """The lifecycle owner calls with config=None; the switch must still apply."""

    warmup.reset_warmup_state_for_tests()
    monkeypatch.delenv("VIBELUTION_LLM_STARTUP_WARMUP", raising=False)
    instances = _install_fake_client(monkeypatch)
    monkeypatch.setattr(warmup, "prewarm_llm_imports", lambda: {})
    config = _relay_config(**{"llm.startup_warmup": False})
    monkeypatch.setattr("config.get_config", lambda: config)

    summary = warmup.run_llm_startup_warmup()

    assert summary["enabled"] is False
    assert instances == []


def test_switch_defaults_to_enabled(monkeypatch):
    monkeypatch.delenv("VIBELUTION_LLM_STARTUP_WARMUP", raising=False)
    assert warmup.llm_startup_warmup_enabled() is True
    assert warmup.llm_startup_warmup_enabled(_relay_config()) is True
    for value in ("0", "false", "no", "off"):
        monkeypatch.setenv("VIBELUTION_LLM_STARTUP_WARMUP", value)
        assert warmup.llm_startup_warmup_enabled(_relay_config()) is False


# ---------------------------------------------------------------------------
# Usage ledger exclusion for warmup-marked invocations.
# ---------------------------------------------------------------------------


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
        "choices": [{"message": {"role": "assistant", "content": "hello", "tool_calls": []}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 90, "completion_tokens": 15, "total_tokens": 105},
    }


def test_record_usage_ledger_event_skips_warmup_marker(monkeypatch):
    recorded: list[object] = []
    monkeypatch.setattr("core.llm.client.record_usage_event", lambda event: recorded.append(event))

    from core.llm.client import _record_usage_ledger_event
    from core.llm.types import UsageStats

    _record_usage_ledger_event(
        usage=UsageStats(input_tokens=1, output_tokens=1, total_tokens=2),
        metadata={"llmWarmup": True},
        provider="relay",
        model="m",
        profile_id="primary",
        transport="chat_completions",
    )
    _record_usage_ledger_event(
        usage=UsageStats(input_tokens=1, output_tokens=1, total_tokens=2),
        metadata={"sessionId": "s"},
        provider="relay",
        model="m",
        profile_id="primary",
        transport="chat_completions",
    )

    assert len(recorded) == 1


def test_warmup_invoke_never_reaches_usage_ledger(tmp_path, monkeypatch):
    from core.infrastructure import developer_sandbox
    from core.llm.client import LLMClient
    from core.llm.usage_ledger import build_usage_summary

    _disable_developer_mode(monkeypatch)
    monkeypatch.setattr(developer_sandbox, "resolve_workspace_home", lambda *args, **kwargs: tmp_path / "workspace")
    monkeypatch.setattr("core.llm.usage_ledger.PROJECT_ROOT", tmp_path)

    client = LLMClient(config=_usage_config(), backend=lambda _payload: _usage_response())
    # A warmup-marked call shares the session id with a real call on purpose:
    # if the marker were dropped anywhere on the invoke path, the warmup
    # invocation would double-count in the session rollup below.
    client.invoke(
        [{"role": "user", "content": "warm"}],
        metadata={"llmWarmup": True, "sessionId": "warm-session"},
    )
    client.invoke([{"role": "user", "content": "real"}], metadata={"sessionId": "warm-session"})

    summary = build_usage_summary(scope="session", session_id="warm-session", project_root=tmp_path)
    assert summary["sessionTokenUsage"]["observedCallCount"] == 1
    assert summary["sessionTokenUsage"]["totalTokens"] == 105
