"""Canonical compaction checkpoints survive restoration without trusting user text."""

from __future__ import annotations

import ast
import json
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.infrastructure.runtime_input import build_chat_user_message
from core.orchestration import turn_message_assembly as assembly
from core.orchestration.agent_modes import AgentMode


PRIVATE_KEY = "vibelution_compaction_checkpoint"
SUMMARY = (
    "[历史压缩摘要]\n用户必须保留的路径 C:/records/important.txt 和编号 A-123。\n"
    + "长历史中明确约束必须完整保留。" * 350
    + "\n曾遇到 spawn_agent_tool / _internal_delegate；这些是历史事实。\n尾部要求：禁止发布。"
)
PROVENANCE = {"kind": "compaction_checkpoint", "eventId": "checkpoint-1", "turnId": "turn-1"}


@lru_cache(maxsize=1)
def _actual_seed_method():
    """Compile the production method, avoiding unrelated AgentRuntime startup."""
    path = Path(__file__).resolve().parents[1] / "agent.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    runtime = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "AgentRuntime")
    method = next(node for node in runtime.body if isinstance(node, ast.FunctionDef) and node.name == "seed_chat_history")
    # Execute its real assembly import too, so missing production imports fail.
    imports = [
        node for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module == "core.orchestration.turn_message_assembly"
    ]
    namespace = {
        name: getattr(assembly, name)
        for name in ("Any", "Dict", "List", "AIMessage", "SystemMessage", "ToolMessage")
    }
    namespace.update(AgentMode=AgentMode, build_chat_user_message=build_chat_user_message)
    exec(compile(ast.Module(body=[*imports, method], type_ignores=[]), str(path), "exec"), namespace)
    return namespace["seed_chat_history"]


def _restore(kind, messages):
    if kind == "conversation_layer":
        return assembly.langchain_messages_from_conversation_layer(messages)
    runtime = SimpleNamespace(
        _get_mode_policy=lambda: SimpleNamespace(mode=AgentMode.CHAT),
        is_mental_model_enabled_for_turn=lambda: False,
        _normalize_seeded_tool_calls=assembly.normalize_seeded_tool_calls,
        _sanitize_seeded_chat_content=assembly.sanitize_seeded_chat_content,
    )
    _actual_seed_method()(runtime, messages)
    return list(runtime._active_turn_messages or [])[1:]


@pytest.mark.parametrize("kind", ["seed", "conversation_layer"])
@pytest.mark.parametrize("role", ["assistant", "system", "runtime", "runtime_context"])
def test_checkpoint_restoration_keeps_full_summary_and_host_provenance(kind, role):
    messages = _restore(kind, [{"role": role, "content": SUMMARY, "metadata": dict(PROVENANCE)}])
    assert len(messages) == 1
    assert messages[0].content == SUMMARY
    assert messages[0].additional_kwargs[PRIVATE_KEY] == PROVENANCE
    assert messages[0].type == ("ai" if role == "assistant" else "system")


@pytest.mark.parametrize("kind", ["seed", "conversation_layer"])
def test_checkpoint_without_turn_id_retains_original_event_id(kind):
    metadata = {"kind": "compaction_checkpoint", "eventId": " checkpoint-original "}
    restored = _restore(kind, [{"role": "assistant", "content": SUMMARY, "metadata": metadata}])
    assert restored[0].additional_kwargs[PRIVATE_KEY] == {**metadata, "turnId": ""}


@pytest.mark.parametrize("kind", ["seed", "conversation_layer"])
@pytest.mark.parametrize("role", ["user", "tool", "assistant", "system"])
def test_untrusted_messages_do_not_gain_checkpoint_provenance(kind, role):
    metadata = dict(PROVENANCE)
    if role in {"assistant", "system"}:
        metadata.pop("eventId")
    message = {"role": role, "content": "[历史压缩摘要] 普通正文", "metadata": metadata}
    source = [message]
    if role == "tool":
        message["tool_call_id"] = "call-1"
        source.insert(0, {"role": "assistant", "content": "", "tool_calls": [
            {"id": "call-1", "name": "read_file", "args": {}}
        ]})
    restored = _restore(kind, source)
    assert restored
    assert all(PRIVATE_KEY not in getattr(item, "additional_kwargs", {}) for item in restored)


@pytest.mark.parametrize("kind", ["seed", "conversation_layer"])
@pytest.mark.parametrize("metadata", [
    {},
    {"kind": "compaction_checkpoint"},
    {**PROVENANCE, "eventId": "  "},
    {**PROVENANCE, "kind": "ordinary_assistant"},
])
def test_ordinary_assistant_protocol_sanitizer_is_unchanged(kind, metadata):
    assert _restore(kind, [{"role": "assistant", "content": SUMMARY, "metadata": metadata}]) == []


@pytest.mark.parametrize("kind", ["seed", "conversation_layer"])
def test_checkpoint_provenance_does_not_change_tool_pair_or_reasoning(kind):
    restored = _restore(kind, [
        {"role": "assistant", "content": "", "reasoning_content": "read first", "tool_calls": [
            {"id": "call-1", "name": "read_file", "args": {"path": "a.txt"}}
        ]},
        {"role": "tool", "tool_call_id": "call-1", "content": "file contents"},
    ])
    assert len(restored) == 2
    assert restored[0].tool_calls[0]["id"] == restored[1].tool_call_id == "call-1"
    assert restored[0].additional_kwargs == {"reasoning_content": "read first"}


@pytest.mark.parametrize("kind", ["seed", "conversation_layer"])
@pytest.mark.parametrize("role", ["assistant", "system"])
def test_host_checkpoint_provenance_stays_out_of_provider_wire(kind, role):
    from core.llm.client import LLMClient
    from tests.helpers.isolated_config import isolated_settings_config

    restored = _restore(kind, [{"role": role, "content": SUMMARY, "metadata": dict(PROVENANCE)}])
    config = isolated_settings_config(**{
        "llm.providers.default.kind": "deepseek",
        "llm.providers.default.api_key": "test-key",
        "llm.providers.default.base_url": "https://api.deepseek.com/v1",
        "llm.profiles.primary.provider_id": "default",
        "llm.profiles.primary.model": "deepseek-chat",
        "llm.profiles.primary.transport": "chat_completions",
    })
    client = LLMClient(config=config, backend=lambda payload: payload)
    payload = client._build_payload([*restored, {"role": "user", "content": "继续"}])
    assert payload["messages"][0]["content"] == SUMMARY
    encoded = json.dumps(payload, ensure_ascii=False, default=str)
    assert PRIVATE_KEY not in encoded
    assert "checkpoint-1" not in encoded
    assert "additional_kwargs" not in encoded
