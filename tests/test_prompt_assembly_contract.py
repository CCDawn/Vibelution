from __future__ import annotations

from core.orchestration import context_engine
from core.prompt_manager.assembly_contract import (
    PromptAssemblyManifest,
    PromptCachePolicy,
    PromptDecision,
    PromptPlacement,
    PromptSegment,
    PromptStability,
    PromptTier,
    PromptTrust,
)
from core.prompt_manager.builder import get_system_prompt, split_sys_prompt_prefix, to_string
from core.prompt_manager.prompt_manager import PromptManager
from core.prompt_manager.section_cache import SystemPromptCache
from core.prompt_manager.types import SystemPromptSection


def _assert_manifest_has_no_prompt_body(value: object) -> None:
    if isinstance(value, dict):
        assert "content" not in value
        assert "block" not in value
        for nested in value.values():
            _assert_manifest_has_no_prompt_body(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            _assert_manifest_has_no_prompt_body(nested)


def test_prompt_segment_keeps_body_internal_and_manifest_sanitized() -> None:
    segment = PromptSegment.from_content(
        key="agent_prompt_snapshot",
        content="private prompt body with token sk-secret",
        tier=PromptTier.SESSION_SNAPSHOT,
        placement=PromptPlacement.SYSTEM_PREFIX,
        stability=PromptStability.SESSION_STATIC,
        trust=PromptTrust.OPERATOR_CONTROLLED,
        source="prompt_template_service",
        required=True,
        cache_policy=PromptCachePolicy.CACHEABLE,
        decision=PromptDecision.FULL,
        decision_reason="session_snapshot",
    )

    internal = segment.to_internal_dict(block_key="block")
    public = segment.to_manifest_entry()

    assert internal["block"] == "private prompt body with token sk-secret"
    assert internal["hash"] == segment.content_hash
    assert internal["estimated_tokens"] == segment.estimated_tokens
    assert public["key"] == "agent_prompt_snapshot"
    assert public["tier"] == "session_snapshot"
    assert public["contentHash"] == segment.content_hash
    assert public["estimatedTokens"] == segment.estimated_tokens
    assert "private prompt body" not in repr(public)
    assert "sk-secret" not in repr(public)
    _assert_manifest_has_no_prompt_body(public)


def test_prompt_builder_emits_manifest_without_changing_model_prompt() -> None:
    sections = [
        SystemPromptSection(
            name="COMMON",
            compute=lambda: "stable core body",
            priority=10,
            required=True,
        ),
        SystemPromptSection(
            name="TURN_STATE",
            compute=lambda: "volatile turn body",
            cache_break=True,
            priority=20,
        ),
    ]

    result = get_system_prompt(sections, SystemPromptCache())
    static_parts, dynamic_parts = split_sys_prompt_prefix(result.prompt)

    assert static_parts == ("stable core body",)
    assert dynamic_parts[0].startswith("## 提示词组件")
    assert dynamic_parts[-1] == "volatile turn body"
    assert to_string(result.prompt) == "\n\n".join((*static_parts, *dynamic_parts))

    manifest = result.assembly_manifest.to_public_dict()
    assert manifest["schemaVersion"] == 1
    assert manifest["assemblyMode"] == "legacy_observe"
    assert [item["key"] for item in manifest["segments"]] == [
        "COMMON",
        "AVAILABLE_SECTIONS",
        "TURN_STATE",
    ]
    assert manifest["segments"][0]["tier"] == "stable_core"
    assert manifest["segments"][1]["tier"] == "turn_context"
    assert manifest["segments"][2]["tier"] == "turn_context"
    assert manifest["stablePrefixHash"]
    assert manifest["totalEstimatedTokens"] > 0
    assert "stable core body" not in repr(manifest)
    assert "volatile turn body" not in repr(manifest)
    _assert_manifest_has_no_prompt_body(manifest)


def test_context_engine_segments_share_contract_and_offer_sanitized_manifest() -> None:
    static_segment = context_engine._context_segment(
        "agent_runtime",
        "stable private agent context",
        placement="cache_prefix",
        stability="agent_static",
    )
    dynamic_segment = context_engine._context_segment(
        "agent_messages",
        "current private inbox context",
        placement="volatile_turn",
        stability="turn_dynamic",
    )

    assert static_segment is not None
    assert dynamic_segment is not None
    assert static_segment["block"] == "stable private agent context"
    assert static_segment["tier"] == "session_snapshot"
    assert static_segment["placement"] == "cache_prefix"
    assert static_segment["cache_policy"] == "cacheable"
    assert dynamic_segment["tier"] == "turn_context"
    assert dynamic_segment["cache_policy"] == "never_cache"

    packet = context_engine.AgentContextPacket(
        agent_id="agent-a",
        context_segments=[static_segment, dynamic_segment],
    )
    manifest = packet.prompt_assembly_manifest

    assert isinstance(manifest, PromptAssemblyManifest)
    public = manifest.to_public_dict()
    assert [item["key"] for item in public["segments"]] == ["agent_runtime", "agent_messages"]
    assert public["sessionSnapshotHash"]
    assert "stable private agent context" not in repr(public)
    assert "current private inbox context" not in repr(public)
    _assert_manifest_has_no_prompt_body(public)


def test_prompt_manager_exposes_last_sanitized_assembly_manifest() -> None:
    manager = PromptManager()
    manager.register(
        SystemPromptSection(
            name="PRIVATE_DIAGNOSTIC_TEST",
            compute=lambda: "private manager body sk-private",
            cache_break=True,
            priority=999,
        )
    )

    manager.build(include=["PRIVATE_DIAGNOSTIC_TEST"])
    manifest = manager.get_last_assembly_manifest()

    assert manifest["schemaVersion"] == 1
    assert any(
        item["key"] == "PRIVATE_DIAGNOSTIC_TEST"
        for item in manifest["segments"]
    )
    assert "private manager body" not in repr(manifest)
    assert "sk-private" not in repr(manifest)
    _assert_manifest_has_no_prompt_body(manifest)
