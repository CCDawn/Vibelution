"""
稳定运行时配置档案

将“稳定运行基线”收敛为几个明确的 profile，
避免每次启动都依赖手工拼装参数。
"""

from __future__ import annotations

import copy
import logging
from typing import TYPE_CHECKING, Any, Callable

from .llm_security import is_llm_local_network_base_url

if TYPE_CHECKING:
    from .models import AppConfig, ProviderConfig, LLMProfile


logger = logging.getLogger(__name__)

VALID_RUNTIME_PROFILES = {"", "safe_local", "safe_remote", "debug", "ci"}

_security_clamp_audit_sink: Callable[[list[dict[str, Any]]], None] | None = None


def set_security_clamp_audit_sink(
    sink: Callable[[list[dict[str, Any]]], None] | None,
) -> None:
    """Install (or clear) a sink receiving runtime profile security clamp events."""
    global _security_clamp_audit_sink
    _security_clamp_audit_sink = sink


def _redact_security_value(field: str, value: Any) -> Any:
    if field.endswith(("api_key", "api_key_env")) and isinstance(value, str) and value:
        return "***"
    return value


def _record_security_clamp_events(events: list[dict[str, Any]]) -> None:
    if not events:
        return
    logger.warning(
        "runtime profile security clamps re-applied after explicit overrides: %s",
        events,
    )
    sink = _security_clamp_audit_sink
    if sink is None:
        return
    try:
        sink(copy.deepcopy(events))
    except Exception:  # pragma: no cover - audit sink must never break config load
        logger.exception("runtime profile security clamp audit sink failed")


def _is_local_base_url(base_url: str) -> bool:
    return is_llm_local_network_base_url(base_url)


def _find_local_profile_id(config: "AppConfig") -> str | None:
    for profile_id, profile in config.llm.profiles.items():
        try:
            provider = config.llm.get_provider(profile.provider_id)
        except ValueError:
            continue
        if provider.kind == "local" or _is_local_base_url(provider.base_url):
            return profile_id
    return None


def _overlay_profile(target: "LLMProfile", source: "LLMProfile") -> None:
    for key, value in source.model_dump().items():
        if key == "profile_id":
            continue
        setattr(target, key, copy.deepcopy(value))


def _enforce_safe_local_security(config: "AppConfig") -> None:
    """强制 safe_local 的本地 provider 边界（provider 引用、地址、凭据、发现）。"""
    primary = config.llm.get_profile(role="primary")
    provider = config.llm.get_provider(primary.provider_id)
    if provider.kind != "local" or not _is_local_base_url(provider.base_url):
        local_template_id = _find_local_profile_id(config)
        if local_template_id and local_template_id != primary.profile_id:
            _overlay_profile(primary, config.llm.get_profile(local_template_id))
            provider = config.llm.get_provider(primary.provider_id)
    provider.kind = "local"
    if not _is_local_base_url(provider.base_url):
        provider.base_url = "http://localhost:11434/v1"
    provider.requires_api_key = False
    provider.api_key = ""
    provider.api_key_env = ""
    primary.discovery_enabled = False
    config.llm.discovery.enabled = False


def _safe_local_security_snapshot(config: "AppConfig") -> dict[str, Any]:
    primary = config.llm.get_profile(role="primary")
    provider = config.llm.get_provider(primary.provider_id)
    return {
        "llm.profiles.primary.provider_id": primary.provider_id,
        "llm.providers.<primary>.kind": provider.kind,
        "llm.providers.<primary>.base_url": provider.base_url,
        "llm.providers.<primary>.requires_api_key": provider.requires_api_key,
        "llm.providers.<primary>.api_key": provider.api_key,
        "llm.providers.<primary>.api_key_env": provider.api_key_env,
        "llm.profiles.primary.discovery_enabled": primary.discovery_enabled,
        "llm.discovery.enabled": config.llm.discovery.enabled,
    }


