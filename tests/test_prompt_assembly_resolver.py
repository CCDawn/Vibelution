from __future__ import annotations

import pytest

from core.orchestration import context_engine
from core.prompt_manager.assembly_contract import (
    PromptCachePolicy,
    PromptDecision,
    PromptPlacement,
    PromptSegment,
    PromptStability,
    PromptTier,
    PromptTrust,
)
from core.prompt_manager.assembly_resolver import (
    PromptAssemblyBudgetError,
    PromptAssemblyContext,
    PromptSectionResolver,
    prompt_assembly_budget,
    render_discovery_index,
)
from core.prompt_manager.builder import get_system_prompt, to_string
from core.prompt_manager.prompt_manager import PromptManager
from core.prompt_manager.section_cache import SystemPromptCache
from core.prompt_manager.types import SystemPromptSection


@pytest.mark.parametrize(
    ("context_window", "expected"),
    [
        (16_000, 4_000),
        (32_000, 5_760),
        (128_000, 23_040),
    ],
)
def test_prompt_assembly_budget_uses_resolved_context_window(
    context_window: int,
    expected: int,
) -> None:
    assert prompt_assembly_budget(context_window) == expected


def test_resolver_fails_closed_when_protected_core_is_missing_or_over_budget() -> None:
    resolver = PromptSectionResolver()
    context = PromptAssemblyContext(
        context_window=16_000,
        enforce_core_floor=True,
    )
    common = _segment(
        "COMMON",
        "common",
        tier=PromptTier.STABLE_CORE,
        required=True,
    )

    with pytest.raises(PromptAssemblyBudgetError, match="missing_required_core"):
        resolver.resolve([common], context)

    oversized = [
        _segment(
            name,
            "x" * 8_000,
            tier=PromptTier.STABLE_CORE,
            required=True,
        )
        for name in ("COMMON", "SOUL", "AGENTS")
    ]
    with pytest.raises(PromptAssemblyBudgetError, match="protected_tier_over_budget"):
        resolver.resolve(oversized, context)


def test_builder_blocks_tool_guidance_when_tool_calling_is_disabled() -> None:
    sections = [
        SystemPromptSection(
            name="TOOL_GUIDANCE",
            compute=lambda: "call tools with structured arguments",
            cache_break=True,
            capability_requirements=("tool_calling",),
        ),
        SystemPromptSection(
            name="PLAIN_CHAT",
            compute=lambda: "answer directly",
            cache_break=True,
        ),
    ]
    result = get_system_prompt(
        sections,
        SystemPromptCache(),
        assembly_context=PromptAssemblyContext(
            context_window=16_000,
            capabilities=frozenset(),
        ),
    )

    text = to_string(result.prompt)
    manifest = result.assembly_manifest.to_public_dict()
    tool_segment = next(
        item for item in manifest["segments"] if item["key"] == "TOOL_GUIDANCE"
    )

    assert "call tools" not in text
    assert "answer directly" in text
    assert tool_segment["decision"] == "blocked"
    assert tool_segment["decisionReason"] == "missing_capability:tool_calling"


def test_prompt_manager_core_floor_ignores_include_exclude_and_model_override() -> None:
    manager = PromptManager()
    manager.select_components(["MEMORY"])

    manager.build(
        include=["MEMORY"],
        exclude=["COMMON", "SOUL", "AGENTS"],
        assembly_context=PromptAssemblyContext(
            context_window=128_000,
            enforce_core_floor=True,
        ),
    )
    manifest = manager.get_last_assembly_manifest()
    core = [
        item
        for item in manifest["segments"]
        if item["tier"] == "stable_core"
    ]

    assert [item["key"] for item in core] == ["COMMON", "SOUL", "AGENTS"]
    assert all(item["decision"] == "full" for item in core)


def test_skill_index_degrades_deterministically_with_budget_and_permissions() -> None:
    items = [
        {"name": "alpha", "description": "A" * 80},
        {"name": "beta", "description": "B" * 80},
        {"name": "gamma", "description": "C" * 80},
    ]
    context = PromptAssemblyContext(
        context_window=16_000,
        allowed_skills=("alpha", "gamma"),
    )

    full = render_discovery_index(
        "skills",
        items,
        context=context,
        budget_tokens=100,
    )
    truncated = render_discovery_index(
        "skills",
        items,
        context=context,
        budget_tokens=30,
    )
    names_only = render_discovery_index(
        "skills",
        items,
        context=context,
        budget_tokens=6,
    )
    omitted = render_discovery_index(
        "skills",
        items,
        context=context,
        budget_tokens=1,
    )

    assert full.decision == PromptDecision.FULL
    assert "alpha" in full.content and "gamma" in full.content
    assert "beta" not in full.content
    assert truncated.decision == PromptDecision.TRUNCATED
    assert names_only.decision == PromptDecision.INDEX_ONLY
    assert names_only.content == "alpha\ngamma"
    assert omitted.decision == PromptDecision.OMITTED
    assert omitted.content == ""


def test_turn_context_is_truncated_and_manifest_records_reason() -> None:
    resolver = PromptSectionResolver()
    result = resolver.resolve(
        [
            _segment(
                "RUNTIME_LOG_INDEX",
                "diagnostic " * 2_000,
                tier=PromptTier.TURN_CONTEXT,
            )
        ],
        PromptAssemblyContext(
            context_window=16_000,
            tier_budgets={PromptTier.TURN_CONTEXT: 64},
        ),
    )

    segment = result.segments[0]
    public = result.manifest.to_public_dict()["segments"][0]

    assert segment.decision == PromptDecision.TRUNCATED
    assert segment.estimated_tokens <= 64
    assert public["decisionReason"] == "tier_budget_truncated"
    assert public["budgetTokens"] == 64


def test_context_engine_applies_same_turn_budget_and_logs_sanitized_decision() -> None:
    raw = context_engine._context_segment(
        "agent_messages",
        "private inbox " * 200,
        placement="volatile_turn",
        stability="turn_dynamic",
    )
    assert raw is not None

    resolved = context_engine._resolve_context_segments(
        [raw],
        PromptAssemblyContext(
            context_window=16_000,
            tier_budgets={PromptTier.TURN_CONTEXT: 12},
        ),
    )
    summary = context_engine._context_segment_log_summary(resolved)[0]

    assert resolved[0]["decision"] == "truncated"
    assert resolved[0]["estimated_tokens"] <= 12
    assert len(resolved[0]["block"]) < len(raw["block"])
    assert summary["decision"] == "truncated"
    assert summary["decisionReason"] == "tier_budget_truncated"
    assert "private inbox" not in repr(summary)


def _segment(
    key: str,
    content: str,
    *,
    tier: PromptTier,
    required: bool = False,
) -> PromptSegment:
    return PromptSegment.from_content(
        key=key,
        content=content,
        tier=tier,
        placement=(
            PromptPlacement.SYSTEM_PREFIX
            if tier in {
                PromptTier.STABLE_CORE,
                PromptTier.PROTOCOL_ADAPTER,
                PromptTier.SESSION_SNAPSHOT,
            }
            else PromptPlacement.BEFORE_CURRENT_USER
        ),
        stability=(
            PromptStability.PROJECT_STATIC
            if tier == PromptTier.STABLE_CORE
            else PromptStability.TURN_DYNAMIC
        ),
        trust=(
            PromptTrust.PROTECTED_CORE
            if tier == PromptTier.STABLE_CORE
            else PromptTrust.DERIVED_RUNTIME
        ),
        source=f"test.{key.lower()}",
        required=required,
        cache_policy=PromptCachePolicy.NEVER_CACHE,
    )
