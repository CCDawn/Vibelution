"""
Pydantic 数据模型定义

使用 Pydantic v2 定义所有配置项的数据模型，提供严格的类型校验和验证逻辑。

所有配置支持：
1. 从外部 operator config.toml 加载
2. 从环境变量覆盖
3. 从字典创建
4. 程序化修改

默认值语义：
- 本文件中的 default / default_factory 仅作为最低优先级兜底
- 主配置面由用户级外部 config.toml 显式表达，项目根不再承载运行配置
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple, Literal
from urllib.parse import urlparse

from pydantic import (
    BaseModel,
    Field,
    field_validator,
    model_validator,
    computed_field,
)
from pydantic import ConfigDict

from .llm_security import is_llm_local_network_base_url


PROVIDER_API_KEY_ENV_MAP: Dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "relay": "OPENAI_API_KEY",
    "openai_compatible": "OPENAI_API_KEY",
    "opencode": "OPENCODE_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "aliyun": "DASHSCOPE_API_KEY",
    "zhipu": "ZHIPU_API_KEY",
    "google": "GOOGLE_API_KEY",
    "siliconflow": "SILICONFLOW_API_KEY",
    "groq": "GROQ_API_KEY",
    "minimax": "MINIMAX_API_KEY",
    "xiaomi": "MIMO_API_KEY",
}

PROVIDER_API_KEY_ENV_ALIASES: Dict[str, List[str]] = {
    "anthropic": ["ANTHROPIC_AUTH_TOKEN"],
    "minimax": ["MINIMAX2_7_API_KEY", "minimax2.7"],
    "xiaomi": ["XIAOMI_MIMO_API_KEY"],
}

VALID_AGENT_MODES = ("chat", "self_evolution", "supervised_evolution")


def get_provider_api_key_env(provider: str) -> Optional[str]:
    """返回 provider 对应的 API Key 环境变量名。"""
    normalized = (provider or "").strip().lower()
    return PROVIDER_API_KEY_ENV_MAP.get(normalized)


def _read_windows_user_env_var(name: str) -> Optional[str]:
    if os.name != "nt":
        return None
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _value_type = winreg.QueryValueEx(key, name)
        value = str(value or "").strip()
        return value or None
    except (OSError, ImportError, ValueError):
        return None


def _read_env_var(name: str) -> Optional[str]:
    """读取环境变量；Windows 下在进程环境缺失时回退到用户级环境变量。"""
    value = os.environ.get(name)
    if value:
        return value
    fallback_enabled = str(os.environ.get("VIBELUTION_ENABLE_USER_ENV_FALLBACK", "") or "").strip().lower()
    if fallback_enabled not in {"1", "true", "yes", "on"}:
        return None
    return _read_windows_user_env_var(name)


def _is_local_base_url(base_url: str) -> bool:
    return is_llm_local_network_base_url(base_url)


def _discover_llm_facing_tool_names() -> Tuple[List[str], str]:
    """Return tool names actually registered for the project LLM surface.

    ``tools.shell.enabled`` only describes configuration permission.  The model
    can call a shell only when the runtime exposes a concrete tool such as
    ``cli_tool``.  Keeping this lightweight probe in config diagnosis makes the
    awareness section distinguish configured capability from the effective
    project tool surface.
    """
    try:
        from tools.Key_Tools import create_llm_facing_tools

        names: List[str] = []
        seen: set[str] = set()
        for tool in create_llm_facing_tools():
            name = str(getattr(tool, "name", "") or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            names.append(name)
        return sorted(names), ""
    except Exception as exc:  # pragma: no cover - diagnostic fallback only
        return [], f"{exc.__class__.__name__}: {exc}"


def resolve_api_key(provider: str, explicit_api_key: str = "") -> Optional[str]:
    """解析当前 provider 的 API Key。"""
    if explicit_api_key:
        return explicit_api_key

    normalized = (provider or "").strip().lower()
    env_var = get_provider_api_key_env(provider)
    if env_var:
        value = _read_env_var(env_var)
        if value:
            return value

    for alias in PROVIDER_API_KEY_ENV_ALIASES.get(normalized, []):
        value = _read_env_var(alias)
        if value:
            return value

    return None


# ============================================================================
# LLM 配置
# ============================================================================

class RetryPolicyConfig(BaseModel):
    """重试策略。"""
    model_config = ConfigDict(extra="ignore")

    max_attempts: int = Field(default=5, ge=1)
    backoff_base_seconds: float = Field(default=2.0, ge=0.1)


class PromptCacheConfig(BaseModel):
    """Prompt cache behavior declared by the model configuration."""
    model_config = ConfigDict(extra="ignore")

    mode: str = Field(default="disabled")
    key: str = Field(default="")
    retention: str = Field(default="")

    @field_validator("mode")
    @classmethod
    def normalize_mode(cls, v: str) -> str:
        value = (v or "disabled").strip().lower()
        if value not in {"disabled", "automatic", "explicit_cache_control", "unsupported"}:
            raise ValueError(
                "prompt_cache.mode must be one of: disabled, automatic, explicit_cache_control, unsupported"
            )
        return value

    @field_validator("key")
    @classmethod
    def normalize_key(cls, v: str) -> str:
        return (v or "").strip()

    @field_validator("retention")
    @classmethod
    def normalize_retention(cls, v: str) -> str:
        value = (v or "").strip().lower()
        if value not in {"", "in_memory", "24h"}:
            raise ValueError("prompt_cache.retention must be one of: in_memory, 24h")
        return value


class ProviderProtocolsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default: str = ""
    allowed: List[str] = Field(default_factory=list)
    routes: Dict[str, str] = Field(default_factory=dict)


class ProviderDiscoverySettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: str = "manual"
    adapter: str = "manual"
    models_url_override: str = ""
    cache_ttl_seconds: int = Field(default=3600, ge=0, le=86400)
    include: List[str] = Field(default_factory=list)
    exclude: List[str] = Field(default_factory=list)


class ProviderDeploymentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runtime_framework: str = ""
    artifact_path: str = ""


_KNOWN_REASONING_EFFORT_VALUES = {"none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"}
_REASONING_ADAPTERS = {"", "reasoning_object", "reasoning_effort", "thinking_toggle", "none"}


def _normalize_reasoning_effort_value(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in _KNOWN_REASONING_EFFORT_VALUES else ""


def _validate_model_reasoning_contract(model: Any) -> Any:
    values = [
        normalized
        for value in list(getattr(model, "reasoning_effort_values", []) or [])
        if (normalized := _normalize_reasoning_effort_value(value))
    ]
    values = list(dict.fromkeys(values))
    model.reasoning_effort_values = values
    if not values:
        model.default_reasoning_effort = ""
        model.reasoning_effort_adapter = "none"
        model.reasoning_effort_map = {}
        return model

    default = _normalize_reasoning_effort_value(getattr(model, "default_reasoning_effort", ""))
    if default and default not in values:
        raise ValueError("default_reasoning_effort must be present in reasoning_effort_values")
    model.default_reasoning_effort = default

    adapter = str(getattr(model, "reasoning_effort_adapter", "") or "reasoning_object").strip().lower()
    if adapter not in _REASONING_ADAPTERS:
        raise ValueError("unsupported reasoning_effort_adapter")
    if adapter in {"", "none"}:
        adapter = "reasoning_object"
    model.reasoning_effort_adapter = adapter

    mapping = {
        _normalize_reasoning_effort_value(key): str(value or "").strip().lower()
        for key, value in dict(getattr(model, "reasoning_effort_map", {}) or {}).items()
    }
    mapping = {key: value for key, value in mapping.items() if key and value}
    unknown_keys = sorted(set(mapping) - set(values))
    if unknown_keys:
        raise ValueError("reasoning_effort_map keys must be present in reasoning_effort_values")
    if adapter == "thinking_toggle" and set(mapping) != set(values):
        raise ValueError("thinking_toggle requires an on/off mapping for every reasoning effort value")
    allowed_targets = {"on", "off"} if adapter == "thinking_toggle" else _KNOWN_REASONING_EFFORT_VALUES
    if any(value not in allowed_targets for value in mapping.values()):
        raise ValueError("reasoning_effort_map contains an invalid adapter target")
    model.reasoning_effort_map = mapping
    return model


class PinnedModelDefaults(BaseModel):
    model_config = ConfigDict(extra="allow")

    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_output_tokens: int = Field(default=4096, gt=0)
    timeout: int = Field(default=60, gt=0)
    connect_timeout: int = Field(default=30, gt=0)
    streaming: bool = True
    tool_calling_mode: str = "auto"
    reasoning_effort_values: List[str] = Field(default_factory=list)
    default_reasoning_effort: str = ""
    reasoning_effort_adapter: Literal["", "reasoning_object", "reasoning_effort", "thinking_toggle", "none"] = ""
    reasoning_effort_map: Dict[str, str] = Field(default_factory=dict)
    prompt_cache: PromptCacheConfig = Field(default_factory=PromptCacheConfig)

    @model_validator(mode="after")
    def validate_reasoning_contract(self) -> "PinnedModelDefaults":
        return _validate_model_reasoning_contract(self)


class PinnedModelConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    upstream_id: str
    label: str = ""
    enabled: bool = True
    wire_protocol: str = ""
    interaction_contract: str = "tool_chat"
    model_protocol: str = ""
    context_window: Optional[int] = Field(default=None, gt=0)
    defaults: PinnedModelDefaults = Field(default_factory=PinnedModelDefaults)
    compatibility: Dict[str, Any] = Field(default_factory=dict)
    capabilities: Dict[str, Any] = Field(default_factory=dict)


class ProviderConfig(BaseModel):
    """Provider 级配置。"""
    model_config = ConfigDict(extra="ignore")

    provider_id: str = Field(default="")
    kind: str = Field(default="openai")
    api: str = Field(
        default="",
        description="Provider API contract, for example openai-completions, openai-responses, or anthropic-messages.",
    )
    api_key: str = Field(default="")
    api_key_env: str = Field(default="")
    base_url: str = Field(default="")
    extra_headers: Dict[str, str] = Field(default_factory=dict)
    compat_mode: str = Field(default="native")
    requires_api_key: bool = Field(default=True)
    # None = not configured. Never invent 32768; missing must fail closed at runtime.
    context_window: Optional[int] = Field(
        default=None,
        description="Provider-level max context window. None means unconfigured (no silent default).",
    )
    label: str = ""
    service_class: Literal["official_api", "aggregator", "relay", "self_hosted", "local_runtime"] = "official_api"
    vendor: str = "custom"
    driver: Literal["openai", "anthropic", "gemini"] = "openai"
    auth_kind: Literal["api_key", "oauth", "none"] = "api_key"
    credential_ref: str = ""
    requires_credential: bool = True
    protocols: ProviderProtocolsConfig = Field(default_factory=ProviderProtocolsConfig)
    discovery: ProviderDiscoverySettings = Field(default_factory=ProviderDiscoverySettings)
    deployment: ProviderDeploymentConfig = Field(default_factory=ProviderDeploymentConfig)
    models: Dict[str, PinnedModelConfig] = Field(default_factory=dict)
    legacy_inference_allowed: bool = Field(default=True, exclude=True)

    @field_validator("kind")
    @classmethod
    def normalize_kind(cls, v: str) -> str:
        return (v or "").strip().lower()

    @field_validator("api")
    @classmethod
    def normalize_api(cls, v: str) -> str:
        return (v or "").strip().lower().replace("_", "-")

    @field_validator("context_window", mode="before")
    @classmethod
    def normalize_context_window(cls, v: Any) -> Optional[int]:
        if v is None or v == "" or v is False:
            return None
        try:
            number = int(v)
        except Exception as exc:
            raise ValueError("context_window must be a positive integer when set") from exc
        if number <= 0:
            return None
        return number

    @model_validator(mode="after")
    def validate_v2_provider_contract(self) -> "ProviderConfig":
        if not self.credential_ref and not self.models:
            return self
        from .llm_credentials import canonicalize_credential_ref
        from .llm_identity import make_model_ref, normalize_provider_endpoint

        normalize_provider_endpoint(self.base_url)
        canonical_ref = canonicalize_credential_ref(self.credential_ref or "none")
        if self.auth_kind == "none" and canonical_ref != "none":
            raise ValueError("auth_kind none requires credential_ref none")
        if self.auth_kind != "none" and canonical_ref == "none" and self.requires_credential:
            raise ValueError("credential_ref is required when provider requires a credential")
        if self.protocols.default and self.protocols.allowed and self.protocols.default not in self.protocols.allowed:
            raise ValueError("provider default protocol must be present in protocols.allowed")
        if self.service_class != "local_runtime" and self.deployment.runtime_framework:
            raise ValueError("runtime_framework is only valid for local_runtime providers")
        for model_key, model in self.models.items():
            make_model_ref(self.provider_id or "provider", model_key)
            if not model.upstream_id.strip():
                raise ValueError(f"pinned model {model_key} requires upstream_id")
        return self

    def resolve_api_key(self) -> Optional[str]:
        if self.credential_ref:
            from .llm_credentials import resolve_credential_ref

            resolution = resolve_credential_ref(self.credential_ref)
            return resolution.secret or None
        env_candidates: List[str] = []
        if self.api_key_env:
            env_candidates.append(self.api_key_env)
        canonical_env = get_provider_api_key_env(self.kind)
        if canonical_env and canonical_env not in env_candidates:
            env_candidates.append(canonical_env)
        for env_var in env_candidates:
            value = _read_env_var(env_var)
            if value:
                return value
        for alias in PROVIDER_API_KEY_ENV_ALIASES.get((self.kind or "").strip().lower(), []):
            value = _read_env_var(alias)
            if value:
                return value
        return self.api_key or None


class LLMProfile(BaseModel):
    """模型运行档案。"""
    model_config = ConfigDict(extra="ignore")

    profile_id: str = Field(default="")
    model_ref: str = Field(default="")
    provider_id: str = Field(default="default")
    model: str = Field(default="qwen-plus")
    api_key_env: str = Field(default="")
    transport: str = Field(default="chat_completions")
    contract: str = Field(default="tool_chat")
    protocol: str = Field(
        default="",
        description="Explicit model protocol route, for example llamacpp_qwen_thinking.",
    )
    compat: Dict[str, Any] = Field(
        default_factory=dict,
        description="Model-level compatibility hints for protocol payload shaping.",
    )
    reasoning_state_field: str = Field(default="")
    strict_compatibility: bool = Field(default=True)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_output_tokens: int = Field(default=4096, gt=0)
    timeout: int = Field(default=60, gt=0)
    connect_timeout: int = Field(default=30, gt=0)
    streaming: bool = Field(default=True)
    tool_calling_mode: str = Field(default="auto")
    retry_policy: RetryPolicyConfig = Field(default_factory=RetryPolicyConfig)
    prompt_cache: PromptCacheConfig = Field(default_factory=PromptCacheConfig)
    discovery_enabled: bool = Field(default=True)
    thinking_type: str = Field(
        default="",
        description="Provider-specific thinking mode, for example Anthropic adaptive thinking.",
    )
    thinking_display: str = Field(
        default="",
        description="Provider-specific thinking display mode, for example summarized or omitted.",
    )
    reasoning_effort: str = Field(
        default="",
        description="OpenAI Responses reasoning effort for GPT reasoning-capable models.",
    )
    reasoning_effort_values: List[str] = Field(default_factory=list)
    default_reasoning_effort: str = ""
    reasoning_effort_adapter: Literal["", "reasoning_object", "reasoning_effort", "thinking_toggle", "none"] = ""
    reasoning_effort_map: Dict[str, str] = Field(default_factory=dict)
    supports_image_input: Optional[bool] = Field(
        default=None,
        description="Whether this profile is confirmed to accept image inputs in chat turns.",
    )

    @field_validator("transport")
    @classmethod
    def normalize_transport(cls, v: str) -> str:
        value = (v or "chat_completions").strip().lower()
        if value not in {"chat_completions", "responses"}:
            raise ValueError("transport must be one of: chat_completions, responses")
        return value

    @field_validator("contract")
    @classmethod
    def normalize_contract(cls, v: str) -> str:
        value = (v or "tool_chat").strip().lower()
        if value not in {"basic_chat", "tool_chat", "reasoning_chat", "responses_agent"}:
            raise ValueError(
                "contract must be one of: basic_chat, tool_chat, reasoning_chat, responses_agent"
            )
        return value

    @field_validator("protocol")
    @classmethod
    def normalize_protocol(cls, v: str) -> str:
        return (v or "").strip().lower()

    @field_validator("reasoning_state_field")
    @classmethod
    def normalize_reasoning_state_field(cls, v: str) -> str:
        return (v or "").strip()

    @field_validator("thinking_type")
    @classmethod
    def normalize_thinking_type(cls, v: str) -> str:
        value = (v or "").strip().lower()
        if value not in {"", "adaptive", "disabled"}:
            raise ValueError("thinking_type must be one of: adaptive, disabled")
        return value

    @field_validator("thinking_display")
    @classmethod
    def normalize_thinking_display(cls, v: str) -> str:
        value = (v or "").strip().lower()
        if value not in {"", "summarized", "omitted"}:
            raise ValueError("thinking_display must be one of: summarized, omitted")
        return value

    @field_validator("reasoning_effort")
    @classmethod
    def normalize_reasoning_effort(cls, v: str) -> str:
        value = (v or "").strip().lower()
        if value not in {"", "none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"}:
            raise ValueError("reasoning_effort must be one of: none, minimal, low, medium, high, xhigh, max, ultra")
        return value

    @model_validator(mode="after")
    def validate_thinking_display(self) -> "LLMProfile":
        if self.thinking_type == "disabled" and self.thinking_display:
            self.thinking_display = ""
        if self.thinking_display and not self.thinking_type:
            raise ValueError("thinking_display requires thinking_type")
        return _validate_model_reasoning_contract(self)


class LLMDiscoveryConfig(BaseModel):
    """LLM 动态发现配置"""
    model_config = ConfigDict(extra="ignore")

    enabled: bool = Field(
        default=True,
        description="是否启用运行时模型发现"
    )
    timeout: int = Field(
        default=30,
        gt=0,
        description="发现请求超时（秒）"
    )
    fallback_max_tokens: Optional[int] = Field(
        default=None,
        description="发现失败时使用的 max_tokens"
    )
    fallback_max_token_limit: Optional[int] = Field(
        default=None,
        description="发现失败时使用的 max_token_limit"
    )
    auto_adjust: bool = Field(
        default=True,
        description="是否自动调整压缩阈值"
    )
    output_reserve_ratio: float = Field(
        default=0.125,
        ge=0.1,
        le=0.5,
        description="预留输出 tokens 比例"
    )


DEFAULT_ROLE_PROFILE_IDS = (
    "primary",
    "mental_model",
    "runtime_status",
    "subagent_worker",
    "subagent_explorer",
    "supervised_baseline",
    "supervised_candidate",
    "research_broad",
    "research_deep",
    "research_review",
    "research_themes",
    "research_card",
    "compression",
)


DEFAULT_LLM_ROUTE_CONCURRENCY = 4


class LLMConfig(BaseModel):
    """新的 LLM 根配置：providers / profiles / discovery。"""
    model_config = ConfigDict(extra="ignore")

    schema_version: int | None = Field(default=None, ge=2, le=2)
    providers: Dict[str, ProviderConfig] = Field(default_factory=dict)
    profiles: Dict[str, LLMProfile] = Field(default_factory=dict)
    model_library: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    model_aliases: Dict[str, str] = Field(default_factory=dict)
    discovery: LLMDiscoveryConfig = Field(default_factory=LLMDiscoveryConfig)
    route_concurrency: int = Field(
        default=DEFAULT_LLM_ROUTE_CONCURRENCY,
        description="单条 LLM 路由（provider|base_url|model|profile）的最大并发请求数",
    )

    @field_validator("route_concurrency", mode="before")
    @classmethod
    def _fallback_invalid_route_concurrency(cls, value: Any) -> int:
        # 非法值（0/负数/bool/浮点/字符串/None）不阻断启动，统一回退缺省。
        if isinstance(value, bool) or not isinstance(value, int):
            return DEFAULT_LLM_ROUTE_CONCURRENCY
        return value if value >= 1 else DEFAULT_LLM_ROUTE_CONCURRENCY

    @model_validator(mode="after")
    def ensure_defaults(self) -> "LLMConfig":
        implicit_default = self.schema_version is None
        if implicit_default:
            self.schema_version = 2
        if self.schema_version == 2 and not implicit_default:
            if not self.providers:
                raise ValueError("llm.providers must not be empty in schema v2")
            if not self.profiles:
                raise ValueError("llm.profiles must not be empty in schema v2")
        if not self.providers:
            self.providers["default"] = ProviderConfig(
                provider_id="default",
                kind="aliyun",
                api_key_env="DASHSCOPE_API_KEY",
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                compat_mode="openai",
                requires_api_key=True,
                context_window=131072,
            )
        if not self.profiles:
            self.profiles["primary"] = LLMProfile(
                profile_id="primary",
                provider_id=next(iter(self.providers.keys())),
                model="qwen-plus",
                max_output_tokens=4096,
            )
        for provider_id, provider in self.providers.items():
            if not provider.provider_id:
                provider.provider_id = provider_id
        for profile_id, profile in self.profiles.items():
            if not profile.profile_id:
                profile.profile_id = profile_id
        return self

    def get_role_profile_id(self, role: str = "primary") -> str:
        normalized_role = (role or "primary").strip() or "primary"
        if normalized_role in self.profiles:
            return normalized_role
        if "primary" in self.profiles:
            return "primary"
        if self.profiles:
            return next(iter(self.profiles.keys()))
        raise ValueError("missing profile: primary")

    def get_profile(self, profile_id: Optional[str] = None, role: str = "primary") -> LLMProfile:
        resolved_id = profile_id or self.get_role_profile_id(role)
        profile = self.profiles.get(resolved_id)
        if profile is None:
            raise ValueError(f"missing profile: {resolved_id}")
        return profile

    def get_provider(self, provider_id: Optional[str] = None, role: str = "primary") -> ProviderConfig:
        resolved_provider_id = provider_id
        if resolved_provider_id is None:
            resolved_provider_id = self.get_profile(role=role).provider_id
        provider = self.providers.get(resolved_provider_id)
        if provider is None:
            raise ValueError(f"missing provider: {resolved_provider_id}")
        return provider

    def resolve_model_ref(self, model_ref: str) -> str:
        requested = str(model_ref or "").strip()
        current = requested
        visited: set[str] = set()
        while current in self.model_aliases:
            if current in visited:
                raise ValueError(f"cyclic model alias: {requested}")
            visited.add(current)
            current = str(self.model_aliases[current] or "").strip()
        return current

    @staticmethod
    def _provider_identity(provider: Optional[ProviderConfig]) -> tuple:
        if provider is None:
            return tuple()
        return (
            str(provider.kind or "").strip().lower(),
            str(provider.api_key or "").strip(),
            str(provider.api_key_env or "").strip(),
            str(provider.base_url or "").strip(),
            tuple(sorted((provider.extra_headers or {}).items())),
            str(provider.compat_mode or "").strip().lower(),
            bool(provider.requires_api_key),
            int(provider.context_window or 0),
        )

    def get_model_library_entry_for_profile(self, profile: LLMProfile) -> tuple[str, Dict[str, Any]] | tuple[None, None]:
        requested_ref = str(profile.model_ref or "").strip()
        if requested_ref:
            canonical_ref = self.resolve_model_ref(requested_ref)
            direct_entry = self.model_library.get(canonical_ref)
            if isinstance(direct_entry, dict):
                return canonical_ref, direct_entry
        profile_provider = self.get_provider(profile.provider_id)
        for model_id, item in self.model_library.items():
            if not isinstance(item, dict):
                continue
            if item.get("model") != profile.model:
                continue
            item_provider_id = str(item.get("provider_id") or "").strip()
            if item_provider_id == profile.provider_id:
                return model_id, item
            item_provider = self.providers.get(item_provider_id)
            if self._provider_identity(item_provider) == self._provider_identity(profile_provider):
                return model_id, item
        return None, None

    def resolve_api_key_for_profile(self, profile_id: Optional[str] = None, role: str = "primary") -> Optional[str]:
        profile = self.get_profile(profile_id=profile_id, role=role)
        provider = self.get_provider(profile.provider_id)
        profile_model_env = str(getattr(profile, "api_key_env", "") or "").strip()
        if profile_model_env:
            value = _read_env_var(profile_model_env)
            if value:
                return value
        _, model_entry = self.get_model_library_entry_for_profile(profile)
        if isinstance(model_entry, dict):
            model_env = str(model_entry.get("api_key_env") or "").strip()
            if model_env:
                value = _read_env_var(model_env)
                if value:
                    return value
        return provider.resolve_api_key()

    def get_api_key_source_label_for_profile(self, profile_id: Optional[str] = None, role: str = "primary") -> str:
        profile = self.get_profile(profile_id=profile_id, role=role)
        provider = self.get_provider(profile.provider_id)
        profile_model_env = str(getattr(profile, "api_key_env", "") or "").strip()
        _, model_entry = self.get_model_library_entry_for_profile(profile)
        model_env = ""
        if isinstance(model_entry, dict):
            model_env = str(model_entry.get("api_key_env") or "").strip()
            if model_env and model_env == profile_model_env and _read_env_var(model_env):
                return f"model-env:{model_env}"
        if profile_model_env and _read_env_var(profile_model_env):
            return f"profile-env:{profile_model_env}"
        if model_env and _read_env_var(model_env):
            return f"model-env:{model_env}"

        provider_env = provider.api_key_env or get_provider_api_key_env(provider.kind)
        if provider_env and _read_env_var(provider_env):
            return f"provider-env:{provider_env}"

        if provider.api_key:
            return "config-or-kwargs"

        canonical_env = get_provider_api_key_env(provider.kind)
        if canonical_env and canonical_env != provider_env and _read_env_var(canonical_env):
            return f"provider-env:{canonical_env}"

        return "missing"

    @property
    def api_key(self) -> str:
        return self.get_provider(role="primary").api_key or ""

    @api_key.setter
    def api_key(self, value: str) -> None:
        self.get_provider(role="primary").api_key = value

# ============================================================================
# Agent 行为配置
# ============================================================================

class AgentModesConfig(BaseModel):
    """Agent 运行模式配置。"""
    model_config = ConfigDict(extra="ignore")

    chat_enabled: bool = Field(default=True, description="是否启用 chat 模式")
    self_evolution_enabled: bool = Field(default=False, description="是否启用 self_evolution 模式")
    supervised_evolution_enabled: bool = Field(default=False, description="是否启用 supervised_evolution 模式")
    default_shell_mode: str = Field(default="chat", description="交互工作台默认模式")
    default_headless_mode: str = Field(default="self_evolution", description="无交互运行默认模式")

    @field_validator("default_shell_mode", "default_headless_mode")
    @classmethod
    def validate_mode_name(cls, v: str) -> str:
        value = (v or "").strip().lower()
        if value not in VALID_AGENT_MODES:
            raise ValueError(f"mode must be one of: {', '.join(VALID_AGENT_MODES)}")
        return value

class AgentConfig(BaseModel):
    """
    Agent 行为配置

    Attributes:
        name: Agent 实例名称
        workspace: 工作区目录路径
        awake_interval: 苏醒间隔（秒），Agent 定期检查是否有任务
        max_iterations: 单次苏醒的最大工具调用次数
        max_runtime: 最大运行时间（秒），0 表示无限制
        auto_backup: 是否启用自动备份
        backup_interval: 自动备份间隔（秒）
        auto_restart_threshold: 自动重启阈值（错误次数），0 表示禁用
        exploration_mode: 是否启用探索模式
    """
    model_config = ConfigDict(extra="ignore")

    name: str = Field(
        default="SelfEvolvingAgent",
        description="Agent 名称"
    )
    workspace: str = Field(
        default="workspace",
        description="工作区目录（相对于项目根目录）"
    )
    awake_interval: int = Field(
        default=60,
        gt=0,
        description="苏醒间隔（秒）"
    )
    max_iterations: int = Field(
        default=200,
        gt=0,
        description="单次苏醒的最大工具调用次数"
    )
    max_runtime: int = Field(
        default=0,
        ge=0,
        description="最大运行时间（秒），0 表示无限制"
    )
    auto_backup: bool = Field(
        default=False,
        description="是否启用自动备份"
    )
    backup_interval: int = Field(
        default=300,
        gt=0,
        description="自动备份间隔（秒）"
    )
    auto_restart_threshold: int = Field(
        default=0,
        ge=0,
        description="自动重启阈值，0 表示禁用"
    )
    exploration_mode: bool = Field(
        default=False,
        description="是否启用探索模式"
    )
    default_mode: str = Field(
        default="self_evolution",
        description="Agent 默认运行模式"
    )
    modes: AgentModesConfig = Field(
        default_factory=AgentModesConfig,
        description="Agent 运行模式配置"
    )

    @field_validator("awake_interval", "max_iterations", "backup_interval")
    @classmethod
    def validate_positive(cls, v: int) -> int:
        """验证正整数"""
        if v <= 0:
            raise ValueError(f"Value must be positive, got {v}")
        return v

    @field_validator("default_mode")
    @classmethod
    def validate_default_mode(cls, v: str) -> str:
        value = (v or "self_evolution").strip().lower()
        if value not in VALID_AGENT_MODES:
            raise ValueError(f"default_mode must be one of: {', '.join(VALID_AGENT_MODES)}")
        return value


class WebChatConfig(BaseModel):
    """Web Chat 任务级持续执行配置。"""
    model_config = ConfigDict(extra="ignore")

    max_continuation_turns: int = Field(
        default=4,
        ge=1,
        description="一次 Web Chat 用户消息最多连续推进多少个 single_turn",
    )


class SessionCatalogConfig(BaseModel):
    """Rebuildable session metadata catalog rollout settings."""

    model_config = ConfigDict(extra="ignore")

    mode: str = Field(default="off")
    reconcile_on_startup: bool = Field(default=True)
    incremental_reconcile_delay_ms: int = Field(default=750, ge=0, le=60000)
    busy_timeout_ms: int = Field(default=5000, ge=0, le=120000)

    @field_validator("mode")
    @classmethod
    def normalize_mode(cls, value: str) -> str:
        normalized = str(value or "off").strip().lower()
        if normalized not in {"off", "shadow", "read_preferred"}:
            raise ValueError(
                "session_catalog.mode must be one of: off, shadow, read_preferred"
            )
        return normalized


class ExternalAgentGatewayConfig(BaseModel):
    """Fail-closed operator policy for the local managed MCP gateway."""

    model_config = ConfigDict(extra="ignore")

    enabled: bool = False
    permission_ceiling: str = "read_only"
    runtime_permission_ceiling: str = "workspace_write"
    approval_persist_enabled: bool = False
    allowed_agent_ids: list[str] = Field(default_factory=list)
    denied_agent_ids: list[str] = Field(default_factory=list)
    max_concurrent_tasks_per_owner: int = Field(default=4, ge=1, le=32)
    max_concurrent_tasks_per_agent: int = Field(default=1, ge=1, le=8)
    max_task_seconds: int = Field(default=1800, ge=5, le=7200)
    lease_seconds: int = Field(default=30, ge=5, le=300)

    @field_validator("permission_ceiling", "runtime_permission_ceiling")
    @classmethod
    def normalize_permission_profile(cls, value: str) -> str:
        normalized = str(value or "").strip().lower()
        if normalized not in {"read_only", "workspace_write", "full_access"}:
            raise ValueError(
                "external Agent permission profile must be one of: "
                "read_only, workspace_write, full_access"
            )
        return normalized

    @field_validator("allowed_agent_ids", "denied_agent_ids", mode="before")
    @classmethod
    def normalize_agent_ids(cls, value: Any) -> list[str]:
        if not isinstance(value, (list, tuple, set)):
            return []
        result: list[str] = []
        seen: set[str] = set()
        for item in value:
            agent_id = str(item or "").strip()
            if not agent_id or agent_id in seen:
                continue
            seen.add(agent_id)
            result.append(agent_id)
        return result


# ============================================================================
# 上下文压缩配置
# ============================================================================

class CompressionLevelsConfig(BaseModel):
    """压缩级别阈值配置"""
    model_config = ConfigDict(extra="ignore")

    light: float = Field(
        default=0.6,
        ge=0.0,
        le=1.0,
        description="轻度压缩阈值（相对于 max_token_limit）"
    )
    standard: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description="标准压缩阈值"
    )
    deep: float = Field(
        default=0.9,
        ge=0.0,
        le=1.0,
        description="深度压缩阈值"
    )
    emergency: float = Field(
        default=0.95,
        ge=0.0,
        le=1.0,
        description="紧急压缩阈值"
    )


class CompressionSummaryCharsConfig(BaseModel):
    """各压缩级别摘要字数配置"""
    model_config = ConfigDict(extra="ignore")

    light: int = Field(
        default=500,
        ge=0,
        description="轻度压缩摘要字数"
    )
    standard: int = Field(
        default=1000,
        ge=0,
        description="标准压缩摘要字数"
    )
    deep: int = Field(
        default=2000,
        ge=0,
        description="深度压缩摘要字数"
    )
    emergency: int = Field(
        default=3000,
        ge=0,
        description="紧急压缩摘要字数"
    )


class CompressionPreservationConfig(BaseModel):
    """智能保留策略配置"""
    model_config = ConfigDict(extra="ignore")

    keep_ai_messages: int = Field(
        default=5,
        ge=0,
        description="保留最近 AI 消息数"
    )
    keep_tool_results: bool = Field(
        default=True,
        description="保留工具调用结果"
    )
    preserve_errors: bool = Field(
        default=True,
        description="保留错误信息"
    )
    extract_key_decisions: bool = Field(
        default=True,
        description="提取关键决策"
    )


class ContextCompressionConfig(BaseModel):
    """
    运行时上下文压缩配置

    Attributes:
        enabled: 是否启用压缩
        max_token_limit: Token 阈值，超过此值触发压缩
        keep_recent_steps: 保留最近的工具调用次数
        summary_max_chars: 压缩摘要的最大字符数
        compression_model: 用于压缩的模型名称
        compression_temperature: 压缩用模型温度
        max_compressions_per_session: 每会话最大压缩次数
        effectiveness_threshold: 压缩效率阈值
    """
    model_config = ConfigDict(extra="ignore")

    enabled: bool = Field(
        default=True,
        description="是否启用上下文压缩"
    )
    max_token_limit: int = Field(
        default=16000,
        gt=0,
        description="Token 阈值，超过此值触发压缩"
    )
    keep_recent_steps: int = Field(
        default=2,
        ge=0,
        description="保留最近的工具调用次数"
    )
    summary_max_chars: int = Field(
        default=200,
        gt=0,
        description="压缩摘要的最大字符数"
    )
    compression_model: str = Field(
        default="qwen-turbo",
        description="用于压缩的轻量模型"
    )
    compression_temperature: float = Field(
        default=0.3,
        ge=0.0,
        le=2.0,
        description="压缩用模型温度"
    )
    max_compressions_per_session: int = Field(
        default=20,
        ge=0,
        description="每会话最大压缩次数"
    )
    effectiveness_threshold: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description="压缩效率阈值"
    )
    reserved_max_output_tokens: int = Field(
        default=0,
        ge=0,
        description="调用前为模型输出预留的 token 上限；0 表示使用模型能力配置的 max_output"
    )
    protocol_and_safety_reserve_tokens: int = Field(
        default=0,
        ge=0,
        description="协议封装、工具 schema 与估算误差的安全余量；0 表示使用版本化默认值 8192"
    )
    levels: CompressionLevelsConfig = Field(
        default_factory=CompressionLevelsConfig,
        description="压缩级别阈值配置"
    )
    summary_chars: CompressionSummaryCharsConfig = Field(
        default_factory=CompressionSummaryCharsConfig,
        description="各压缩级别摘要字数配置"
    )
    preservation: CompressionPreservationConfig = Field(
        default_factory=CompressionPreservationConfig,
        description="智能保留策略配置"
    )

    @model_validator(mode="after")
    def validate_limits(self) -> "ContextCompressionConfig":
        """验证限制参数"""
        if self.keep_recent_steps > 10:
            raise ValueError("keep_recent_steps should not exceed 10")
        if self.summary_max_chars > 1000:
            raise ValueError("summary_max_chars should not exceed 1000")
        return self


# ============================================================================
# 形象配置
# ============================================================================

class AvatarConfig(BaseModel):
    """ASCII 形象配置"""
    model_config = ConfigDict(extra="ignore")

    preset: str = Field(
        default="lobster",
        description="预设形象: lobster(龙虾), shrimp(小虾米), crab(小螃蟹), cat(猫猫), chick(小鸡), bunny(兔兔), slime(果冻团), penguin(企鹅), moose(驼鹿)"
    )


# ============================================================================
# 用户画像配置
# ============================================================================

class UserProfileConfig(BaseModel):
    """用户画像配置，供 UI 展示和 agent 运行时参考。"""
    model_config = ConfigDict(extra="ignore")

    display_name: str = Field(default="", description="用户显示名。为空时回退到系统用户名。")
    bio: str = Field(default="", description="给 agent 参考的简短用户背景。")
    preferences: List[str] = Field(default_factory=list, description="给 agent 参考的用户偏好列表。")
    avatar_preset: str = Field(default="default", description="用户头像预设，用于 Web UI 展示。")
    avatar_image_path: str = Field(default="", description="用户本地头像图片路径，仅限 Web UI 展示。")

    @field_validator("display_name", "bio", "avatar_preset", "avatar_image_path")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return (value or "").strip()

    @field_validator("preferences")
    @classmethod
    def normalize_preferences(cls, value: List[str]) -> List[str]:
        normalized: List[str] = []
        for item in value or []:
            text = str(item or "").strip()
            if text:
                normalized.append(text)
        return normalized


# ============================================================================
# 文件操作配置
# ============================================================================

class ToolsFileConfig(BaseModel):
    """文件操作工具配置"""
    model_config = ConfigDict(extra="ignore")

    edit_enabled: bool = Field(
        default=True,
        description="是否启用文件编辑"
    )
    create_enabled: bool = Field(
        default=True,
        description="是否启用文件创建"
    )
    syntax_check_enabled: bool = Field(
        default=True,
        description="是否启用语法检查"
    )
    max_read_lines: int = Field(
        default=0,
        ge=0,
        description="单次读取最大行数（0 表示无限制）"
    )
    max_read_chars: int = Field(
        default=0,
        ge=0,
        description="单次读取最大字符数（0 表示无限制）"
    )
    encoding_priority: List[str] = Field(
        default_factory=lambda: ["utf-8", "utf-8-sig", "gbk", "gb2312", "latin-1"],
        description="文件编码自动检测顺序"
    )
    editable_extensions: List[str] = Field(
        default_factory=lambda: [
            ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".kt", ".go", ".rs",
            ".c", ".cpp", ".h", ".hpp", ".rb", ".php", ".html", ".css", ".scss",
            ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".md", ".txt",
            ".sh", ".sql", ".xml", ".svg"
        ],
        description="允许编辑的文件扩展名"
    )


# ============================================================================
# Shell 命令配置
# ============================================================================

class ToolsShellConfig(BaseModel):
    """Shell 命令工具配置"""
    model_config = ConfigDict(extra="ignore")

    enabled: bool = Field(
        default=True,
        description="是否启用 Shell 执行"
    )
    default_timeout: int = Field(
        default=60,
        gt=0,
        description="默认超时时间（秒）"
    )
    max_output_length: int = Field(
        default=10000,
        gt=0,
        description="最大输出长度（字符）"
    )
    max_file_size: int = Field(
        default=10485760,
        gt=0,
        description="最大文件大小（字节）"
    )
    safety_check: bool = Field(
        default=True,
        description="是否启用安全检查"
    )
    dangerous_pattern_check: bool = Field(
        default=True,
        description="危险命令黑名单检测"
    )
    allowed_shells: List[str] = Field(
        default_factory=lambda: ["powershell", "cmd", "bash"],
        description="允许的 Shell 类型"
    )


# ============================================================================
# 搜索工具配置
# ============================================================================

class ToolsSearchConfig(BaseModel):
    """搜索工具配置"""
    model_config = ConfigDict(extra="ignore")

    max_file_size: int = Field(
        default=10485760,
        gt=0,
        description="搜索最大文件大小（字节）"
    )
    max_matches_per_file: int = Field(
        default=100,
        gt=0,
        description="每个文件最大匹配数"
    )
    max_results: int = Field(
        default=500,
        gt=0,
        description="最大总结果数"
    )
    context_lines: int = Field(
        default=3,
        ge=0,
        description="上下文行数"
    )
    skip_directories: List[str] = Field(
        default_factory=lambda: [
            "__pycache__", ".git", ".svn", ".hg", "node_modules",
            ".venv", "venv", "env", ".env", ".idea", ".vscode",
            "dist", "build", ".tox", ".pytest_cache", ".mypy_cache",
            "site-packages", "egg-info", ".eggs"
        ],
        description="搜索时跳过的目录"
    )
    skip_extensions: List[str] = Field(
        default_factory=lambda: [".exe", ".dll", ".so", ".dylib", ".pyc", ".pyo", ".pyd"],
        description="搜索时跳过的文件扩展名"
    )
    include_extensions: List[str] = Field(
        default_factory=lambda: [
            ".py", ".js", ".ts", ".jsx", ".tsx", ".md", ".json", ".yaml",
            ".yml", ".toml", ".txt", ".html", ".css", ".xml", ".sh", ".bat", ".ps1"
        ],
        description="搜索时包含的文件扩展名"
    )


# ============================================================================
# 网络工具配置
# ============================================================================

class ToolsWebConfig(BaseModel):
    """网络工具配置"""
    model_config = ConfigDict(extra="ignore")

    search_enabled: bool = Field(
        default=True,
        description="是否启用网络搜索"
    )
    max_search_results: int = Field(
        default=10,
        gt=0,
        description="搜索结果数量"
    )
    search_timeout: int = Field(
        default=30,
        gt=0,
        description="搜索超时（秒）"
    )


class ToolsImage2Config(BaseModel):
    """image2 生图工具配置"""
    model_config = ConfigDict(extra="ignore")

    default_model_ref: str = Field(
        default="",
        description="全局默认 image2 模型库引用，留空时回退到环境变量或内置模型名。"
    )

    @field_validator("default_model_ref")
    @classmethod
    def normalize_default_model_ref(cls, v: str) -> str:
        return (v or "").strip()


# ============================================================================
# 工具配置
# ============================================================================

class ToolConfig(BaseModel):
    """工具模块配置"""
    model_config = ConfigDict(extra="ignore")

    restart_enabled: bool = Field(
        default=True,
        description="是否允许 Agent 自我重启"
    )
    allowed_directories: List[str] = Field(
        default_factory=list,
        description="允许访问的目录列表"
    )
    forbidden_patterns: List[str] = Field(
        default_factory=lambda: [
            ".env", ".password", ".secret", ".key",
            "id_rsa", "credentials.json"
        ],
        description="禁止访问的文件模式"
    )
    file: ToolsFileConfig = Field(
        default_factory=ToolsFileConfig,
        description="文件操作配置"
    )
    shell: ToolsShellConfig = Field(
        default_factory=ToolsShellConfig,
        description="Shell 命令配置"
    )
    search: ToolsSearchConfig = Field(
        default_factory=ToolsSearchConfig,
        description="搜索工具配置"
    )
    web: ToolsWebConfig = Field(
        default_factory=ToolsWebConfig,
        description="网络工具配置"
    )
    image2: ToolsImage2Config = Field(
        default_factory=ToolsImage2Config,
        description="image2 生图工具配置"
    )

    @model_validator(mode="after")
    def setup_directories(self) -> "ToolConfig":
        """自动设置默认允许目录"""
        if not self.allowed_directories:
            project_root = Path(__file__).parent.parent.resolve()
            self.allowed_directories = [
                str(project_root),
                str(project_root / "tools"),
                str(Path.cwd()),
                str(Path.home()),
            ]
        return self


# ============================================================================
# 安全配置
# ============================================================================

class SecurityConfig(BaseModel):
    """安全配置"""
    model_config = ConfigDict(extra="ignore")

    enabled: bool = Field(
        default=True,
        description="是否启用安全验证"
    )
    allowed_directories: List[str] = Field(
        default_factory=list,
        description="允许访问的根目录"
    )
    forbidden_patterns: List[str] = Field(
        default_factory=lambda: [
            ".env", ".password", ".secret", ".key",
            "id_rsa", "credentials.json"
        ],
        description="禁止访问的文件模式"
    )
    forbidden_delete_patterns: List[str] = Field(
        default_factory=lambda: [
            ".env", ".password", ".secret", ".key", "id_rsa", "credentials.json",
            "config.py", "config.toml", ".git", "core/restarter_manager/restarter.py", "agent.py"
        ],
        description="禁止删除的文件/目录"
    )
    dangerous_commands: List[str] = Field(
        default_factory=lambda: [
            "rm -rf /", "rm -rf /*", "mkfs", "dd if=/dev/zero of=/dev/sda",
            "format", "del /f /s /q", "rmdir /s /q", "rm -rf",
            "cipher /w:", "shutdown", "sysprep", ":(){ :|:& };:"
        ],
        description="危险命令黑名单"
    )


# ============================================================================
# 日志配置
# ============================================================================

class LogThirdPartyConfig(BaseModel):
    """第三方库日志级别配置"""
    model_config = ConfigDict(extra="ignore")

    httpx: str = Field(default="WARNING")
    httpcore: str = Field(default="WARNING")
    langchain: str = Field(default="WARNING")
    openai: str = Field(default="WARNING")
    anthropic: str = Field(default="WARNING")
    urllib3: str = Field(default="WARNING")
    litellm: str = Field(default="WARNING")
    rich: str = Field(default="WARNING")


class LogConfig(BaseModel):
    """日志系统配置"""
    model_config = ConfigDict(extra="ignore")

    level: str = Field(
        default="INFO",
        description="日志级别"
    )
    format: str = Field(
        default="%(asctime)s | %(levelname)-8s | %(message)s",
        description="日志格式"
    )
    date_format: str = Field(
        default="%Y-%m-%d %H:%M:%S",
        description="日期时间格式"
    )
    file_enabled: bool = Field(
        default=False,
        description="是否写入文件"
    )
    file_path: str = Field(
        default="logs/agent.log",
        description="日志文件路径"
    )
    max_file_size: int = Field(
        default=10485760,
        ge=0,
        description="最大日志文件大小（字节）"
    )
    backup_count: int = Field(
        default=5,
        ge=0,
        description="保留的日志文件数量"
    )
    detailed_traceback: bool = Field(
        default=False,
        description="是否启用详细错误堆栈"
    )
    third_party: LogThirdPartyConfig = Field(
        default_factory=LogThirdPartyConfig,
        description="第三方库日志级别"
    )

    @field_validator("level")
    @classmethod
    def validate_level(cls, v: str) -> str:
        """验证日志级别"""
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        upper = v.upper()
        if upper not in valid_levels:
            raise ValueError(f"Invalid log level: {v}. Must be one of {valid_levels}")
        return upper


# ============================================================================
# 网络配置
# ============================================================================

class NetworkConfig(BaseModel):
    """网络请求配置"""
    model_config = ConfigDict(extra="ignore")

    timeout: int = Field(
        default=30,
        gt=0,
        description="请求超时时间（秒）"
    )
    user_agent: str = Field(
        default="Mozilla/5.0 (compatible; SelfEvolvingAgent/1.0)",
        description="HTTP User-Agent"
    )
    max_retries: int = Field(
        default=3,
        ge=0,
        description="最大重试次数"
    )
    retry_delay: float = Field(
        default=1.0,
        ge=0,
        description="重试延迟（秒）"
    )
    verify_ssl: bool = Field(
        default=True,
        description="是否验证 SSL 证书"
    )
    proxy_enabled: bool = Field(
        default=False,
        description="是否启用 HTTP/HTTPS 代理"
    )
    proxy_url: str = Field(
        default="",
        description="代理服务器地址，例如 http://127.0.0.1:7890"
    )

    @field_validator("proxy_url")
    @classmethod
    def validate_proxy_url(cls, v: str) -> str:
        """验证代理地址。"""
        value = str(v or "").strip()
        if not value:
            return ""
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(
                "network.proxy_url must be an http(s) URL, "
                "for example http://127.0.0.1:7890"
            )
        return value

    @model_validator(mode="after")
    def validate_proxy_settings(self) -> "NetworkConfig":
        """启用代理时必须提供代理地址。"""
        if self.proxy_enabled and not self.proxy_url:
            raise ValueError("network.proxy_url is required when network.proxy_enabled is true")
        return self


# ============================================================================
# 进化引擎配置
# ============================================================================

class ChatDatasetCaptureConfig(BaseModel):
    """chat 对话采样为进化数据的配置。"""
    model_config = ConfigDict(extra="ignore")

    enabled: bool = Field(default=True, description="是否启用 chat 数据采集")
    source_modes: List[str] = Field(
        default_factory=lambda: ["chat"],
        description="允许采样的 Agent 模式",
    )
    auto_capture: bool = Field(default=True, description="是否静默自动采样候选片段")
    segmentation_strategy: str = Field(
        default="task_contiguous",
        description="对话分段策略",
    )
    min_turns: int = Field(default=2, ge=1, description="候选片段最少轮数")
    max_turns: int = Field(default=12, ge=1, description="候选片段最多轮数")
    require_tool_call_or_analysis_or_conclusion: bool = Field(
        default=True,
        description="是否要求工具/分析/结论信号至少满足其一",
    )
    exclude_pure_chitchat: bool = Field(default=True, description="是否排除纯闲聊")
    candidate_dir: str = Field(
        default="workspace/evaluation/chat_candidates",
        description="候选片段原始文件目录",
    )
    review_queue_path: str = Field(
        default="workspace/evaluation/chat_review_queue.jsonl",
        description="候选审核队列索引路径",
    )
    approved_raw_dir: str = Field(
        default="workspace/evaluation/chat_approved/raw",
        description="已通过原始片段目录",
    )
    approved_jsonl_path: str = Field(
        default="workspace/evaluation/datasets/chat_reviewed_multiturn.jsonl",
        description="审核通过后的结构化数据集 JSONL 路径",
    )
    rejected_log_path: str = Field(
        default="workspace/evaluation/chat_rejected.jsonl",
        description="被拒绝候选的审计日志路径",
    )

    @field_validator("source_modes")
    @classmethod
    def validate_source_modes(cls, v: List[str]) -> List[str]:
        cleaned: List[str] = []
        for item in v or []:
            mode = str(item or "").strip().lower()
            if not mode:
                continue
            if mode not in VALID_AGENT_MODES:
                raise ValueError(f"source mode must be one of: {', '.join(VALID_AGENT_MODES)}")
            if mode not in cleaned:
                cleaned.append(mode)
        return cleaned or ["chat"]

    @field_validator("segmentation_strategy")
    @classmethod
    def validate_segmentation_strategy(cls, v: str) -> str:
        value = (v or "task_contiguous").strip().lower()
        if value not in {"task_contiguous"}:
            raise ValueError("segmentation_strategy must be task_contiguous")
        return value

    @model_validator(mode="after")
    def validate_turn_window(self) -> "ChatDatasetCaptureConfig":
        if self.max_turns < self.min_turns:
            raise ValueError("max_turns must be >= min_turns")
        return self

class EvolutionConfig(BaseModel):
    """进化引擎配置"""
    model_config = ConfigDict(extra="ignore")

    enabled: bool = Field(
        default=True,
        description="是否启用自动进化"
    )
    intake_mode: str = Field(
        default="manual_review",
        description="Library 引入模式：manual_review 或 auto"
    )
    config_path: str = Field(
        default="workspace/evolution_config.json",
        description="进化配置路径"
    )
    archive_dir: str = Field(
        default="workspace/archives",
        description="归档目录"
    )
    backup_dir: str = Field(
        default="backups",
        description="备份目录"
    )
    test_gate_enabled: bool = Field(
        default=True,
        description="是否在重启前运行测试"
    )
    test_gate_timeout: int = Field(
        default=120,
        gt=0,
        description="进化测试超时（秒）"
    )
    test_command: str = Field(
        default="pytest tests/ -v --tb=short -q",
        description="测试命令"
    )
    # ── 熵减进化流程配置 ──
    proposals_dir: str = Field(
        default="workspace/evolution/proposals",
        description="进化提案存储目录"
    )
    audit_log_path: str = Field(
        default="workspace/evolution/audit.jsonl",
        description="进化审计日志路径（JSONL 格式）"
    )
    auto_check_approved: bool = Field(
        default=True,
        description="Agent 苏醒时是否自动检查已审批提案"
    )
    allowed_target_dirs: List[str] = Field(
        default_factory=lambda: ["workspace/prompts/", "tests/harness_safe_modify_probe.py"],
        description="允许进化修改的目录或文件白名单"
    )
    chat_dataset: ChatDatasetCaptureConfig = Field(
        default_factory=ChatDatasetCaptureConfig,
        description="chat 对话数据采样配置"
    )

    @field_validator("intake_mode")
    @classmethod
    def validate_intake_mode(cls, v: str) -> str:
        value = (v or "manual_review").strip().lower()
        if value not in {"manual_review", "auto"}:
            raise ValueError("intake_mode must be manual_review or auto")
        return value


# ============================================================================
# 记忆系统配置
# ============================================================================

class MemoryConfig(BaseModel):
    """记忆系统配置"""
    model_config = ConfigDict(extra="ignore")

    storage_dir: str = Field(
        default="workspace/memory",
        description="记忆存储目录"
    )
    memory_file: str = Field(
        default="memory.json",
        description="记忆文件名称"
    )
    archive_dir: str = Field(
        default="workspace/memory/archives",
        description="归档目录"
    )
    max_entries: int = Field(
        default=1000,
        gt=0,
        description="最大记忆条目数"
    )
    history_persistence: bool = Field(default=True, description="是否持久化会话历史")
    semantic_memory_enabled: bool = Field(default=False, description="是否启用语义记忆")
    llm_extraction_enabled: bool = Field(default=False, description="是否启用 LLM 记忆提取")
    llm_summary_enabled: bool = Field(default=False, description="是否启用 LLM 记忆摘要")


class MentalModelConfig(BaseModel):
    """可信操作员配置控制的心智模型功能。"""

    model_config = ConfigDict(extra="ignore")
    enabled: bool = Field(default=False, description="是否启用心智模型")


class RuntimeStatusConfig(BaseModel):
    """回合运行时状态栏（预算/进度追加）功能开关。"""

    model_config = ConfigDict(extra="ignore")
    enabled: bool = Field(default=True, description="是否启用运行时状态通道")
    inject_into_model: bool = Field(default=True, description="是否注入模型可见上下文")
    show_in_status_rail: bool = Field(default=True, description="是否在前端状态栏展示")


class WorkflowSessionScopeV3Config(BaseModel):
    """Workflow candidate-session rollout controlled by trusted operator config."""

    model_config = ConfigDict(extra="ignore")
    hypothesis_design: Literal["off", "shadow", "on"] = Field(
        default="shadow",
        description="假说设计会话作用域模式：off / shadow / on",
    )


class ResearchKnowledgeSideflowConfig(BaseModel):
    """知识侧流程 rollout 模式，由可信操作员配置控制（默认 off，安全）。

    - ``off``：现状行为——新建正式 Run 仍按 2.1.0 默认定义创建，知识命令
      offer 在快照层隐藏。
    - ``shadow``：新建 Run 仍走 2.1.0，但旧链每次创建搜集 run /
      collection_request 时同步生成 shadow 知识 invocation 对照记录（不驱动
      父流程、不建 child Run、不写知识包）。
    - ``on``：新建正式 Run 使用注册的主流程 3.0.0 定义（知识搜集已移出主
      链）；历史 2.1.0 Run 永远按注册表钉住的旧定义解释。
    """

    model_config = ConfigDict(extra="ignore")
    mode: Literal["off", "shadow", "on"] = Field(
        default="off",
        description="知识侧流程 rollout 模式：off / shadow / on",
    )


DEFAULT_RESEARCH_BLOCKING_FANOUT_WAIT = False


class ResearchConfig(BaseModel):
    """研究工作流（research workflow）配置。"""

    model_config = ConfigDict(extra="ignore")
    knowledge_sideflow: ResearchKnowledgeSideflowConfig = Field(
        default_factory=ResearchKnowledgeSideflowConfig,
        description="知识侧流程 rollout 配置",
    )
    blocking_fanout_wait: bool = Field(
        default=DEFAULT_RESEARCH_BLOCKING_FANOUT_WAIT,
        description=(
            "hypothesis_design 候选 fan-out 是否回到旧同步语义：在编排线程内"
            "阻塞等待全部候选终态后再聚合（仅作为回滚开关保留一个版本）。"
            "缺省 false：启动候选后立即返回 pending，由 durable requeue 驱动。"
        ),
    )

    @field_validator("blocking_fanout_wait", mode="before")
    @classmethod
    def _fallback_invalid_blocking_fanout_wait(cls, value: Any) -> bool:
        # 非法值（None/字符串/数字）不阻断启动，统一回退缺省（非阻塞）。
        if isinstance(value, bool):
            return value
        return DEFAULT_RESEARCH_BLOCKING_FANOUT_WAIT

    challenge_meeting_per_call_budget_ms: Optional[int] = Field(
        default=None,
        description=(
            "挑战杯会议讲者单次调用的围栏（毫秒）。留空（None）：先回落环境变量"
            " VIBELUTION_CHALLENGE_MEETING_PER_CALL_BUDGET_MS，再回落 receipt"
            " 推导。配置时必须等于治理上限（PER_CALL_MAX_MS，当前 800000）；"
            "越域值在启动自检与会议围栏派生时 fail-loud 拒绝。"
        ),
    )


class SupervisedEvolutionFeatureConfig(BaseModel):
    """可信操作员配置控制的监督进化功能族。"""

    model_config = ConfigDict(extra="ignore")
    enabled: bool = Field(default=False, description="是否启用监督进化")
    mental_model_enabled: bool = Field(default=False, description="是否允许监督运行使用心智模型")
    compression_enabled: bool = Field(default=False, description="是否允许监督运行使用上下文压缩")
    memory_update_enabled: bool = Field(default=False, description="是否允许监督运行更新记忆")


# ============================================================================
# 策略系统配置
# ============================================================================

class StrategyConfig(BaseModel):
    """策略系统配置"""
    model_config = ConfigDict(extra="ignore")

    data_dir: str = Field(
        default="workspace/strategy",
        description="策略数据目录"
    )
    exploration_rate: float = Field(
        default=0.2,
        ge=0.0,
        le=1.0,
        description="探索率"
    )
    learning_enabled: bool = Field(
        default=True,
        description="是否启用策略学习"
    )
    learning_data_path: str = Field(
        default="workspace/strategy/learner_data.json",
        description="学习数据存储路径"
    )


# ============================================================================
# 提示词管理器配置
# ============================================================================

class SectionConfig(BaseModel):
    """单个提示词章节配置

    每个章节对应一个 Markdown 文件，通过 [[prompt.sections]] 表格在 config.toml 中定义。
    动态章节（ENV_INFO、MEMORY 等）不需要在此定义，由代码内置注册。
    """
    model_config = ConfigDict(extra="ignore")

    name: str = Field(
        ...,
        description="章节唯一标识 (SOUL, SPEC, MY_RULES 等)"
    )
    path: str = Field(
        ...,
        description="Markdown 文件路径（相对于项目根目录）"
    )
    priority: int = Field(
        default=50,
        description="排序优先级，数字越小越靠前"
    )
    required: bool = Field(
        default=False,
        description="是否为必选章节（不可被 exclude 移除）"
    )
    cache_break: bool = Field(
        default=False,
        description="是否每轮重新计算（动态章节设为 true）"
    )
    description: str = Field(
        default="",
        description="章节描述"
    )


class PromptConfig(BaseModel):
    """提示词管理器配置"""
    model_config = ConfigDict(extra="ignore")

    default_components: List[str] = Field(
        default=["SOUL", "SPEC", "CODEBASE_MAP", "GIT_MEMORY", "RUNTIME_LOG_INDEX", "DELEGATION_RULES", "CONFIG_AWARENESS", "LANGUAGE_AWARENESS", "GIT_RULES", "MEMORY", "ENV_INFO"],
        description="默认拼装的组件列表（静态章节 + 内置动态章节）"
    )
    sections: List[SectionConfig] = Field(
        default_factory=list,
        description="静态章节定义列表（对应 TOML [[prompt.sections]] 表格）"
    )


# ============================================================================
# 代码分析配置
# ============================================================================

class AnalysisConfig(BaseModel):
    """代码分析配置"""
    model_config = ConfigDict(extra="ignore")

    data_dir: str = Field(
        default="workspace/analytics",
        description="分析数据目录"
    )
    feedback_dir: str = Field(
        default="workspace/feedback",
        description="反馈数据目录"
    )
    knowledge_graph_path: str = Field(
        default="workspace/knowledge_graph.json",
        description="知识图谱存储路径"
    )
    pattern_library_path: str = Field(
        default="workspace/pattern_library.json",
        description="模式库存储路径"
    )


# ============================================================================
# CLI UI 配置
# ============================================================================

class WorkbenchThemeConfig(BaseModel):
    """Web workbench theme configuration."""
    model_config = ConfigDict(extra="ignore")

    background_image_path: str = Field(
        default="",
        description="工作台背景图片的安全相对路径"
    )
    background_readability: str = Field(
        default="standard",
        description="工作台背景图片可读性保护强度（soft、standard、strong）",
    )

    @field_validator("background_image_path")
    @classmethod
    def validate_background_image_path(cls, value: str) -> str:
        return str(value or "").strip().replace("\\", "/")

    @field_validator("background_readability")
    @classmethod
    def validate_background_readability(cls, value: str) -> str:
        normalized = str(value or "standard").strip().lower()
        if normalized not in {"soft", "standard", "strong"}:
            return "standard"
        return normalized


class UIConfig(BaseModel):
    """CLI UI 配置"""
    model_config = ConfigDict(extra="ignore")

    language: str = Field(
        default="zh",
        description="界面语言（zh 或 en）"
    )
    theme: str = Field(
        default="lobster",
        description="主题名称"
    )
    max_log_entries: int = Field(
        default=100,
        gt=0,
        description="日志面板最大条目数"
    )
    refresh_rate: int = Field(
        default=4,
        gt=0,
        description="实时刷新频率"
    )
    show_ascii_art: bool = Field(
        default=True,
        description="是否显示 ASCII Art"
    )
    show_welcome: bool = Field(
        default=True,
        description="是否显示欢迎面板"
    )
    workbench_theme: WorkbenchThemeConfig = Field(
        default_factory=WorkbenchThemeConfig,
        description="Web 工作台主题配置"
    )


# ============================================================================
# 响应解析器配置
# ============================================================================

class ParserConfig(BaseModel):
    """响应解析器配置"""
    model_config = ConfigDict(extra="ignore")

    strip_tags: List[str] = Field(
        default_factory=lambda: [
            "<think>",  # 必须放最前面：先去除 <think>...</think>，再去除 <thinking>（顺序重要）
            "tool_call", "invoke", "skill",
            "thinking", "state_memory",
            "active_rules", "active_components",
        ],
        description="解析时需要去除的 XML 标签名列表"
    )
    strip_thinking_alias: bool = Field(
        default=True,
        description="是否去除 <think>...</think> 格式的思考标签"
    )


# ============================================================================
# 调试配置
# ============================================================================

class DebugConfig(BaseModel):
    """调试配置"""
    model_config = ConfigDict(extra="ignore")

    enabled: bool = Field(
        default=False,
        description="是否启用调试模式"
    )
    verbose: bool = Field(
        default=False,
        description="是否打印详细日志"
    )
    trace_llm: bool = Field(
        default=False,
        description="是否跟踪 LLM 调用"
    )
    trace_tools: bool = Field(
        default=False,
        description="是否跟踪工具调用"
    )
    track_token_usage: bool = Field(
        default=True,
        description="Token 使用统计"
    )


# ============================================================================
# 运行时基线配置
# ============================================================================

class RuntimeConfig(BaseModel):
    """运行时基线与启动前检查配置"""
    model_config = ConfigDict(extra="ignore")

    profile: str = Field(
        default="",
        description="稳定运行档案：safe_local / safe_remote / debug / ci"
    )
    preflight_doctor: bool = Field(
        default=True,
        description="启动前是否执行 doctor 自检"
    )
    require_venv: bool = Field(
        default=True,
        description="是否要求使用项目 .venv 解释器"
    )

    @field_validator("profile")
    @classmethod
    def normalize_profile(cls, v: str) -> str:
        return (v or "").strip().lower()


class WorkbenchConfig(BaseModel):
    """本地 Web 工作台启动配置。"""
    model_config = ConfigDict(extra="ignore")

    backend_port: int = Field(default=8000, ge=1, le=65535, description="后端服务端口")
    frontend_port: int = Field(default=5173, ge=1, le=65535, description="前端开发服务端口")
    window_mode: str = Field(default="fullscreen", description="工作台窗口模式：windowed / fullscreen")
    window_size: str = Field(default="auto", description="工作台窗口化启动尺寸：auto 或 WIDTHxHEIGHT")
    window_position: str = Field(
        default="auto",
        description="工作台窗口化启动位置：auto 或 X,Y（屏幕坐标，支持负值多显示器）",
    )

    @field_validator("window_mode")
    @classmethod
    def normalize_window_mode(cls, v: str) -> str:
        value = (v or "fullscreen").strip().lower()
        if value not in {"windowed", "fullscreen"}:
            raise ValueError("window_mode must be one of: windowed, fullscreen")
        return value

    @field_validator("window_size")
    @classmethod
    def normalize_window_size(cls, v: str) -> str:
        value = (v or "auto").strip().lower()
        if value == "auto":
            return value
        if "x" not in value:
            # Soft-normalize so stale/operator typos do not block AppConfig load.
            return "auto"
        width_text, height_text = value.split("x", 1)
        try:
            width = int(width_text)
            height = int(height_text)
        except ValueError:
            return "auto"
        # Floor matches launcher / window memory (usable workbench, not Edge 320x240 chrome).
        if not (960 <= width <= 7680 and 600 <= height <= 4320):
            return "auto"
        return f"{width}x{height}"

    @field_validator("window_position")
    @classmethod
    def normalize_window_position(cls, v: str) -> str:
        value = (v or "auto").strip().lower()
        if value == "auto":
            return value
        if "," not in value:
            return "auto"
        x_text, y_text = value.split(",", 1)
        try:
            x = int(x_text.strip())
            y = int(y_text.strip())
        except ValueError:
            return "auto"
        # Multi-monitor range; reject extreme sentinels that open fully off-screen.
        if not (-8000 <= x <= 8000 and -8000 <= y <= 8000):
            return "auto"
        return f"{x},{y}"


# ============================================================================
# 宠物系统配置
# ============================================================================

class PetConfig(BaseModel):
    """宠物系统主配置"""
    model_config = ConfigDict(extra="ignore")

    enabled: bool = Field(default=False, description="是否启用宠物系统")
    name: str = Field(default="虾宝", description="宠物名称")
    auto_save: bool = Field(default=True, description="自动保存")
    save_interval: int = Field(default=60, description="自动保存间隔(秒)")


class GeneConfig(BaseModel):
    """基因系统配置"""
    model_config = ConfigDict(extra="ignore")

    inherit_from_model: bool = Field(default=True, description="从模型继承基因特征")
    context_window_factor: float = Field(default=0.001, description="上下文窗口→寿命因子")


class HeartConfig(BaseModel):
    """心跳系统配置"""
    model_config = ConfigDict(extra="ignore")

    enabled: bool = Field(default=True, description="启用心跳可视化")
    active_rate: float = Field(default=2.0, description="活跃时心跳频率(Hz)")
    idle_rate: float = Field(default=0.5, description="空闲时心跳频率(Hz)")
    cooldown_time: int = Field(default=5, description="心跳冷却时间(秒)")


class DreamConfig(BaseModel):
    """梦境系统配置"""
    model_config = ConfigDict(extra="ignore")

    enabled: bool = Field(default=True, description="启用梦境系统")
    compression_triggers_dream: bool = Field(default=True, description="压缩时触发梦境")
    dream_duration: int = Field(default=3, description="梦境持续时间(秒)")
    keep_key_memory_ratio: float = Field(default=0.7, description="梦境中保留关键记忆比例")


class PersonalityConfig(BaseModel):
    """性格系统配置"""
    model_config = ConfigDict(extra="ignore")

    enabled: bool = Field(default=True, description="启用性格养成")
    learning_window: int = Field(default=100, description="学习窗口(操作次数)")
    trait_change_rate: float = Field(default=0.05, description="性格变化率")


class HungerConfig(BaseModel):
    """饥饿系统配置"""
    model_config = ConfigDict(extra="ignore")

    enabled: bool = Field(default=True, description="启用饥饿系统")
    food_per_meal: float = Field(default=0.1, description="每次饭量占上下文比例")
    hunger_decay_rate: float = Field(default=1.0, description="饱食度衰减率")
    mood_decay_rate: float = Field(default=0.5, description="心情衰减率")
    auto_feed_threshold: int = Field(default=1000, description="自动投喂阈值(tokens)")


class DiaryConfig(BaseModel):
    """日记系统配置"""
    model_config = ConfigDict(extra="ignore")

    enabled: bool = Field(default=True, description="启用成长日记")
    max_entries: int = Field(default=365, description="最大日记条目数")
    auto_summarize: bool = Field(default=True, description="自动生成摘要")
    sentiment_analysis: bool = Field(default=True, description="情感分析")


class SocialConfig(BaseModel):
    """社交系统配置"""
    model_config = ConfigDict(extra="ignore")

    enabled: bool = Field(default=True, description="启用同伴社交")
    track_other_models: bool = Field(default=True, description="跟踪其他模型")
    friendship_gain_rate: float = Field(default=1.0, description="友谊增长速度")
    max_friends: int = Field(default=10, description="最大好友数")


class HealthConfig(BaseModel):
    """健康系统配置"""
    model_config = ConfigDict(extra="ignore")

    enabled: bool = Field(default=True, description="启用健康体检")
    check_interval: int = Field(default=30, description="健康检查间隔(秒)")
    response_time_weight: float = Field(default=0.3, description="响应时间权重")
    error_rate_weight: float = Field(default=0.4, description="错误率权重")
    efficiency_weight: float = Field(default=0.3, description="效率权重")


class SkinConfig(BaseModel):
    """装扮系统配置"""
    model_config = ConfigDict(extra="ignore")

    enabled: bool = Field(default=True, description="启用装扮系统")
    unlock_by_achievement: bool = Field(default=True, description="通过成就解锁皮肤")


class SoundConfig(BaseModel):
    """声音系统配置"""
    model_config = ConfigDict(extra="ignore")

    enabled: bool = Field(default=True, description="启用情绪声音")
    volume: float = Field(default=0.5, description="音量(0-1)")
    mood_sounds: bool = Field(default=True, description="心情声音")
    action_sounds: bool = Field(default=True, description="动作声音")


# ============================================================================
# 主配置类
# ============================================================================

class AppConfig(BaseModel):
    """
    应用主配置类

    整合所有子配置模块，提供统一的配置管理接口。

    Example:
        # 创建默认配置
        config = AppConfig()

        # 从 TOML 加载（路径可通过 VIBELUTION_CONFIG_PATH/VIBELUTION_CONFIG_HOME 指定）
        config = AppConfig.from_toml("path/to/operator/config.toml")

        # 访问配置
        config.llm.get_profile(role="primary").model = "gpt-4"
        print(config.llm.get_profile(role="primary").temperature)
    """
    model_config = ConfigDict(extra="ignore")

    llm: LLMConfig = Field(default_factory=LLMConfig)
    avatar: AvatarConfig = Field(default_factory=AvatarConfig)
    user_profile: UserProfileConfig = Field(default_factory=UserProfileConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    web_chat: WebChatConfig = Field(default_factory=WebChatConfig)
    session_catalog: SessionCatalogConfig = Field(
        default_factory=SessionCatalogConfig
    )
    external_agent_gateway: ExternalAgentGatewayConfig = Field(
        default_factory=ExternalAgentGatewayConfig
    )
    context_compression: ContextCompressionConfig = Field(
        default_factory=ContextCompressionConfig
    )
    mental_model: MentalModelConfig = Field(default_factory=MentalModelConfig)
    runtime_status: RuntimeStatusConfig = Field(default_factory=RuntimeStatusConfig)
    workflow_session_scope_v3: WorkflowSessionScopeV3Config = Field(
        default_factory=WorkflowSessionScopeV3Config
    )
    research: ResearchConfig = Field(default_factory=ResearchConfig)
    supervised_evolution: SupervisedEvolutionFeatureConfig = Field(
        default_factory=SupervisedEvolutionFeatureConfig
    )
    tools: ToolConfig = Field(default_factory=ToolConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    log: LogConfig = Field(default_factory=LogConfig)
    network: NetworkConfig = Field(default_factory=NetworkConfig)
    evolution: EvolutionConfig = Field(default_factory=EvolutionConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    strategy: StrategyConfig = Field(default_factory=StrategyConfig)
    analysis: AnalysisConfig = Field(default_factory=AnalysisConfig)
    ui: UIConfig = Field(default_factory=UIConfig)
    parser: ParserConfig = Field(default_factory=ParserConfig)
    prompt: PromptConfig = Field(default_factory=PromptConfig)
    debug: DebugConfig = Field(default_factory=DebugConfig)
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    workbench: WorkbenchConfig = Field(default_factory=WorkbenchConfig)

    # 宠物系统配置
    pet: PetConfig = Field(default_factory=PetConfig)
    pet_gene: GeneConfig = Field(default_factory=GeneConfig)
    pet_heart: HeartConfig = Field(default_factory=HeartConfig)
    pet_dream: DreamConfig = Field(default_factory=DreamConfig)
    pet_personality: PersonalityConfig = Field(default_factory=PersonalityConfig)
    pet_hunger: HungerConfig = Field(default_factory=HungerConfig)
    pet_diary: DiaryConfig = Field(default_factory=DiaryConfig)
    pet_social: SocialConfig = Field(default_factory=SocialConfig)
    pet_health: HealthConfig = Field(default_factory=HealthConfig)
    pet_skin: SkinConfig = Field(default_factory=SkinConfig)
    pet_sound: SoundConfig = Field(default_factory=SoundConfig)

    @computed_field
    @property
    def workspace_path(self) -> Path:
        """获取工作区的绝对路径"""
        project_root = Path(__file__).parent.parent
        return project_root / self.agent.workspace

    @computed_field
    @property
    def effective_api_base(self) -> Optional[str]:
        primary = self.llm.get_profile(role="primary")
        return self.llm.get_provider(primary.provider_id).base_url

    def model_dump_simple(self) -> dict:
        """
        简化的字典导出（用于日志和调试）

        Returns:
            包含主要配置的字典
        """
        primary = self.llm.get_profile(role="primary")
        provider = self.llm.get_provider(primary.provider_id)
        return {
            "llm": {
                "provider": provider.kind,
                "model_name": primary.model,
                "temperature": primary.temperature,
                "max_tokens": primary.max_output_tokens,
            },
            "agent": {
                "name": self.agent.name,
                "awake_interval": self.agent.awake_interval,
                "max_iterations": self.agent.max_iterations,
            },
            "web_chat": {
                "max_continuation_turns": self.web_chat.max_continuation_turns,
            },
            "compression": {
                "enabled": self.context_compression.enabled,
                "max_token_limit": self.context_compression.max_token_limit,
            },
            "log_level": self.log.level,
        }

    def get_api_key_source_label(self) -> str:
        """返回当前 API Key 的粗粒度来源标签。"""
        return self.llm.get_api_key_source_label_for_profile(role="primary")

    def diagnose_config(self) -> Dict[str, Any]:
        """生成配置健康摘要，供 prompt / doctor 等感知层使用。"""
        warnings: List[str] = []
        blocking_issues: List[str] = []
        suggested_actions: List[str] = []

        primary = self.llm.get_profile(role="primary")
        provider_cfg = self.llm.get_provider(primary.provider_id)
        provider = provider_cfg.kind
        profile = self.runtime.profile or "(none)"
        api_key_source = self.get_api_key_source_label()
        has_api_key = bool(self.get_api_key())
        llm_tool_names, tool_surface_error = _discover_llm_facing_tool_names()
        effective_shell_tool = "cli_tool" if "cli_tool" in llm_tool_names else ""

        if provider != "local" and not has_api_key:
            blocking_issues.append(f"{provider} provider 缺少可用 API Key")
            suggested_actions.append("设置对应 provider 的环境变量，或在 config.toml 中显式配置 api_key")

        if provider == "local" and not _is_local_base_url(provider_cfg.base_url):
            blocking_issues.append("local provider 指向了非本地 API base")
            suggested_actions.append("将 local provider 的 base_url 改为 localhost / 127.0.0.1 / ::1 或私有局域网地址")

        if provider != "local" and _is_local_base_url(provider_cfg.base_url):
            warnings.append(f"{provider} provider 使用了本地 API base")

        if "CONFIG_AWARENESS" not in self.prompt.default_components:
            warnings.append("prompt.default_components 未包含 CONFIG_AWARENESS")
            suggested_actions.append("将 CONFIG_AWARENESS 注册为默认 prompt 组件，并交由相关性门控按需展开")

        if "LANGUAGE_AWARENESS" not in self.prompt.default_components:
            warnings.append("prompt.default_components 未包含 LANGUAGE_AWARENESS")
            suggested_actions.append("将 LANGUAGE_AWARENESS 加入默认 prompt 组件，压制自然语言输出向英文漂移")

        if "MEMORY" not in self.prompt.default_components:
            warnings.append("prompt.default_components 未包含 MEMORY")
            suggested_actions.append("将 MEMORY 加入默认 prompt 组件，确保状态记忆与复盘约束进入当前轮提示词")

        if "RUNTIME_LOG_INDEX" not in self.prompt.default_components:
            warnings.append("prompt.default_components 未包含 RUNTIME_LOG_INDEX")
            suggested_actions.append("将 RUNTIME_LOG_INDEX 加入默认 prompt 组件，让 agent 感知最近运行现场日志索引")

        if not self.prompt.sections:
            warnings.append("未配置任何静态 prompt sections")
            suggested_actions.append("至少保留 SOUL / SPEC 两个静态章节")

        if profile == "safe_remote" and primary.connect_timeout > 20:
            warnings.append("safe_remote 档案下 connect_timeout 高于推荐值 20")

        if profile == "safe_local" and provider != "local":
            warnings.append("safe_local 档案下当前 provider 不是 local")

        if self.tools.search.max_results > 200:
            warnings.append("tools.search.max_results 较高，可能导致上下文噪声增加")

        if self.tools.shell.enabled:
            if effective_shell_tool:
                suggested_actions.append(
                    f"Shell 配置已启用；当前项目 LLM 工具面暴露 {effective_shell_tool} 作为实际 shell 入口"
                )
            elif tool_surface_error:
                warnings.append(f"无法探测当前项目 LLM 工具面：{tool_surface_error}")
            else:
                warnings.append("tools.shell.enabled=true，但当前项目 LLM 工具面未暴露 cli_tool")
                suggested_actions.append("按实际工具列表行动；不要仅凭 tools.shell.enabled 假设 shell 可调用")
        else:
            suggested_actions.append("Shell 配置已禁用；当前轮应优先使用结构化读写、搜索和测试工具")

        from core.llm import doctor_llm_profile

        for profile_id in self.llm.profiles.keys():
            report = doctor_llm_profile(self, str(profile_id))
            for item in report.errors:
                scoped = f"{report.profile_id}: {item}"
                if scoped not in blocking_issues:
                    blocking_issues.append(scoped)
            for item in report.warnings:
                scoped = f"{report.profile_id}: {item}"
                if scoped not in warnings:
                    warnings.append(scoped)

        if not suggested_actions and not warnings and not blocking_issues:
            suggested_actions.append("当前配置健康，可直接按当前基线继续运行")

        return {
            "identity": {
                "provider": provider,
                "provider_id": provider_cfg.provider_id,
                "profile_id": primary.profile_id,
                "model_name": primary.model,
                "api_base": provider_cfg.base_url,
                "runtime_profile": profile,
            },
            "sources": {
                "api_key": api_key_source,
                "prompt_sections": "config.toml",
                "runtime_profile": "config.toml" if self.runtime.profile else "default-or-kwargs",
            },
            "status": {
                "has_api_key": has_api_key,
                "prompt_sections_count": len(self.prompt.sections),
                "default_components_count": len(self.prompt.default_components),
            },
            "tool_surface": {
                "config_shell_enabled": self.tools.shell.enabled,
                "effective_shell_tool": effective_shell_tool,
                "llm_facing_tool_count": len(llm_tool_names),
                "probe_error": tool_surface_error,
            },
            "warnings": warnings,
            "blocking_issues": blocking_issues,
            "suggested_actions": suggested_actions,
        }

    def format_config_awareness_prompt(self) -> str:
        """格式化为 prompt section 文本。"""
        diagnosis = self.diagnose_config()
        identity = diagnosis["identity"]
        sources = diagnosis["sources"]
        status = diagnosis["status"]
        tool_surface = diagnosis.get("tool_surface") or {}

        lines = [
            "## 配置自感知",
            (
                f"- 当前身份: provider={identity['provider']} | "
                f"model={identity['model_name']} | profile={identity['runtime_profile']}"
            ),
            f"- API Base: {identity['api_base']}",
            (
                f"- 关键来源: api_key={sources['api_key']} | "
                f"prompt_sections={sources['prompt_sections']} | "
                f"runtime_profile={sources['runtime_profile']}"
            ),
            (
                f"- 当前状态: has_api_key={status['has_api_key']} | "
                f"prompt_sections={status['prompt_sections_count']} | "
                f"default_components={status['default_components_count']}"
            ),
            (
                "- 工具能力面: "
                f"config_shell_enabled={tool_surface.get('config_shell_enabled')} | "
                f"effective_shell_tool={tool_surface.get('effective_shell_tool') or 'none'} | "
                f"llm_facing_tools={tool_surface.get('llm_facing_tool_count', 0)}"
            ),
        ]

        if diagnosis["blocking_issues"]:
            lines.append("- 阻断问题:")
            for item in diagnosis["blocking_issues"][:3]:
                lines.append(f"  - {item}")

        if diagnosis["warnings"]:
            lines.append("- 风险提示:")
            for item in diagnosis["warnings"][:3]:
                lines.append(f"  - {item}")

        if diagnosis["suggested_actions"]:
            lines.append("- 建议动作:")
            for item in diagnosis["suggested_actions"][:3]:
                lines.append(f"  - {item}")

        return "\n".join(lines)

    def get_api_key(self) -> Optional[str]:
        """
        获取 API Key（优先从配置读取，其次环境变量）

        Returns:
            API Key，未设置返回 None
        """
        return self.llm.resolve_api_key_for_profile(role="primary")

    def get_api_key_for_profile(self, profile_id: Optional[str] = None, role: str = "primary") -> Optional[str]:
        """获取指定 profile/role 的 API Key，优先使用模型库级环境变量。"""
        return self.llm.resolve_api_key_for_profile(profile_id=profile_id, role=role)

    def set_api_key(self, api_key: str) -> None:
        """
        设置 API Key

        Args:
            api_key: API 密钥
        """
        self.llm.get_provider(role="primary").api_key = api_key

    def __repr__(self) -> str:
        primary = self.llm.get_profile(role="primary")
        provider = self.llm.get_provider(primary.provider_id)
        return (
            f"AppConfig(model={primary.model}, "
            f"provider={provider.kind}, "
            f"temperature={primary.temperature})"
        )


# ============================================================================
# 导出
# ============================================================================

__all__ = [
    # LLM 配置
    "LLMConfig",
    "LLMDiscoveryConfig",
    "ProviderConfig",
    "LLMProfile",
    "RetryPolicyConfig",
    # Agent 配置
    "AgentConfig",
    "AgentModesConfig",
    # 上下文压缩配置
    "ContextCompressionConfig",
    "CompressionLevelsConfig",
    "CompressionSummaryCharsConfig",
    "CompressionPreservationConfig",
    # 形象配置
    "AvatarConfig",
    # 工具配置
    "ToolConfig",
    "ToolsFileConfig",
    "ToolsShellConfig",
    "ToolsSearchConfig",
    "ToolsWebConfig",
    # 安全配置
    "SecurityConfig",
    # 日志配置
    "LogConfig",
    "LogThirdPartyConfig",
    # 网络配置
    "NetworkConfig",
    # 进化引擎配置
    "EvolutionConfig",
    "ChatDatasetCaptureConfig",
    # 记忆系统配置
    "MemoryConfig",
    # 策略系统配置
    "StrategyConfig",
    # 代码分析配置
    "AnalysisConfig",
    # 提示词管理器配置
    "PromptConfig",
    "SectionConfig",
    # UI 配置
    "UIConfig",
    "ParserConfig",
    # 调试配置
    "DebugConfig",
    # 工作台配置
    "WorkbenchConfig",
    # 主配置类
    "AppConfig",
]
