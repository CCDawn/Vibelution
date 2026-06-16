"""Config workspace helpers for the web workbench."""

from __future__ import annotations

import copy
import ctypes
import hashlib
import os
import queue
import secrets
import subprocess
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

import config.public_config as public_config_module
from config import LLMProfile, ProviderConfig
from config.models import PROVIDER_API_KEY_ENV_ALIASES, _read_env_var, get_provider_api_key_env
from config.runtime_capabilities import (
    apply_model_capability_overrides,
    record_model_image_input_capability,
    strip_runtime_model_capability_fields,
)
from core.chat.chat_task_types import trim_lines
from core.llm import LLMInvocationContext, invoke_llm
from core.llm.protocol_resolver import resolve_model_protocol
from config.public_config import (
    CONFIG_PATH,
    UNCONFIGURED_MODEL_REF,
    _delete_user_env_var,
    _set_user_env_var,
    add_llm_model,
    apply_llm_model_preset,
    build_effective_config,
    delete_llm_model,
    inspect_public_config,
    list_llm_model_options,
    list_llm_model_preset_options,
    list_llm_provider_preset_options,
    load_public_config,
    preserve_secret_blanks,
    public_config_hash,
    save_public_config,
    update_llm_model,
    validate_llm_api_key_env,
    validate_llm_public_config,
)
from config.llm_security import validate_llm_provider_target
from config.settings import reload_config

from .config_editor_schema import build_editor_meta, build_editor_sections
from .git_status_service import validate_git_commit_message_prompt, with_git_config_defaults
from .i18n import resolve_language, text_for
from .model_capability_service import model_record_image_input_support
from .model_reference_service import ModelReferenceConflictError, assert_model_delete_safe
from .runtime_scene_service import record_runtime_scene_event
from .theme_background_service import theme_background_image_url
from .workbench_contract_service import get_workbench_contract


class ConfigConflictError(ValueError):
    """Raised when a saved config changed since the draft was loaded."""


_MISSING = object()


PROFILE_LABELS = {
    "primary": {"zh": "主智能体", "en": "Primary"},
    "mental_model": {"zh": "心智模型", "en": "Mental Model"},
    "subagent_worker": {"zh": "子代理执行", "en": "Subagent Worker"},
    "subagent_explorer": {"zh": "子代理探索", "en": "Subagent Explorer"},
    "supervised_baseline": {"zh": "监督基线", "en": "Supervised Baseline"},
    "supervised_candidate": {"zh": "监督候选", "en": "Supervised Candidate"},
    "research_broad": {"zh": "科研广搜", "en": "Research Broad Search"},
    "research_deep": {"zh": "科研深搜", "en": "Research Deep Search"},
    "research_review": {"zh": "科研审查", "en": "Research Review"},
    "research_themes": {"zh": "科研主题生成", "en": "Research Theme Generation"},
    "research_card": {"zh": "科研主题卡", "en": "Research Theme Card"},
    "compression": {"zh": "上下文压缩", "en": "Compression"},
}
_PENDING_SECRET_PREFIX = "pending-secret:"
_PENDING_API_KEY_SECRETS: dict[str, tuple[str, str]] = {}
_PENDING_CLEAR_ENVS: set[str] = set()
_MODEL_DISCOVERY_DEFAULT_TIMEOUT_SECONDS = 3.0
_MODEL_DISCOVERY_NEGATIVE_CACHE_TTL_SECONDS = 45.0
_MODEL_DISCOVERY_NEGATIVE_CACHE: dict[str, tuple[float, str, list[dict[str, Any]]]] = {}
_MODEL_DISCOVERY_CACHE_LOCK = threading.Lock()
_LLM_TEST_PROBE_TIMEOUT_GRACE_SECONDS = 0.5
_LLM_TEST_PROBE_WORKER_SLOTS = threading.BoundedSemaphore(2)


def _model_option_protocol_route_summary(option: dict[str, Any], details: dict[str, Any]) -> dict[str, Any]:
    provider_input = option.get("provider") if isinstance(option.get("provider"), dict) else {}
    try:
        provider = ProviderConfig.model_validate({
            **copy.deepcopy(provider_input),
            "provider_id": "__model_option_provider__",
        })
        profile = LLMProfile.model_validate({
            **copy.deepcopy(details),
            "profile_id": "__model_option_profile__",
            "provider_id": "__model_option_provider__",
            "model": str(option.get("model") or "").strip(),
        })
        route = resolve_model_protocol(
            profile,
            provider,
            model_entry={
                **copy.deepcopy(details),
                "model_id": str(option.get("model_id") or "").strip(),
            },
        )
        summary = route.log_summary()
        summary["compat"] = route.compat.to_log_dict()
        return summary
    except Exception as exc:
        return {
            "protocol": str(details.get("protocol") or option.get("protocol") or "").strip().lower(),
            "protocolSource": "unresolved",
            "providerApi": str(provider_input.get("api") or option.get("provider_api") or "").strip().lower().replace("_", "-"),
            "protocolWarnings": [trim_lines(str(exc), max_lines=2)],
            "compat": copy.deepcopy(details.get("compat", {})) if isinstance(details.get("compat"), dict) else {},
        }
_OPEN_ENVIRONMENT_TASK_NAME = r"\Vibelution\OpenEnvironmentVariables"
_ENVIRONMENT_WINDOW_TITLE_PARTS = ("环境变量", "Environment Variables")
_MODEL_DISCOVERY_ENDPOINTS = ("models", "v1/models")
_SW_RESTORE = 9
_SW_SHOW = 5
_HWND_TOPMOST = -1
_HWND_NOTOPMOST = -2
_SWP_NOSIZE = 0x0001
_SWP_NOMOVE = 0x0002
_SWP_SHOWWINDOW = 0x0040
_IMAGE_INPUT_PROBE_DATA_URL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)
_IMAGE_INPUT_UNSUPPORTED_PATTERNS = (
    "no endpoints found that support image input",
    "does not support image input",
    "doesn't support image input",
    "unsupported image",
    "unsupported content type",
    "vision is not supported",
    "image input is not supported",
    "does not support vision",
)

def _record_config_scene_event(
    phase: str,
    event_code: str,
    *,
    message: str = "",
    level: str = "info",
    outcome: str = "observed",
    fields: dict[str, Any] | None = None,
    lifecycle: bool = False,
) -> None:
    try:
        record_runtime_scene_event(
            "config",
            phase,
            event_code,
            message=message or event_code,
            level=level,
            outcome=outcome,
            fields=fields or {},
            lifecycle=lifecycle,
        )
    except Exception:
        return


def _normalize_llm_test_capability(capability: str | None) -> str:
    normalized = str(capability or "text").strip().lower()
    if normalized in {"", "text", "connection", "llm", "chat"}:
        return "text"
    if normalized in {"image", "image_input", "vision", "multimodal"}:
        return "image_input"
    raise ValueError(f"Unsupported LLM test capability: {capability}")


def _resolve_workspace_language(public_config: dict[str, Any]) -> str:
    return resolve_language(public_config.get("ui", {}).get("language", "zh"))


def _theme_background_path(public_config: dict[str, Any]) -> str:
    ui_config = public_config.get("ui", {}) if isinstance(public_config.get("ui"), dict) else {}
    workbench_theme = ui_config.get("workbench_theme", {}) if isinstance(ui_config.get("workbench_theme"), dict) else {}
    return str(workbench_theme.get("background_image_path") or "").strip().replace("\\", "/")


def _with_config_workspace_defaults(
    public_config: dict[str, Any],
    *,
    repair_stale_model_ref: bool = True,
) -> dict[str, Any]:
    payload = with_git_config_defaults(public_config, repair_stale_model_ref=repair_stale_model_ref)
    ui_config = payload.setdefault("ui", {})
    if not isinstance(ui_config, dict):
        payload["ui"] = ui_config = {}
    workbench_theme = ui_config.setdefault("workbench_theme", {})
    if not isinstance(workbench_theme, dict):
        ui_config["workbench_theme"] = workbench_theme = {}
    workbench_theme.setdefault("background_image_path", "")
    return payload


def _profile_label(profile_id: str, lang: str, profile: dict[str, Any] | None = None) -> str:
    configured_label = str((profile or {}).get("label", "") or "").strip() if isinstance(profile, dict) else ""
    if configured_label:
        return configured_label
    mapping = PROFILE_LABELS.get(str(profile_id).strip())
    if mapping:
        return text_for(lang, zh=mapping["zh"], en=mapping["en"])
    token = str(profile_id or "").strip().replace("_", " ")
    return token.title() if lang == "en" else token


def _config_sections(lang: str, editor_sections: list[dict[str, Any]] | None = None) -> list[dict[str, str]]:
    sections = [
        {
            "id": "overview",
            "title": text_for(lang, zh="配置源", en="Config Source"),
            "summary": text_for(
                lang,
                zh="当前生效网页入口与外部 operator config.toml 原始内容都在这里，避免再维护第二套页面。",
                en="The active web entry and external operator config.toml source live here so there is only one surface.",
            ),
        },
        {
            "id": "shell",
            "title": text_for(lang, zh="工作台默认项", en="Workbench Defaults"),
            "summary": text_for(
                lang,
                zh="语言、intake mode 和当前工作台默认项可以先在这里快速修改。",
                en="Language, intake mode, and current workbench defaults can be changed here.",
            ),
        },
        {
            "id": "models",
            "title": text_for(lang, zh="模型库", en="Model Library"),
            "summary": text_for(
                lang,
                zh="集中管理模型资产、服务商账号、密钥、能力检测和模型发现。",
                en="Manage model assets, provider accounts, keys, capability checks, and discovery in one place.",
            ),
        },
    ]
    for section in editor_sections or []:
        sections.append(
            {
                "id": str(section.get("id", "")),
                "title": str(section.get("title", "")),
                "summary": str(section.get("summary", "")),
            }
        )
    sections.extend(
        [
            {
                "id": "health-diagnostics",
                "title": text_for(lang, zh="健康诊断", en="Health Diagnostics"),
                "summary": text_for(
                    lang,
                    zh="只读整理日志 Helper、最近信号、Reset 清理建议和保护边界。",
                    en="Read-only log helpers, recent signals, Reset cleanup hints, and protected boundaries.",
                ),
            },
            {
                "id": "draft",
                "title": text_for(lang, zh="高级配置检查", en="Advanced Config Check"),
                "summary": text_for(
                    lang,
                    zh="结构化操作之外，还可以检查整份当前配置；保存时仍只写外部 operator config.toml。",
                    en="Beyond structured controls, check the full current config here while saving still writes only the external operator config.toml.",
                ),
            },
            {
                "id": "diagnostics",
                "title": text_for(lang, zh="诊断", en="Diagnostics"),
                "summary": text_for(
                    lang,
                    zh="阻塞问题、警告与保存冲突保护会在保存前保持可见。",
                    en="Blocking issues, warnings, and save-conflict protection remain visible before saving.",
                ),
            },
        ]
    )
    return sections


def _empty_draft_meta() -> dict[str, object]:
    return {
        "pending_api_keys": {},
        "pending_cleared_api_keys": [],
    }


def _register_pending_api_key(api_key_env: str, api_key: str) -> str:
    env_name = validate_llm_api_key_env(api_key_env, required=True, context="api_key_env")
    token = f"{_PENDING_SECRET_PREFIX}{secrets.token_urlsafe(24)}"
    _PENDING_API_KEY_SECRETS[token] = (env_name, str(api_key))
    return token


def _resolve_pending_api_key(env_name: str, token: object) -> str | None:
    env_name = validate_llm_api_key_env(env_name, required=True, context="api_key_env")
    value = str(token or "").strip()
    if not value.startswith(_PENDING_SECRET_PREFIX):
        return None
    stored = _PENDING_API_KEY_SECRETS.get(value)
    if not stored:
        return None
    stored_env, secret = stored
    if stored_env != env_name:
        return None
    return secret


def _drop_pending_api_key_token(token: object) -> None:
    value = str(token or "").strip()
    if value.startswith(_PENDING_SECRET_PREFIX):
        _PENDING_API_KEY_SECRETS.pop(value, None)


