"""Deterministic resolved LLM routing graph."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

from .llm_identity import normalize_provider_endpoint, split_model_ref
from .models import LLMConfig, LLMProfile, PinnedModelConfig, ProviderConfig


def _digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


@dataclass(frozen=True, slots=True)
class LLMGraphIssue:
    code: str
    subject_ref: str
    message: str


class LLMGraphError(ValueError):
    def __init__(self, issues: tuple[LLMGraphIssue, ...]) -> None:
        self.issues = issues
        super().__init__("; ".join(f"{item.code}: {item.message}" for item in issues))


@dataclass(frozen=True, slots=True)
class EffectiveLLMRoute:
    profile_id: str
    provider_id: str
    model_ref: str
    upstream_model: str
    service_class: str
    driver: str
    wire_protocol: str
    adapter_id: str
    backend_identity: str
    endpoint_identity: str
    model_protocol: str
    interaction_contract: str
    route_fingerprint: str
    effective_identity: str
    runtime_route_fingerprint: str


@dataclass(frozen=True, slots=True)
class EffectiveLLMGraph:
    routes: tuple[EffectiveLLMRoute, ...]
    aliases: tuple[tuple[str, str], ...]
    fingerprint: str

    def route_for_profile(self, profile_id: str) -> EffectiveLLMRoute:
        matches = tuple(route for route in self.routes if route.profile_id == profile_id)
        if len(matches) != 1:
            raise LookupError(f"profile `{profile_id}` does not resolve to exactly one LLM route")
        return matches[0]


class EffectiveLLMGraphBuilder:
    def build(self, config: LLMConfig, *, fallback_profile_ids: Mapping[str, str] | None = None) -> EffectiveLLMGraph:
        issues: list[LLMGraphIssue] = []
        aliases: dict[str, str] = {}

        def resolve_alias(alias: str, trail: tuple[str, ...] = ()) -> str | None:
            if alias in trail:
                issues.append(LLMGraphIssue("cyclic_model_alias", alias, "model alias cycle detected"))
                return None
            target = str(config.model_aliases.get(alias) or "").strip()
            if not target:
                return alias
            if target in config.model_aliases:
                return resolve_alias(target, (*trail, alias))
            try:
                provider_id, model_key = split_model_ref(target)
            except ValueError:
                issues.append(LLMGraphIssue("dangling_model_alias", alias, "model alias target is not a model_ref"))
                return None
            provider = config.providers.get(provider_id)
            if provider is None or model_key not in provider.models:
                issues.append(LLMGraphIssue("dangling_model_alias", alias, "model alias target does not exist"))
                return None
            return target

        for alias in sorted(config.model_aliases):
            target = resolve_alias(alias)
            if target is not None:
                aliases[alias] = target

        routes: list[EffectiveLLMRoute] = []
        for profile_id, profile in sorted(config.profiles.items()):
            route = self._resolve_profile(profile_id, profile, config, aliases, issues)
            if route is not None:
                routes.append(route)

        by_profile = {route.profile_id: route for route in routes}
        for primary, fallback in sorted((fallback_profile_ids or {}).items()):
            primary_route = by_profile.get(primary)
            fallback_route = by_profile.get(fallback)
            if primary_route is None or fallback_route is None:
                issues.append(LLMGraphIssue("fallback_profile_not_found", primary, "fallback references an unresolved profile"))
            elif primary_route.effective_identity == fallback_route.effective_identity:
                issues.append(LLMGraphIssue("fallback_same_effective_identity", primary, "fallback resolves to the same provider/model/wire/backend endpoint"))

        if issues:
            raise LLMGraphError(tuple(sorted(issues, key=lambda item: (item.code, item.subject_ref))))
        route_tuple = tuple(routes)
        alias_tuple = tuple(sorted(aliases.items()))
        return EffectiveLLMGraph(route_tuple, alias_tuple, _digest({"routes": [route.route_fingerprint for route in route_tuple], "aliases": alias_tuple}))

    def _resolve_profile(
        self,
        profile_id: str,
        profile: LLMProfile,
        config: LLMConfig,
        aliases: Mapping[str, str],
        issues: list[LLMGraphIssue],
    ) -> EffectiveLLMRoute | None:
        requested_ref = str(profile.model_ref or "").strip()
        if requested_ref in config.model_aliases:
            requested_ref = str(aliases.get(requested_ref) or "")
        provider_id = str(profile.provider_id or "").strip()
        provider: ProviderConfig | None = None
        model: PinnedModelConfig | None = None
        model_ref = requested_ref
        if requested_ref:
            try:
                provider_id, model_key = split_model_ref(requested_ref)
            except ValueError:
                issues.append(LLMGraphIssue("invalid_model_ref", profile_id, "profile model_ref is invalid"))
                return None
            provider = config.providers.get(provider_id)
            model = provider.models.get(model_key) if provider is not None else None
            if provider is None or model is None:
                issues.append(LLMGraphIssue("model_ref_not_found", profile_id, "profile model_ref does not exist"))
                return None
        else:
            provider = config.providers.get(provider_id)
            if provider is None:
                issues.append(LLMGraphIssue("provider_not_found", profile_id, "profile provider does not exist"))
                return None
            matches = [(key, item) for key, item in provider.models.items() if item.upstream_id == profile.model]
            if len(matches) == 1:
                model_key, model = matches[0]
                model_ref = f"{provider_id}/{model_key}"

        model_entry = {
            "model_ref": model_ref,
            "model": model.upstream_id if model is not None else profile.model,
            "wire_protocol": model.wire_protocol if model is not None else profile.transport,
            "protocol": model.model_protocol if model is not None else profile.protocol,
            "compat": model.compatibility if model is not None else profile.compat,
        }
        from core.llm.protocol_resolver import ProtocolResolutionError, resolve_model_protocol

        try:
            route = resolve_model_protocol(profile, provider, model_entry=model_entry)
        except ProtocolResolutionError as exc:
            issues.append(LLMGraphIssue(exc.code, profile_id, str(exc)))
            return None
        endpoint = normalize_provider_endpoint(provider.base_url)
        backend = route.backend_identity
        effective_payload = {
            "providerId": provider_id,
            "serviceClass": provider.service_class,
            "driver": provider.driver,
            "modelRef": model_ref,
            "upstreamModel": route.effective_model,
            "wireProtocol": route.wire_protocol.value,
            "adapterId": route.adapter_id,
            "backendIdentity": backend,
            "endpointIdentity": endpoint,
            "modelProtocol": route.protocol.value,
        }
        effective_identity = _digest(effective_payload)
        interaction = model.interaction_contract if model is not None else profile.contract
        return EffectiveLLMRoute(
            profile_id=profile_id,
            provider_id=provider_id,
            model_ref=model_ref,
            upstream_model=route.effective_model,
            service_class=provider.service_class,
            driver=provider.driver,
            wire_protocol=route.wire_protocol.value,
            adapter_id=route.adapter_id,
            backend_identity=backend,
            endpoint_identity=endpoint,
            model_protocol=route.protocol.value,
            interaction_contract=interaction,
            route_fingerprint=_digest({**effective_payload, "profileId": profile_id, "interactionContract": interaction}),
            effective_identity=effective_identity,
            runtime_route_fingerprint=route.route_fingerprint,
        )


__all__ = ["EffectiveLLMGraph", "EffectiveLLMGraphBuilder", "EffectiveLLMRoute", "LLMGraphError", "LLMGraphIssue"]
