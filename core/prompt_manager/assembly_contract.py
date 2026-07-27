# -*- coding: utf-8 -*-
"""Shared Prompt Assembly segment and sanitized manifest contracts."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Iterable, Mapping


PROMPT_ASSEMBLY_SCHEMA_VERSION = 1
LEGACY_OBSERVE_ASSEMBLY_MODE = "legacy_observe"


class PromptTier(StrEnum):
    STABLE_CORE = "stable_core"
    PROTOCOL_ADAPTER = "protocol_adapter"
    SESSION_SNAPSHOT = "session_snapshot"
    TURN_CONTEXT = "turn_context"
    EPHEMERAL_OVERLAY = "ephemeral_overlay"


class PromptPlacement(StrEnum):
    SYSTEM_PREFIX = "system_prefix"
    BEFORE_CURRENT_USER = "before_current_user"
    CONVERSATION = "conversation"


class PromptStability(StrEnum):
    PROJECT_STATIC = "project_static"
    PROTOCOL_STATIC = "protocol_static"
    SESSION_STATIC = "session_static"
    TURN_DYNAMIC = "turn_dynamic"
    CALL_EPHEMERAL = "call_ephemeral"


class PromptTrust(StrEnum):
    PROTECTED_CORE = "protected_core"
    OPERATOR_CONTROLLED = "operator_controlled"
    DERIVED_RUNTIME = "derived_runtime"
    UNTRUSTED_CONTENT = "untrusted_content"


class PromptDecision(StrEnum):
    FULL = "full"
    TRUNCATED = "truncated"
    INDEX_ONLY = "index_only"
    OMITTED = "omitted"
    BLOCKED = "blocked"


class PromptCachePolicy(StrEnum):
    CACHEABLE = "cacheable"
    PREFIX_CANDIDATE = "prefix_candidate"
    NEVER_CACHE = "never_cache"


def prompt_content_hash(content: str) -> str:
    """Return a bounded content identity suitable for diagnostics."""

    text = str(content or "")
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:16]


def estimate_prompt_tokens(content: str) -> int:
    """Return a deterministic conservative prompt-size estimate."""

    text = str(content or "")
    if not text:
        return 0
    return max(1, math.ceil(len(text.encode("utf-8", errors="ignore")) / 4))


def _enum_value(enum_type: type[StrEnum], value: Any, default: StrEnum) -> StrEnum:
    try:
        return enum_type(str(value or "").strip())
    except ValueError:
        return default


@dataclass(frozen=True)
class PromptSegment:
    """One internal Prompt segment.

    ``content`` remains internal. Public diagnostics must use
    :meth:`to_manifest_entry`, which intentionally omits prompt bodies.
    """

    key: str
    tier: PromptTier
    placement: PromptPlacement
    stability: PromptStability
    trust: PromptTrust
    source: str
    required: bool
    content: str = field(repr=False)
    content_hash: str
    chars: int
    estimated_tokens: int
    budget_tokens: int
    cache_policy: PromptCachePolicy
    capability_requirements: tuple[str, ...]
    decision: PromptDecision
    decision_reason: str
    cache_hit: bool | None = None

    @classmethod
    def from_content(
        cls,
        *,
        key: str,
        content: str,
        tier: PromptTier,
        placement: PromptPlacement,
        stability: PromptStability,
        trust: PromptTrust,
        source: str,
        required: bool = False,
        budget_tokens: int = 0,
        cache_policy: PromptCachePolicy = PromptCachePolicy.NEVER_CACHE,
        capability_requirements: Iterable[str] = (),
        decision: PromptDecision = PromptDecision.FULL,
        decision_reason: str = "rendered",
        cache_hit: bool | None = None,
    ) -> "PromptSegment":
        text = str(content or "")
        return cls(
            key=str(key or "").strip(),
            tier=tier,
            placement=placement,
            stability=stability,
            trust=trust,
            source=str(source or "").strip(),
            required=bool(required),
            content=text,
            content_hash=prompt_content_hash(text),
            chars=len(text),
            estimated_tokens=estimate_prompt_tokens(text),
            budget_tokens=max(0, int(budget_tokens or 0)),
            cache_policy=cache_policy,
            capability_requirements=tuple(
                str(item or "").strip()
                for item in capability_requirements
                if str(item or "").strip()
            ),
            decision=decision,
            decision_reason=str(decision_reason or "").strip(),
            cache_hit=cache_hit,
        )

    @classmethod
    def from_internal_dict(cls, raw: Mapping[str, Any]) -> "PromptSegment":
        content = str(raw.get("block") or raw.get("content") or "")
        placement = _enum_value(
            PromptPlacement,
            raw.get("prompt_placement") or raw.get("placement"),
            PromptPlacement.BEFORE_CURRENT_USER,
        )
        stability = _enum_value(
            PromptStability,
            raw.get("prompt_stability") or raw.get("stability"),
            PromptStability.TURN_DYNAMIC,
        )
        return cls.from_content(
            key=str(raw.get("key") or "").strip(),
            content=content,
            tier=_enum_value(
                PromptTier,
                raw.get("tier"),
                PromptTier.TURN_CONTEXT,
            ),
            placement=placement,
            stability=stability,
            trust=_enum_value(
                PromptTrust,
                raw.get("trust"),
                PromptTrust.DERIVED_RUNTIME,
            ),
            source=str(raw.get("source") or "unknown").strip(),
            required=bool(raw.get("required")),
            budget_tokens=max(0, int(raw.get("budget_tokens") or 0)),
            cache_policy=_enum_value(
                PromptCachePolicy,
                raw.get("cache_policy"),
                PromptCachePolicy.NEVER_CACHE,
            ),
            capability_requirements=tuple(raw.get("capability_requirements") or ()),
            decision=_enum_value(
                PromptDecision,
                raw.get("decision"),
                PromptDecision.FULL,
            ),
            decision_reason=str(raw.get("decision_reason") or "rendered").strip(),
            cache_hit=raw.get("cache_hit") if raw.get("cache_hit") is not None else None,
        )

    def to_internal_dict(
        self,
        *,
        block_key: str = "content",
        legacy_placement: str | None = None,
        legacy_stability: str | None = None,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "key": self.key,
            block_key: self.content,
            "tier": self.tier.value,
            "placement": str(legacy_placement or self.placement.value),
            "prompt_placement": self.placement.value,
            "stability": str(legacy_stability or self.stability.value),
            "prompt_stability": self.stability.value,
            "trust": self.trust.value,
            "source": self.source,
            "required": self.required,
            "chars": self.chars,
            "hash": self.content_hash,
            "estimated_tokens": self.estimated_tokens,
            "budget_tokens": self.budget_tokens,
            "cache_policy": self.cache_policy.value,
            "capability_requirements": list(self.capability_requirements),
            "decision": self.decision.value,
            "decision_reason": self.decision_reason,
        }
        if self.cache_hit is not None:
            result["cache_hit"] = self.cache_hit
        return result

    def to_manifest_entry(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "key": self.key,
            "tier": self.tier.value,
            "placement": self.placement.value,
            "stability": self.stability.value,
            "trust": self.trust.value,
            "source": self.source,
            "required": self.required,
            "chars": self.chars,
            "contentHash": self.content_hash,
            "estimatedTokens": self.estimated_tokens,
            "budgetTokens": self.budget_tokens,
            "cachePolicy": self.cache_policy.value,
            "capabilityRequirements": list(self.capability_requirements),
            "decision": self.decision.value,
            "decisionReason": self.decision_reason,
        }
        if self.cache_hit is not None:
            result["cacheHit"] = self.cache_hit
        return result


@dataclass(frozen=True)
class PromptAssemblyManifest:
    """Sanitized Prompt Assembly diagnostics for one build."""

    segments: tuple[PromptSegment, ...]
    schema_version: int = PROMPT_ASSEMBLY_SCHEMA_VERSION
    assembly_mode: str = LEGACY_OBSERVE_ASSEMBLY_MODE
    model_protocol: str = ""
    capability_fingerprint: str = ""
    permission_fingerprint: str = ""
    stable_prefix_hash: str = ""
    session_snapshot_hash: str = ""
    total_estimated_tokens: int = 0
    budget_tokens: int = 0

    @classmethod
    def from_segments(
        cls,
        segments: Iterable[PromptSegment],
        *,
        assembly_mode: str = LEGACY_OBSERVE_ASSEMBLY_MODE,
        model_protocol: str = "",
        capability_fingerprint: str = "",
        permission_fingerprint: str = "",
        budget_tokens: int = 0,
    ) -> "PromptAssemblyManifest":
        normalized = tuple(segments)
        stable_content = "\n\n".join(
            segment.content
            for segment in normalized
            if segment.placement == PromptPlacement.SYSTEM_PREFIX
            and segment.decision not in {PromptDecision.OMITTED, PromptDecision.BLOCKED}
            and segment.content
        )
        session_content = "\n\n".join(
            segment.content
            for segment in normalized
            if segment.tier == PromptTier.SESSION_SNAPSHOT
            and segment.decision not in {PromptDecision.OMITTED, PromptDecision.BLOCKED}
            and segment.content
        )
        return cls(
            segments=normalized,
            assembly_mode=str(assembly_mode or LEGACY_OBSERVE_ASSEMBLY_MODE),
            model_protocol=str(model_protocol or "").strip(),
            capability_fingerprint=str(capability_fingerprint or "").strip(),
            permission_fingerprint=str(permission_fingerprint or "").strip(),
            stable_prefix_hash=prompt_content_hash(stable_content),
            session_snapshot_hash=prompt_content_hash(session_content),
            total_estimated_tokens=sum(
                segment.estimated_tokens
                for segment in normalized
                if segment.decision not in {PromptDecision.OMITTED, PromptDecision.BLOCKED}
            ),
            budget_tokens=max(0, int(budget_tokens or 0)),
        )

    @classmethod
    def from_internal_segments(
        cls,
        segments: Iterable[Mapping[str, Any]],
        **kwargs: Any,
    ) -> "PromptAssemblyManifest":
        return cls.from_segments(
            (PromptSegment.from_internal_dict(item) for item in segments if isinstance(item, Mapping)),
            **kwargs,
        )

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "assemblyMode": self.assembly_mode,
            "modelProtocol": self.model_protocol,
            "capabilityFingerprint": self.capability_fingerprint,
            "permissionFingerprint": self.permission_fingerprint,
            "stablePrefixHash": self.stable_prefix_hash,
            "sessionSnapshotHash": self.session_snapshot_hash,
            "totalEstimatedTokens": self.total_estimated_tokens,
            "budgetTokens": self.budget_tokens,
            "segments": [segment.to_manifest_entry() for segment in self.segments],
        }