def _move_pending_api_key_token(token: object, old_env: str, new_env: str) -> None:
    value = str(token or "").strip()
    if not value.startswith(_PENDING_SECRET_PREFIX):
        return
    stored = _PENDING_API_KEY_SECRETS.get(value)
    if not stored:
        return
    stored_env, secret = stored
    if stored_env == old_env:
        _PENDING_API_KEY_SECRETS[value] = (new_env, secret)


def _normalize_draft_meta(meta: dict | None) -> dict[str, object]:
    payload = _empty_draft_meta()
    if not isinstance(meta, dict):
        return payload
    pending = meta.get("pending_api_keys", {})
    if isinstance(pending, dict):
        normalized_pending: dict[str, str] = {}
        for key, value in pending.items():
            env_name = str(key or "").strip()
            if not env_name or str(value) == "":
                continue
            try:
                validate_llm_api_key_env(env_name, required=True, context="api_key_env")
            except ValueError:
                continue
            if _resolve_pending_api_key(env_name, value) is None:
                continue
            normalized_pending[env_name] = str(value)
        payload["pending_api_keys"] = normalized_pending
    cleared = meta.get("pending_cleared_api_keys", [])
    if isinstance(cleared, list):
        normalized_cleared: list[str] = []
        for item in cleared:
            env_name = str(item or "").strip()
            if not env_name:
                continue
            try:
                env_name = validate_llm_api_key_env(env_name, required=True, context="api_key_env")
            except ValueError:
                continue
            if env_name in _PENDING_CLEAR_ENVS and env_name not in normalized_cleared:
                normalized_cleared.append(env_name)
        payload["pending_cleared_api_keys"] = normalized_cleared
    return payload


def _draft_meta_has_pending_changes(draft_meta: dict | None) -> bool:
    meta = _normalize_draft_meta(draft_meta)
    return bool(meta["pending_api_keys"] or meta["pending_cleared_api_keys"])


def _llm_test_config_scope(public_config: dict[str, Any], draft_meta: dict | None) -> str:
    try:
        persisted_hash = public_config_hash(_with_config_workspace_defaults(load_public_config()))
    except Exception:
        persisted_hash = ""
    draft_hash = public_config_hash(public_config)
    if persisted_hash and draft_hash == persisted_hash and not _draft_meta_has_pending_changes(draft_meta):
        return "saved"
    return "draft"


def _with_pending_api_key(meta: dict[str, object], api_key_env: str, api_key: str) -> dict[str, object]:
    payload = _normalize_draft_meta(meta)
    env_name = validate_llm_api_key_env(api_key_env, required=False, context="api_key_env")
    if not env_name:
        return payload
    pending = payload["pending_api_keys"]
    cleared = payload["pending_cleared_api_keys"]
    if isinstance(pending, dict):
        _drop_pending_api_key_token(pending.get(env_name))
        pending[env_name] = _register_pending_api_key(env_name, api_key)
    if isinstance(cleared, list):
        payload["pending_cleared_api_keys"] = [item for item in cleared if item != env_name]
        _PENDING_CLEAR_ENVS.discard(env_name)
    return payload


def _with_cleared_api_key(meta: dict[str, object], api_key_env: str) -> dict[str, object]:
    payload = _normalize_draft_meta(meta)
    env_name = validate_llm_api_key_env(api_key_env, required=False, context="api_key_env")
    if not env_name:
        return payload
    pending = payload["pending_api_keys"]
    cleared = payload["pending_cleared_api_keys"]
    if isinstance(pending, dict):
        _drop_pending_api_key_token(pending.pop(env_name, None))
    if isinstance(cleared, list) and env_name not in cleared:
        cleared.append(env_name)
        _PENDING_CLEAR_ENVS.add(env_name)
    return payload


def _drop_api_key_state(meta: dict[str, object], api_key_env: str) -> dict[str, object]:
    payload = _normalize_draft_meta(meta)
    env_name = validate_llm_api_key_env(api_key_env, required=False, context="api_key_env")
    if not env_name:
        return payload
    pending = payload["pending_api_keys"]
    cleared = payload["pending_cleared_api_keys"]
    if isinstance(pending, dict):
        _drop_pending_api_key_token(pending.pop(env_name, None))
    if isinstance(cleared, list):
        payload["pending_cleared_api_keys"] = [item for item in cleared if item != env_name]
        _PENDING_CLEAR_ENVS.discard(env_name)
    return payload


def _move_pending_api_key_env(meta: dict[str, object], old_env: str, new_env: str) -> dict[str, object]:
    payload = _normalize_draft_meta(meta)
    old_env = validate_llm_api_key_env(old_env, required=False, context="api_key_env")
    new_env = validate_llm_api_key_env(new_env, required=False, context="api_key_env")
    if not old_env or old_env == new_env:
        return payload
    pending = payload["pending_api_keys"]
    cleared = payload["pending_cleared_api_keys"]
    if isinstance(pending, dict) and old_env in pending and new_env:
        token = pending.pop(old_env)
        _drop_pending_api_key_token(pending.get(new_env))
        _move_pending_api_key_token(token, old_env, new_env)
        pending[new_env] = token
    elif isinstance(pending, dict):
        _drop_pending_api_key_token(pending.pop(old_env, None))
    if isinstance(cleared, list):
        payload["pending_cleared_api_keys"] = [
            new_env if item == old_env and new_env else item
            for item in cleared
            if item != old_env or new_env
        ]
        if old_env in _PENDING_CLEAR_ENVS:
            _PENDING_CLEAR_ENVS.discard(old_env)
            if new_env:
                _PENDING_CLEAR_ENVS.add(new_env)
    return payload


def _env_has_value(env_name: str) -> bool:
    env_name = validate_llm_api_key_env(env_name, required=False, context="api_key_env")
    return bool(env_name and os.environ.get(env_name))


def _with_model_key_env_migration(meta: dict[str, object], old_env: str, new_env: str) -> dict[str, object]:
    payload = _move_pending_api_key_env(meta, old_env, new_env)
    old_env = validate_llm_api_key_env(old_env, required=False, context="api_key_env")
    new_env = validate_llm_api_key_env(new_env, required=False, context="api_key_env")
    if not old_env or not new_env or old_env == new_env:
        return payload
    pending = payload["pending_api_keys"]
    if isinstance(pending, dict) and new_env in pending:
        return payload
    if _env_has_value(old_env) and not _env_has_value(new_env):
        secret = os.environ.get(old_env, "")
        if secret:
            payload = _with_pending_api_key(payload, new_env, secret)
    return _with_cleared_api_key(payload, old_env)


def _api_key_display_state(api_key_env: str, configured: bool, draft_meta: dict | None) -> tuple[bool, str]:
    env_name = str(api_key_env or "").strip()
    meta = _normalize_draft_meta(draft_meta)
    pending = meta["pending_api_keys"]
    cleared = meta["pending_cleared_api_keys"]
    if env_name and isinstance(pending, dict) and env_name in pending:
        return True, "pending"
    if env_name and isinstance(cleared, list) and env_name in cleared:
        return False, "clear_pending"
    return configured, "configured" if configured else "missing"


def _decorate_model_options(public_config: dict[str, Any], draft_meta: dict | None) -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = []
    view_config = apply_model_capability_overrides(public_config)
    for option in list_llm_model_options(view_config):
        decorated = copy.deepcopy(option)
        details = decorated.get("details") if isinstance(decorated.get("details"), dict) else {}
        provider = decorated.get("provider") if isinstance(decorated.get("provider"), dict) else {}
        api_key_env = str(option.get("api_key_env", "") or details.get("api_key_env", "")).strip()
        option_provider = ProviderConfig.model_validate(
            {
                **copy.deepcopy(provider),
                "provider_id": _model_option_provider_id(str(option.get("model_id") or "")),
            }
        )
        option_profile = LLMProfile.model_validate(
            {
                **copy.deepcopy(details),
                "profile_id": _model_probe_route_id(str(option.get("model_id") or "")),
                "provider_id": option_provider.provider_id,
                "model": str(option.get("model") or "").strip(),
                "api_key_env": api_key_env,
            }
        )
        resolved_api_key, api_key_source = _resolve_model_option_api_key(option_provider, option_profile, draft_meta)
        resolved_configured, state = _api_key_display_state(
            api_key_env,
            bool(resolved_api_key) or bool(option.get("api_key_configured", False)),
            draft_meta,
        )
        if option_provider.requires_api_key and not resolved_api_key and not str(api_key_source or "").startswith(("pending-clear:", "pending-env:")):
            state = "missing"
            resolved_configured = False
        protocol_route = _model_option_protocol_route_summary(decorated, details)
        decorated["api_key_configured"] = resolved_configured
        decorated["api_key_state"] = state
        decorated["api_key_source"] = api_key_source
        decorated["provider_api"] = str(decorated.get("provider_api") or provider.get("api") or "").strip().lower().replace("_", "-")
        decorated["protocol"] = str(decorated.get("protocol") or details.get("protocol") or "").strip().lower()
        decorated["compat"] = copy.deepcopy(decorated.get("compat") if isinstance(decorated.get("compat"), dict) else details.get("compat") if isinstance(details.get("compat"), dict) else {})
        decorated["resolved_protocol"] = str(protocol_route.get("protocol") or "").strip()
        decorated["protocol_source"] = str(protocol_route.get("protocolSource") or "").strip()
        decorated["protocol_warnings"] = protocol_route.get("protocolWarnings") if isinstance(protocol_route.get("protocolWarnings"), list) else []
        decorated["resolved_provider_api"] = str(protocol_route.get("providerApi") or decorated["provider_api"]).strip()
        decorated["resolved_compat"] = copy.deepcopy(protocol_route.get("compat") if isinstance(protocol_route.get("compat"), dict) else {})
        decorated["supports_image_input"] = _image_input_support_from_model_record(decorated)
        decorated["capability_status"] = str(details.get("capability_status") or "").strip() or (
            "supported" if decorated["supports_image_input"] is True else "unsupported" if decorated["supports_image_input"] is False else "unknown"
        )
        decorated["capability_source"] = str(details.get("capability_source") or "").strip()
        decorated["capability_checked_at"] = str(details.get("capability_checked_at") or "").strip()
        decorated["capability_error"] = str(details.get("capability_error") or "").strip()
        options.append(decorated)
    return options


def _model_label_map(public_config: dict[str, Any]) -> dict[str, str]:
    labels: dict[str, str] = {}
    for option in list_llm_model_options(public_config):
        model_id = str(option.get("model_id") or "").strip()
        if not model_id:
            continue
        label = str(option.get("label") or option.get("model") or model_id).strip()
        if label:
            labels[model_id] = label
    return labels


def _image_input_support_from_model_record(record: dict[str, Any], *, provider_kind: str = "") -> bool | None:
    return model_record_image_input_support(record, provider_kind=provider_kind)


def _model_record_provider_kind(public_config: dict[str, Any], record: dict[str, Any]) -> str:
    provider = record.get("provider")
    if isinstance(provider, dict):
        kind = str(provider.get("kind") or "").strip()
        if kind:
            return kind
    provider_kind = str(record.get("provider_kind") or "").strip()
    if provider_kind:
        return provider_kind
    provider_id = str(record.get("provider_id") or "").strip()
    if not provider_id:
        return ""
    llm_cfg = public_config.get("llm", {}) if isinstance(public_config, dict) else {}
    providers = llm_cfg.get("providers", {}) if isinstance(llm_cfg, dict) else {}
    provider_record = providers.get(provider_id) if isinstance(providers, dict) else None
    if isinstance(provider_record, dict):
        return str(provider_record.get("kind") or "").strip()
    return ""


def _model_image_input_support_map(public_config: dict[str, Any]) -> dict[str, bool | None]:
    supports_by_model: dict[str, bool | None] = {}
    for option in list_llm_model_options(public_config):
        model_id = str(option.get("model_id") or "").strip()
        if model_id:
            supports_by_model[model_id] = _image_input_support_from_model_record(option)
    llm_cfg = public_config.get("llm", {}) if isinstance(public_config, dict) else {}
    model_library = llm_cfg.get("model_library", {}) if isinstance(llm_cfg, dict) else {}
    if isinstance(model_library, dict):
        for model_id, entry in model_library.items():
            if isinstance(entry, dict):
                supports_by_model[str(model_id)] = _image_input_support_from_model_record(
                    entry,
                    provider_kind=_model_record_provider_kind(public_config, entry),
                )
    return supports_by_model


