# -*- coding: utf-8 -*-
"""LLM profile discovery and diagnostics."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from config import AppConfig
from config.model_catalog import load_model_catalog_state, resolve_model_capabilities

from .adapters import capabilities_for_adapter
from .types import DiagnosticReport, LLMCapabilities, ResolvedModelSpec


KNOWN_CONTEXT_WINDOWS = {
    "minimax-m2.7": 204800,
    "gpt-4o": 128000,
    "gpt-4-turbo": 128000,
    "gpt-5.5": 1050000,
    "gpt-5.4": 1047576,
    "gpt-5.3-codex": 400000,
    "claude-3-5-sonnet": 200000,
    "deepseek-v4-flash": 1000000,
    "deepseek-v4-pro": 1000000,
    "deepseek-chat": 65536,
    "qwen-plus": 131072,
    "qwen-max": 131072,
    "qwen-32b-awq": 65536,
}

JSON_MODE_MODEL_HINTS = (
    "gpt-4",
    "gpt-4o",
    "gpt-5",
    "deepseek",
    "qwen",
    "claude",
)
SUPPORTED_REASONING_STATE_FIELDS = {"reasoning_content"}

_CAPABILITY_FIELD_ALIASES = {
    "streaming": "supports_streaming",
    "supportsStreaming": "supports_streaming",
    "supports_streaming": "supports_streaming",
    "tools": "supports_tool_calling",
    "toolCalling": "supports_tool_calling",
    "supportsToolCalling": "supports_tool_calling",
    "supports_tool_calling": "supports_tool_calling",
    "parallelTools": "supports_parallel_tool_calls",
    "supportsParallelToolCalls": "supports_parallel_tool_calls",
    "supports_parallel_tool_calls": "supports_parallel_tool_calls",
    "systemMessages": "supports_system_messages",
    "supportsSystemMessages": "supports_system_messages",
    "supports_system_messages": "supports_system_messages",
    "jsonMode": "supports_json_mode",
    "supportsJsonMode": "supports_json_mode",
    "supports_json_mode": "supports_json_mode",
    "modelDiscovery": "supports_model_discovery",
    "supportsModelDiscovery": "supports_model_discovery",
    "supports_model_discovery": "supports_model_discovery",
    "imageInput": "supports_image_input",
    "supportsImageInput": "supports_image_input",
    "supports_image_input": "supports_image_input",
    "promptCache": "supports_prompt_cache",
    "supportsPromptCache": "supports_prompt_cache",
    "supports_prompt_cache": "supports_prompt_cache",
    "thinking": "supports_thinking",
    "supportsThinking": "supports_thinking",
    "supports_thinking": "supports_thinking",
    "reasoningRoundtrip": "supports_reasoning_roundtrip",
    "supportsReasoningRoundtrip": "supports_reasoning_roundtrip",
    "supports_reasoning_roundtrip": "supports_reasoning_roundtrip",
    "explicitToolChoice": "supports_explicit_tool_choice",
    "supportsExplicitToolChoice": "supports_explicit_tool_choice",
    "supports_explicit_tool_choice": "supports_explicit_tool_choice",
    "streamUsageOptions": "supports_stream_usage",
    "supportsStreamUsage": "supports_stream_usage",
    "supports_stream_usage": "supports_stream_usage",
    "strictJsonSchema": "supports_strict_json_schema",
    "supportsStrictJsonSchema": "supports_strict_json_schema",
    "supports_strict_json_schema": "supports_strict_json_schema",
    "responsesTransport": "supports_responses_transport",
    "supportsResponsesTransport": "supports_responses_transport",
    "supports_responses_transport": "supports_responses_transport",
    "structuredContent": "supports_structured_content",
    "supportsStructuredContent": "supports_structured_content",
    "supports_structured_content": "supports_structured_content",
}

_RUNTIME_TO_CATALOG_CAPABILITY = {
    "supports_streaming": "streaming",
    "supports_tool_calling": "tool_calling",
    "supports_parallel_tool_calls": "parallel_tool_calls",
    "supports_system_messages": "system_messages",
    "supports_json_mode": "json_mode",
    "supports_model_discovery": "model_discovery",
    "supports_image_input": "image_input",
    "supports_prompt_cache": "prompt_cache",
    "supports_thinking": "thinking",
    "supports_reasoning_roundtrip": "reasoning_roundtrip",
    "supports_explicit_tool_choice": "explicit_tool_choice",
    "supports_stream_usage": "stream_usage",
    "supports_strict_json_schema": "strict_json_schema",
    "supports_responses_transport": "responses_transport",
    "supports_structured_content": "structured_content",
}
_CATALOG_TO_RUNTIME_CAPABILITY = {
    catalog_field: runtime_field
    for runtime_field, catalog_field in _RUNTIME_TO_CATALOG_CAPABILITY.items()
}


def _lookup_context_window(model_name: str, fallback: int) -> int:
    normalized = (model_name or "").strip().lower()
    for key, value in KNOWN_CONTEXT_WINDOWS.items():
        if key in normalized:
            return value
    return int(fallback or 32768)


def _declared_capability_overrides(model_entry: Any) -> tuple[dict[str, bool], list[str]]:
    if not isinstance(model_entry, dict):
        return {}, []
    raw = model_entry.get("capabilities")
    source_fields: list[str] = []
    overrides: dict[str, bool] = {}
    if isinstance(raw, dict):
        for key, value in raw.items():
            field = _CAPABILITY_FIELD_ALIASES.get(str(key))
            if field and isinstance(value, bool):
                overrides[field] = value
                source_fields.append(str(key))
    legacy_image = model_entry.get("supports_image_input")
    if isinstance(legacy_image, bool) and "supports_image_input" not in overrides:
        overrides["supports_image_input"] = legacy_image
        source_fields.append("supports_image_input")
    return overrides, source_fields


def _apply_declared_capability_overrides(
    capabilities: LLMCapabilities,
    overrides: dict[str, bool],
) -> LLMCapabilities:
    if not overrides:
        return capabilities
    return replace(
        capabilities,
        **{
            field: value
            for field, value in overrides.items()
            if hasattr(capabilities, field)
        },
    )


def _apply_runtime_capability_gates(
    capabilities: LLMCapabilities,
    profile: Any,
) -> LLMCapabilities:
    updated = capabilities
    if not bool(getattr(profile, "streaming", True)):
        updated = replace(updated, supports_streaming=False)
    tool_mode = str(getattr(profile, "tool_calling_mode", "") or "auto").strip().lower()
    if tool_mode == "disabled":
        updated = replace(
            updated,
            supports_tool_calling=False,
            supports_parallel_tool_calls=False,
            supports_explicit_tool_choice=False,
        )
    elif tool_mode != "parallel":
        updated = replace(updated, supports_parallel_tool_calls=False)
    return updated


def _curated_capabilities(profile: Any) -> dict[str, bool]:
    from config.public_config import LLM_MODEL_PRESETS

    model_name = str(getattr(profile, "model", "") or "").strip()
    for preset in LLM_MODEL_PRESETS.values():
        if not isinstance(preset, dict):
            continue
        preset_model = preset.get("model") if isinstance(preset.get("model"), dict) else {}
        if str(preset_model.get("model") or "").strip() != model_name:
            continue
        capabilities, _fields = _declared_capability_overrides(preset_model)
        return capabilities
    return {}


def _catalog_model_details(provider_id: str, model_ref: str) -> tuple[dict[str, Any], dict[str, Any]]:
    if "/" not in model_ref:
        return {}, {"catalog_availability": "not_applicable"}
    ref_provider_id, model_key = model_ref.split("/", 1)
    if ref_provider_id != provider_id or not model_key:
        return {}, {"catalog_availability": "not_found"}
    try:
        state = load_model_catalog_state()
    except ValueError:
        return {}, {"catalog_availability": "invalid"}
    providers = state.get("providers", {}) if isinstance(state, dict) else {}
    provider_record = providers.get(provider_id, {}) if isinstance(providers, dict) else {}
    models = provider_record.get("models", {}) if isinstance(provider_record, dict) else {}
    model_record = models.get(model_key, {}) if isinstance(models, dict) else {}
    details = {
        "catalog_availability": str(model_record.get("availability") or "not_found"),
        "catalog_status": str(provider_record.get("status") or "unknown"),
        "catalog_stale": bool(provider_record.get("catalogStale", False)),
    }
    return model_record if isinstance(model_record, dict) else {}, details


def _catalog_capability_layers(model_record: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    provider_metadata: dict[str, Any] = {}
    runtime_probe: dict[str, Any] = {}
    raw = model_record.get("capabilities", {}) if isinstance(model_record, dict) else {}
    if not isinstance(raw, dict):
        return provider_metadata, runtime_probe
    for field, record in raw.items():
        if not isinstance(record, dict):
            continue
        source = str(record.get("source") or "").strip()
        if source == "provider_endpoint":
            provider_metadata[str(field)] = record
        elif source == "runtime_probe":
            runtime_probe[str(field)] = record
    return provider_metadata, runtime_probe


def _catalog_capability_names(capabilities: dict[str, Any]) -> dict[str, Any]:
    return {
        _RUNTIME_TO_CATALOG_CAPABILITY.get(str(field), str(field)): value
        for field, value in capabilities.items()
    }


def _capabilities_from_resolution(
    driver_capabilities: LLMCapabilities,
    resolved: dict[str, Any],
) -> LLMCapabilities:
    values = vars(driver_capabilities).copy()
    for field, record in resolved.items():
        runtime_field = _CATALOG_TO_RUNTIME_CAPABILITY.get(field, field)
        if runtime_field not in values or not isinstance(record, dict):
            continue
        capability_value = str(record.get("value") or "unknown")
        if runtime_field == "supports_image_input" and capability_value == "unknown":
            values[runtime_field] = None
        else:
            values[runtime_field] = capability_value == "supported"
    return LLMCapabilities(**values)


def _base_capabilities_for_model(profile, provider) -> LLMCapabilities:
    model_name = str(profile.model or "").lower()
    provider_kind = str(provider.kind or "").lower()
    supports_json_mode = any(hint in model_name for hint in JSON_MODE_MODEL_HINTS)
    if provider_kind in {"local", "openai_compatible"} and profile.tool_calling_mode == "auto":
        supports_json_mode = False
    return LLMCapabilities(
        supports_streaming=bool(profile.streaming),
        supports_tool_calling=profile.tool_calling_mode != "disabled",
        supports_parallel_tool_calls=profile.tool_calling_mode == "parallel",
        supports_system_messages=True,
        supports_json_mode=supports_json_mode,
        supports_model_discovery=bool(profile.discovery_enabled),
    )


def discover_model(config: AppConfig, profile_id: str) -> ResolvedModelSpec:
    profile = config.llm.get_profile(profile_id)
    provider = config.llm.get_provider(profile.provider_id)
    base_capabilities = _base_capabilities_for_model(profile, provider)
    driver_capabilities = capabilities_for_adapter(provider, profile, base_capabilities)
    model_id, model_entry = config.llm.get_model_library_entry_for_profile(profile)
    model_ref = str((model_entry or {}).get("model_ref") or model_id or "").strip()
    provider_id = str((model_entry or {}).get("provider_id") or provider.provider_id or "").strip()
    upstream_id = str(
        (model_entry or {}).get("upstream_id") or (model_entry or {}).get("model") or profile.model or ""
    ).strip()
    declared_overrides, declared_fields = _declared_capability_overrides(model_entry)
    catalog_model, catalog_details = _catalog_model_details(provider_id, model_ref)
    provider_metadata, runtime_probe = _catalog_capability_layers(catalog_model)
    discovery_metadata = (
        model_entry.get("discovery_metadata", {})
        if isinstance(model_entry, dict) and isinstance(model_entry.get("discovery_metadata"), dict)
        else {}
    )
    metadata_capabilities, _metadata_fields = _declared_capability_overrides(discovery_metadata)
    provider_metadata = {**provider_metadata, **_catalog_capability_names(metadata_capabilities)}
    resolved_capabilities = resolve_model_capabilities(
        operator=_catalog_capability_names(declared_overrides),
        runtime_probe=runtime_probe,
        provider_metadata=provider_metadata,
        curated_snapshot=_catalog_capability_names(_curated_capabilities(profile)),
        driver_default=_catalog_capability_names(vars(driver_capabilities)),
    )
    capabilities = _capabilities_from_resolution(driver_capabilities, resolved_capabilities)
    capabilities = _apply_runtime_capability_gates(capabilities, profile)
    context_window = _lookup_context_window(profile.model, provider.context_window)
    provider_details = {
        "provider_id": provider_id,
        "base_url": provider.base_url,
        "model_ref": model_ref,
        "upstream_id": upstream_id,
        "capabilities": resolved_capabilities,
        **catalog_details,
    }
    if model_id:
        provider_details["model_library_id"] = model_id
    if declared_fields:
        provider_details["capability_source"] = "model_library.capabilities"
        provider_details["declared_capability_fields"] = declared_fields
    return ResolvedModelSpec(
        provider=provider.kind,
        profile_id=profile.profile_id,
        model=profile.model,
        transport=profile.transport,
        contract=profile.contract,
        context_window=context_window,
        capabilities=capabilities,
        discovery_status="configured",
        max_output_tokens=int(profile.max_output_tokens or 0),
        reasoning_state_field=profile.reasoning_state_field,
        strict_compatibility=bool(profile.strict_compatibility),
        provider_details=provider_details,
    )


def _compatibility_issues(profile, provider) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    transport = str(profile.transport or "chat_completions").strip().lower()
    contract = str(profile.contract or "tool_chat").strip().lower()
    tool_mode = str(profile.tool_calling_mode or "auto").strip().lower()
    reasoning_state_field = str(profile.reasoning_state_field or "").strip()
    provider_kind = str(provider.kind or "").strip().lower()
    compat_mode = str(provider.compat_mode or "").strip().lower()

    if contract == "responses_agent":
        errors.append("当前版本尚未启用 responses_agent 合同；请改用 tool_chat 或 reasoning_chat")

    if contract == "basic_chat":
        if tool_mode != "disabled":
            errors.append("basic_chat 要求 tool_calling_mode=disabled")
        if reasoning_state_field:
            warnings.append("basic_chat 不需要 reasoning_state_field，建议留空")

    if contract == "tool_chat":
        if transport not in {"chat_completions", "responses"}:
            errors.append("tool_chat 目前只支持 chat_completions 或 responses transport")
        if tool_mode == "disabled":
            errors.append("tool_chat 要求启用 tool calling，tool_calling_mode 不能为 disabled")

    if contract == "reasoning_chat":
        if transport != "chat_completions":
            errors.append("reasoning_chat 目前只支持 chat_completions transport")
        if tool_mode == "disabled":
            errors.append("reasoning_chat 要求启用 tool calling，tool_calling_mode 不能为 disabled")
        if reasoning_state_field not in SUPPORTED_REASONING_STATE_FIELDS:
            errors.append(
                "reasoning_chat 需要受支持的 reasoning_state_field；当前仅支持 reasoning_content"
            )
        if provider_kind == "anthropic":
            errors.append("anthropic provider 当前未接入 reasoning_chat 回放合同")

    if not compat_mode and provider_kind != "anthropic":
        warnings.append("provider 未声明 compat_mode，建议显式设置以减少切换歧义")

    if provider_kind == "local" and contract in {"tool_chat", "reasoning_chat"}:
        warnings.append("local provider 的高级协议兼容性依赖具体服务实现，保存后建议先做连接测试")

    return errors, warnings


def doctor_llm_profile(config: AppConfig, profile_id: str) -> DiagnosticReport:
    profile = config.llm.get_profile(profile_id)
    provider = config.llm.get_provider(profile.provider_id)
    errors = []
    warnings = []
    if provider.requires_api_key and not config.get_api_key_for_profile(profile_id=profile_id):
        errors.append(f"provider `{provider.provider_id}` 缺少 API Key")
    if not provider.base_url:
        warnings.append(f"provider `{provider.provider_id}` 未设置 base_url")
    spec = discover_model(config, profile_id)
    compat_errors, compat_warnings = _compatibility_issues(profile, provider)
    errors.extend(compat_errors)
    warnings.extend(compat_warnings)
    return DiagnosticReport(
        ok=not errors,
        provider=provider.kind,
        profile_id=profile.profile_id,
        model=profile.model,
        messages=[
            (
                f"{profile.profile_id} -> {provider.provider_id}:{profile.model} "
                f"[{profile.transport}/{profile.contract}]"
            )
        ],
        warnings=warnings,
        errors=errors,
        resolved_spec=spec,
    )


def assert_llm_compatibility(config: AppConfig) -> AppConfig:
    issues: list[str] = []
    for profile_id, profile in config.llm.profiles.items():
        provider = config.llm.get_provider(profile.provider_id)
        errors, _warnings = _compatibility_issues(profile, provider)
        if errors and bool(getattr(profile, "strict_compatibility", True)):
            issues.extend(f"[{profile_id}] {item}" for item in errors)
    if issues:
        raise ValueError("LLM 兼容性校验失败:\n- " + "\n- ".join(issues))
    return config