def apply_runtime_profile_security_clamps(config: "AppConfig") -> list[dict[str, Any]]:
    """在显式覆盖（env/kwargs）之后重施加不可绕过的安全钳位。

    返回被钳位字段的审计事件列表（redacted）。普通运行基线字段不在此列，
    操作者可用 env/kwargs 覆盖。目前只有 safe_local 定义安全钳位。
    """
    profile = (getattr(config.runtime, "profile", "") or "").strip().lower()
    if profile != "safe_local":
        return []

    before = _safe_local_security_snapshot(config)
    _enforce_safe_local_security(config)
    after = _safe_local_security_snapshot(config)

    events: list[dict[str, Any]] = []
    for field, before_value in before.items():
        after_value = after[field]
        if before_value == after_value:
            continue
        events.append(
            {
                "profile": profile,
                "field": field,
                "before": _redact_security_value(field, before_value),
                "after": _redact_security_value(field, after_value),
            }
        )
    _record_security_clamp_events(events)
    return events


def apply_runtime_profile(config: "AppConfig") -> "AppConfig":
    """根据 runtime.profile 对配置做受控覆写。

    该函数提供运行基线（温度、超时、迭代上限等），调用方应在显式覆盖
    （环境变量、kwargs）之前应用，使普通字段可被操作者显式覆盖；
    safe_local 的本地 provider 边界等安全字段由
    :func:`apply_runtime_profile_security_clamps` 在显式覆盖之后重施加。
    """
    profile = (getattr(config.runtime, "profile", "") or "").strip().lower()
    if not profile:
        return config

    if profile not in VALID_RUNTIME_PROFILES:
        raise ValueError(
            f"未知 runtime profile: {profile}。"
            f"可用值: {', '.join(sorted(p for p in VALID_RUNTIME_PROFILES if p))}"
        )

    if profile == "safe_local":
        primary = config.llm.get_profile(role="primary")
        local_template_id = _find_local_profile_id(config)
        if local_template_id and local_template_id != primary.profile_id:
            _overlay_profile(primary, config.llm.get_profile(local_template_id))
        _enforce_safe_local_security(config)
        primary = config.llm.get_profile(role="primary")
        primary.temperature = 0.1
        primary.timeout = 45
        primary.connect_timeout = 5
        config.agent.max_iterations = min(config.agent.max_iterations, 40)
        config.agent.awake_interval = min(config.agent.awake_interval, 30)
        config.context_compression.enabled = True
        config.context_compression.max_token_limit = min(
            config.context_compression.max_token_limit, 24576
        )
        config.runtime.preflight_doctor = True
        config.runtime.require_venv = True
        return config

    if profile == "safe_remote":
        primary = config.llm.get_profile(role="primary")
        primary.temperature = max(primary.temperature, 0.1)
        primary.timeout = max(primary.timeout, 120)
        primary.connect_timeout = min(primary.connect_timeout, 20)
        config.llm.discovery.enabled = True
        config.agent.max_iterations = min(config.agent.max_iterations, 200)
        config.agent.awake_interval = min(config.agent.awake_interval, 60)
        config.context_compression.enabled = True
        config.runtime.preflight_doctor = True
        config.runtime.require_venv = True
        return config

    if profile == "debug":
        config.debug.enabled = True
        config.debug.verbose = True
        config.debug.trace_llm = True
        config.debug.trace_tools = True
        config.log.level = "DEBUG"
        config.agent.max_iterations = min(config.agent.max_iterations, 20)
        config.agent.awake_interval = min(config.agent.awake_interval, 15)
        config.runtime.preflight_doctor = True
        return config

    if profile == "ci":
        config.debug.enabled = False
        config.debug.verbose = False
        config.debug.trace_llm = False
        config.debug.trace_tools = False
        config.log.level = "WARNING"
        primary = config.llm.get_profile(role="primary")
        primary.temperature = max(primary.temperature, 0.1)
        config.llm.discovery.enabled = False
        config.agent.max_iterations = min(config.agent.max_iterations, 5)
        config.agent.awake_interval = min(config.agent.awake_interval, 5)
        config.agent.auto_backup = False
        config.context_compression.enabled = False
        config.runtime.preflight_doctor = True
        config.runtime.require_venv = True
        return config

    return config