def _image_input_capability_result_details(result: dict[str, Any]) -> dict[str, Any]:
    status = str(result.get("capability_status") or "").strip().lower()
    if status not in {"supported", "unsupported", "unknown"}:
        status = "supported" if result.get("supports_image_input") is True else "unsupported" if result.get("supports_image_input") is False else "unknown"
    details: dict[str, Any] = {
        "capability_status": status,
        "capability_source": "runtime_probe",
        "capability_checked_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }
    supports = result.get("supports_image_input")
    if supports is not None:
        details["supports_image_input"] = bool(supports)
    error = trim_lines(result.get("message") or result.get("error") or "", max_lines=2)
    if status != "supported" and error:
        details["capability_error"] = error
    return details


def _model_probe_route_id(model_id: str) -> str:
    safe = "".join(ch if ch.isalnum() else "_" for ch in str(model_id or "").strip().lower()).strip("_")
    return f"__capability_probe_{safe or 'model'}"


def _model_option_provider_id(model_id: str) -> str:
    safe = "".join(ch if ch.isalnum() else "_" for ch in str(model_id or "").strip().lower()).strip("_")
    return f"__model_probe_provider_{safe or 'model'}"


def _resolve_model_option_api_key(
    provider: ProviderConfig,
    profile: LLMProfile,
    draft_meta: dict | None = None,
) -> tuple[str | None, str]:
    if not provider.requires_api_key:
        return None, "not-required"
    meta = _normalize_draft_meta(draft_meta)
    pending = meta["pending_api_keys"]
    cleared = meta["pending_cleared_api_keys"]
    env_candidates = [
        str(profile.api_key_env or "").strip(),
        str(provider.api_key_env or "").strip(),
    ]
    canonical_env = get_provider_api_key_env(provider.kind)
    if canonical_env:
        env_candidates.append(canonical_env)
    env_candidates.extend(PROVIDER_API_KEY_ENV_ALIASES.get(str(provider.kind or "").strip().lower(), []))
    seen: set[str] = set()
    for env_name in env_candidates:
        env_name = str(env_name or "").strip()
        if not env_name or env_name in seen:
            continue
        seen.add(env_name)
        if isinstance(cleared, list) and env_name in cleared:
            return None, f"pending-clear:{env_name}"
        if isinstance(pending, dict) and env_name in pending:
            pending_secret = _resolve_pending_api_key(env_name, pending[env_name])
            if pending_secret is not None:
                return pending_secret, f"pending-env:{env_name}"
        value = _read_env_var(env_name)
        if value:
            if env_name == str(profile.api_key_env or "").strip():
                return value, f"model-env:{env_name}"
            return value, f"provider-env:{env_name}"
    if provider.api_key:
        return provider.api_key, "config-or-kwargs"
    return None, "missing"


def _model_option_test_target(
    public_config: dict[str, Any],
    option: dict[str, Any],
    draft_meta: dict | None = None,
) -> dict[str, Any]:
    model_id = str(option.get("model_id") or "").strip()
    if not model_id:
        raise ValueError("modelId is required")
    provider_input = option.get("provider") if isinstance(option.get("provider"), dict) else {}
    details = option.get("details") if isinstance(option.get("details"), dict) else {}
    provider_id = _model_option_provider_id(model_id)
    route_id = _model_probe_route_id(model_id)
    provider = ProviderConfig.model_validate(
        {
            **copy.deepcopy(provider_input),
            "provider_id": provider_id,
        }
    )
    profile_payload: dict[str, Any] = {
        **copy.deepcopy(details),
        "profile_id": route_id,
        "provider_id": provider_id,
        "model": str(option.get("model") or "").strip(),
    }
    api_key_env = str(option.get("api_key_env") or details.get("api_key_env") or "").strip()
    if api_key_env:
        profile_payload["api_key_env"] = api_key_env
    profile = LLMProfile.model_validate(profile_payload)
    api_key, api_key_source = _resolve_model_option_api_key(provider, profile, draft_meta)
    return {
        "model_id": model_id,
        "route_id": route_id,
        "provider": provider,
        "profile": profile,
        "api_key": api_key,
        "api_key_source": api_key_source,
    }


def _profile_test_target(
    public_config: dict[str, Any],
    profile_id: str,
    draft_meta: dict | None = None,
) -> dict[str, Any]:
    normalized_profile_id = str(profile_id or "").strip() or "primary"
    public_profile = _public_profile(public_config, normalized_profile_id)
    effective = build_effective_config(public_config)
    profile = effective.llm.get_profile(profile_id=normalized_profile_id)
    provider = effective.llm.get_provider(profile.provider_id)
    if provider.requires_api_key:
        api_key, api_key_source = _resolve_model_option_api_key(provider, profile, draft_meta)
    else:
        api_key = None
        api_key_source = "not-required"
    model_id = str((public_profile or {}).get("model_ref") or "").strip()
    if not model_id:
        model_id, _ = effective.llm.get_model_library_entry_for_profile(profile)
    model_id = str(model_id or "").strip() or normalized_profile_id
    return {
        "model_id": model_id,
        "route_id": normalized_profile_id,
        "provider": provider,
        "profile": profile,
        "api_key": api_key,
        "api_key_source": api_key_source,
    }


def _apply_image_input_capability_details_to_runtime_view(
    public_config: dict[str, Any],
    model_id: str,
    details: dict[str, Any],
) -> None:
    model_id = str(model_id or "").strip()
    llm = public_config.setdefault("llm", {})
    model_library = llm.setdefault("model_library", {})
    if not isinstance(model_library, dict) or not isinstance(model_library.get(model_id), dict):
        return
    entry = model_library[model_id]
    if "supports_image_input" in details:
        entry["supports_image_input"] = details["supports_image_input"]
    entry["capability_status"] = details["capability_status"]
    entry["capability_source"] = details["capability_source"]
    entry["capability_checked_at"] = details["capability_checked_at"]
    if details.get("capability_error"):
        entry["capability_error"] = details["capability_error"]
    else:
        entry.pop("capability_error", None)


def _llm_test_probe_timeout_seconds(provider: ProviderConfig, profile: LLMProfile) -> int:
    if hasattr(public_config_module, "coerce_llm_runtime_probe_timeout"):
        return int(public_config_module.coerce_llm_runtime_probe_timeout(provider, profile.connect_timeout, profile.timeout))
    if hasattr(public_config_module, "coerce_llm_probe_timeout"):
        return int(public_config_module.coerce_llm_probe_timeout(profile.connect_timeout, profile.timeout))
    try:
        return max(1, min(int(profile.connect_timeout), int(profile.timeout), 10))
    except (TypeError, ValueError):
        return 10


def _invoke_llm_runtime_probe(provider: ProviderConfig, profile: LLMProfile, api_key: str | None) -> dict[str, Any]:
    return public_config_module._probe_llm_runtime(provider, profile, api_key)


def _run_bounded_llm_runtime_probe(provider: ProviderConfig, profile: LLMProfile, api_key: str | None) -> dict[str, Any]:
    probe_timeout = _llm_test_probe_timeout_seconds(provider, profile)
    if not _LLM_TEST_PROBE_WORKER_SLOTS.acquire(blocking=False):
        return {
            "ok": False,
            "message": "another LLM connection probe is still running",
            "status": "busy",
            "error": "probe_busy",
            "busy": True,
        }
    result_queue: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=1)

    def run_probe() -> None:
        try:
            result_queue.put(("result", _invoke_llm_runtime_probe(provider, profile, api_key)))
        except Exception as exc:
            result_queue.put(("error", exc))
        finally:
            _LLM_TEST_PROBE_WORKER_SLOTS.release()

    thread = threading.Thread(target=run_probe, name="config-llm-test-probe", daemon=True)
    thread.start()
    try:
        kind, value = result_queue.get(timeout=probe_timeout + _LLM_TEST_PROBE_TIMEOUT_GRACE_SECONDS)
    except queue.Empty:
        return {
            "ok": False,
            "message": f"probe timed out after {probe_timeout}s",
            "status": "timeout",
            "error": "probe_timeout",
            "timeout": True,
            "probe_timeout_seconds": probe_timeout,
        }
    if kind == "error":
        raise value
    return value if isinstance(value, dict) else {"ok": False, "message": str(value)}


def _run_draft_test_llm_connection(
    public_config: dict[str, Any],
    *,
    model_id: str,
    route_id: str,
    profile: LLMProfile,
    provider: ProviderConfig,
    api_key: str | None,
    api_key_source: str,
    draft_meta: dict | None = None,
    capability: str | None = None,
) -> dict[str, Any]:
    normalized_capability = _normalize_llm_test_capability(capability)
    if normalized_capability == "image_input":
        return _run_draft_test_llm_image_input(
            public_config,
            model_id,
            route_id,
            profile,
            provider,
            api_key,
            api_key_source,
            draft_meta,
        )
    try:
        result = _run_bounded_llm_runtime_probe(provider, profile, api_key)
    except Exception as exc:
        _record_config_scene_event(
            "llm_test",
            "config.llm_test.failed",
            message=f"Draft LLM connection test failed: {type(exc).__name__}",
            level="error",
            outcome="failed",
            fields={
                "routeId": route_id,
                "modelId": model_id,
                "providerId": provider.provider_id,
                "providerKind": provider.kind,
                "model": profile.model,
                "apiKeySource": api_key_source,
                "requiresApiKey": bool(provider.requires_api_key),
                "transport": profile.transport,
                "contract": profile.contract,
                "configScope": _llm_test_config_scope(public_config, draft_meta),
                "errorType": type(exc).__name__,
                "error": str(exc),
            },
            lifecycle=True,
        )
        raise
    success = bool(result.get("ok") if isinstance(result, dict) and "ok" in result else result.get("success") if isinstance(result, dict) else False)
    _record_config_scene_event(
        "llm_test",
        "config.llm_test.completed",
        message="Draft LLM connection test completed.",
        level="info" if success else "warning",
        outcome="succeeded" if success else "failed",
        fields={
            "routeId": route_id,
            "modelId": model_id,
            "providerId": provider.provider_id,
            "providerKind": provider.kind,
            "model": profile.model,
            "apiKeySource": api_key_source,
            "requiresApiKey": bool(provider.requires_api_key),
            "transport": profile.transport,
            "contract": profile.contract,
            "configScope": _llm_test_config_scope(public_config, draft_meta),
            "ok": success,
            "status": str(result.get("status") if isinstance(result, dict) else "").strip(),
            "error": str(result.get("error") if isinstance(result, dict) else "").strip(),
        },
        lifecycle=True,
    )
    return {
        **result,
        "route_id": route_id,
        "model_id": model_id,
        "provider_id": provider.provider_id,
        "provider_kind": provider.kind,
        "base_url": provider.base_url,
        "model": profile.model,
        "transport": profile.transport,
        "contract": profile.contract,
        "api_key_source": api_key_source,
        "config_scope": _llm_test_config_scope(public_config, draft_meta),
        "requires_api_key": bool(provider.requires_api_key),
        "capability": "text",
        "capability_status": "supported" if success else "unknown",
        "supports_image_input": None,
    }


def _build_image_input_probe_profile(profile: Any) -> Any:
    probe_timeout = (
        public_config_module.coerce_llm_probe_timeout(profile.connect_timeout, profile.timeout)
        if hasattr(public_config_module, "coerce_llm_probe_timeout")
        else 20
    )
    retry_policy = (
        public_config_module.RetryPolicyConfig(max_attempts=1, backoff_base_seconds=0.1)
        if hasattr(public_config_module, "RetryPolicyConfig")
        else getattr(profile, "retry_policy", None)
    )
    try:
        return profile.model_copy(
            update={
                "max_output_tokens": 8,
                "timeout": probe_timeout,
                "connect_timeout": min(int(getattr(profile, "connect_timeout", probe_timeout) or probe_timeout), probe_timeout),
                "streaming": False,
                "retry_policy": retry_policy,
            }
        )
    except Exception:
        probe_profile = copy.deepcopy(profile)
        probe_profile.max_output_tokens = 8
        probe_profile.timeout = probe_timeout
        probe_profile.connect_timeout = min(int(getattr(profile, "connect_timeout", probe_timeout) or probe_timeout), probe_timeout)
        probe_profile.streaming = False
        if retry_policy is not None:
            probe_profile.retry_policy = retry_policy
        return probe_profile


