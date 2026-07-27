# -*- coding: utf-8 -*-
"""Deterministic Prompt Assembly selection, capability and budget resolver."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from core.prompt_manager.assembly_contract import (
    PromptAssemblyManifest,
    PromptCachePolicy,
    PromptDecision,
    PromptPlacement,
    PromptSegment,
    PromptStability,
    PromptTier,
    PromptTrust,
    estimate_prompt_tokens,
)


CORE_FLOOR = ("COMMON", "SOUL", "AGENTS")


class PromptAssemblyBudgetError(ValueError):
    """Raised when protected Prompt Assembly content cannot fit safely."""


def prompt_assembly_budget(context_window: int) -> int:
    window = int(context_window or 0)
    if window <= 0:
        raise PromptAssemblyBudgetError("missing_context_window")
    return min(24_000, max(4_000, math.floor(window * 0.18)))


def default_tier_budgets(context_window: int) -> dict[PromptTier, int]:
    window = int(context_window or 0)
    if window <= 0:
        raise PromptAssemblyBudgetError("missing_context_window")
    total = prompt_assembly_budget(window)
    return {
        PromptTier.STABLE_CORE: min(6_000, max(3_000, math.floor(window * 0.05))),
        PromptTier.PROTOCOL_ADAPTER: 512,
        PromptTier.SESSION_SNAPSHOT: min(10_000, max(2_000, math.floor(window * 0.06))),
        PromptTier.TURN_CONTEXT: min(8_000, max(1_000, math.floor(window * 0.05))),
        PromptTier.EPHEMERAL_OVERLAY: total,
    }


@dataclass(frozen=True)
class PromptAssemblyContext:
    """Authoritative runtime facts used by the resolver."""

    context_window: int
    max_output_tokens: int = 0
    capabilities: frozenset[str] = frozenset()
    allowed_tools: tuple[str, ...] = ()
    allowed_skills: tuple[str, ...] = ()
    allowed_agents: tuple[str, ...] = ()
    model_protocol: str = ""
    capability_fingerprint: str = ""
    permission_fingerprint: str = ""
    enforce_core_floor: bool = False
    assembly_mode: str = "v2"
    tier_budgets: Mapping[PromptTier, int] = field(default_factory=dict)

    @property
    def total_budget_tokens(self) -> int:
        return prompt_assembly_budget(self.context_window)

    def resolved_tier_budgets(self) -> dict[PromptTier, int]:
        result = default_tier_budgets(self.context_window)
        for raw_tier, raw_budget in dict(self.tier_budgets).items():
            tier = raw_tier if isinstance(raw_tier, PromptTier) else PromptTier(str(raw_tier))
            result[tier] = max(0, int(raw_budget or 0))
        return result


@dataclass(frozen=True)
class PromptResolutionResult:
    segments: tuple[PromptSegment, ...]
    manifest: PromptAssemblyManifest


class PromptSectionResolver:
    """Resolve Prompt segments without consulting model output."""

    def resolve(
        self,
        segments: Iterable[PromptSegment],
        context: PromptAssemblyContext,
    ) -> PromptResolutionResult:
        normalized = tuple(segments)
        if context.enforce_core_floor:
            present = {
                segment.key
                for segment in normalized
                if segment.tier == PromptTier.STABLE_CORE and segment.content
            }
            missing = [name for name in CORE_FLOOR if name not in present]
            if missing:
                raise PromptAssemblyBudgetError(
                    "missing_required_core:" + ",".join(missing)
                )

        tier_budgets = context.resolved_tier_budgets()
        total_budget = context.total_budget_tokens
        used_by_tier = {tier: 0 for tier in PromptTier}
        used_total = 0
        resolved: list[PromptSegment] = []

        for segment in normalized:
            if (
                segment.trust == PromptTrust.UNTRUSTED_CONTENT
                and segment.tier != PromptTier.EPHEMERAL_OVERLAY
            ):
                resolved.append(
                    _rebuild_segment(
                        segment,
                        content="",
                        decision=PromptDecision.BLOCKED,
                        decision_reason="untrusted_content_requires_ephemeral_tier",
                        budget_tokens=0,
                    )
                )
                continue
            missing_capabilities = sorted(
                requirement
                for requirement in segment.capability_requirements
                if requirement not in context.capabilities
            )
            if missing_capabilities:
                resolved.append(
                    _rebuild_segment(
                        segment,
                        content="",
                        decision=PromptDecision.BLOCKED,
                        decision_reason=(
                            "missing_capability:" + ",".join(missing_capabilities)
                        ),
                        budget_tokens=0,
                    )
                )
                continue

            tier_remaining = max(
                0,
                tier_budgets[segment.tier] - used_by_tier[segment.tier],
            )
            total_remaining = max(0, total_budget - used_total)
            available = min(tier_remaining, total_remaining)
            requested = segment.estimated_tokens

            if requested <= available:
                selected = _rebuild_segment(
                    segment,
                    content=segment.content,
                    decision=segment.decision,
                    decision_reason=segment.decision_reason,
                    budget_tokens=available,
                )
            elif segment.tier in {
                PromptTier.STABLE_CORE,
                PromptTier.PROTOCOL_ADAPTER,
            }:
                raise PromptAssemblyBudgetError(
                    "protected_tier_over_budget:"
                    f"{segment.tier.value}:{segment.key}:{requested}>{available}"
                )
            elif segment.tier == PromptTier.SESSION_SNAPSHOT and segment.required:
                raise PromptAssemblyBudgetError(
                    f"required_snapshot_over_budget:{segment.key}:{requested}>{available}"
                )
            elif available <= 0:
                selected = _rebuild_segment(
                    segment,
                    content="",
                    decision=PromptDecision.OMITTED,
                    decision_reason="tier_budget_exhausted",
                    budget_tokens=0,
                )
            else:
                selected = _rebuild_segment(
                    segment,
                    content=_truncate_to_tokens(segment.content, available),
                    decision=PromptDecision.TRUNCATED,
                    decision_reason="tier_budget_truncated",
                    budget_tokens=available,
                )

            if selected.decision not in {
                PromptDecision.OMITTED,
                PromptDecision.BLOCKED,
            }:
                used_by_tier[selected.tier] += selected.estimated_tokens
                used_total += selected.estimated_tokens
            resolved.append(selected)

        manifest = PromptAssemblyManifest.from_segments(
            resolved,
            assembly_mode=context.assembly_mode,
            model_protocol=context.model_protocol,
            capability_fingerprint=context.capability_fingerprint,
            permission_fingerprint=context.permission_fingerprint,
            budget_tokens=total_budget,
        )
        return PromptResolutionResult(segments=tuple(resolved), manifest=manifest)


def render_discovery_index(
    kind: str,
    items: Sequence[Mapping[str, Any]],
    *,
    context: PromptAssemblyContext,
    budget_tokens: int | None = None,
) -> PromptSegment:
    """Render an allowed Skill/Agent index with deterministic degradation."""

    normalized_kind = str(kind or "").strip().lower()
    if normalized_kind not in {"skills", "agents"}:
        raise ValueError(f"unsupported_discovery_index:{normalized_kind}")
    allowed = set(
        context.allowed_skills
        if normalized_kind == "skills"
        else context.allowed_agents
    )
    selected = [
        {
            "name": str(item.get("name") or "").strip(),
            "description": str(item.get("description") or "").strip(),
        }
        for item in items
        if str(item.get("name") or "").strip() in allowed
    ]
    selected.sort(key=lambda item: item["name"])

    index_cap = min(
        2_000,
        max(0, math.floor(context.context_window * 0.01)),
    )
    budget = min(
        index_cap,
        max(0, int(index_cap if budget_tokens is None else budget_tokens)),
    )
    full = "\n".join(
        f"{item['name']} — {item['description']}".rstrip(" —")
        for item in selected
    )
    truncated = "\n".join(
        f"{item['name']} — {_truncate_text(item['description'], 24)}".rstrip(" —")
        for item in selected
    )
    names_only = "\n".join(item["name"] for item in selected)

    if full and estimate_prompt_tokens(full) <= budget:
        content, decision, reason = full, PromptDecision.FULL, "full_description"
    elif truncated and estimate_prompt_tokens(truncated) <= budget:
        content, decision, reason = (
            truncated,
            PromptDecision.TRUNCATED,
            "truncated_description",
        )
    elif names_only and estimate_prompt_tokens(names_only) <= budget:
        content, decision, reason = (
            names_only,
            PromptDecision.INDEX_ONLY,
            "names_only",
        )
    else:
        content, decision, reason = "", PromptDecision.OMITTED, "index_budget_exhausted"

    return PromptSegment.from_content(
        key=f"{normalized_kind.upper()}_INDEX",
        content=content,
        tier=PromptTier.SESSION_SNAPSHOT,
        placement=PromptPlacement.SYSTEM_PREFIX,
        stability=PromptStability.SESSION_STATIC,
        trust=PromptTrust.DERIVED_RUNTIME,
        source=f"prompt_assembly.discovery.{normalized_kind}",
        budget_tokens=budget,
        cache_policy=PromptCachePolicy.CACHEABLE,
        decision=decision,
        decision_reason=reason,
    )


def _rebuild_segment(
    segment: PromptSegment,
    *,
    content: str,
    decision: PromptDecision,
    decision_reason: str,
    budget_tokens: int,
) -> PromptSegment:
    return PromptSegment.from_content(
        key=segment.key,
        content=content,
        tier=segment.tier,
        placement=segment.placement,
        stability=segment.stability,
        trust=segment.trust,
        source=segment.source,
        required=segment.required,
        budget_tokens=budget_tokens,
        cache_policy=segment.cache_policy,
        capability_requirements=segment.capability_requirements,
        decision=decision,
        decision_reason=decision_reason,
        cache_hit=segment.cache_hit,
    )


def _truncate_to_tokens(content: str, budget_tokens: int) -> str:
    raw = str(content or "").encode("utf-8", errors="ignore")
    bounded = raw[: max(0, int(budget_tokens or 0)) * 4]
    return bounded.decode("utf-8", errors="ignore").rstrip()


def _truncate_text(content: str, chars: int) -> str:
    text = str(content or "").strip()
    if len(text) <= chars:
        return text
    return text[: max(0, chars - 1)].rstrip() + "…"


__all__ = [
    "CORE_FLOOR",
    "PromptAssemblyBudgetError",
    "PromptAssemblyContext",
    "PromptResolutionResult",
    "PromptSectionResolver",
    "default_tier_budgets",
    "prompt_assembly_budget",
    "render_discovery_index",
]
