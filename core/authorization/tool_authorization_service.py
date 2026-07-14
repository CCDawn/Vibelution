"""Shadow-mode integration for canonical Agent tool authorization."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter
from typing import Any, Callable, Mapping, Sequence

from .tool_policy_evaluator import evaluate_tool_policy, normalize_legacy_tool_policy
from .tool_policy_models import AuthorizationDecision, TurnToolGrant


@dataclass(frozen=True, slots=True)
class _RegistryDescriptor:
    name: str
    enabled: bool
    capabilities: tuple[str, ...]
    risk: str
    approval: str
    aliases: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ShadowAuthorizationReport:
    decision: AuthorizationDecision
    legacy_visible_tools: tuple[str, ...]
    shadow_only_tools: tuple[str, ...]
    legacy_only_tools: tuple[str, ...]
    deny_code_counts: tuple[tuple[str, int], ...]
    registry_fingerprint: str
    duration_ms: int

    @property
    def parity(self) -> bool:
        return not self.shadow_only_tools and not self.legacy_only_tools


def resolve_shadow_authorization(
    *,
    runtime: Mapping[str, Any],
    legacy_visible_tool_names: Sequence[str],
    registry_payload: Mapping[str, Any] | None = None,
    registry_loader: Callable[[], Mapping[str, Any]] | None = None,
    generated_at: str = "",
) -> ShadowAuthorizationReport:
    """Resolve and compare a canonical decision without enforcing it."""

    started = perf_counter()
    payload = dict(registry_payload or _load_registry_payload(registry_loader))
    descriptors = _descriptors_from_registry(payload)
    registered_names = tuple(descriptor.name for descriptor in descriptors)
    agent = runtime.get("agent") if isinstance(runtime.get("agent"), Mapping) else {}
    raw_policy = runtime.get("toolPolicy")
    policy = _role_policy_projection(
        agent=agent,
        raw_policy=raw_policy,
        registered_names=registered_names,
    )
    turn_id = str(runtime.get("turnId") or runtime.get("runId") or "").strip()
    source = _turn_source(runtime, agent)
    capabilities = tuple(sorted({capability for descriptor in descriptors for capability in descriptor.capabilities}))
    grant = TurnToolGrant(
        turn_id=turn_id,
        source=source,
        allowed_capabilities=capabilities,
        denied_tools=(),
        approval_mode="on_request",
    )
    available_names = tuple(
        sorted(
            {
                str(item.get("name") or "").strip()
                for item in payload.get("tools") or []
                if isinstance(item, Mapping)
                and item.get("enabled")
                and item.get("runtimeActive")
                and item.get("llmVisible")
                and str(item.get("name") or "").strip()
            }
        )
    )
    decision = evaluate_tool_policy(
        agent_id=str(runtime.get("agentId") or agent.get("agentId") or "").strip(),
        policy=policy,
        grant=grant,
        descriptors=descriptors,
        registry_version=int(payload.get("registryVersion") or 0),
        registry_fingerprint=str(payload.get("registryFingerprint") or "").strip(),
        available_tool_names=available_names,
        generated_at=generated_at or datetime.now(timezone.utc).isoformat(),
    )
    legacy_visible = tuple(_ordered_unique(legacy_visible_tool_names))
    shadow_visible = set(decision.visible_tools)
    legacy_visible_set = set(legacy_visible)
    deny_counts = Counter(reason.code.value for _, reason in decision.denied)
    return ShadowAuthorizationReport(
        decision=decision,
        legacy_visible_tools=legacy_visible,
        shadow_only_tools=tuple(sorted(shadow_visible.difference(legacy_visible_set))),
        legacy_only_tools=tuple(sorted(legacy_visible_set.difference(shadow_visible))),
        deny_code_counts=tuple(sorted(deny_counts.items())),
        registry_fingerprint=str(payload.get("registryFingerprint") or "").strip(),
        duration_ms=max(0, int((perf_counter() - started) * 1000)),
    )


def _load_registry_payload(registry_loader: Callable[[], Mapping[str, Any]] | None) -> Mapping[str, Any]:
    if registry_loader is not None:
        return registry_loader()
    from core.web.services.tool_registry_service import get_tool_registry

    return get_tool_registry()


def _descriptors_from_registry(payload: Mapping[str, Any]) -> tuple[_RegistryDescriptor, ...]:
    descriptors: list[_RegistryDescriptor] = []
    for item in payload.get("descriptors") or []:
        if not isinstance(item, Mapping):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        descriptors.append(
            _RegistryDescriptor(
                name=name,
                enabled=bool(item.get("enabled")),
                capabilities=tuple(str(value or "").strip() for value in item.get("capabilities") or [] if str(value or "").strip()),
                risk=str(item.get("risk") or "read").strip() or "read",
                approval=str(item.get("approval") or "never").strip() or "never",
                aliases=tuple(str(value or "").strip() for value in item.get("aliases") or [] if str(value or "").strip()),
            )
        )
    return tuple(descriptors)


def _role_policy_projection(*, agent: Mapping[str, Any], raw_policy: Any, registered_names: Sequence[str]):
    from core.web.services import agent_role_tool_profile_service

    role_policy = agent_role_tool_profile_service.resolve_role_tool_policy_v2(
        role_key=str(agent.get("roleKey") or "").strip(),
        primary_mode=str(agent.get("primaryMode") or "").strip(),
        metadata=dict(agent.get("metadata") or {}) if isinstance(agent.get("metadata"), Mapping) else {},
        policy_id=str(
            (raw_policy or {}).get("policyId") if isinstance(raw_policy, Mapping) else ""
        ).strip()
        or f"tool-{str(agent.get('agentId') or 'agent').strip()}",
        registered_tool_names=registered_names,
    )
    if role_policy is not None and agent_role_tool_profile_service.role_has_explicit_tool_profile(
        str(agent.get("roleKey") or "").strip(),
        primary_mode=str(agent.get("primaryMode") or "").strip(),
        metadata=dict(agent.get("metadata") or {}) if isinstance(agent.get("metadata"), Mapping) else {},
    ):
        return role_policy
    return normalize_legacy_tool_policy(
        raw_policy,
        registered_tool_names=registered_names,
    )


def _turn_source(runtime: Mapping[str, Any], agent: Mapping[str, Any]) -> str:
    mode = str(agent.get("primaryMode") or runtime.get("primaryMode") or runtime.get("mode") or "").strip().lower()
    if runtime.get("roomId") or runtime.get("roundId"):
        return "team"
    if mode == "research":
        return "research"
    if mode == "supervised_evolution" or runtime.get("supervisedRole"):
        return "supervised"
    if mode == "self_evolution":
        return "self_evolution"
    return "session"


def _ordered_unique(values: Sequence[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in values:
        value = str(item or "").strip()
        if not value or value in seen:
            continue
        result.append(value)
        seen.add(value)
    return result