def _image_input_probe_status(error_text: str) -> tuple[bool | None, str]:
    lowered = str(error_text or "").lower()
    if any(pattern in lowered for pattern in _IMAGE_INPUT_UNSUPPORTED_PATTERNS):
        return False, "unsupported"
    return None, "unknown"


def _build_image_input_probe_config(
    public_config: dict[str, Any],
    *,
    model_id: str,
    route_id: str,
    provider: Any,
    profile: Any,
    api_key: str | None,
) -> Any:
    probe_config = build_effective_config(public_config)
    probe_provider = copy.deepcopy(provider)
    probe_profile = _build_image_input_probe_profile(profile)
    probe_provider.provider_id = str(provider.provider_id or "").strip()
    probe_profile.profile_id = route_id
    probe_profile.provider_id = probe_provider.provider_id
    probe_profile.supports_image_input = True
    probe_config.llm.providers[probe_provider.provider_id] = probe_provider
    probe_config.llm.profiles[route_id] = probe_profile
    model_entry = probe_config.llm.model_library.get(str(model_id or "").strip())
    if isinstance(model_entry, dict):
        model_entry["provider_id"] = probe_provider.provider_id
        model_entry["supports_image_input"] = True

    class _ProbeConfig:
        def __init__(self, wrapped: Any) -> None:
            self._wrapped = wrapped
            self.llm = wrapped.llm

        def __getattr__(self, name: str) -> Any:
            return getattr(self._wrapped, name)

        def get_api_key_for_profile(self, profile_id=None, role="primary"):
            if str(profile_id or "").strip() == route_id:
                return api_key
            return self._wrapped.get_api_key_for_profile(profile_id=profile_id, role=role)

    return _ProbeConfig(probe_config)


def _run_draft_test_llm_image_input(
    public_config: dict[str, Any],
    model_id: str,
    route_id: str,
    profile: Any,
    provider: Any,
    api_key: str | None,
    api_key_source: str,
    draft_meta: dict | None,
) -> dict[str, Any]:
    if provider.requires_api_key and not api_key:
        result: dict[str, Any] = {
            "ok": False,
            "message": f"missing API key for provider `{provider.provider_id}`",
            "capability": "image_input",
            "capability_status": "unknown",
            "supports_image_input": None,
            "capability_reason": "missing_api_key",
        }
    elif not provider.base_url:
        result = {
            "ok": False,
            "message": f"missing base_url for provider `{provider.provider_id}`",
            "capability": "image_input",
            "capability_status": "unknown",
            "supports_image_input": None,
            "capability_reason": "missing_base_url",
        }
    else:
        if not provider.requires_api_key:
            api_key = None
        try:
            validate_llm_provider_target(provider, context="probe", resolve_dns=True)
        except ValueError as exc:
            result = {
                "ok": False,
                "message": str(exc),
                "capability": "image_input",
                "capability_status": "unknown",
                "supports_image_input": None,
                "capability_reason": "invalid_provider_target",
            }
            _record_config_scene_event(
                "llm_capability_test",
                "config.llm_capability_test.completed",
                message="Draft LLM image input capability test blocked by provider target validation.",
                level="error",
                outcome="failed",
                fields={
                    "routeId": route_id,
                    "modelId": model_id,
                    "providerId": provider.provider_id,
                    "providerKind": provider.kind,
                    "model": profile.model,
                    "transport": profile.transport,
                    "contract": profile.contract,
                    "configScope": _llm_test_config_scope(public_config, draft_meta),
                    "capability": "image_input",
                    "capabilityStatus": "unknown",
                    "supportsImageInput": None,
                    "reason": "invalid_provider_target",
                },
                lifecycle=True,
            )
            return {
                **result,
                "route_id": route_id,
                "model_id": model_id,
                "provider_id": provider.provider_id,
                "provider_kind": provider.kind,
                "base_url": provider.base_url,
                "model": profile.model,
                "transport": profile.transport,
                "contract": profile.contract,
                "api_key_source": api_key_source,
                "config_scope": _llm_test_config_scope(public_config, draft_meta),
                "requires_api_key": bool(provider.requires_api_key),
            }
        probe_config = _build_image_input_probe_config(
            public_config,
            model_id=model_id,
            route_id=route_id,
            provider=provider,
            profile=profile,
            api_key=api_key,
        )

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Reply with ok if you can inspect this image."},
                    {"type": "image_url", "image_url": {"url": _IMAGE_INPUT_PROBE_DATA_URL}},
                ],
            }
        ]
        try:
            from core.llm import LLMClient

            client = LLMClient(config=probe_config, profile_id=route_id)
            invoke_llm(
                client,
                messages,
                tools=[],
                context=LLMInvocationContext(
                    surface="config_image_input_probe",
                    run_kind="non_conversation_probe",
                    agent_id="config_service",
                    llm_slot="vision",
                    model_id=model_id,
                    cache_scope="config_probe",
                    cache_partition=f"config-image-input-probe-{route_id}",
                    prompt_purpose="image_input_probe",
                    conversation_bound=False,
                ),
                metadata={"probeCapability": "image_input"},
            )
            result = {
                "ok": True,
                "message": "image input is supported",
                "capability": "image_input",
                "capability_status": "supported",
                "supports_image_input": True,
                "capability_reason": "runtime_probe_succeeded",
            }
        except Exception as exc:
            error_text = public_config_module.redact_llm_probe_error(str(exc), api_key=api_key)
            supports_image_input, capability_status = _image_input_probe_status(error_text)
            result = {
                "ok": False,
                "message": (
                    "image input is not supported by this model route"
                    if capability_status == "unsupported"
                    else error_text
                ),
                "capability": "image_input",
                "capability_status": capability_status,
                "supports_image_input": supports_image_input,
                "capability_reason": type(exc).__name__,
                "error": error_text,
            }
    _record_config_scene_event(
        "llm_capability_test",
        "config.llm_capability_test.completed",
        message="Draft LLM image input capability test completed.",
        level="info" if result.get("supports_image_input") is True else "warning",
        outcome="succeeded" if result.get("supports_image_input") is True else "failed",
        fields={
            "routeId": route_id,
            "modelId": model_id,
            "providerId": provider.provider_id,
            "providerKind": provider.kind,
            "model": profile.model,
            "apiKeySource": api_key_source,
            "requiresApiKey": bool(provider.requires_api_key),
            "transport": profile.transport,
            "contract": profile.contract,
            "configScope": _llm_test_config_scope(public_config, draft_meta),
            "capability": "image_input",
            "capabilityStatus": result.get("capability_status"),
            "supportsImageInput": result.get("supports_image_input"),
            "reason": result.get("capability_reason"),
        },
        lifecycle=True,
    )
    return {
        **result,
        "route_id": route_id,
        "model_id": model_id,
        "provider_id": provider.provider_id,
        "provider_kind": provider.kind,
        "base_url": provider.base_url,
        "model": profile.model,
        "transport": profile.transport,
        "contract": profile.contract,
        "api_key_source": api_key_source,
        "config_scope": _llm_test_config_scope(public_config, draft_meta),
        "requires_api_key": bool(provider.requires_api_key),
    }


def _read_raw_public_config() -> str:
    try:
        return CONFIG_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def _build_workspace(
    public_config: dict[str, Any],
    *,
    draft_meta: dict | None = None,
    base_hash: str = "",
    message: str = "",
    raw_toml: str | None = None,
) -> dict[str, Any]:
    public_config = _with_config_workspace_defaults(public_config)
    diagnostics = inspect_public_config(public_config)
    diagnosis = diagnostics.get("diagnosis", {})
    summary = diagnostics.get("summary", {})
    lang = _resolve_workspace_language(public_config)
    contract = get_workbench_contract(public_config)
    llm_cfg = public_config.get("llm", {})
    model_library = llm_cfg.get("model_library", {}) if isinstance(llm_cfg, dict) else {}
    draft_hash = public_config_hash(public_config)
    blocking = diagnosis.get("blocking_issues") or []
    warnings = diagnosis.get("warnings") or []
    normalized_meta = _normalize_draft_meta(draft_meta)
    editor_sections = build_editor_sections(public_config, lang)
    editor_meta = build_editor_meta(public_config, lang)

    return {
        "message": message,
        "hash": draft_hash,
        "baseHash": str(base_hash or draft_hash).strip() or draft_hash,
        "language": lang,
        "configPath": str(CONFIG_PATH),
        "runtimeProfile": public_config.get("runtime", {}).get("profile", "safe_local"),
        "defaultMode": contract["defaultMode"],
        "defaultRoute": contract["defaultRoute"],
        "intakeMode": contract["intakeMode"],
        "modeAvailability": contract["modeAvailability"],
        "domainAvailability": contract["domainAvailability"],
        "modelLibraryCount": len(model_library) if isinstance(model_library, dict) else 0,
        "blockingCount": len(blocking),
        "warningCount": len(warnings),
        "themeBackgroundImagePath": _theme_background_path(public_config),
        "themeBackgroundImageUrl": theme_background_image_url(_theme_background_path(public_config)),
        "sections": _config_sections(lang, editor_sections),
        "publicConfig": public_config,
        "rawToml": _read_raw_public_config() if raw_toml is None else raw_toml,
        "draftMeta": normalized_meta,
        "diagnosis": diagnosis,
        "summary": summary,
        "editorSections": editor_sections,
        "editorMeta": editor_meta,
        "modelPresetOptions": list_llm_model_preset_options(),
        "providerPresetOptions": list_llm_provider_preset_options(),
        "modelOptions": _decorate_model_options(public_config, normalized_meta),
    }


def _prepare_submitted_public_config(public_config: dict[str, Any] | None, old_public: dict[str, Any]) -> dict[str, Any]:
    old_with_defaults = _with_config_workspace_defaults(old_public)
    submitted = copy.deepcopy(public_config) if isinstance(public_config, dict) else copy.deepcopy(old_with_defaults)
    submitted_with_secret_blanks = preserve_secret_blanks(submitted, old_with_defaults)
    prepared = _with_config_workspace_defaults(submitted_with_secret_blanks, repair_stale_model_ref=False)
    raw_submitted_git_model_ref = _git_commit_model_ref(submitted_with_secret_blanks)
    old_raw_git_model_ref = _git_commit_model_ref(old_public)
    old_default_git_model_ref = _git_commit_model_ref(old_with_defaults)
    if (
        raw_submitted_git_model_ref
        and raw_submitted_git_model_ref == old_raw_git_model_ref
        and raw_submitted_git_model_ref != old_default_git_model_ref
    ):
        _set_git_commit_model_ref(prepared, old_default_git_model_ref)
    return strip_runtime_model_capability_fields(prepared)


