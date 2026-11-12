"""Contract tests for runtime context-compression policy application.

Two behaviours are locked here:

1. An unmaterialized Agent policy means "not configured yet". It must inherit
   the global ``context_compression.enabled`` switch instead of writing
   ``False``, because the feature gate reads that same field and would then
   silently disable compression for the whole runtime.
2. The automatic compression threshold fallback must match the configured
   ``levels.standard`` default (0.8), not a stale 0.95 that leaves only a 5%
   buffer before the provider hard limit.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from config.models import ContextCompressionConfig


def _runtime(monkeypatch, policy: dict):
    from agent import AgentRuntime
    from core.web.services import agent_directory_service

    runtime = object.__new__(AgentRuntime)
    runtime.runtime_agent_binding = {"agentId": "agent-unmaterialized"}
    runtime.config = SimpleNamespace(context_compression=ContextCompressionConfig())
    runtime.config.context_compression.enabled = True
    runtime._effective_max_token_limit = 16_000
    runtime._context_window_limit = 200_000
    runtime.model_info = SimpleNamespace(max_output_tokens=8_192)
    runtime._context_compression_policy = {}

    monkeypatch.setattr(
        agent_directory_service,
        "get_agent",
        lambda *a, **k: {"agentId": "agent-unmaterialized", "name": "runtime"},
    )
    monkeypatch.setattr(
        agent_directory_service,
        "effective_agent_context_compression_policy",
        lambda *a, **k: policy,
    )
    AgentRuntime._apply_runtime_agent_context_compression_policy(runtime)
    return runtime


def test_unmaterialized_policy_inherits_compression_switch(monkeypatch):
    runtime = _runtime(
        monkeypatch,
        {
            "mode": "unmaterialized",
            "source": "migration_required",
            "enabled": False,
            "effectiveTokenLimit": 0,
        },
    )
    assert runtime.config.context_compression.enabled is True
    # No explicit limit means the inherited runtime limit stays authoritative.
    assert runtime._effective_max_token_limit >= 1


def test_custom_policy_still_controls_compression(monkeypatch):
    runtime = _runtime(
        monkeypatch,
        {
            "mode": "custom",
            "source": "agent",
            "enabled": False,
            "effectiveTokenLimit": 32_000,
        },
    )
    assert runtime.config.context_compression.enabled is False
    assert runtime.config.context_compression.max_token_limit == 32_000


def test_threshold_fallback_matches_config_default():
    from agent import AgentRuntime

    runtime = object.__new__(AgentRuntime)
    runtime.config = SimpleNamespace(
        context_compression=SimpleNamespace(levels=None)
    )
    threshold = AgentRuntime._automatic_context_compression_threshold(runtime)
    assert threshold == pytest.approx(0.8)
