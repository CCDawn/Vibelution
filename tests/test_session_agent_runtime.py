from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from core.orchestration.turn_runner import create_agent_runtime
from core.web.services import session_service


def test_web_session_factory_propagates_agent_runtime_binding(
    tmp_path: Path,
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}
    runtime_agent = SimpleNamespace()

    def fake_chat_agent_factory(**kwargs):
        captured.update(kwargs)
        return runtime_agent

    monkeypatch.setattr(session_service, "create_chat_agent", fake_chat_agent_factory)
    agent_instance = {
        "agentId": "agent-luna-pressure",
        "directSessionId": "session-luna-pressure",
        "workspacePath": "workspace/agents/agent-luna-pressure",
    }

    created = session_service._create_chat_agent_for_session(
        tmp_path,
        agent_instance=agent_instance,
        llm_slot="dialogue",
        resolved_llm=SimpleNamespace(config=object()),
    )

    assert created is runtime_agent
    assert captured["runtime_agent_binding"] == {
        "agentId": "agent-luna-pressure",
        "directSessionId": "session-luna-pressure",
        "workspacePath": "workspace/agents/agent-luna-pressure",
        "llmSlot": "dialogue",
    }


def test_shared_agent_factory_propagates_explicit_runtime_binding() -> None:
    captured: dict[str, object] = {}
    runtime_agent = object()
    runtime_binding = {
        "agentId": "agent-luna-pressure",
        "llmSlot": "dialogue",
    }

    def factory(**kwargs):
        captured.update(kwargs)
        return runtime_agent

    created = create_agent_runtime(
        mode="chat",
        workspace_path="workspace/sessions/session-luna-pressure",
        config="config",
        runtime_agent_binding=runtime_binding,
        agent_factory=factory,
    )

    assert created is runtime_agent
    assert captured["runtime_agent_binding"] == runtime_binding


def test_runtime_cache_fingerprint_tracks_authoritative_agent_compression_policy(
    tmp_path: Path,
) -> None:
    base_agent = {
        "agentId": "agent-luna-pressure",
        "updatedAt": "2026-07-31T12:00:00Z",
        "configRevision": 8,
        "configHash": "config-hash-v8",
        "contextCompressionPolicy": {
            "mode": "custom",
            "enabled": True,
            "maxTokenLimit": 262_144,
        },
    }
    fingerprint = session_service._session_agent_runtime_cache_fingerprint(
        session_workspace=tmp_path,
        agent_instance=base_agent,
        llm_slot="dialogue",
        resolved_llm=SimpleNamespace(
            config={"context_compression": {"enabled": True}},
            model_id="gpt-5.6-luna",
        ),
        mode="chat",
        prompt_snapshot_hash="prompt-v1",
    )
    changed_policy = session_service._session_agent_runtime_cache_fingerprint(
        session_workspace=tmp_path,
        agent_instance={
            **base_agent,
            "contextCompressionPolicy": {
                **base_agent["contextCompressionPolicy"],
                "maxTokenLimit": 300_000,
            },
        },
        llm_slot="dialogue",
        resolved_llm=SimpleNamespace(
            config={"context_compression": {"enabled": True}},
            model_id="gpt-5.6-luna",
        ),
        mode="chat",
        prompt_snapshot_hash="prompt-v1",
    )

    assert changed_policy != fingerprint
