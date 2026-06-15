from __future__ import annotations

from types import SimpleNamespace

from core.infrastructure import developer_sandbox
from core.llm import LLMInvocationContext, invoke_llm
from core.llm.payload_builder import current_prompt_cache_partition


class _Response:
    content = "ok"
    tool_calls = []


class _FakeClient:
    protocol_route = SimpleNamespace(
        protocol=SimpleNamespace(value="openai_responses"),
        source="test-route",
        policy=SimpleNamespace(transport="responses"),
    )
    profile = SimpleNamespace(transport="responses", contract="tool_chat")

    def __init__(self):
        self.invocations = []

    def invoke(self, messages, tools=None, metadata=None):
        self.invocations.append(
            {
                "messages": messages,
                "tools": tools,
                "metadata": dict(metadata or {}),
                "active_partition": current_prompt_cache_partition(),
            }
        )
        return _Response()


def _enable_sandbox(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    config_path.write_text("[launcher]\ncontrol_port = 8765\n", encoding="utf-8")
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setattr(developer_sandbox, "CONFIG_PATH", config_path)
    monkeypatch.setattr(developer_sandbox, "PROJECT_ROOT", project_root)
    status = developer_sandbox.get_developer_mode_status(config_path=config_path, project_root=project_root)
    enabled = developer_sandbox.update_developer_mode_status(
        True,
        base_hash=status["configHash"],
        config_path=config_path,
        project_root=project_root,
    )
    return config_path, project_root, enabled


def test_invoke_llm_routes_explicit_prompt_cache_partition_through_developer_sandbox(tmp_path, monkeypatch):
    _config_path, _project_root, enabled = _enable_sandbox(tmp_path, monkeypatch)
    client = _FakeClient()

    invoke_llm(
        client,
        [{"role": "user", "content": "ping"}],
        context=LLMInvocationContext(
            surface="agent_turn",
            run_kind="main_reply",
            cache_partition="chat-agent-static-main",
            prompt_purpose="main_reply",
            conversation_bound=True,
        ),
    )

    expected = f"dev-agent_turn-{enabled['sandbox']['sandboxId']}-chat-agent-static-main"
    invocation = client.invocations[0]
    assert invocation["active_partition"] == expected
    assert invocation["metadata"]["promptCachePartition"] == expected
    assert invocation["metadata"]["developerMode"] is True
    assert invocation["metadata"]["developerSandboxId"] == enabled["sandbox"]["sandboxId"]
    assert invocation["metadata"]["recordKind"] == "debug"
    assert invocation["metadata"]["statePersistence"] == "sandbox_only"


def test_invoke_llm_adds_default_developer_partition_when_call_has_no_partition(tmp_path, monkeypatch):
    _config_path, _project_root, enabled = _enable_sandbox(tmp_path, monkeypatch)
    client = _FakeClient()

    invoke_llm(
        client,
        [{"role": "user", "content": "ping"}],
        context=LLMInvocationContext(
            surface="config_image_input_probe",
            run_kind="non_conversation_probe",
            prompt_purpose="image_input_probe",
            conversation_bound=False,
        ),
    )

    expected = f"dev-config_image_input_probe-{enabled['sandbox']['sandboxId']}-default"
    invocation = client.invocations[0]
    assert invocation["active_partition"] == expected
    assert invocation["metadata"]["promptCachePartition"] == expected


def test_invoke_llm_does_not_double_wrap_existing_developer_partition(tmp_path, monkeypatch):
    _config_path, project_root, enabled = _enable_sandbox(tmp_path, monkeypatch)
    client = _FakeClient()
    existing = developer_sandbox.sandbox_prompt_cache_partition(
        "research-team-agent-abc",
        surface="team",
        project_root=project_root,
    )

    invoke_llm(
        client,
        [{"role": "user", "content": "ping"}],
        context=LLMInvocationContext(
            surface="team_workflow_local_research_model",
            run_kind="challenge_cup_local_research",
            cache_partition=existing,
            prompt_purpose="source_collection",
            conversation_bound=False,
        ),
    )

    assert existing == f"dev-team-{enabled['sandbox']['sandboxId']}-research-team-agent-abc"
    invocation = client.invocations[0]
    assert invocation["active_partition"] == existing
    assert invocation["metadata"]["promptCachePartition"] == existing
