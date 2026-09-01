"""Context assembly boundary for long-lived Agent runtimes."""

from __future__ import annotations

import json
import re
import hashlib
import threading
import time
import copy
from collections import OrderedDict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from vibelution_storage import resolve_project_memory_home

from core.infrastructure import developer_sandbox
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
from core.prompt_manager.assembly_resolver import (
    PromptAssemblyContext,
    PromptSectionResolver,
)
from core.runtime_manager import agent_run_store
from core.web.services.runtime_scene_service import record_runtime_scene_event


AGENT_RUN_KIND = agent_run_store.AGENT_RUN_KIND
SUB_AGENT_RUN_KIND = agent_run_store.SUB_AGENT_RUN_KIND
_RESEARCH_ORG_CONTEXT_CACHE_TTL_SECONDS = 5.0
_RESEARCH_ORG_CONTEXT_CACHE_LOCK = threading.Lock()
_RESEARCH_ORG_CONTEXT_CACHE: dict[tuple[str, int, tuple[tuple[str, int, str], ...]], dict[str, Any]] = {}
_PROJECT_AGENT_REGISTRY_CACHE_LOCK = threading.Lock()
_PROJECT_AGENT_REGISTRY_CACHE: dict[tuple[str, int, int], dict[str, Any]] = {}
_ACTIVE_AGENT_DIRECTORY_CACHE_LOCK = threading.Lock()
_ACTIVE_AGENT_DIRECTORY_CACHE: dict[tuple[str, int, int], list[dict[str, Any]]] = {}
# Session-scoped byte freeze for cache-prefix context segments.
#
# The first system message merges the ContextEngine "cache_prefix" blocks
# (agent static runtime header, research organization roster, prompt template,
# public structure catalog). Those blocks drift across turns (catalog refresh
# ordering / conflict queue state, roster onboarding progress, template edits),
# which silently invalidates the provider implicit cache every round even
# though the chat history itself is append-only and byte-stable. Freezing the
# rendered bytes per (session, agent) keeps the prefix stable for the session
# lifetime; the shared services underneath stay unfrozen so tool callers and
# other consumers still read fresh data. Frozen semantics: the prompt block is
# a session-start snapshot of low-frequency reference information.
_STATIC_CONTEXT_FREEZE_LOCK = threading.Lock()
_STATIC_CONTEXT_FREEZE_MAX_ENTRIES = 512
# 0 = freeze for the whole session lifetime. A positive value would refresh a
# segment after the TTL elapses (one extra provider cache rebuild per refresh).
_STATIC_CONTEXT_FREEZE_TTL_SECONDS = 0.0
_STATIC_CONTEXT_FREEZE_CACHE: "OrderedDict[tuple[str, str, str], dict[str, Any]]" = OrderedDict()


class AgentContextInterrupted(RuntimeError):
    """Raised when a turn stop is observed during context assembly."""

    def __init__(self, reason: str = "", *, stage: str = "") -> None:
        normalized_reason = str(reason or "").strip()
        super().__init__(normalized_reason or "agent context interrupted")
        self.reason = normalized_reason
        self.stage = str(stage or "").strip()


def raise_if_agent_context_interrupted(interrupt_checker: Any, *, stage: str) -> None:
    if not callable(interrupt_checker):
        return
    try:
        reason = str(interrupt_checker() or "").strip()
    except Exception:
        return
    if reason:
        raise AgentContextInterrupted(reason, stage=stage)


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).decode("utf-8", errors="replace")
    if isinstance(value, str):
        return value
    return str(value)


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (bytes, bytearray, memoryview)):
        value = bytes(value).decode("utf-8", errors="replace")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return bool(value)
    text = str(value).strip().lower()
    if not text:
        return default
    if text in {"1", "true", "yes", "on", "enabled"}:
        return True
    if text in {"0", "false", "no", "off", "disabled"}:
        return False
    return default


def _maybe_json(value: Any) -> Any:
    if isinstance(value, (bytes, bytearray, memoryview)):
        value = bytes(value).decode("utf-8", errors="replace")
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("{") or text.startswith("["):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return value
    return value