def _normalize_apply_base_config(base_config: dict[str, Any] | None, old_public: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(base_config, dict):
        return None
    old_with_defaults = _with_config_workspace_defaults(old_public)
    prepared = _with_config_workspace_defaults(preserve_secret_blanks(copy.deepcopy(base_config), old_with_defaults))
    return strip_runtime_model_capability_fields(prepared)


def _config_values_equal(left: Any, right: Any) -> bool:
    return left == right


def _iter_config_changed_paths(base: Any, submitted: Any, prefix: tuple[str, ...] = ()) -> list[tuple[str, ...]]:
    if isinstance(base, dict) and isinstance(submitted, dict):
        paths: list[tuple[str, ...]] = []
        keys = sorted(set(base.keys()) | set(submitted.keys()), key=str)
        for key in keys:
            key_path = (*prefix, str(key))
            if key not in base or key not in submitted:
                paths.append(key_path)
                continue
            paths.extend(_iter_config_changed_paths(base[key], submitted[key], key_path))
        return paths
    if _config_values_equal(base, submitted):
        return []
    return [prefix]


def _get_config_path(root: Any, path: tuple[str, ...]) -> Any:
    current = root
    for token in path:
        if isinstance(current, dict) and token in current:
            current = current[token]
            continue
        return _MISSING
    return current


def _set_config_path(root: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    current: dict[str, Any] = root
    for token in path[:-1]:
        next_value = current.get(token)
        if not isinstance(next_value, dict):
            next_value = {}
            current[token] = next_value
        current = next_value
    current[path[-1]] = copy.deepcopy(value)


def _delete_config_path(root: dict[str, Any], path: tuple[str, ...]) -> None:
    current: Any = root
    for token in path[:-1]:
        if not isinstance(current, dict) or token not in current:
            return
        current = current[token]
    if isinstance(current, dict):
        current.pop(path[-1], None)


def _format_config_path(path: tuple[str, ...]) -> str:
    return ".".join(path)


def _model_library_ids(public_config: dict[str, Any]) -> set[str]:
    llm_config = public_config.get("llm", {}) if isinstance(public_config.get("llm", {}), dict) else {}
    model_library = llm_config.get("model_library", {}) if isinstance(llm_config, dict) else {}
    if not isinstance(model_library, dict):
        return set()
    return {str(model_id) for model_id in model_library.keys()}


def _changed_model_ids_from_paths(changed_paths: list[tuple[str, ...]], base_config: dict[str, Any], submitted: dict[str, Any]) -> list[str]:
    base_ids = _model_library_ids(base_config)
    submitted_ids = _model_library_ids(submitted)
    touched = {
        path[2]
        for path in changed_paths
        if len(path) >= 3 and path[0] == "llm" and path[1] == "model_library"
    }
    return sorted(str(model_id) for model_id in touched if model_id in base_ids and model_id in submitted_ids)


def _added_model_ids_from_paths(changed_paths: list[tuple[str, ...]], base_config: dict[str, Any], submitted: dict[str, Any]) -> list[str]:
    base_ids = _model_library_ids(base_config)
    submitted_ids = _model_library_ids(submitted)
    touched = {
        path[2]
        for path in changed_paths
        if len(path) >= 3 and path[0] == "llm" and path[1] == "model_library"
    }
    return sorted(str(model_id) for model_id in touched if model_id in submitted_ids and model_id not in base_ids)


def _removed_model_ids_from_paths(changed_paths: list[tuple[str, ...]], base_config: dict[str, Any], submitted: dict[str, Any]) -> list[str]:
    base_ids = _model_library_ids(base_config)
    submitted_ids = _model_library_ids(submitted)
    touched = {
        path[2]
        for path in changed_paths
        if len(path) >= 3 and path[0] == "llm" and path[1] == "model_library"
    }
    return sorted(str(model_id) for model_id in touched if model_id in base_ids and model_id not in submitted_ids)


def _merge_submitted_config_changes(
    *,
    base_config: dict[str, Any] | None,
    submitted: dict[str, Any],
    old_public: dict[str, Any],
    lang: str,
) -> tuple[dict[str, Any], list[tuple[str, ...]], list[tuple[str, ...]]]:
    if base_config is None:
        changed_paths = _iter_config_changed_paths(old_public, submitted)
        return submitted, changed_paths, []

    changed_paths = _iter_config_changed_paths(base_config, submitted)
    merged = copy.deepcopy(old_public)
    conflicted_paths: list[tuple[str, ...]] = []
    for path in changed_paths:
        base_value = _get_config_path(base_config, path)
        current_value = _get_config_path(old_public, path)
        if not _config_values_equal(base_value, current_value):
            conflicted_paths.append(path)
            continue
        submitted_value = _get_config_path(submitted, path)
        if submitted_value is _MISSING:
            _delete_config_path(merged, path)
        else:
            _set_config_path(merged, path, submitted_value)

    if conflicted_paths:
        preview = ", ".join(_format_config_path(path) for path in conflicted_paths[:8])
        raise ConfigConflictError(
            text_for(
                lang,
                zh=f"当前配置中的这些字段已被其他页面或进程改动，请重新加载后再保存：{preview}",
                en=f"These config fields changed in another page or process. Reload before saving: {preview}",
            )
        )
    return merged, changed_paths, []


def _assert_base_hash_matches(base_hash: str, old_public: dict[str, Any], lang: str) -> str:
    current_hash = public_config_hash(_with_config_workspace_defaults(old_public))
    raw_current_hash = public_config_hash(old_public)
    expected_hash = str(base_hash or "").strip()
    if expected_hash and expected_hash not in {current_hash, raw_current_hash}:
        raise ConfigConflictError(
            text_for(
                lang,
                zh="当前配置已被其他页面或进程改动，请重新加载后再保存这次修改",
                en="The saved config changed in another page or process. Reload before saving these changes.",
            )
        )
    return current_hash


def _assert_apply_base_hash_matches(base_hash: str, base_config: dict[str, Any], lang: str) -> str:
    base_hash_value = public_config_hash(_with_config_workspace_defaults(base_config))
    expected_hash = str(base_hash or "").strip()
    if expected_hash and expected_hash != base_hash_value:
        raise ConfigConflictError(
            text_for(
                lang,
                zh="设置页的配置基线已过期，请重新加载后再保存这次修改",
                en="The config edit baseline is stale. Reload before saving these changes.",
            )
        )
    return base_hash_value


def get_config_summary() -> dict[str, Any]:
    """Return a condensed config summary for shell-wide consumers."""

    public_config = _with_config_workspace_defaults(load_public_config())
    diagnostics = inspect_public_config(public_config)
    diagnosis = diagnostics.get("diagnosis", {})
    contract = get_workbench_contract(public_config)
    llm_cfg = public_config.get("llm", {})
    model_library = llm_cfg.get("model_library", {})
    lang = _resolve_workspace_language(public_config)

    blocking = diagnosis.get("blocking_issues") or []
    warnings = diagnosis.get("warnings") or []
    theme_background_path = _theme_background_path(public_config)

    return {
        "hash": public_config_hash(public_config),
        "language": lang,
        "runtimeProfile": public_config.get("runtime", {}).get("profile", "safe_local"),
        "defaultMode": contract["defaultMode"],
        "defaultRoute": contract["defaultRoute"],
        "intakeMode": contract["intakeMode"],
        "modeAvailability": contract["modeAvailability"],
        "domainAvailability": contract["domainAvailability"],
        "modelLibraryCount": len(model_library) if isinstance(model_library, dict) else 0,
        "modelLabels": _model_label_map(public_config),
        "modelImageInputSupport": _model_image_input_support_map(public_config),
        "themeBackgroundImagePath": theme_background_path,
        "themeBackgroundImageUrl": theme_background_image_url(theme_background_path),
        "blockingCount": len(blocking),
        "warningCount": len(warnings),
        "sections": _config_sections(lang, build_editor_sections(public_config, lang)),
    }


def get_config_workspace() -> dict[str, Any]:
    """Return the full config workspace payload for the Config route."""

    public_config = _with_config_workspace_defaults(load_public_config())
    return _build_workspace(public_config)


def preview_config_workspace(public_config: dict[str, Any] | None, draft_meta: dict | None = None, base_hash: str = "") -> dict[str, Any]:
    """Validate and normalize a draft config without persisting it."""

    old_public = load_public_config()
    submitted = _prepare_submitted_public_config(public_config, old_public)
    return _build_workspace(
        submitted,
        draft_meta=draft_meta,
        base_hash=str(base_hash or public_config_hash(old_public)).strip(),
        message=text_for(
            _resolve_workspace_language(submitted),
            zh="当前修改已刷新，尚未保存到外部 operator config.toml。",
            en="Current changes refreshed and not yet saved to external operator config.toml.",
        ),
    )


def update_intake_mode(intake_mode: str) -> dict[str, Any]:
    """Persist the evolution intake mode and return the refreshed config summary."""

    public_config = _with_config_workspace_defaults(load_public_config())
    evolution_cfg = public_config.setdefault("evolution", {})
    evolution_cfg["intake_mode"] = intake_mode
    save_public_config(public_config)
    summary = get_config_summary()
    _record_config_scene_event(
        "persist",
        "config.intake_mode.updated",
        message="Evolution intake mode updated.",
        outcome="succeeded",
        fields={
            "intakeMode": str(intake_mode or "").strip(),
            "configPath": str(CONFIG_PATH),
        },
        lifecycle=True,
    )
    return summary


def update_language(language: str) -> dict[str, Any]:
    """Persist the UI language and return the refreshed config summary."""

    public_config = _with_config_workspace_defaults(load_public_config())
    ui_cfg = public_config.setdefault("ui", {})
    ui_cfg["language"] = "en" if str(language or "").strip().lower() == "en" else "zh"
    save_public_config(public_config)
    summary = get_config_summary()
    _record_config_scene_event(
        "persist",
        "config.language.updated",
        message="UI language updated.",
        outcome="succeeded",
        fields={
            "language": ui_cfg["language"],
            "configPath": str(CONFIG_PATH),
        },
        lifecycle=True,
    )
    return summary


def draft_add_model(
    public_config: dict[str, Any] | None,
    *,
    draft_meta: dict | None = None,
    base_hash: str = "",
    preset_id: str = "",
    model_id: str = "",
    provider: Any = None,
    model: str = "",
    label: str = "",
    details: dict | None = None,
    api_key_env: str = "",
    api_key: str = "",
) -> dict[str, Any]:
    old_public = _with_config_workspace_defaults(load_public_config())
    current = _prepare_submitted_public_config(public_config, old_public)
    current_meta = _normalize_draft_meta(draft_meta)
    validate_llm_public_config(current)
    before_keys = set(current.get("llm", {}).get("model_library", {}).keys()) if isinstance(current.get("llm", {}), dict) else set()
    if str(preset_id or "").strip():
        updated = apply_llm_model_preset(
            current,
            preset_id,
            model_id=model_id,
            provider_id=provider or "",
            model=model,
            label=label,
            details=details,
            api_key_env=api_key_env,
        )
    else:
        updated = add_llm_model(
            current,
            model_id,
            provider or "",
            model,
            label,
            details,
            api_key_env=api_key_env,
        )
    after_library = updated.get("llm", {}).get("model_library", {}) if isinstance(updated.get("llm", {}), dict) else {}
    resolved_model_id = str(model_id or "").strip()
    if not resolved_model_id and isinstance(after_library, dict):
        created = [key for key in after_library.keys() if key not in before_keys]
        if created:
            resolved_model_id = str(created[0])
    if isinstance(after_library, dict):
        resolved_item = after_library.get(resolved_model_id, {})
        if isinstance(resolved_item, dict):
            resolved_env = str(resolved_item.get("api_key_env", "")).strip()
            if api_key and resolved_env:
                current_meta = _with_pending_api_key(current_meta, resolved_env, api_key)
    return _build_workspace(
        updated,
        draft_meta=current_meta,
        base_hash=str(base_hash or public_config_hash(old_public)).strip(),
        message=text_for(
            _resolve_workspace_language(updated),
            zh="模型修改已更新，尚未保存到外部 operator config.toml。",
            en="Model changes updated and not yet saved to external operator config.toml.",
        ),
    )


def draft_update_model(
    public_config: dict[str, Any] | None,
    *,
    draft_meta: dict | None = None,
    base_hash: str = "",
    model_id: str,
    provider: Any = None,
    model: str = "",
    label: str = "",
    details: dict | None = None,
    api_key_env: str = "",
    api_key: str = "",
    clear_api_key: bool = False,
) -> dict[str, Any]:
    old_public = _with_config_workspace_defaults(load_public_config())
    current = _prepare_submitted_public_config(public_config, old_public)
    current_meta = _normalize_draft_meta(draft_meta)
    validate_llm_public_config(current)
    current_library = current.get("llm", {}).get("model_library", {}) if isinstance(current.get("llm", {}), dict) else {}
    old_item = current_library.get(model_id, {}) if isinstance(current_library, dict) else {}
    old_env = str(old_item.get("api_key_env", "")).strip() if isinstance(old_item, dict) else ""
    updated = update_llm_model(
        current,
        model_id,
        provider or "",
        model,
        label,
        details,
        api_key_env,
    )
    updated_library = updated.get("llm", {}).get("model_library", {}) if isinstance(updated.get("llm", {}), dict) else {}
    new_item = updated_library.get(model_id, {}) if isinstance(updated_library, dict) else {}
    new_env = str(new_item.get("api_key_env", "")).strip() if isinstance(new_item, dict) else ""
    current_meta = _with_model_key_env_migration(current_meta, old_env, new_env)
    if clear_api_key:
        current_meta = _with_cleared_api_key(current_meta, new_env)
    elif api_key:
        current_meta = _with_pending_api_key(current_meta, new_env, api_key)
    return _build_workspace(
        updated,
        draft_meta=current_meta,
        base_hash=str(base_hash or public_config_hash(old_public)).strip(),
        message=text_for(
            _resolve_workspace_language(updated),
            zh="模型修改已更新，尚未保存到外部 operator config.toml。",
            en="Model changes updated and not yet saved to external operator config.toml.",
        ),
    )


def draft_delete_model(
    public_config: dict[str, Any] | None,
    *,
    draft_meta: dict | None = None,
    base_hash: str = "",
    model_id: str,
) -> dict[str, Any]:
    old_public = _with_config_workspace_defaults(load_public_config())
    current = _prepare_submitted_public_config(public_config, old_public)
    current_meta = _normalize_draft_meta(draft_meta)
    current_library = current.get("llm", {}).get("model_library", {}) if isinstance(current.get("llm", {}), dict) else {}
    old_item = current_library.get(model_id, {}) if isinstance(current_library, dict) else {}
    old_env = str(old_item.get("api_key_env", "")).strip() if isinstance(old_item, dict) else ""
    _assert_model_deletion_allowed(current, model_id)
    _assert_model_delete_workspace_references_allowed(current, model_id)
    updated = delete_llm_model(current, model_id)
    updated = _mark_model_ref_profiles_unconfigured(updated, model_id)
    current_meta = _with_cleared_api_key(_drop_api_key_state(current_meta, old_env), old_env)
    return _build_workspace(
        updated,
        draft_meta=current_meta,
        base_hash=str(base_hash or public_config_hash(old_public)).strip(),
        message=text_for(
            _resolve_workspace_language(updated),
            zh="模型修改已更新，尚未保存到外部 operator config.toml。",
            en="Model changes updated and not yet saved to external operator config.toml.",
        ),
    )


def run_draft_llm_test(
    public_config: dict[str, Any] | None,
    *,
    draft_meta: dict | None = None,
    model_id: str | None = None,
    profile_id: str | None = None,
    capability: str | None = None,
) -> dict[str, Any]:
    old_public = _with_config_workspace_defaults(load_public_config())
    submitted = _prepare_submitted_public_config(public_config, old_public)
    validate_llm_public_config(submitted)
    normalized_model_id = str(model_id or "").strip()
    normalized_profile_id = str(profile_id or "").strip()
    if normalized_model_id:
        options = list_llm_model_options(submitted)
        option = next((item for item in options if str(item.get("model_id") or "").strip() == normalized_model_id), None)
        if option is None:
            raise ValueError(f"unknown LLM model: {normalized_model_id}")
        target = _model_option_test_target(submitted, option, draft_meta)
    elif normalized_profile_id:
        target = _profile_test_target(submitted, normalized_profile_id, draft_meta)
    else:
        raise ValueError("modelId is required")
    return _run_draft_test_llm_connection(
        submitted,
        model_id=target["model_id"],
        route_id=target["route_id"],
        profile=target["profile"],
        provider=target["provider"],
        api_key=target["api_key"],
        api_key_source=target["api_key_source"],
        draft_meta=_normalize_draft_meta(draft_meta),
        capability=capability,
    )


def draft_check_model_image_input_capabilities(
    public_config: dict[str, Any] | None,
    *,
    draft_meta: dict | None = None,
    base_hash: str = "",
    model_ids: list[str] | None = None,
) -> dict[str, Any]:
    old_public = _with_config_workspace_defaults(load_public_config())
    current = _prepare_submitted_public_config(public_config, old_public)
    current_meta = _normalize_draft_meta(draft_meta)
    validate_llm_public_config(current)
    requested_ids = {str(item or "").strip() for item in list(model_ids or []) if str(item or "").strip()}
    options = [
        option
        for option in list_llm_model_options(current)
        if not requested_ids or str(option.get("model_id") or "").strip() in requested_ids
    ]
    if requested_ids and len(options) != len(requested_ids):
        found = {str(option.get("model_id") or "").strip() for option in options}
        missing = sorted(requested_ids - found)
        raise ValueError(f"unknown LLM model: {', '.join(missing)}")

    results: list[dict[str, Any]] = []
    cache_persisted_count = 0
    for option in options:
        model_id = str(option.get("model_id") or "").strip()
        try:
            target = _model_option_test_target(current, option, current_meta)
            result = _run_draft_test_llm_connection(
                current,
                model_id=target["model_id"],
                route_id=target["route_id"],
                profile=target["profile"],
                provider=target["provider"],
                api_key=target["api_key"],
                api_key_source=target["api_key_source"],
                draft_meta=current_meta,
                capability="image_input",
            )
        except Exception as exc:
            result = {
                "ok": False,
                "message": public_config_module.redact_llm_probe_error(str(exc)),
                "capability": "image_input",
                "capability_status": "unknown",
                "supports_image_input": None,
                "capability_reason": type(exc).__name__,
                "error": public_config_module.redact_llm_probe_error(str(exc)),
            }
            _record_config_scene_event(
                "llm_capability_batch",
                "config.llm_capability_batch.item_failed",
                message="Model image input capability check failed before result persistence.",
                level="warning",
                outcome="failed",
                fields={
                    "modelId": model_id,
                    "model": str(option.get("model") or "").strip(),
                    "providerKind": str(option.get("provider_kind") or "").strip(),
                    "reason": type(exc).__name__,
                },
                lifecycle=True,
            )
        details = _image_input_capability_result_details(result)
        try:
            record_model_image_input_capability(model_id, details)
            cache_persisted_count += 1
        except Exception as exc:
            _record_config_scene_event(
                "llm_capability_batch",
                "config.llm_capability_batch.cache_persist_failed",
                message="Model image input capability result could not be persisted to the runtime cache.",
                level="warning",
                outcome="failed",
                fields={
                    "modelId": model_id,
                    "reason": type(exc).__name__,
                },
                lifecycle=True,
            )
        _apply_image_input_capability_details_to_runtime_view(current, model_id, details)
        results.append(
            {
                "modelId": model_id,
                "label": str(option.get("label") or "").strip(),
                "model": str(option.get("model") or "").strip(),
                "providerKind": str(option.get("provider_kind") or "").strip(),
                "ok": bool(result.get("ok")),
                "capability": "image_input",
                "capabilityStatus": str(details.get("capability_status") or "").strip() or "unknown",
                "supportsImageInput": details.get("supports_image_input"),
                "reason": str(result.get("capability_reason") or "").strip(),
                "message": str(result.get("message") or "").strip(),
            }
        )

    supported_count = sum(1 for item in results if item.get("supportsImageInput") is True)
    unsupported_count = sum(1 for item in results if item.get("supportsImageInput") is False)
    unknown_count = len(results) - supported_count - unsupported_count
    _record_config_scene_event(
        "llm_capability_batch",
        "config.llm_capability_batch.completed",
        message="Model image input capability batch check completed.",
        level="info" if unknown_count == 0 else "warning",
        outcome="succeeded" if unknown_count == 0 else "partial",
        fields={
            "modelCount": len(results),
            "supportedCount": supported_count,
            "unsupportedCount": unsupported_count,
            "unknownCount": unknown_count,
            "runtimeCachePersistedCount": cache_persisted_count,
        },
        lifecycle=True,
    )
    workspace = _build_workspace(
        current,
        draft_meta=current_meta,
        base_hash=str(base_hash or public_config_hash(old_public)).strip(),
        message=text_for(
            _resolve_workspace_language(current),
            zh=f"已完成 {len(results)} 个模型的图像输入能力检测，结果已写入运行态能力缓存，不会写入外部 operator config.toml。",
            en=f"Checked image input capability for {len(results)} models. Results were stored in the runtime capability cache, not the external operator config.toml.",
        ),
    )
    workspace["capabilityResults"] = results
    return workspace


def _normalize_discovered_models(data: Any) -> list[dict[str, Any]]:
    raw_models: list[Any]
    if isinstance(data, dict) and isinstance(data.get("data"), list):
        raw_models = data["data"]
    elif isinstance(data, list):
        raw_models = data
    elif isinstance(data, dict) and data.get("id"):
        raw_models = [data]
    else:
        raw_models = []

    models: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_models:
        if not isinstance(raw, dict):
            continue
        model_id = str(raw.get("id") or raw.get("model") or raw.get("name") or "").strip()
        if not model_id or model_id in seen:
            continue
        seen.add(model_id)
        context_window = raw.get("contextWindow") or raw.get("context_window") or raw.get("max_model_len") or raw.get("context_length") or raw.get("max_tokens")
        item: dict[str, Any] = {
            "id": model_id,
            "label": str(raw.get("name") or raw.get("label") or model_id),
        }
        if isinstance(context_window, int) and context_window > 0:
            item["contextWindow"] = context_window
        models.append(item)
    return models


def _model_discovery_urls(api_base: str) -> list[str]:
    normalized_base = str(api_base or "").strip().rstrip("/")
    if not normalized_base:
        return []
    parsed = urlparse(normalized_base)
    path_parts = [part for part in parsed.path.split("/") if part]
    if path_parts and path_parts[-1] == "models":
        return [normalized_base]
    endpoints = ("models",) if path_parts and path_parts[-1] == "v1" else _MODEL_DISCOVERY_ENDPOINTS
    urls: list[str] = []
    seen: set[str] = set()
    for endpoint in endpoints:
        candidate = urljoin(normalized_base + "/", endpoint)
        if candidate not in seen:
            seen.add(candidate)
            urls.append(candidate)
    return urls


def _discovery_key_source_label(*, explicit_api_key: str, api_key_env: str, draft_meta: dict[str, object]) -> tuple[str, str]:
    if str(explicit_api_key or "").strip():
        return str(explicit_api_key or "").strip(), "手动输入"
    env_name = validate_llm_api_key_env(api_key_env, required=False, context="api_key_env")
    if env_name:
        pending = draft_meta.get("pending_api_keys", {})
        token = pending.get(env_name) if isinstance(pending, dict) else None
        pending_secret = _resolve_pending_api_key(env_name, token)
        if pending_secret:
            return pending_secret, f"草稿环境变量 {env_name}"
        env_secret = str(os.environ.get(env_name) or "").strip()
        if env_secret:
            return env_secret, f"系统环境变量 {env_name}"
        return "", f"未找到环境变量 {env_name}"
    return "", "未提供密钥"


def _model_library_api_key_env(public_config: dict[str, Any], model_id: str) -> str:
    model_id = str(model_id or "").strip()
    if not model_id:
        return ""
    llm_cfg = public_config.get("llm", {}) if isinstance(public_config, dict) else {}
    model_library = llm_cfg.get("model_library", {}) if isinstance(llm_cfg, dict) else {}
    item = model_library.get(model_id, {}) if isinstance(model_library, dict) else {}
    if not isinstance(item, dict):
        return ""
    return str(item.get("api_key_env") or "").strip()


def _optional_unconfigured_profile_ids(public_config: dict[str, Any]) -> list[str]:
    llm = public_config.get("llm", {}) if isinstance(public_config, dict) else {}
    profiles = llm.get("profiles", {}) if isinstance(llm, dict) else {}
    if not isinstance(profiles, dict):
        return []
    profile_ids: list[str] = []
    for profile_id, profile in sorted(profiles.items()):
        if str(profile_id or "").strip() == "primary" or not isinstance(profile, dict):
            continue
        if str(profile.get("model_ref") or "").strip() == UNCONFIGURED_MODEL_REF:
            profile_ids.append(str(profile_id or "").strip())
    return [item for item in profile_ids if item]


def _public_profile(public_config: dict[str, Any], profile_id: str) -> dict[str, Any] | None:
    llm = public_config.get("llm", {}) if isinstance(public_config, dict) else {}
    profiles = llm.get("profiles", {}) if isinstance(llm, dict) else {}
    profile = profiles.get(str(profile_id or "").strip()) if isinstance(profiles, dict) else None
    return profile if isinstance(profile, dict) else None


def _git_config(public_config: dict[str, Any]) -> dict[str, Any]:
    git_config = public_config.get("git", {}) if isinstance(public_config, dict) else {}
    return git_config if isinstance(git_config, dict) else {}


def _git_commit_model_ref(public_config: dict[str, Any]) -> str:
    return str(_git_config(public_config).get("commit_message_model_ref") or "").strip()


def _set_git_commit_model_ref(public_config: dict[str, Any], model_ref: str) -> None:
    git_config = public_config.setdefault("git", {})
    if not isinstance(git_config, dict):
        git_config = {}
        public_config["git"] = git_config
    git_config["commit_message_model_ref"] = str(model_ref or "").strip()


def _assert_model_deletion_allowed(public_config: dict[str, Any], model_id: str) -> None:
    normalized_model_id = str(model_id or "").strip()
    if not normalized_model_id:
        return
    primary_profile = _public_profile(public_config, "primary")
    if str((primary_profile or {}).get("model_ref") or "").strip() == normalized_model_id:
        _record_config_scene_event(
            "validate",
            "config.llm_model.delete_rejected",
            message="LLM model deletion rejected because primary profile still references it.",
            level="warning",
            outcome="rejected",
            fields={"modelId": normalized_model_id, "reason": "primary_profile_ref"},
            lifecycle=True,
        )
        raise ValueError("Cannot delete the model used by the primary LLM profile. Rebind primary before deleting this model.")
    git_model_id = str(_git_config(public_config).get("commit_message_model_ref") or "").strip()
    if git_model_id == normalized_model_id:
        _record_config_scene_event(
            "validate",
            "config.llm_model.delete_rejected",
            message="LLM model deletion rejected because Git commit messages still reference it.",
            level="warning",
            outcome="rejected",
            fields={"modelId": normalized_model_id, "reason": "git_commit_model_ref"},
            lifecycle=True,
        )
        raise ValueError("Cannot delete the model used for Git commit messages. Rebind the Git commit model before deleting this model.")


def _assert_model_delete_workspace_references_allowed(public_config: dict[str, Any], model_id: str) -> None:
    normalized_model_id = str(model_id or "").strip()
    if not normalized_model_id:
        return
    try:
        assert_model_delete_safe(
            normalized_model_id,
            public_config=public_config,
            include_public_config=False,
        )
    except ModelReferenceConflictError as exc:
        _record_config_scene_event(
            "validate",
            "config.model_delete.blocked",
            message="LLM model deletion blocked by live workspace references.",
            level="warning",
            outcome="rejected",
            fields={
                "modelId": normalized_model_id,
                "liveReferenceCount": exc.impact.get("liveReferenceCount", 0),
                "historicalReferenceCount": exc.impact.get("historicalReferenceCount", 0),
                "liveReferences": exc.impact.get("liveReferences", [])[:20],
            },
            lifecycle=True,
        )
        raise


def _validate_git_commit_settings(public_config: dict[str, Any]) -> None:
    git_config = _git_config(public_config)
    prompt = git_config.get("commit_message_prompt")
    if prompt is not None:
        try:
            validate_git_commit_message_prompt(str(prompt))
        except ValueError as exc:
            _record_config_scene_event(
                "validate",
                "config.git_commit_prompt.rejected",
                message="Git commit message prompt validation rejected the config draft.",
                level="warning",
                outcome="rejected",
                fields={"reason": "missing_required_placeholder", "error": str(exc)},
                lifecycle=True,
            )
            raise
    model_id = str(git_config.get("commit_message_model_ref") or "").strip()
    if not model_id:
        return
    llm = public_config.get("llm", {}) if isinstance(public_config, dict) else {}
    model_library = llm.get("model_library", {}) if isinstance(llm, dict) else {}
    if not isinstance(model_library, dict) or model_id not in model_library:
        _record_config_scene_event(
            "validate",
            "config.git_commit_model_ref.rejected",
            message="Git commit message model reference is not in the LLM model library.",
            level="warning",
            outcome="rejected",
            fields={"modelId": model_id, "reason": "unknown_model"},
            lifecycle=True,
        )
        raise ValueError(f"unknown Git commit message model: {model_id}")


def _mark_model_ref_profiles_unconfigured(public_config: dict[str, Any], model_id: str) -> dict[str, Any]:
    normalized_model_id = str(model_id or "").strip()
    if not normalized_model_id:
        return public_config
    llm = public_config.get("llm", {}) if isinstance(public_config, dict) else {}
    profiles = llm.get("profiles", {}) if isinstance(llm, dict) else {}
    if not isinstance(profiles, dict):
        return public_config
    for profile in profiles.values():
        if not isinstance(profile, dict):
            continue
        if str(profile.get("model_ref") or "").strip() != normalized_model_id:
            continue
        profile["model_ref"] = UNCONFIGURED_MODEL_REF
        profile["overrides"] = dict(profile.get("overrides") or {})
    return public_config


def _http_status_hint(error: Exception) -> str:
    if isinstance(error, httpx.HTTPStatusError):
        status_code = error.response.status_code
        if status_code == 401:
            return "认证失败（HTTP 401），请检查 API Key 是否正确、是否属于这个中转服务。"
        if status_code == 403:
            return "无权限（HTTP 403），请检查 API Key 权限或服务商访问限制。"
        if status_code == 404:
            return "接口不存在（HTTP 404），请检查服务地址是否填到了正确的 API 根路径。"
        return f"HTTP {status_code}"
    return str(error)


def _model_discovery_cache_key(api_base: str, *, api_key: str, api_key_source: str) -> str:
    normalized_base = str(api_base or "").strip().rstrip("/")
    source = str(api_key_source or "").strip()
    key_digest = hashlib.sha256(str(api_key or "").encode("utf-8")).hexdigest()[:16] if api_key else "no-key"
    return "|".join((normalized_base, source, key_digest))


def _model_discovery_safe_url(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    if not parsed.scheme or not parsed.netloc:
        return str(url or "").strip()
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path or ''}"


def _record_model_discovery_event(
    event_code: str,
    *,
    outcome: str,
    api_base: str,
    attempted: list[dict[str, Any]],
    elapsed_ms: int,
    cache_hit: bool = False,
    model_count: int = 0,
    error_type: str = "",
    error_hint: str = "",
) -> None:
    try:
        record_runtime_scene_event(
            "config",
            "model_discovery",
            event_code,
            level="warning" if outcome == "failed" else "info",
            outcome=outcome,
            message="Config model discovery completed.",
            fields={
                "apiBase": _model_discovery_safe_url(api_base),
                "attempted": attempted[:4],
                "attemptCount": len(attempted),
                "elapsedMs": elapsed_ms,
                "cacheHit": cache_hit,
                "modelCount": model_count,
                "errorType": error_type,
                "errorHint": trim_lines(error_hint, max_lines=2),
            },
        )
    except Exception:
        return


def _get_cached_model_discovery_failure(cache_key: str) -> tuple[str, list[dict[str, Any]]] | None:
    now = time.monotonic()
    with _MODEL_DISCOVERY_CACHE_LOCK:
        cached = _MODEL_DISCOVERY_NEGATIVE_CACHE.get(cache_key)
        if cached is None:
            return None
        expires_at, message, attempted = cached
        if expires_at > now:
            return message, copy.deepcopy(attempted)
        _MODEL_DISCOVERY_NEGATIVE_CACHE.pop(cache_key, None)
    return None


def _set_cached_model_discovery_failure(cache_key: str, message: str, attempted: list[dict[str, Any]]) -> None:
    with _MODEL_DISCOVERY_CACHE_LOCK:
        _MODEL_DISCOVERY_NEGATIVE_CACHE[cache_key] = (
            time.monotonic() + _MODEL_DISCOVERY_NEGATIVE_CACHE_TTL_SECONDS,
            message,
            copy.deepcopy(attempted),
        )


def _clear_cached_model_discovery_failure(cache_key: str) -> None:
    with _MODEL_DISCOVERY_CACHE_LOCK:
        _MODEL_DISCOVERY_NEGATIVE_CACHE.pop(cache_key, None)


def _discover_model_url(
    url: str,
    *,
    headers: dict[str, str],
    timeout: float,
) -> tuple[str, int | None, int, list[dict[str, Any]], Exception | None]:
    started_at = time.monotonic()
    try:
        with httpx.Client(timeout=timeout, headers=headers) as client:
            response = client.get(url)
            response.raise_for_status()
            return (
                url,
                response.status_code,
                int((time.monotonic() - started_at) * 1000),
                _normalize_discovered_models(response.json()),
                None,
            )
    except Exception as exc:
        status_code = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
        return url, status_code, int((time.monotonic() - started_at) * 1000), [], exc


def _discover_openai_compatible_model_list(
    api_base: str,
    *,
    api_key: str = "",
    timeout: float = _MODEL_DISCOVERY_DEFAULT_TIMEOUT_SECONDS,
    api_key_source: str = "",
) -> list[dict[str, Any]]:
    started_at = time.monotonic()
    effective_timeout = max(
        0.5,
        min(float(timeout or _MODEL_DISCOVERY_DEFAULT_TIMEOUT_SECONDS), _MODEL_DISCOVERY_DEFAULT_TIMEOUT_SECONDS),
    )
    cache_key = _model_discovery_cache_key(api_base, api_key=api_key, api_key_source=api_key_source)
    cached_failure = _get_cached_model_discovery_failure(cache_key)
    if cached_failure is not None:
        message, attempted = cached_failure
        _record_model_discovery_event(
            "config.model_discovery.cached_failure",
            outcome="failed",
            api_base=api_base,
            attempted=attempted,
            elapsed_ms=int((time.monotonic() - started_at) * 1000),
            cache_hit=True,
            error_type="cached_failure",
            error_hint=message,
        )
        raise ValueError(message)

    last_error: Exception | None = None
    attempted_urls = _model_discovery_urls(api_base)
    attempted: list[dict[str, Any]] = []
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    if attempted_urls:
        executor = ThreadPoolExecutor(max_workers=min(len(attempted_urls), 3), thread_name_prefix="model-discovery")
        try:
            futures = {
                executor.submit(
                    _discover_model_url,
                    url,
                    headers=headers,
                    timeout=effective_timeout,
                ): url
                for url in attempted_urls
            }
            pending = set(futures)
            while pending:
                done, pending = wait(pending, timeout=effective_timeout, return_when=FIRST_COMPLETED)
                if not done:
                    for pending_future in pending:
                        pending_future.cancel()
                    break
                for future in done:
                    url, status_code, elapsed_ms, models, exc = future.result()
                    if exc is None and models:
                        attempted.append({
                            "url": _model_discovery_safe_url(url),
                            "statusCode": status_code,
                            "elapsedMs": elapsed_ms,
                            "outcome": "succeeded",
                        })
                        for pending_future in pending:
                            pending_future.cancel()
                            attempted.append({
                                "url": _model_discovery_safe_url(futures[pending_future]),
                                "statusCode": None,
                                "elapsedMs": int((time.monotonic() - started_at) * 1000),
                                "outcome": "cancelled",
                                "errorType": "ShortCircuited",
                            })
                        _clear_cached_model_discovery_failure(cache_key)
                        _record_model_discovery_event(
                            "config.model_discovery.succeeded",
                            outcome="succeeded",
                            api_base=api_base,
                            attempted=attempted,
                            elapsed_ms=int((time.monotonic() - started_at) * 1000),
                            model_count=len(models),
                        )
                        return models
                    if exc is None:
                        attempted.append({
                            "url": _model_discovery_safe_url(url),
                            "statusCode": status_code,
                            "elapsedMs": elapsed_ms,
                            "outcome": "empty",
                        })
                    else:
                        last_error = exc
                        attempted.append({
                            "url": _model_discovery_safe_url(url),
                            "statusCode": status_code,
                            "elapsedMs": elapsed_ms,
                            "outcome": "failed",
                            "errorType": type(exc).__name__,
                        })
            for future in pending:
                url = futures[future]
                attempted.append({
                    "url": _model_discovery_safe_url(url),
                    "statusCode": None,
                    "elapsedMs": int(effective_timeout * 1000),
                    "outcome": "cancelled",
                    "errorType": "Timeout",
                })
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
    if last_error is not None:
        attempted_text = ", ".join(attempted_urls) if attempted_urls else "(无)"
        key_source = api_key_source or ("已提供密钥" if api_key else "未提供密钥")
        message = f"{_http_status_hint(last_error)} 已尝试：{attempted_text}。密钥来源：{key_source}。"
        _set_cached_model_discovery_failure(cache_key, message, attempted)
        _record_model_discovery_event(
            "config.model_discovery.failed",
            outcome="failed",
            api_base=api_base,
            attempted=attempted,
            elapsed_ms=int((time.monotonic() - started_at) * 1000),
            error_type=type(last_error).__name__,
            error_hint=message,
        )
        raise ValueError(message) from last_error
    message = "模型发现没有返回可用模型。"
    _set_cached_model_discovery_failure(cache_key, message, attempted)
    _record_model_discovery_event(
        "config.model_discovery.failed",
        outcome="failed",
        api_base=api_base,
        attempted=attempted,
        elapsed_ms=int((time.monotonic() - started_at) * 1000),
        error_type="empty_response",
        error_hint=message,
    )
    raise ValueError(message)


def discover_config_models(
    public_config: dict[str, Any] | None,
    *,
    draft_meta: dict | None = None,
    provider: dict[str, Any] | None = None,
    model_id: str = "",
    api_key_env: str = "",
    api_key: str = "",
) -> dict[str, Any]:
    old_public = _with_config_workspace_defaults(load_public_config())
    current = _prepare_submitted_public_config(public_config, old_public)
    current_meta = _normalize_draft_meta(draft_meta)
    validate_llm_public_config(current)
    provider_input = copy.deepcopy(provider or {})
    validate_llm_provider_target(provider_input, context="llm.model_discovery", resolve_dns=True)
    model_key_env = (
        str(api_key_env or "").strip()
        or _model_library_api_key_env(current, model_id)
    )
    provider_key_env = str(provider_input.get("api_key_env", "") or "").strip()
    discovery_key_env = model_key_env or provider_key_env
    resolved_api_key, api_key_source = _discovery_key_source_label(
        explicit_api_key=api_key,
        api_key_env=discovery_key_env,
        draft_meta=current_meta,
    )
    models = _normalize_discovered_models(_discover_openai_compatible_model_list(
        str(provider_input.get("base_url", "") or "").strip(),
        api_key=resolved_api_key,
        timeout=_MODEL_DISCOVERY_DEFAULT_TIMEOUT_SECONDS,
        api_key_source=api_key_source,
    ))
    return {
        "models": models,
        "providerKind": str(provider_input.get("kind", "") or "").strip(),
        "baseUrl": str(provider_input.get("base_url", "") or "").strip(),
        "apiKeySource": api_key_source,
    }


def _run_schtasks(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


def _assert_schtasks_success(result: subprocess.CompletedProcess[str], action: str) -> None:
    if result.returncode == 0:
        return
    detail = (result.stderr or result.stdout or "").strip()
    raise ValueError(f"无法打开系统环境变量窗口：{action} 失败{f'：{detail}' if detail else ''}")


def _find_environment_variables_window() -> int | None:
    user32 = ctypes.windll.user32
    handles: list[int] = []

    enum_windows_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    @enum_windows_proc
    def callback(hwnd: int, lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        title = buffer.value.strip()
        if any(part in title for part in _ENVIRONMENT_WINDOW_TITLE_PARTS):
            handles.append(int(hwnd))
            return False
        return True

    user32.EnumWindows(callback, 0)
    return handles[0] if handles else None


def _focus_window(hwnd: int) -> bool:
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    foreground_hwnd = user32.GetForegroundWindow()
    current_thread = kernel32.GetCurrentThreadId()
    target_thread = user32.GetWindowThreadProcessId(hwnd, None)
    foreground_thread = user32.GetWindowThreadProcessId(foreground_hwnd, None) if foreground_hwnd else 0
    attached_threads = [thread_id for thread_id in {target_thread, foreground_thread} if thread_id and thread_id != current_thread]
    for thread_id in attached_threads:
        user32.AttachThreadInput(current_thread, thread_id, True)
    user32.ShowWindow(hwnd, _SW_RESTORE)
    user32.ShowWindow(hwnd, _SW_SHOW)
    focused = False
    try:
        user32.BringWindowToTop(hwnd)
        user32.SetActiveWindow(hwnd)
        user32.SetFocus(hwnd)
        user32.SwitchToThisWindow(hwnd, True)
        focused = bool(user32.GetForegroundWindow() == hwnd)
    except Exception:
        focused = False
    try:
        focused = bool(user32.SetForegroundWindow(hwnd)) or focused
        if not focused:
            user32.SetWindowPos(hwnd, _HWND_TOPMOST, 0, 0, 0, 0, _SWP_NOMOVE | _SWP_NOSIZE | _SWP_SHOWWINDOW)
            user32.SetWindowPos(hwnd, _HWND_NOTOPMOST, 0, 0, 0, 0, _SWP_NOMOVE | _SWP_NOSIZE | _SWP_SHOWWINDOW)
        return focused or bool(user32.GetForegroundWindow() == hwnd)
    finally:
        for thread_id in attached_threads:
            user32.AttachThreadInput(current_thread, thread_id, False)


def _focus_environment_variables_window(timeout_seconds: float = 4.0) -> bool:
    if os.name != "nt":
        return False
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        hwnd = _find_environment_variables_window()
        if hwnd is not None:
            return _focus_window(hwnd)
        time.sleep(0.2)
    return False


def open_system_environment_settings() -> dict[str, object]:
    """Open the OS environment variable editor without reading environment values."""
    if os.name != "nt":
        raise ValueError("系统环境变量窗口目前只支持 Windows。")
    focused = False
    cleanup_error: str | None = None
    try:
        _run_schtasks(["schtasks.exe", "/Delete", "/TN", _OPEN_ENVIRONMENT_TASK_NAME, "/F"])
        create_result = _run_schtasks(
            [
                "schtasks.exe",
                "/Create",
                "/TN",
                _OPEN_ENVIRONMENT_TASK_NAME,
                "/SC",
                "ONCE",
                "/ST",
                "23:59",
                "/TR",
                "rundll32.exe sysdm.cpl,EditEnvironmentVariables",
                "/F",
                "/IT",
            ]
        )
        _assert_schtasks_success(create_result, "创建交互启动任务")
        run_result = _run_schtasks(["schtasks.exe", "/Run", "/TN", _OPEN_ENVIRONMENT_TASK_NAME])
        _assert_schtasks_success(run_result, "运行交互启动任务")
        focused = _focus_environment_variables_window()
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError(f"无法打开系统环境变量窗口：{exc}") from exc
    finally:
        try:
            cleanup_result = _run_schtasks(["schtasks.exe", "/Delete", "/TN", _OPEN_ENVIRONMENT_TASK_NAME, "/F"])
            if cleanup_result.returncode != 0:
                cleanup_error_detail = (cleanup_result.stderr or cleanup_result.stdout or "").strip()
                cleanup_error = cleanup_error_detail or f"returncode={cleanup_result.returncode}"
        except Exception as exc:
            cleanup_error = f"{type(exc).__name__}: {exc}"
    return {
        "opened": True,
        "focused": focused,
        "method": "interactive-scheduled-task",
        "cleanup_ok": cleanup_error is None,
        "cleanup_error": cleanup_error,
    }


def apply_config_workspace(
    public_config: dict[str, Any] | None,
    *,
    base_config: dict[str, Any] | None = None,
    draft_meta: dict | None = None,
    base_hash: str = "",
) -> dict[str, Any]:
    old_public = load_public_config()
    current_public = _with_config_workspace_defaults(old_public)
    submitted = _prepare_submitted_public_config(public_config, old_public)
    submitted_base = _normalize_apply_base_config(base_config, old_public)
    lang = _resolve_workspace_language(submitted)
    if submitted_base is None:
        _assert_base_hash_matches(base_hash, old_public, lang)
    else:
        _assert_apply_base_hash_matches(base_hash, submitted_base, lang)
    merged, changed_paths, _ = _merge_submitted_config_changes(
        base_config=submitted_base,
        submitted=submitted,
        old_public=current_public,
        lang=lang,
    )
    base_for_summary = submitted_base or current_public
    removed_model_ids = _removed_model_ids_from_paths(changed_paths, base_for_summary, submitted)
    for removed_model_id in removed_model_ids:
        _assert_model_delete_workspace_references_allowed(merged, removed_model_id)
    validate_llm_public_config(merged)
    _validate_git_commit_settings(merged)
    optional_unconfigured_profile_ids = _optional_unconfigured_profile_ids(merged)
    if optional_unconfigured_profile_ids:
        _record_config_scene_event(
            "validate",
            "config.llm_profiles.optional_missing_allowed",
            message="Optional LLM profiles are intentionally unconfigured.",
            outcome="allowed",
            fields={
                "profileCount": len(optional_unconfigured_profile_ids),
                "profileIds": optional_unconfigured_profile_ids,
            },
            lifecycle=True,
        )
    build_effective_config(merged)
    save_public_config(merged)

    normalized_meta = _normalize_draft_meta(draft_meta)
    cleared_envs = [str(env_name) for env_name in normalized_meta.get("pending_cleared_api_keys", [])]
    updated_envs: list[str] = []
    for env_name in normalized_meta.get("pending_cleared_api_keys", []):
        _delete_user_env_var(str(env_name))
        _PENDING_CLEAR_ENVS.discard(str(env_name))
    for env_name, api_key in normalized_meta.get("pending_api_keys", {}).items():
        secret = _resolve_pending_api_key(str(env_name), api_key)
        if secret is None:
            continue
        _set_user_env_var(str(env_name), secret)
        updated_envs.append(str(env_name))
        _drop_pending_api_key_token(api_key)

    persisted = _with_config_workspace_defaults(load_public_config())
    reload_config(str(CONFIG_PATH))
    llm_config = persisted.get("llm", {}) if isinstance(persisted.get("llm", {}), dict) else {}
    model_library = llm_config.get("model_library", {}) if isinstance(llm_config, dict) else {}
    model_options = list_llm_model_options(persisted)
    effective_config = build_effective_config(persisted)
    primary_profile = effective_config.llm.get_profile(role="primary")
    primary_provider = effective_config.llm.get_provider(primary_profile.provider_id)
    workspace = _build_workspace(
        persisted,
        message=text_for(
            _resolve_workspace_language(persisted),
            zh="配置已保存到外部 operator config.toml。",
            en="Config saved to external operator config.toml.",
        ),
    )
    _record_config_scene_event(
        "persist",
        "config.workspace.applied",
        message="Config workspace applied.",
        outcome="succeeded",
        fields={
            "configPath": str(CONFIG_PATH),
            "baseHash": str(base_hash or "").strip(),
            "resultHash": public_config_hash(persisted),
            "language": _resolve_workspace_language(persisted),
            "pendingApiKeyEnvCount": len(updated_envs),
            "pendingApiKeyEnvs": updated_envs,
            "clearedApiKeyEnvCount": len(cleared_envs),
            "clearedApiKeyEnvs": cleared_envs,
            "applyMode": "patch" if submitted_base is not None else "snapshot",
            "changedPathCount": len(changed_paths),
            "changedPaths": [_format_config_path(path) for path in changed_paths[:50]],
            "addedModelIds": _added_model_ids_from_paths(changed_paths, base_for_summary, submitted),
            "removedModelIds": removed_model_ids,
            "changedModelIds": _changed_model_ids_from_paths(changed_paths, base_for_summary, submitted),
            "runtimeConfigReloaded": True,
            "primaryProviderKind": primary_provider.kind,
            "primaryModel": primary_profile.model,
            "primaryTransport": primary_profile.transport,
            "primaryContract": primary_profile.contract,
            "modelLibraryCount": len(model_library) if isinstance(model_library, dict) else 0,
            "selectableModelCount": len(model_options),
            "modelIds": [str(item.get("model_id") or "").strip() for item in model_options[:20]],
        },
        lifecycle=True,
    )
    return workspace


__all__ = [
    "ConfigConflictError",
    "apply_config_workspace",
    "draft_add_model",
    "draft_check_model_image_input_capabilities",
    "draft_delete_model",
    "draft_update_model",
    "get_config_summary",
    "get_config_workspace",
    "open_system_environment_settings",
    "preview_config_workspace",
    "run_draft_llm_test",
    "update_intake_mode",
    "update_language",
]
