"""Configuration public API without eager loading of models and provider services."""

from __future__ import annotations

from importlib import import_module as _import_module
from typing import Any as _Any


_EXPORT_GROUPS = {
    '.models': (
        'AgentConfig', 'AgentModesConfig', 'AnalysisConfig',
        'AppConfig', 'AvatarConfig', 'ChatDatasetCaptureConfig',
        'CompressionLevelsConfig', 'CompressionPreservationConfig', 'CompressionSummaryCharsConfig',
        'ContextCompressionConfig', 'DebugConfig', 'DiaryConfig',
        'DreamConfig', 'EvolutionConfig', 'GeneConfig',
        'HeartConfig', 'HungerConfig', 'LLMConfig',
        'LLMProfile', 'LogConfig', 'LogThirdPartyConfig',
        'MemoryConfig', 'NetworkConfig', 'ParserConfig',
        'PetConfig', 'PersonalityConfig', 'PromptConfig',
        'ProviderConfig', 'ProviderDeploymentConfig', 'ProviderDiscoverySettings',
        'ProviderProtocolsConfig', 'PinnedModelConfig', 'PinnedModelDefaults',
        'RetryPolicyConfig', 'RuntimeConfig', 'SectionConfig',
        'SecurityConfig', 'SkinConfig', 'SocialConfig',
        'SoundConfig', 'StrategyConfig', 'ToolConfig',
        'ToolsFileConfig', 'ToolsSearchConfig', 'ToolsShellConfig',
        'ToolsWebConfig', 'UIConfig', 'WebChatConfig',
        'WorkbenchConfig', 'resolve_api_key',
    ),
    '.llm_projection': (
        'project_v2_llm_for_runtime',
    ),
    '.effective_llm_graph': (
        'EffectiveLLMGraph', 'EffectiveLLMGraphBuilder', 'EffectiveLLMRoute',
        'LLMGraphError', 'LLMGraphIssue',
    ),
    '.llm_canonical_schema': (
        'CanonicalLLMConfigError', 'CanonicalLLMSchemaIssue', 'validate_canonical_llm_payload',
    ),
    '.llm_provider_registry': (
        'add_llm_provider', 'delete_llm_provider', 'pin_llm_model',
        'preview_provider_route_replacement', 'suggest_provider_id', 'unpin_llm_model',
        'update_llm_provider', 'validate_provider_registry',
    ),
    '.providers': (
        'MODEL_PRESETS', 'get_model_preset', 'list_models',
        'resolve_model_alias', 'show_model_info',
    ),
    '.paths': (
        'ensure_global_config_initialized', 'resolve_config_home', 'resolve_config_path',
    ),
    '.settings': (
        'ConfigLoader', 'Settings', 'denormalize_config_dict',
        'get_config', 'get_settings', 'normalize_public_config_dict',
        'reload_config',
    ),
}
_EXPORTS = {name: module for module, names in _EXPORT_GROUPS.items() for name in names}
__all__ = [
    'AgentConfig',
    'AgentModesConfig',
    'AnalysisConfig',
    'AppConfig',
    'AvatarConfig',
    'ChatDatasetCaptureConfig',
    'CompressionLevelsConfig',
    'CompressionPreservationConfig',
    'CompressionSummaryCharsConfig',
    'ConfigLoader',
    'ContextCompressionConfig',
    'DebugConfig',
    'CanonicalLLMConfigError',
    'CanonicalLLMSchemaIssue',
    'DiaryConfig',
    'DreamConfig',
    'EvolutionConfig',
    'EffectiveLLMGraph',
    'EffectiveLLMGraphBuilder',
    'EffectiveLLMRoute',
    'GeneConfig',
    'HeartConfig',
    'HungerConfig',
    'LLMConfig',
    'LLMProfile',
    'LLMGraphError',
    'LLMGraphIssue',
    'LogConfig',
    'LogThirdPartyConfig',
    'MemoryConfig',
    'NetworkConfig',
    'ParserConfig',
    'PetConfig',
    'PersonalityConfig',
    'PromptConfig',
    'ProviderConfig',
    'ProviderDeploymentConfig',
    'ProviderDiscoverySettings',
    'ProviderProtocolsConfig',
    'PinnedModelConfig',
    'PinnedModelDefaults',
    'RetryPolicyConfig',
    'RuntimeConfig',
    'SectionConfig',
    'SecurityConfig',
    'Settings',
    'SkinConfig',
    'SocialConfig',
    'SoundConfig',
    'StrategyConfig',
    'ToolConfig',
    'ToolsFileConfig',
    'ToolsSearchConfig',
    'ToolsShellConfig',
    'ToolsWebConfig',
    'UIConfig',
    'WebChatConfig',
    'WorkbenchConfig',
    'MODEL_PRESETS',
    'add_llm_provider',
    'denormalize_config_dict',
    'delete_llm_provider',
    'ensure_global_config_initialized',
    'get_config',
    'get_model_preset',
    'get_settings',
    'list_models',
    'normalize_public_config_dict',
    'project_v2_llm_for_runtime',
    'pin_llm_model',
    'preview_provider_route_replacement',
    'reload_config',
    'resolve_api_key',
    'resolve_config_home',
    'resolve_config_path',
    'resolve_model_alias',
    'show_model_info',
    'suggest_provider_id',
    'unpin_llm_model',
    'update_llm_provider',
    'validate_provider_registry',
    'validate_canonical_llm_payload',
]


def __getattr__(name: str) -> _Any:
    module_name = _EXPORTS.get(name)
    if module_name is None:
        # Let Python resolve real submodules through its normal import fallback.
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(_import_module(module_name, __name__), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()).union(_EXPORTS))