def _as_mapping(value: Any) -> dict[str, Any]:
    value = _maybe_json(value)
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _mapping_get(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping:
            return mapping.get(key)
    return None


def _perf_counter() -> float:
    return time.perf_counter()


def _elapsed_ms(started_at: float) -> int:
    return max(0, int(round((_perf_counter() - started_at) * 1000)))


def _file_signature(path: Path) -> tuple[str, int, int] | None:
    try:
        stat = Path(path).stat()
    except OSError:
        return None
    return (str(Path(path)), int(stat.st_mtime_ns), int(stat.st_size))


def _context_hash(value: str) -> str:
    text = _coerce_text(value)
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _context_segment(
    key: str,
    block: str,
    *,
    placement: str,
    stability: str,
    trust: str = "",
    cache_hit: bool | None = None,
) -> dict[str, Any] | None:
    text = _coerce_text(block).strip()
    if not text:
        return None
    normalized_key = _coerce_text(key).strip()
    normalized_placement = _coerce_text(placement).strip()
    normalized_stability = _coerce_text(stability).strip()
    is_cache_prefix = normalized_placement == "cache_prefix"
    if normalized_stability == "project_static":
        prompt_stability = PromptStability.PROJECT_STATIC
    elif normalized_stability in {"agent_static", "session_static"}:
        prompt_stability = PromptStability.SESSION_STATIC
    else:
        prompt_stability = PromptStability.TURN_DYNAMIC
    segment = PromptSegment.from_content(
        key=normalized_key,
        content=text,
        tier=(
            PromptTier.SESSION_SNAPSHOT
            if is_cache_prefix
            else PromptTier.TURN_CONTEXT
        ),
        placement=(
            PromptPlacement.SYSTEM_PREFIX
            if is_cache_prefix
            else PromptPlacement.BEFORE_CURRENT_USER
        ),
        stability=prompt_stability,
        trust=(
            PromptTrust.OPERATOR_CONTROLLED
            if str(trust or "").strip() == "operator_controlled"
            or normalized_key in {"prompt_template", "agent_prompt_snapshot"}
            else PromptTrust.DERIVED_RUNTIME
        ),
        source=f"context_engine.{normalized_key}",
        cache_policy=(
            PromptCachePolicy.CACHEABLE
            if is_cache_prefix
            else PromptCachePolicy.NEVER_CACHE
        ),
        decision=PromptDecision.FULL,
        decision_reason="rendered",
        cache_hit=cache_hit,
    )
    return segment.to_internal_dict(
        block_key="block",
        legacy_placement=normalized_placement,
        legacy_stability=normalized_stability,
    )


def _join_context_segments(segments: list[dict[str, Any]], placement: str) -> str:
    normalized_placement = _coerce_text(placement).strip()
    return "\n\n".join(
        _coerce_text(segment.get("block")).strip()
        for segment in _mapping_items(segments)
        if _coerce_text(segment.get("placement")).strip() == normalized_placement
        and _coerce_text(segment.get("block")).strip()
    ).strip()


def _resolve_context_segments(
    segments: list[dict[str, Any]],
    assembly_context: PromptAssemblyContext,
) -> list[dict[str, Any]]:
    raw_segments = _mapping_items(segments)
    resolution = PromptSectionResolver().resolve(
        (
            PromptSegment.from_internal_dict(segment)
            for segment in raw_segments
        ),
        assembly_context,
    )
    return [
        resolved.to_internal_dict(
            block_key="block",
            legacy_placement=str(raw.get("placement") or ""),
            legacy_stability=str(raw.get("stability") or ""),
        )
        for raw, resolved in zip(raw_segments, resolution.segments)
    ]


def _join_context_blocks(*blocks: str) -> str:
    return "\n\n".join(str(block or "").strip() for block in blocks if str(block or "").strip()).strip()


def _split_agent_runtime_context_block(block: str) -> tuple[str, str]:
    text = str(block or "").strip()
    if not text:
        return "", ""
    lines = text.splitlines()
    dynamic_markers = ("## 个人记忆", "PersonalEpisodes:", "GroupContextEvents:", "AgentInboxMessages:")
    dynamic_start: int | None = None
    for index, line in enumerate(lines):
        stripped = str(line or "").strip()
        if any(stripped.startswith(marker) for marker in dynamic_markers):
            dynamic_start = index
            break
    if dynamic_start is None:
        return text, ""
    return "\n".join(lines[:dynamic_start]).strip(), "\n".join(lines[dynamic_start:]).strip()


def _session_frozen_context_block(
    segment_key: str,
    *,
    agent_id: str,
    session_id: str,
    produce: Any,
    ttl_seconds: float | None = None,
) -> tuple[str, bool]:
    """Return session-frozen bytes for a cache-prefix context segment.

    The first call inside a session invokes ``produce`` and freezes the
    rendered bytes; later calls in the same session reuse those bytes so the
    merged first system message stays byte-stable across turns. A positive
    ``ttl_seconds`` lets the segment refresh after the TTL elapses at the cost
    of one provider cache rebuild. Empty session identity disables the freeze
    (callers without a session cannot scope stable bytes).
    """
    normalized_key = _coerce_text(segment_key).strip()
    normalized_agent = _coerce_text(agent_id).strip()
    normalized_session = _coerce_text(session_id).strip()
    if not normalized_key or not normalized_agent or not normalized_session:
        return _coerce_text(produce() or "").strip(), False
    effective_ttl = (
        _STATIC_CONTEXT_FREEZE_TTL_SECONDS if ttl_seconds is None else float(ttl_seconds)
    )
    cache_key = (normalized_session, normalized_agent, normalized_key)
    now = time.perf_counter()
    with _STATIC_CONTEXT_FREEZE_LOCK:
        cached = _STATIC_CONTEXT_FREEZE_CACHE.get(cache_key)
        if cached is not None:
            age_seconds = now - float(cached.get("createdAt") or 0.0)
            expired = effective_ttl > 0 and age_seconds > effective_ttl
            if not expired:
                _STATIC_CONTEXT_FREEZE_CACHE.move_to_end(cache_key)
                return _coerce_text(cached.get("block") or "").strip(), True
            _STATIC_CONTEXT_FREEZE_CACHE.pop(cache_key, None)
    block = _coerce_text(produce() or "").strip()
    with _STATIC_CONTEXT_FREEZE_LOCK:
        _STATIC_CONTEXT_FREEZE_CACHE[cache_key] = {"block": block, "createdAt": time.perf_counter()}
        _STATIC_CONTEXT_FREEZE_CACHE.move_to_end(cache_key)
        while len(_STATIC_CONTEXT_FREEZE_CACHE) > _STATIC_CONTEXT_FREEZE_MAX_ENTRIES:
            _STATIC_CONTEXT_FREEZE_CACHE.popitem(last=False)
    return block, False


def reset_session_context_freeze_cache() -> None:
    """Drop every frozen session block (test and maintenance seam)."""
    with _STATIC_CONTEXT_FREEZE_LOCK:
        _STATIC_CONTEXT_FREEZE_CACHE.clear()


def _context_segment_log_summary(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for segment in list(segments or []):
        if not isinstance(segment, dict):
            continue
        summary = {
            "key": str(segment.get("key") or "").strip(),
            "placement": str(segment.get("placement") or "").strip(),
            "stability": str(segment.get("stability") or "").strip(),
            "chars": _safe_int(segment.get("chars")),
            "hash": str(segment.get("hash") or "").strip(),
            "estimatedTokens": _safe_int(segment.get("estimated_tokens")),
            "budgetTokens": _safe_int(segment.get("budget_tokens")),
            "decision": str(segment.get("decision") or "").strip(),
            "decisionReason": str(segment.get("decision_reason") or "").strip(),
        }
        if segment.get("cache_hit") is not None:
            summary["cacheHit"] = _coerce_bool(segment.get("cache_hit"), default=False)
        summaries.append(summary)
    return summaries


@dataclass(frozen=True)
class AgentContextPacket:
    agent_id: str
    agent_code: str = ""
    display_name: str = ""
    session_id: str = ""
    run_id: str = ""
    workspace_path: str = ""
    dialogue_model_id: str = ""
    prompt_template_id: str = ""
    role_key: str = ""
    memory_policy: dict[str, Any] = field(default_factory=dict)
    tool_policy: dict[str, Any] = field(default_factory=dict)
    group_context_events: list[dict[str, Any]] = field(default_factory=list)
    inbox_messages: list[dict[str, Any]] = field(default_factory=list)
    episodic_events: list[dict[str, Any]] = field(default_factory=list)
    static_context_block: str = ""
    dynamic_context_block: str = ""
    context_segments: list[dict[str, Any]] = field(default_factory=list)
    context_block: str = ""
    timings: dict[str, Any] = field(default_factory=dict)

    @property
    def prompt_assembly_manifest(self) -> PromptAssemblyManifest:
        return PromptAssemblyManifest.from_internal_segments(self.context_segments)


@dataclass(frozen=True)
class SubAgentContextPacket:
    parent_agent_id: str
    parent_session_id: str
    context_mode: str
    parent_context: AgentContextPacket | None = None


def build_agent_context(
    agent_id: str,
    *,
    session_id: str = "",
    run_id: str = "",
    limit: int = 6,
    agent_snapshot: dict[str, Any] | None = None,
    include_prompt_template_context: bool = True,
    assembly_context: PromptAssemblyContext | None = None,
    interrupt_checker: Any = None,
) -> AgentContextPacket:
    """Build the bounded context packet used by a persistent Agent turn."""

    from core.web.services import agent_directory_service

    context_started_at = _perf_counter()
    timings: dict[str, Any] = {}

    def _stop(stage: str) -> None:
        raise_if_agent_context_interrupted(
            interrupt_checker,
            stage=f"prepare_agent_context.{stage}",
        )
    normalized_agent_id = _coerce_text(agent_id).strip()
    bounded_limit = _bounded_limit(limit, default=6)
    session_id = _coerce_text(session_id).strip()
    run_id = _coerce_text(run_id).strip()
    include_prompt_template_context = _coerce_bool(include_prompt_template_context, default=True)
    stage_started_at = _perf_counter()
    supplied_agent = _as_mapping(agent_snapshot)
    snapshot_agent_id = _coerce_text(_mapping_get(supplied_agent, "agentId", "agent_id")).strip()
    if supplied_agent and snapshot_agent_id != normalized_agent_id:
        supplied_agent = {}
    agent = supplied_agent or agent_directory_service.get_agent(normalized_agent_id, include_archived=False)
    historical_agent = (
        None
        if agent
        else agent_directory_service.get_agent(normalized_agent_id, include_archived=True)
    )
    timings["agentLookupMs"] = _elapsed_ms(stage_started_at)
    if not agent:
        status = str((historical_agent or {}).get("status") or "").strip().lower()
        reason = "archived_agent" if status == "archived" else "missing_agent"
        _record_context_event(
            "agent_runtime.resolve_failed",
            outcome="failed",
            level="error",
            fields={
                "agentId": normalized_agent_id,
                "sessionId": session_id,
                "runId": run_id,
                "reason": reason,
                "agentStatus": status,
                "source": "ContextEngine",
            },
        )
        return AgentContextPacket(
            agent_id=normalized_agent_id,
            session_id=session_id,
            run_id=run_id,
            timings={
                "reason": reason,
                "agentStatus": status,
                "totalDurationMs": _elapsed_ms(context_started_at),
                **timings,
            },
        )

    _stop("episodic_events")
    stage_started_at = _perf_counter()
    episodic_events = agent_directory_service.list_current_episodic_events(
        normalized_agent_id,
        limit=agent_directory_service.PROMPT_LIST_LIMIT,
    )
    timings["episodicEventsMs"] = _elapsed_ms(stage_started_at)
    _stop("group_context_events")
    stage_started_at = _perf_counter()
    group_events = agent_directory_service.list_group_context_events_for_agent(
        normalized_agent_id,
        limit=bounded_limit,
        prompt_eligible_only=True,
    )
    timings["groupContextEventsMs"] = _elapsed_ms(stage_started_at)
    _stop("inbox_messages")
    stage_started_at = _perf_counter()
    inbox_messages = agent_directory_service.list_agent_inbox_messages_for_agent(
        normalized_agent_id,
        limit=bounded_limit,
        status="pending",
        prompt_eligible_only=True,
    )
    timings["inboxMessagesMs"] = _elapsed_ms(stage_started_at)
    _stop("memory_policy")
    stage_started_at = _perf_counter()
    memory_policy = agent_directory_service.resolve_memory_policy_for_agent(normalized_agent_id)
    timings["memoryPolicyMs"] = _elapsed_ms(stage_started_at)
    _stop("runtime_context_block")
    stage_started_at = _perf_counter()
    raw_runtime_context_block = agent_directory_service.build_agent_runtime_context_block(
        normalized_agent_id,
        limit=bounded_limit,
        agent_snapshot=agent,
        group_events_snapshot=group_events,
        inbox_messages_snapshot=inbox_messages,
        episodic_events_snapshot=episodic_events,
        memory_policy_snapshot=memory_policy,
    )
    timings["runtimeContextBlockMs"] = _elapsed_ms(stage_started_at)

    def _produce_agent_static_block() -> str:
        static_part, _dynamic_part = _split_agent_runtime_context_block(raw_runtime_context_block)
        return static_part

    agent_static_context_block, agent_static_frozen = _session_frozen_context_block(
        "agent_runtime",
        agent_id=normalized_agent_id,
        session_id=session_id,
        produce=_produce_agent_static_block,
    )
    timings["agentRuntimeStaticFrozen"] = bool(agent_static_frozen)
    # The dynamic half (episodes / group events / inbox) stays per-turn fresh;
    # only the static header bytes are session-frozen.
    _static_probe, agent_dynamic_context_block = _split_agent_runtime_context_block(raw_runtime_context_block)
    research_org_context_block = ""
    research_org_frozen = False
    if _agent_needs_research_organization_context(agent):
        _stop("research_organization")
        stage_started_at = _perf_counter()
        research_org_probe: dict[str, Any] = {}

        def _produce_research_org_block() -> str:
            research_org_result = _build_research_organization_context_block(
                normalized_agent_id,
                limit=bounded_limit,
            )
            research_org_probe.update(research_org_result)
            return str(research_org_result.get("contextBlock") or "")

        research_org_context_block, research_org_frozen = _session_frozen_context_block(
            "research_organization",
            agent_id=normalized_agent_id,
            session_id=session_id,
            produce=_produce_research_org_block,
        )
        timings["researchOrgContextFrozen"] = bool(research_org_frozen)
        if research_org_frozen:
            timings["researchOrgContextCacheHit"] = True
            timings["researchOrgContextCacheAgeMs"] = 0
        elif "cacheHit" in research_org_probe:
            timings["researchOrgContextCacheHit"] = bool(research_org_probe.get("cacheHit"))
            timings["researchOrgContextCacheAgeMs"] = research_org_probe.get("cacheAgeMs")
        timings["researchOrgContextMs"] = _elapsed_ms(stage_started_at)
    else:
        timings["researchOrgContextMs"] = 0
        timings["researchOrgContextSkipped"] = True
    prompt_template_id = _coerce_text(
        _mapping_get(agent, "promptTemplateId", "prompt_template_id")
    ).strip()
    prompt_context_block = ""
    prompt_template_frozen = False
    if include_prompt_template_context:
        _stop("prompt_template")
        stage_started_at = _perf_counter()

        def _produce_prompt_template_block() -> str:
            return _build_prompt_template_context_block(
                prompt_template_id,
                project_root=agent_directory_service.PROJECT_ROOT,
                agent_id=normalized_agent_id,
                session_id=session_id,
                run_id=run_id,
                include_chat_base=_coerce_text(
                    _mapping_get(agent, "primaryMode", "primary_mode")
                ).strip().lower()
                == "chat",
            )

        prompt_context_block, prompt_template_frozen = _session_frozen_context_block(
            "prompt_template",
            agent_id=normalized_agent_id,
            session_id=session_id,
            produce=_produce_prompt_template_block,
        )
        timings["promptTemplateContextFrozen"] = bool(prompt_template_frozen)
        timings["promptTemplateContextMs"] = _elapsed_ms(stage_started_at)
    else:
        timings["promptTemplateContextMs"] = 0
        timings["promptTemplateContextSkipped"] = True
    # COMMON / SOUL / AGENTS are owned by PromptManager and session snapshots.
    # ContextEngine must not inject a second, independently filtered AGENTS copy.
    timings["projectRulesContextMs"] = 0
    timings["projectRulesContextSkipped"] = True
    project_agent_registry_context_block = ""
    if _agent_allows_project_agent_registry_context(agent):
        _stop("project_agent_registry")
        stage_started_at = _perf_counter()
        project_agent_registry_context_block = _build_project_agent_registry_context_block(
            agent_directory_service.PROJECT_ROOT,
            current_agent=agent,
            session_id=str(session_id or "").strip(),
            run_id=str(run_id or "").strip(),
        )
        timings["projectAgentRegistryContextMs"] = _elapsed_ms(stage_started_at)
    else:
        timings["projectAgentRegistryContextMs"] = 0
        timings["projectAgentRegistryContextSkipped"] = True
    public_structure_context_block = ""
    public_structure_frozen = False
    if _agent_allows_public_structure_context(agent):
        _stop("public_structure")
        stage_started_at = _perf_counter()

        def _produce_public_structure_block() -> str:
            public_structure_result = _build_public_structure_context_block(
                agent_directory_service.PROJECT_ROOT,
                agent_id=normalized_agent_id,
            )
            return str(public_structure_result.get("contextBlock") or "")

        public_structure_context_block, public_structure_frozen = _session_frozen_context_block(
            "public_structure",
            agent_id=normalized_agent_id,
            session_id=session_id,
            produce=_produce_public_structure_block,
        )
        timings["publicStructureContextFrozen"] = bool(public_structure_frozen)
        timings["publicStructureContextMs"] = _elapsed_ms(stage_started_at)
    else:
        timings["publicStructureContextMs"] = 0
        timings["publicStructureContextSkipped"] = True
    frozen_static_segments = [
        segment_key
        for segment_key, frozen_flag in (
            ("agent_runtime", agent_static_frozen),
            ("research_organization", research_org_frozen),
            ("prompt_template", prompt_template_frozen),
            ("public_structure", public_structure_frozen),
        )
        if frozen_flag
    ]
    if frozen_static_segments:
        timings["staticContextFrozenSegments"] = list(frozen_static_segments)
    context_segments = [
        segment
        for segment in (
            _context_segment(
                "agent_runtime",
                agent_static_context_block,
                placement="cache_prefix",
                stability="agent_static",
            ),
            _context_segment(
                "research_organization",
                research_org_context_block,
                placement="cache_prefix",
                stability="project_static",
                cache_hit=timings.get("researchOrgContextCacheHit") if "researchOrgContextCacheHit" in timings else None,
            ),
            _context_segment(
                "prompt_template",
                prompt_context_block,
                placement="cache_prefix",
                stability="agent_static",
            ),
            _context_segment(
                "public_structure",
                public_structure_context_block,
                placement="cache_prefix",
                stability="project_static",
            ),
            _context_segment(
                "project_agent_registry",
                project_agent_registry_context_block,
                placement="volatile_turn",
                stability="turn_dynamic",
            ),
            _context_segment(
                "agent_messages",
                agent_dynamic_context_block,
                placement="volatile_turn",
                stability="turn_dynamic",
            ),
        )
        if segment is not None
    ]
    # Trusted first-party Agent plugins append bounded segments. Providers fail
    # closed and unbound/disabled Agents return no placeholder segment.
    try:
        from core.agent_plugins.runtime_extensions import (
            build_agent_plugin_prompt_segments,
        )

        for plugin_segment in build_agent_plugin_prompt_segments(
            normalized_agent_id,
            session_id=session_id,
            run_id=run_id,
        ):
            normalized_plugin_segment = _context_segment(
                _coerce_text(plugin_segment.get("key")).strip(),
                _coerce_text(plugin_segment.get("block")).strip(),
                placement=_coerce_text(plugin_segment.get("placement")).strip()
                or "volatile_turn",
                stability=_coerce_text(plugin_segment.get("stability")).strip()
                or "turn_dynamic",
                trust=_coerce_text(plugin_segment.get("trust")).strip(),
            )
            if normalized_plugin_segment is not None:
                context_segments.append(normalized_plugin_segment)
    except Exception:
        # Plugin context must never break ordinary Agent turns.
        pass
    if assembly_context is not None:
        context_segments = _resolve_context_segments(
            context_segments,
            assembly_context,
        )
    static_context_block = _join_context_segments(context_segments, "cache_prefix")
    dynamic_context_block = _join_context_segments(context_segments, "volatile_turn")
    runtime_context_block = _join_context_blocks(static_context_block, dynamic_context_block)
    _stop("tool_policy")
    stage_started_at = _perf_counter()
    tool_policy = agent_directory_service.resolve_tool_policy_for_agent(normalized_agent_id)
    timings["toolPolicyMs"] = _elapsed_ms(stage_started_at)
    timings["staticContextChars"] = len(static_context_block)
    timings["dynamicContextChars"] = len(dynamic_context_block)
    timings["staticContextHash"] = _context_hash(static_context_block)
    timings["dynamicContextHash"] = _context_hash(dynamic_context_block)
    timings["contextSegmentCount"] = len(context_segments)
    timings["totalDurationMs"] = _elapsed_ms(context_started_at)
    packet = AgentContextPacket(
        agent_id=normalized_agent_id,
        agent_code=_coerce_text(_mapping_get(agent, "agentCode", "agent_code")).strip(),
        display_name=_coerce_text(_mapping_get(agent, "displayName", "display_name")).strip(),
        session_id=session_id,
        run_id=run_id,
        workspace_path=_coerce_text(_mapping_get(agent, "workspacePath", "workspace_path")).strip(),
        dialogue_model_id=agent_directory_service.agent_dialogue_model_id(agent),
        prompt_template_id=prompt_template_id,
        role_key=_coerce_text(_mapping_get(agent, "roleKey", "role_key")).strip(),
        memory_policy=memory_policy,
        tool_policy=tool_policy,
        group_context_events=group_events,
        inbox_messages=inbox_messages,
        episodic_events=episodic_events,
        static_context_block=static_context_block,
        dynamic_context_block=dynamic_context_block,
        context_segments=context_segments,
        context_block=runtime_context_block,
        timings=dict(timings),
    )
    _record_context_event(
        "agent_runtime.resolved",
        outcome="resolved",
        fields={
            "agentId": packet.agent_id,
            "agentCode": packet.agent_code,
            "sessionId": packet.session_id,
            "runId": packet.run_id,
            "dialogueModelId": packet.dialogue_model_id,
            "promptTemplateId": packet.prompt_template_id,
            "promptTemplateContextSkipped": bool(timings.get("promptTemplateContextSkipped")),
            "roleKey": packet.role_key,
            "groupContextEventCount": len(packet.group_context_events),
            "inboxMessageCount": len(packet.inbox_messages),
            "researchOrgContextIncluded": bool(research_org_context_block),
            "researchOrgContextCacheHit": bool(timings.get("researchOrgContextCacheHit")),
            "researchOrgContextCacheAgeMs": timings.get("researchOrgContextCacheAgeMs", 0),
            "projectRulesContextIncluded": False,
            "projectRulesContextOwner": "prompt_manager_or_session_snapshot",
            "projectAgentRegistryContextIncluded": bool(project_agent_registry_context_block),
            "publicStructureContextIncluded": bool(public_structure_context_block),
            "staticContextChars": timings["staticContextChars"],
            "dynamicContextChars": timings["dynamicContextChars"],
            "staticContextHash": timings["staticContextHash"],
            "dynamicContextHash": timings["dynamicContextHash"],
            "staticContextFrozenSegments": timings.get("staticContextFrozenSegments", []),
            "contextSegmentCount": timings["contextSegmentCount"],
            "contextSegments": _context_segment_log_summary(context_segments),
            "source": "ContextEngine",
        },
    )
    return packet


def _build_research_organization_context_block(agent_id: str, *, limit: int = 6) -> dict[str, Any]:
    """Return the research organization context block, logging service failures at the turn seam."""

    normalized_agent_id = str(agent_id or "").strip()
    bounded_limit = _bounded_limit(limit, default=6)
    try:
        from core.web.services import agent_directory_service, research_organization_service

        project_root = Path(agent_directory_service.PROJECT_ROOT)
        signature = _research_organization_context_signature(project_root, research_organization_service)
        cache_key = (normalized_agent_id, bounded_limit, signature)
        now = _perf_counter()
        with _RESEARCH_ORG_CONTEXT_CACHE_LOCK:
            cached = _RESEARCH_ORG_CONTEXT_CACHE.get(cache_key)
            if cached:
                age_seconds = now - float(cached.get("createdAt") or 0)
                if 0 <= age_seconds <= _RESEARCH_ORG_CONTEXT_CACHE_TTL_SECONDS:
                    return {
                        "contextBlock": str(cached.get("contextBlock") or ""),
                        "cacheHit": True,
                        "cacheAgeMs": max(0, int(round(age_seconds * 1000))),
                    }
                _RESEARCH_ORG_CONTEXT_CACHE.pop(cache_key, None)

        context_block = research_organization_service.build_research_organization_context_block(
            normalized_agent_id,
            limit=bounded_limit,
        )
        signature = _research_organization_context_signature(project_root, research_organization_service)
        cache_key = (normalized_agent_id, bounded_limit, signature)
        with _RESEARCH_ORG_CONTEXT_CACHE_LOCK:
            _RESEARCH_ORG_CONTEXT_CACHE[cache_key] = {
                "createdAt": _perf_counter(),
                "contextBlock": context_block,
            }
        return {
            "contextBlock": str(context_block or ""),
            "cacheHit": False,
            "cacheAgeMs": 0,
        }
    except Exception as exc:
        _record_context_event(
            "agent_runtime.research_org_context_failed",
            outcome="failed",
            level="warning",
            fields={
                "agentId": normalized_agent_id,
                "reason": type(exc).__name__,
                "source": "ContextEngine",
            },
        )
        return {
            "contextBlock": "",
            "cacheHit": False,
            "cacheAgeMs": 0,
        }


def _research_organization_context_signature(
    project_root: Path,
    research_organization_service: Any,
) -> tuple[tuple[str, int, str], ...]:
    watched_paths = [
        _workspace_path(project_root, "agents", "agents.json"),
    ]
    try:
        workspace = research_organization_service.get_workspace()
        getter = getattr(workspace, "get_research_organization_path", None)
        if callable(getter):
            watched_paths.append(Path(getter()))
    except Exception:
        watched_paths.append(_workspace_path(project_root, "research", "organization_graph.json"))
    return tuple(_file_signature(path) for path in watched_paths)


def _file_signature(path: Path) -> tuple[str, int, str]:
    try:
        payload = Path(path).read_bytes()
    except OSError:
        return (str(path), -1, "")
    return (str(path), len(payload), hashlib.sha256(payload).hexdigest())


def _agent_needs_research_organization_context(agent: dict[str, Any]) -> bool:
    """Return true only for Agents that can reasonably belong to the research org graph."""

    agent_payload = _as_mapping(agent)
    metadata = _as_mapping(_mapping_get(agent_payload, "metadata"))
    primary_mode = _coerce_text(
        _mapping_get(agent_payload, "primaryMode", "primary_mode")
        or _mapping_get(metadata, "primaryMode", "primary_mode")
    ).strip().lower()
    if primary_mode == "research":
        return True
    role_key = _coerce_text(
        _mapping_get(agent_payload, "roleKey", "role_key")
        or _mapping_get(metadata, "roleKey", "role_key")
    ).strip().lower()
    if role_key.startswith("research_") or role_key in {"ceo", "organization_advisor", "capability_steward"}:
        return True
    prompt_template_id = _coerce_text(
        _mapping_get(agent_payload, "promptTemplateId", "prompt_template_id")
        or _mapping_get(metadata, "promptTemplateId", "prompt_template_id")
    ).strip().lower()
    if prompt_template_id.startswith("prompt-research"):
        return True
    research_role = _coerce_text(
        _mapping_get(metadata, "researchOrgRole", "research_org_role", "systemRole", "system_role")
    ).strip()
    return bool(research_role)


def _agent_allows_public_structure_context(agent: dict[str, Any]) -> bool:
    """Keep the curated public structure digest opt-in per Agent.

    The digest is an independent segment (``public_structure``) with its own
    exclusion set; it never re-injects AGENTS/COMMON/SOUL (PromptManager owns
    those) and never includes agent_directory projections.
    """
    metadata = _as_mapping(_mapping_get(_as_mapping(agent), "metadata"))
    for key in (
        "includePublicStructureContext",
        "publicStructureContextEnabled",
        "runtimePublicStructureContext",
    ):
        if _coerce_bool(metadata.get(key), default=False):
            return True
    return False


def _build_public_structure_context_block(project_root: Path, *, agent_id: str) -> dict[str, Any]:
    """Return the bounded public structure digest, logging failures at the turn seam."""
    try:
        from core.web.services import team_knowledge_service

        result = team_knowledge_service.build_startup_structure_block(agent_id=agent_id)
        return {
            "contextBlock": str(result.get("block") or ""),
            "budget": dict(result.get("budget") or {}),
        }
    except Exception as exc:
        _record_context_event(
            "agent_runtime.public_structure_context_failed",
            outcome="failed",
            level="warning",
            fields={
                "agentId": str(agent_id or "").strip(),
                "reason": type(exc).__name__,
                "source": "ContextEngine",
            },
        )
        return {"contextBlock": "", "budget": {}}


def _agent_allows_project_agent_registry_context(agent: dict[str, Any]) -> bool:
    """Keep development-lane registry context out of product Agent prompts unless explicitly enabled."""

    metadata = _as_mapping(_mapping_get(_as_mapping(agent), "metadata"))
    for key in (
        "includeProjectAgentRegistryContext",
        "projectAgentRegistryContextEnabled",
        "runtimeProjectRegistryContext",
    ):
        if _coerce_bool(metadata.get(key), default=False):
            return True
    return False


def prepare_subagent_spawn(
    parent_agent_id: str,
    parent_session_id: str,
    *,
    context_mode: str,
    requested_depth: int | None = None,
) -> SubAgentContextPacket:
    """Prepare an isolated or explicit fork context for a temporary sub-agent."""

    normalized_mode = _coerce_text(context_mode or "isolated").strip().lower()
    if normalized_mode not in {"isolated", "fork"}:
        raise ValueError("Sub-agent context_mode must be isolated or fork.")
    from core.web.services import agent_directory_service

    decision = agent_directory_service.evaluate_delegation_policy(
        agent_directory_service.resolve_delegation_policy_for_agent(parent_agent_id),
        agent_id=str(parent_agent_id or "").strip(),
        context_mode=normalized_mode,
        requested_depth=requested_depth,
    )
    if not decision.allowed:
        _record_context_event(
            "subagent.context_blocked",
            outcome="blocked",
            level="warning",
            fields={
                "parentAgentId": str(parent_agent_id or "").strip(),
                "parentSessionId": str(parent_session_id or "").strip(),
                "contextMode": normalized_mode,
                "reason": decision.reason,
                "maxDepth": decision.max_depth,
            },
        )
        raise ValueError(decision.message or "Sub-agent spawn blocked by DelegationPolicy.")
    parent_context = (
        build_agent_context(parent_agent_id, session_id=parent_session_id)
        if normalized_mode == "fork"
        else None
    )
    packet = SubAgentContextPacket(
        parent_agent_id=str(parent_agent_id or "").strip(),
        parent_session_id=str(parent_session_id or "").strip(),
        context_mode=normalized_mode,
        parent_context=parent_context,
    )
    _record_context_event(
        "subagent.context_prepared",
        outcome="prepared",
        fields={
            "parentAgentId": packet.parent_agent_id,
            "parentSessionId": packet.parent_session_id,
            "contextMode": packet.context_mode,
            "forked": packet.parent_context is not None,
        },
    )
    return packet


def record_agent_turn_result(
    agent_id: str,
    session_id: str,
    result: dict[str, Any],
    *,
    run_id: str = "",
) -> dict[str, Any] | None:
    """Persist a bounded result breadcrumb for an Agent turn."""

    from core.web.services import agent_directory_service

    normalized_agent_id = _coerce_text(agent_id).strip()
    agent = agent_directory_service.get_agent(normalized_agent_id)
    if not agent:
        return None
    result_payload = _as_mapping(result)
    event_id = f"turn-{_now_compact()}"
    source_run_id = _coerce_text(
        run_id
        or _mapping_get(result_payload, "runId", "run_id", "turnId", "turn_id")
    ).strip()
    status = agent_run_store.result_status(result_payload)
    summary = agent_run_store.result_summary(result_payload)
    tool_call_count = _safe_int(
        _first_present(
            _mapping_get(result_payload, "tool_call_count", "toolCallCount"),
        )
    )
    created_at = _now()
    payload = {
        "eventId": event_id,
        "runId": source_run_id,
        "agentId": normalized_agent_id,
        "sessionId": _coerce_text(session_id).strip(),
        "status": status,
        "summary": summary,
        "toolCallCount": tool_call_count,
        "createdAt": created_at,
    }
    _append_agent_event(
        agent_directory_service.PROJECT_ROOT,
        _coerce_text(_mapping_get(agent, "workspacePath", "workspace_path")),
        "agent_turn_results.jsonl",
        payload,
    )
    snapshot = agent_run_store.persist_agent_run_snapshot(
        agent,
        source_run_id=source_run_id or event_id,
        session_id=payload["sessionId"],
        status=status,
        summary=summary,
        tool_call_count=tool_call_count,
        timestamp=created_at,
        result=result_payload,
    )
    _record_context_event(
        "agent_context.turn_result_recorded",
        outcome="written",
        fields={
            "agentId": normalized_agent_id,
            "runId": snapshot.get("runId") if snapshot else "",
            "sourceRunId": source_run_id,
            "sessionId": payload["sessionId"],
            "status": payload["status"],
            "toolCallCount": payload["toolCallCount"],
        },
    )
    return snapshot


def record_subagent_result(parent_run_id: str, sub_run_id: str, result: dict[str, Any]) -> dict[str, Any]:
    """Persist a bounded sub-agent completion breadcrumb."""

    from core.web.services import agent_directory_service

    result_payload = _as_mapping(result)
    status = agent_run_store.result_status(result_payload)
    summary = agent_run_store.result_summary(result_payload)
    created_at = _now()
    payload = {
        "parentRunId": _coerce_text(parent_run_id).strip(),
        "subRunId": _coerce_text(sub_run_id).strip(),
        "status": status,
        "summary": summary,
        "createdAt": created_at,
    }
    path = _workspace_path(Path(agent_directory_service.PROJECT_ROOT), "agent_runs", "subagent_results.jsonl")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    snapshot = agent_run_store.persist_sub_agent_run_snapshot(
        parent_run_id=payload["parentRunId"],
        sub_run_id=payload["subRunId"],
        status=status,
        summary=summary,
        tool_call_count=_safe_int(
            _first_present(
                _mapping_get(result_payload, "tool_call_count", "toolCallCount"),
            )
        ),
        timestamp=created_at,
        result=result_payload,
    )
    _record_context_event(
        "subagent.result_recorded",
        outcome="written",
        fields={
            "parentRunId": payload["parentRunId"],
            "subRunId": payload["subRunId"],
            "runId": snapshot.get("runId") or "",
            "status": payload["status"],
        },
    )
    return snapshot


def list_agent_runs_for_agent(agent_id: str, *, limit: int = 20) -> dict[str, Any]:
    """Return recent bounded AgentRun/SubAgentRun snapshots for one persistent Agent."""

    return agent_run_store.list_agent_runs_for_agent(
        agent_id,
        limit=_bounded_limit(limit, default=20),
    )


def list_agent_runs_for_agents(agent_ids: list[str], *, limit: int = 20) -> dict[str, Any]:
    """Return recent bounded AgentRun/SubAgentRun snapshots for many persistent Agents."""

    return agent_run_store.list_agent_runs_for_agents(
        _coerce_str_list(agent_ids),
        limit=_bounded_limit(limit, default=20),
    )


def _append_agent_event(project_root: Path, workspace_path: str, filename: str, payload: dict[str, Any]) -> None:
    safe_workspace = str(workspace_path or "").strip()
    if not safe_workspace:
        return
    root = Path(project_root).resolve()
    normalized = safe_workspace.replace("\\", "/").strip("/")
    parts = PurePosixPath(normalized).parts
    if parts and parts[0] == "workspace":
        workspace_root = developer_sandbox.sandboxed_workspace_path(root).resolve()
        event_path = (workspace_root.joinpath(*parts[1:]) / "events" / filename).resolve()
        if workspace_root != event_path and workspace_root not in event_path.parents:
            return
    else:
        event_path = (root / normalized / "events" / filename).resolve()
        if root != event_path and root not in event_path.parents:
            return
    event_path.parent.mkdir(parents=True, exist_ok=True)
    with event_path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _workspace_path(project_root: Path, *parts: str) -> Path:
    return developer_sandbox.seeded_sandbox_workspace_path(Path(project_root), *parts)


def _build_prompt_template_context_block(
    prompt_template_id: str,
    *,
    project_root: Path,
    agent_id: str,
    session_id: str,
    run_id: str,
    include_chat_base: bool = False,
) -> str:
    normalized = str(prompt_template_id or "").strip()
    if not normalized:
        return ""
    from core.web.services import prompt_template_service

    result = prompt_template_service.build_agent_prompt_template_context(
        normalized,
        project_root=project_root,
        include_chat_base=include_chat_base,
    )
    reason = str(result.get("reason") or "").strip()
    if reason == "missing_template":
        _record_context_event(
            "agent_runtime.prompt_template_missing",
            outcome="missing_prompt_template",
            level="warning",
            fields={
                "agentId": agent_id,
                "sessionId": session_id,
                "runId": run_id,
                "promptTemplateId": normalized,
                "reason": "missing_template",
                "source": "ContextEngine",
            },
        )
        return ""
    if reason == "empty_template_content":
        is_default_chat_template = normalized == "prompt-chat-default"
        _record_context_event(
            "agent_runtime.prompt_template_empty_fallback" if is_default_chat_template else "agent_runtime.prompt_template_missing",
            outcome="empty_prompt_template" if is_default_chat_template else "missing_prompt_template",
            level="info" if is_default_chat_template else "warning",
            fields={
                "agentId": agent_id,
                "sessionId": session_id,
                "runId": run_id,
                "promptTemplateId": normalized,
                "sourcePath": str(result.get("sourcePath") or "").strip(),
                "sourceExists": bool(result.get("sourceExists")),
                "reason": "empty_template_content",
                "source": "ContextEngine",
            },
        )
        return ""
    return str(result.get("contextBlock") or "").strip()


def _build_project_agent_registry_context_block(
    project_root: Path,
    *,
    current_agent: dict[str, Any],
    session_id: str,
    run_id: str,
) -> str:
    """Return project-local Agent territory and handoff context for a session Agent."""

    agent_id = str(current_agent.get("agentId") or "").strip()
    if not agent_id:
        return ""
    from core.web.services import agent_directory_service

    registry_path = resolve_project_memory_home(project_root) / "agent-registry.json"
    registry = _ensure_project_agent_registry(
        registry_path,
        agent_id=agent_id,
        session_id=session_id,
        run_id=run_id,
    )
    active_agents, active_agent_cache_hit = _active_project_agents_from_directory(agent_directory_service)
    entries = _merge_project_agent_registry_entries(registry, active_agents)
    current_entry = _find_project_agent_registry_entry(
        entries,
        agent_id=agent_id,
        session_id=session_id or str(current_agent.get("directSessionId") or "").strip(),
    )
    if not current_entry:
        return ""
    handoff_entries = _project_agent_handoff_entries(current_entry, entries, limit=8)
    lines = [
        "## Project Agent Territory Registry",
        "Source: active external project memory/agent-registry.json + active AgentDirectory",
        "Contract:",
        "- You are bound to the sessionId and management territory listed below.",
        (
            "- If a user request is outside your management scope, say it is out of scope "
            "and recommend a matching Agent/session from HandoffTargets."
        ),
        (
            "- Do not silently take over another Agent's territory; recommend handoff "
            "unless the user explicitly asks you to coordinate."
        ),
        "CurrentAgent:",
        _format_project_agent_registry_entry(current_entry, include_scope=True),
    ]
    if handoff_entries:
        lines.append("HandoffTargets:")
        lines.extend(
            _format_project_agent_registry_entry(entry, include_scope=True, prefix="- ")
            for entry in handoff_entries
        )
    else:
        lines.append("HandoffTargets: none")
    block = "\n".join(line for line in lines if str(line or "").strip()).strip()
    _record_context_event(
        "agent_runtime.project_agent_registry_context_loaded",
        outcome="included",
        fields={
            "agentId": agent_id,
            "sessionId": session_id,
            "runId": run_id,
            "sourcePath": str(registry_path),
            "sourceExists": registry_path.exists(),
            "autoInitialized": bool(registry.get("_autoInitialized")),
            "cacheHit": bool(registry.get("_cacheHit")),
            "activeAgentDirectoryCacheHit": active_agent_cache_hit,
            "registryAgentCount": len(entries),
            "handoffTargetCount": len(handoff_entries),
            "source": "ContextEngine",
        },
    )
    return block


def _active_project_agents_from_directory(agent_directory_service: Any) -> tuple[list[dict[str, Any]], bool]:
    signature = _file_signature(agent_directory_service.registry_path())
    if signature is not None:
        with _ACTIVE_AGENT_DIRECTORY_CACHE_LOCK:
            cached = _ACTIVE_AGENT_DIRECTORY_CACHE.get(signature)
        if isinstance(cached, list):
            return copy.deepcopy(cached), True
    active_agents = [
        item
        for item in agent_directory_service.list_agents(include_archived=False)
        if isinstance(item, dict) and str(item.get("agentId") or "").strip()
    ]
    if signature is not None:
        with _ACTIVE_AGENT_DIRECTORY_CACHE_LOCK:
            _ACTIVE_AGENT_DIRECTORY_CACHE.clear()
            _ACTIVE_AGENT_DIRECTORY_CACHE[signature] = copy.deepcopy(active_agents)
    return active_agents, False


def _ensure_project_agent_registry(
    registry_path: Path,
    *,
    agent_id: str,
    session_id: str,
    run_id: str,
) -> dict[str, Any]:
    registry = _read_project_agent_registry(
        registry_path,
        agent_id=agent_id,
        session_id=session_id,
        run_id=run_id,
    )
    if registry:
        return registry
    if registry_path.exists():
        return _default_project_agent_registry(registry_path.parent, auto_initialized=False)
    default_registry = _default_project_agent_registry(registry_path.parent)
    try:
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        registry_path.write_text(
            json.dumps(default_registry, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    except OSError as exc:
        _record_context_event(
            "agent_runtime.project_agent_registry_auto_init_failed",
            outcome="failed",
            level="warning",
            fields={
                "agentId": agent_id,
                "sessionId": session_id,
                "runId": run_id,
                "sourcePath": str(registry_path),
                "reason": type(exc).__name__,
                "source": "ContextEngine",
            },
        )
        return default_registry
    default_registry["_autoInitialized"] = True
    _record_context_event(
        "agent_runtime.project_agent_registry_auto_initialized",
        outcome="created",
        fields={
            "agentId": agent_id,
            "sessionId": session_id,
            "runId": run_id,
            "sourcePath": str(registry_path),
            "laneTerritoryCount": len(default_registry.get("laneTerritories") or {}),
            "source": "ContextEngine",
        },
    )
    return default_registry


def _read_project_agent_registry(
    registry_path: Path,
    *,
    agent_id: str,
    session_id: str,
    run_id: str,
) -> dict[str, Any]:
    signature = _file_signature(registry_path)
    if signature is None:
        return {}
    with _PROJECT_AGENT_REGISTRY_CACHE_LOCK:
        cached = _PROJECT_AGENT_REGISTRY_CACHE.get(signature)
    if isinstance(cached, dict):
        payload = copy.deepcopy(cached)
        payload["_cacheHit"] = True
        return payload
    try:
        payload = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _record_context_event(
            "agent_runtime.project_agent_registry_context_failed",
            outcome="failed",
            level="warning",
            fields={
                "agentId": agent_id,
                "sessionId": session_id,
                "runId": run_id,
                "sourcePath": str(registry_path),
                "reason": type(exc).__name__,
                "source": "ContextEngine",
            },
        )
        return {}
    if not isinstance(payload, dict):
        return {}
    with _PROJECT_AGENT_REGISTRY_CACHE_LOCK:
        _PROJECT_AGENT_REGISTRY_CACHE.clear()
        _PROJECT_AGENT_REGISTRY_CACHE[signature] = copy.deepcopy(payload)
    payload["_cacheHit"] = False
    return payload


def _default_project_agent_registry(
    memory_dir: Path | None = None,
    *,
    auto_initialized: bool = True,
) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "sourceOfTruth": {
            "identityBinding": "AgentDirectory",
            "territoryDefaults": "<active-project-memory>/agent-registry.json",
            "runtimeInjection": "core/orchestration/context_engine.py",
        },
        "policy": {
            "outOfScopeDefault": "recommend_handoff",
            "automaticForwarding": False,
            "memoryWriteMode": "serialized_single_writer",
            "autoInitialized": auto_initialized,
        },
        "laneTerritories": _default_project_agent_lane_territories(memory_dir),
        "agents": [],
    }


def _default_project_agent_lane_territories(memory_dir: Path | None = None) -> dict[str, dict[str, Any]]:
    from_lanes = _project_agent_lane_territories_from_memory(memory_dir) if memory_dir else {}
    return from_lanes or _fallback_project_agent_lane_territories()


def _project_agent_lane_territories_from_memory(memory_dir: Path | None) -> dict[str, dict[str, Any]]:
    if not memory_dir:
        return {}
    lane_dir = Path(memory_dir) / "lanes"
    if not lane_dir.exists():
        return {}
    territories: dict[str, dict[str, Any]] = {}
    for lane_path in sorted(lane_dir.glob("*.json")):
        try:
            lane = json.loads(lane_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(lane, dict):
            continue
        lane_id = str(lane.get("id") or lane_path.stem).strip()
        if not lane_id:
            continue
        title = str(lane.get("title") or lane_id).strip()
        focus = str(lane.get("focus") or "").strip()
        summary = f"负责 {title}"
        if focus:
            summary = f"{summary}；当前焦点：{focus}"
        territories[lane_id] = {
            "managementScope": {
                "summary": summary,
                "files": _project_agent_lane_related_files(lane),
                "taskTypes": _project_agent_lane_task_types(lane_id, title),
            },
            "handoffTargets": _default_handoff_targets_for_lane(lane_id),
            "outOfScopePolicy": "recommend_handoff",
        }
    return territories


def _project_agent_lane_related_files(lane: dict[str, Any]) -> list[str]:
    files: list[str] = []
    for module in list(lane.get("modules") or [])[:8]:
        if not isinstance(module, dict):
            continue
        for value in _coerce_str_list(module.get("relatedFiles")):
            if value not in files:
                files.append(value)
            if len(files) >= 8:
                return files
    return files


def _project_agent_lane_task_types(lane_id: str, title: str) -> list[str]:
    task_types: list[str] = []
    for part in re.split(r"[^A-Za-z0-9]+", f"{lane_id} {title}".lower()):
        value = str(part or "").strip()
        if value and value not in task_types:
            task_types.append(value)
        if len(task_types) >= 6:
            break
    return task_types


def _default_handoff_targets_for_lane(lane_id: str) -> list[str]:
    defaults = [
        "agent-runtime-core",
        "chat-coding-surface",
        "web-workbench-surface",
        "quality-and-operations",
        "evolution-control-plane",
        "self-evolution-loop",
    ]
    return [item for item in defaults if item != lane_id][:3]


def _fallback_project_agent_lane_territories() -> dict[str, dict[str, Any]]:
    return {
        "agent-runtime-core": {
            "managementScope": {
                "summary": "负责 Agent 运行主干、上下文装配、身份绑定、工具/记忆/委托策略。",
                "files": ["core/orchestration/**", "core/runtime_manager/**", "agent.py"],
                "taskTypes": [
                    "runtime-context",
                    "agent-directory",
                    "memory-policy",
                    "tool-policy",
                    "delegation",
                ],
            },
            "handoffTargets": ["chat-coding-surface", "quality-and-operations"],
            "outOfScopePolicy": "recommend_handoff",
        },
        "chat-coding-surface": {
            "managementScope": {
                "summary": "负责 Chat/Coding 会话、群聊、消息生命周期和前端对话体验。",
                "files": [
                    "core/web/services/session_service.py",
                    "core/web/services/chat_room_service.py",
                    "web/src/routes/**",
                ],
                "taskTypes": [
                    "chat-session",
                    "group-chat",
                    "message-lifecycle",
                    "conversation-ui",
                ],
            },
            "handoffTargets": ["agent-runtime-core", "web-workbench-surface"],
            "outOfScopePolicy": "recommend_handoff",
        },
        "quality-and-operations": {
            "managementScope": {
                "summary": "负责测试、日志、诊断、发布收口和工作树卫生。",
                "files": ["tests/**", "<active-project-logs>/runtime_scenes/**", "<active-project-memory>/**"],
                "taskTypes": [
                    "testing",
                    "logging",
                    "diagnosis",
                    "release",
                    "git-hygiene",
                ],
            },
            "handoffTargets": ["agent-runtime-core", "chat-coding-surface"],
            "outOfScopePolicy": "recommend_handoff",
        },
    }


def _merge_project_agent_registry_entries(
    registry: dict[str, Any],
    active_agents: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    registry_entries = [
        item
        for item in registry.get("agents") or []
        if isinstance(item, dict) and str(item.get("status") or "active").strip().lower() != "archived"
    ]
    entries_by_agent_id: dict[str, dict[str, Any]] = {}
    entries_by_session_id: dict[str, dict[str, Any]] = {}
    for entry in registry_entries:
        agent_id = str(entry.get("agentId") or "").strip()
        session_id = str(entry.get("sessionId") or entry.get("directSessionId") or "").strip()
        if agent_id:
            entries_by_agent_id[agent_id] = entry
        if session_id:
            entries_by_session_id[session_id] = entry

    lane_defaults = _project_agent_registry_lane_defaults(registry)
    merged: list[dict[str, Any]] = []
    seen_agent_ids: set[str] = set()
    for agent in active_agents:
        agent_id = str(agent.get("agentId") or "").strip()
        session_id = str(agent.get("directSessionId") or "").strip()
        explicit = entries_by_agent_id.get(agent_id) or entries_by_session_id.get(session_id) or {}
        merged.append(_project_agent_registry_entry_from_sources(agent, explicit, lane_defaults=lane_defaults))
        seen_agent_ids.add(agent_id)

    for entry in registry_entries:
        agent_id = str(entry.get("agentId") or "").strip()
        if agent_id and agent_id in seen_agent_ids:
            continue
        if str(entry.get("status") or "active").strip().lower() != "active":
            continue
        merged.append(_project_agent_registry_entry_from_sources({}, entry, lane_defaults=lane_defaults))
    return merged


def _project_agent_registry_entry_from_sources(
    agent: dict[str, Any],
    explicit: dict[str, Any],
    *,
    lane_defaults: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    responsibility_lane = str(
        explicit.get("responsibilityLane")
        or metadata.get("responsibilityLane")
        or _infer_project_agent_responsibility_lane(agent)
    ).strip()
    lane_default = lane_defaults.get(responsibility_lane) or {}
    management_scope = explicit.get("managementScope")
    if not isinstance(management_scope, dict):
        management_scope = (
            metadata.get("managementScope")
            if isinstance(metadata.get("managementScope"), dict)
            else {}
        )
    if not management_scope and isinstance(lane_default.get("managementScope"), dict):
        management_scope = lane_default.get("managementScope") or {}
    return {
        "agentId": str(explicit.get("agentId") or agent.get("agentId") or "").strip(),
        "agentCode": str(explicit.get("agentCode") or agent.get("agentCode") or "").strip(),
        "sessionId": str(
            explicit.get("sessionId") or explicit.get("directSessionId") or agent.get("directSessionId") or ""
        ).strip(),
        "displayName": str(explicit.get("displayName") or agent.get("displayName") or "").strip(),
        "responsibilityLane": responsibility_lane,
        "managementScope": {
            "summary": str(management_scope.get("summary") or "").strip(),
            "files": _coerce_str_list(management_scope.get("files"), limit=8),
            "taskTypes": _coerce_str_list(management_scope.get("taskTypes"), limit=8),
        },
        "handoffTargets": _coerce_str_list(
            explicit.get("handoffTargets")
            or metadata.get("handoffTargets")
            or lane_default.get("handoffTargets")
            or [],
            limit=8,
        ),
        "outOfScopePolicy": str(
            explicit.get("outOfScopePolicy")
            or metadata.get("outOfScopePolicy")
            or lane_default.get("outOfScopePolicy")
            or "recommend_handoff"
        ).strip(),
        "status": str(explicit.get("status") or agent.get("status") or "active").strip() or "active",
    }


def _project_agent_registry_lane_defaults(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = registry.get("laneTerritories") if isinstance(registry.get("laneTerritories"), dict) else {}
    defaults: dict[str, dict[str, Any]] = {}
    for lane_id, value in raw.items():
        normalized_lane = str(lane_id or "").strip()
        if not normalized_lane or not isinstance(value, dict):
            continue
        defaults[normalized_lane] = value
    return defaults


def _find_project_agent_registry_entry(
    entries: list[dict[str, Any]],
    *,
    agent_id: str,
    session_id: str,
) -> dict[str, Any] | None:
    normalized_agent_id = str(agent_id or "").strip()
    normalized_session_id = str(session_id or "").strip()
    for entry in entries:
        if normalized_agent_id and str(entry.get("agentId") or "").strip() == normalized_agent_id:
            return entry
    for entry in entries:
        if normalized_session_id and str(entry.get("sessionId") or "").strip() == normalized_session_id:
            return entry
    return None


def _project_agent_handoff_entries(
    current_entry: dict[str, Any],
    entries: list[dict[str, Any]],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    bounded_limit = _bounded_limit(limit, default=8)
    current_agent_id = str(current_entry.get("agentId") or "").strip()
    targets = _coerce_str_list(current_entry.get("handoffTargets"))
    active_entries = [
        item
        for item in entries
        if str(item.get("status") or "active").strip().lower() == "active"
        and str(item.get("agentId") or "").strip() != current_agent_id
    ]
    if targets:
        matched = [
            item
            for item in active_entries
            if str(item.get("agentId") or "").strip() in targets
            or str(item.get("sessionId") or "").strip() in targets
            or str(item.get("responsibilityLane") or "").strip() in targets
        ]
        if matched:
            return matched[:bounded_limit]
    return active_entries[:bounded_limit]


def _format_project_agent_registry_entry(
    entry: dict[str, Any],
    *,
    include_scope: bool,
    prefix: str = "",
) -> str:
    scope = entry.get("managementScope") if isinstance(entry.get("managementScope"), dict) else {}
    parts = [
        f"agentId={entry.get('agentId') or ''}",
        f"sessionId={entry.get('sessionId') or ''}",
        f"agentCode={entry.get('agentCode') or ''}",
        f"name={entry.get('displayName') or ''}",
        f"lane={entry.get('responsibilityLane') or 'unassigned'}",
        f"outOfScopePolicy={entry.get('outOfScopePolicy') or 'recommend_handoff'}",
    ]
    if include_scope:
        summary = str(scope.get("summary") or "").strip()
        files = ", ".join(_coerce_str_list(scope.get("files"), limit=4))
        task_types = ", ".join(_coerce_str_list(scope.get("taskTypes"), limit=4))
        if summary:
            parts.append(f"scope={summary}")
        if files:
            parts.append(f"files={files}")
        if task_types:
            parts.append(f"taskTypes={task_types}")
    return prefix + "; ".join(parts)


def _infer_project_agent_responsibility_lane(agent: dict[str, Any]) -> str:
    primary_mode = str(agent.get("primaryMode") or "").strip()
    role_key = str(agent.get("roleKey") or "").strip()
    prompt_template_id = str(agent.get("promptTemplateId") or "").strip()
    llm_bindings = json.dumps(agent.get("llmBindings") or {}, ensure_ascii=False, sort_keys=True)
    haystack = " ".join([primary_mode, role_key, prompt_template_id, llm_bindings]).lower()
    if "self_evolution" in haystack or "self-evolution" in haystack:
        return "self-evolution-loop"
    if "supervised_evolution" in haystack or "supervised-evolution" in haystack:
        return "evolution-control-plane"
    if "research" in haystack:
        return "agent-runtime-core"
    if "chat" in haystack:
        return "chat-coding-surface"
    return "agent-runtime-core"


def _record_context_event(event_code: str, *, outcome: str, fields: dict[str, Any], level: str = "info") -> None:
    try:
        record_runtime_scene_event(
            "agent_context",
            "context_engine",
            event_code,
            message=event_code,
            level=level,
            outcome=outcome,
            fields=fields,
            lifecycle=True,
        )
    except Exception:
        return


def _mapping_items(value: Any) -> list[dict[str, Any]]:
    value = _maybe_json(value)
    if value is None or isinstance(value, (str, bytes, bytearray, memoryview)):
        return []
    if isinstance(value, Mapping):
        nested = value.get("items")
        if nested is None:
            nested = value.get("segments")
        if nested is None:
            nested = value.get("entries")
        if nested is not None:
            return _mapping_items(nested)
        return [dict(value)] if value else []
    try:
        iterator = list(value)
    except TypeError:
        return []
    items: list[dict[str, Any]] = []
    for item in iterator:
        item = _maybe_json(item)
        if isinstance(item, Mapping):
            items.append(dict(item))
    return items


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _coerce_str_list(value: Any, *, limit: int | None = None) -> list[str]:
    value = _maybe_json(value)
    if value is None:
        names: list[str] = []
    elif isinstance(value, (bytes, bytearray, memoryview)):
        text = bytes(value).decode("utf-8", errors="replace").strip()
        names = [text] if text else []
    elif isinstance(value, str):
        text = value.strip()
        names = [text] if text else []
    elif isinstance(value, Mapping):
        nested = value.get("items")
        if nested is None:
            nested = value.get("names")
        if nested is None:
            nested = value.get("agentIds")
        if nested is None:
            nested = value.get("agent_ids")
        if nested is not None:
            return _coerce_str_list(nested, limit=limit)
        names = []
        for key, item in value.items():
            if isinstance(item, Mapping) and not _coerce_bool(
                item.get("enabled", item.get("enable")), True
            ):
                continue
            text = _coerce_text(key).strip()
            if text and text not in names:
                names.append(text)
    else:
        try:
            iterator = list(value)
        except TypeError:
            text = _coerce_text(value).strip()
            names = [text] if text else []
        else:
            names = []
            for item in iterator:
                text = _coerce_text(item).strip()
                if text and text not in names:
                    names.append(text)
    if limit is None:
        return names
    return names[: _bounded_limit(limit, default=len(names), minimum=0)]


def _safe_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool) or value is None:
        return default
    if isinstance(value, (bytes, bytearray, memoryview)):
        value = bytes(value).decode("utf-8", errors="replace")
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _bounded_limit(value: Any, *, default: int, minimum: int = 1) -> int:
    parsed = _safe_int(value, default)
    if parsed < minimum:
        return minimum
    return parsed


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")


def packet_to_dict(packet: AgentContextPacket | SubAgentContextPacket) -> dict[str, Any]:
    return asdict(packet)
