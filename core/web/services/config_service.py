"""Config workspace helpers for the web workbench."""

from __future__ import annotations

import copy
import ctypes
import os
import secrets
import subprocess
import time
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

import config.public_config as public_config_module
from config.public_config import (
    CONFIG_PATH,
    UNCONFIGURED_MODEL_REF,
    _delete_user_env_var,
    _set_user_env_var,
    add_llm_model,
    add_llm_profile,
    apply_llm_model_preset,
    build_effective_config,
    delete_llm_model,
    inspect_public_config,
    list_llm_model_options,
    list_llm_model_preset_options,
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
from .git_status_service import with_git_config_defaults
from .i18n import resolve_language, text_for
from .runtime_scene_service import record_runtime_scene_event
from .workbench_contract_service import get_workbench_contract


class ConfigConflictError(ValueError):
    """Raised when a saved config changed since the draft was loaded."""


PROFILE_LABELS = {
    "primary": {"zh": "主智能体", "en": "Primary"},
    "mental_model": {"zh": "心智模型", "en": "Mental Model"},
    "subagent_worker": {"zh": "子代理 Worker", "en": "Subagent Worker"},
    "subagent_explorer": {"zh": "子代理 Explorer", "en": "Subagent Explorer"},
    "supervised_baseline": {"zh": "监督基线", "en": "Supervised Baseline"},
    "supervised_candidate": {"zh": "监督候选", "en": "Supervised Candidate"},
    "compression": {"zh": "压缩配置", "en": "Compression"},
}
_PENDING_SECRET_PREFIX = "pending-secret:"
_PENDING_API_KEY_SECRETS: dict[str, tuple[str, str]] = {}
_PENDING_CLEAR_ENVS: set[str] = set()
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


def _resolve_workspace_language(public_config: dict[str, Any]) -> str:
    return resolve_language(public_config.get("ui", {}).get("language", "zh"))


def _config_sections(lang: str, editor_sections: list[dict[str, Any]] | None = None) -> list[dict[str, str]]:
    sections = [
        {
            "id": "overview",
            "title": text_for(lang, zh="配置源", en="Config Source"),
            "summary": text_for(
                lang,
                zh="当前生效网页入口与 config.toml 原始内容都在这里，避免再维护第二套页面。",
                en="The active web entry and raw config.toml source live here so there is only one surface.",
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
            "id": "profiles",
            "title": text_for(lang, zh="任务模型", en="Task Models"),
            "summary": text_for(
                lang,
                zh="查看每个任务当前使用的模型、密钥状态，并直接做连接测试。",
                en="Inspect the model and key state used by each task, then run direct connection checks.",
            ),
        },
        {
            "id": "models",
            "title": text_for(lang, zh="模型库", en="Models"),
            "summary": text_for(
                lang,
                zh="新增、编辑、删除模型库项时继续复用 public config 的共享变更内核。",
                en="Add, edit, and delete model library entries through the shared public config kernel.",
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
                    zh="结构化操作之外，还可以检查整份当前配置；保存时仍只写 config.toml。",
                    en="Beyond structured controls, check the full current config here while saving still writes only config.toml.",
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
        persisted_hash = public_config_hash(with_git_config_defaults(load_public_config()))
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


def _profile_label(profile_id: str, lang: str) -> str:
    mapping = PROFILE_LABELS.get(str(profile_id).strip())
    if mapping:
        return text_for(lang, zh=mapping["zh"], en=mapping["en"])
    token = str(profile_id or "").strip().replace("_", " ")
    return token.title() if lang == "en" else token


def _provider_signature(provider: Any) -> str:
    if not isinstance(provider, dict):
        return ""
    kind = str(provider.get("kind", "")).strip()
    base_url = str(provider.get("base_url", "")).strip().rstrip("/")
    api_key_env = str(provider.get("api_key_env", "")).strip()
    compat_mode = str(provider.get("compat_mode", "")).strip()
    return "|".join((kind, base_url, api_key_env, compat_mode))


def _selected_model_option(public_config: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any] | None:
    model_ref = str(profile.get("model_ref", "")).strip()
    options = list_llm_model_options(public_config)
    if model_ref:
        if model_ref == UNCONFIGURED_MODEL_REF:
            return None
        for option in options:
            if str(option.get("model_id", "")).strip() == model_ref:
                return option
        return None

    provider_signature = _provider_signature(profile.get("provider"))
    model = str(profile.get("model", "")).strip()
    if not provider_signature or not model:
        return None
    for option in options:
        if _provider_signature(option.get("provider")) == provider_signature and str(option.get("model", "")).strip() == model:
            return option
    return None


def _missing_required_llm_profiles(public_config: dict[str, Any]) -> list[str]:
    llm = public_config.get("llm", {})
    profiles = llm.get("profiles", {}) if isinstance(llm, dict) else {}
    if not isinstance(profiles, dict):
        return []
    missing: list[str] = []
    for profile_id, profile in profiles.items():
        if not isinstance(profile, dict):
            missing.append(str(profile_id))
            continue
        if _selected_model_option(public_config, profile) is None:
            missing.append(str(profile_id))
    return missing


def _validate_required_llm_profiles(public_config: dict[str, Any], lang: str) -> None:
    missing = _missing_required_llm_profiles(public_config)
    if not missing:
        return
    display_names = " / ".join(_profile_label(profile_id, lang) for profile_id in missing)
    raise ValueError(
        text_for(
            lang,
            zh=f"以下任务模型还没有绑定可用模型：{display_names}",
            en=f"These task models do not have a usable model bound yet: {display_names}",
        )
    )


def _decorate_model_options(public_config: dict[str, Any], draft_meta: dict | None) -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = []
    for option in list_llm_model_options(public_config):
        api_key_env = str(option.get("api_key_env", "")).strip()
        configured = bool(option.get("api_key_configured", False))
        resolved_configured, state = _api_key_display_state(api_key_env, configured, draft_meta)
        decorated = copy.deepcopy(option)
        decorated["api_key_configured"] = resolved_configured
        decorated["api_key_state"] = state
        options.append(decorated)
    return options


def _list_profile_cards(public_config: dict[str, Any], draft_meta: dict | None, lang: str) -> list[dict[str, Any]]:
    effective = build_effective_config(public_config)
    llm = public_config.get("llm", {})
    profiles = llm.get("profiles", {}) if isinstance(llm, dict) else {}
    cards: list[dict[str, Any]] = []
    for profile_id in effective.llm.profiles:
        public_profile = profiles.get(profile_id, {}) if isinstance(profiles, dict) else {}
        public_profile = public_profile if isinstance(public_profile, dict) else {}
        selected = _selected_model_option(public_config, public_profile)
        provider = effective.llm.get_provider(effective.llm.get_profile(profile_id=profile_id).provider_id)
        profile = effective.llm.get_profile(profile_id=profile_id)
        api_key_env = (
            str(public_profile.get("api_key_env", "")).strip()
            or str((selected or {}).get("api_key_env", "")).strip()
            or str(getattr(provider, "api_key_env", "") or "").strip()
        )
        configured = bool(effective.get_api_key_for_profile(profile_id=profile_id))
        resolved_configured, api_key_state = _api_key_display_state(api_key_env, configured, draft_meta)
        api_key_source = effective.llm.get_api_key_source_label_for_profile(profile_id=profile_id)
        if api_key_state == "pending":
            api_key_source = f"pending-env:{api_key_env}"
        elif api_key_state == "clear_pending":
            api_key_source = f"pending-clear:{api_key_env}"
        cards.append(
            {
                "profileId": str(profile_id),
                "label": _profile_label(str(profile_id), lang),
                "modelRef": str(public_profile.get("model_ref", "")).strip(),
                "selectedModelId": str((selected or {}).get("model_id", "")).strip(),
                "selectedModelLabel": str((selected or {}).get("label", "")).strip() or profile.model,
                "model": profile.model,
                "providerKind": provider.kind,
                "baseUrl": provider.base_url,
                "apiKeyEnv": api_key_env,
                "apiKeyConfigured": resolved_configured,
                "apiKeyState": api_key_state,
                "apiKeySource": api_key_source,
                "requiredModelMissing": selected is None,
            }
        )
    return cards


def _run_draft_test_llm_connection(
    public_config: dict[str, Any],
    profile_id: str | None = None,
    draft_meta: dict | None = None,
) -> dict[str, Any]:
    validate_llm_public_config(public_config)
    effective = build_effective_config(public_config)
    profile = effective.llm.get_profile(profile_id=profile_id) if profile_id else effective.llm.get_profile(role="primary")
    provider = effective.llm.get_provider(profile.provider_id)
    api_key = effective.get_api_key_for_profile(profile_id=profile.profile_id)
    api_key_source = effective.llm.get_api_key_source_label_for_profile(profile_id=profile.profile_id)
    if not provider.requires_api_key:
        api_key = None
        api_key_source = "not-required"
    meta = _normalize_draft_meta(draft_meta)
    pending = meta["pending_api_keys"]
    cleared = meta["pending_cleared_api_keys"]
    profile_public = (
        public_config.get("llm", {}).get("profiles", {}).get(profile.profile_id, {})
        if isinstance(public_config.get("llm", {}), dict)
        else {}
    )
    profile_public = profile_public if isinstance(profile_public, dict) else {}
    selected_option = _selected_model_option(public_config, profile_public) or {}
    env_candidates = [
        str(profile_public.get("api_key_env", "")).strip(),
        str(selected_option.get("api_key_env", "")).strip(),
        str(getattr(provider, "api_key_env", "") or "").strip(),
    ]
    if provider.requires_api_key:
        for env_name in env_candidates:
            if not env_name:
                continue
            if isinstance(cleared, list) and env_name in cleared:
                api_key = None
                api_key_source = f"pending-clear:{env_name}"
                break
            if isinstance(pending, dict) and env_name in pending:
                pending_secret = _resolve_pending_api_key(env_name, pending[env_name])
                if pending_secret is not None:
                    api_key = pending_secret
                    api_key_source = f"pending-env:{env_name}"
                    break
    try:
        try:
            result = public_config_module._probe_llm_runtime(provider, profile, api_key)
        except TypeError:
            result = public_config_module._probe_llm_runtime(provider, profile)
    except Exception as exc:
        _record_config_scene_event(
            "llm_test",
            "config.llm_test.failed",
            message=f"Draft LLM connection test failed: {type(exc).__name__}",
            level="error",
            outcome="failed",
            fields={
                "profileId": profile.profile_id,
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
            "profileId": profile.profile_id,
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
        "profile_id": profile.profile_id,
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
    public_config = with_git_config_defaults(public_config)
    diagnostics = inspect_public_config(public_config)
    diagnosis = diagnostics.get("diagnosis", {})
    summary = diagnostics.get("summary", {})
    lang = _resolve_workspace_language(public_config)
    contract = get_workbench_contract(public_config)
    llm_cfg = public_config.get("llm", {})
    model_library = llm_cfg.get("model_library", {}) if isinstance(llm_cfg, dict) else {}
    profiles = llm_cfg.get("profiles", {}) if isinstance(llm_cfg, dict) else {}
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
        "profileCount": len(profiles) if isinstance(profiles, dict) else 0,
        "blockingCount": len(blocking),
        "warningCount": len(warnings),
        "sections": _config_sections(lang, editor_sections),
        "publicConfig": public_config,
        "rawToml": _read_raw_public_config() if raw_toml is None else raw_toml,
        "draftMeta": normalized_meta,
        "diagnosis": diagnosis,
        "summary": summary,
        "editorSections": editor_sections,
        "editorMeta": editor_meta,
        "modelPresetOptions": list_llm_model_preset_options(),
        "modelOptions": _decorate_model_options(public_config, normalized_meta),
        "profileCards": _list_profile_cards(public_config, normalized_meta, lang),
    }


def _prepare_submitted_public_config(public_config: dict[str, Any] | None, old_public: dict[str, Any]) -> dict[str, Any]:
    old_with_defaults = with_git_config_defaults(old_public)
    submitted = copy.deepcopy(public_config) if isinstance(public_config, dict) else copy.deepcopy(old_with_defaults)
    return with_git_config_defaults(preserve_secret_blanks(submitted, old_with_defaults))


def _assert_base_hash_matches(base_hash: str, old_public: dict[str, Any], lang: str) -> str:
    current_hash = public_config_hash(with_git_config_defaults(old_public))
    expected_hash = str(base_hash or "").strip()
    if expected_hash and expected_hash != current_hash:
        raise ConfigConflictError(
            text_for(
                lang,
                zh="当前配置已被其他页面或进程改动，请重新加载后再保存这次修改",
                en="The saved config changed in another page or process. Reload before saving these changes.",
            )
        )
    return current_hash


def get_config_summary() -> dict[str, Any]:
    """Return a condensed config summary for shell-wide consumers."""

    public_config = with_git_config_defaults(load_public_config())
    diagnostics = inspect_public_config(public_config)
    diagnosis = diagnostics.get("diagnosis", {})
    contract = get_workbench_contract(public_config)
    llm_cfg = public_config.get("llm", {})
    model_library = llm_cfg.get("model_library", {})
    profiles = llm_cfg.get("profiles", {})
    lang = _resolve_workspace_language(public_config)

    blocking = diagnosis.get("blocking_issues") or []
    warnings = diagnosis.get("warnings") or []

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
        "profileCount": len(profiles) if isinstance(profiles, dict) else 0,
        "blockingCount": len(blocking),
        "warningCount": len(warnings),
        "sections": _config_sections(lang, build_editor_sections(public_config, lang)),
    }


def get_config_workspace() -> dict[str, Any]:
    """Return the full config workspace payload for the Config route."""

    public_config = with_git_config_defaults(load_public_config())
    return _build_workspace(public_config)


def preview_config_workspace(public_config: dict[str, Any] | None, draft_meta: dict | None = None, base_hash: str = "") -> dict[str, Any]:
    """Validate and normalize a draft config without persisting it."""

    old_public = with_git_config_defaults(load_public_config())
    submitted = _prepare_submitted_public_config(public_config, old_public)
    return _build_workspace(
        submitted,
        draft_meta=draft_meta,
        base_hash=str(base_hash or public_config_hash(old_public)).strip(),
        message=text_for(
            _resolve_workspace_language(submitted),
            zh="当前修改已刷新，尚未保存到 config.toml。",
            en="Current changes refreshed and not yet saved to config.toml.",
        ),
    )


def update_intake_mode(intake_mode: str) -> dict[str, Any]:
    """Persist the evolution intake mode and return the refreshed config summary."""

    public_config = with_git_config_defaults(load_public_config())
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

    public_config = with_git_config_defaults(load_public_config())
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
    old_public = with_git_config_defaults(load_public_config())
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
            zh="模型修改已更新，尚未保存到 config.toml。",
            en="Model changes updated and not yet saved to config.toml.",
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
    old_public = with_git_config_defaults(load_public_config())
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
    current_meta = _move_pending_api_key_env(current_meta, old_env, new_env)
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
            zh="模型修改已更新，尚未保存到 config.toml。",
            en="Model changes updated and not yet saved to config.toml.",
        ),
    )


def draft_delete_model(
    public_config: dict[str, Any] | None,
    *,
    draft_meta: dict | None = None,
    base_hash: str = "",
    model_id: str,
) -> dict[str, Any]:
    old_public = with_git_config_defaults(load_public_config())
    current = _prepare_submitted_public_config(public_config, old_public)
    current_meta = _normalize_draft_meta(draft_meta)
    current_library = current.get("llm", {}).get("model_library", {}) if isinstance(current.get("llm", {}), dict) else {}
    old_item = current_library.get(model_id, {}) if isinstance(current_library, dict) else {}
    old_env = str(old_item.get("api_key_env", "")).strip() if isinstance(old_item, dict) else ""
    updated = delete_llm_model(current, model_id)
    current_meta = _drop_api_key_state(current_meta, old_env)
    return _build_workspace(
        updated,
        draft_meta=current_meta,
        base_hash=str(base_hash or public_config_hash(old_public)).strip(),
        message=text_for(
            _resolve_workspace_language(updated),
            zh="模型修改已更新，尚未保存到 config.toml。",
            en="Model changes updated and not yet saved to config.toml.",
        ),
    )


def draft_add_profile(
    public_config: dict[str, Any] | None,
    *,
    draft_meta: dict | None = None,
    base_hash: str = "",
    profile_id: str,
    source_profile_id: str = "primary",
    model_id: str = "",
) -> dict[str, Any]:
    old_public = with_git_config_defaults(load_public_config())
    current = _prepare_submitted_public_config(public_config, old_public)
    validate_llm_public_config(current)
    updated = add_llm_profile(
        current,
        profile_id,
        source_profile_id=source_profile_id,
        model_id=model_id,
    )
    return _build_workspace(
        updated,
        draft_meta=draft_meta,
        base_hash=str(base_hash or public_config_hash(old_public)).strip(),
        message=text_for(
            _resolve_workspace_language(updated),
            zh="任务模型修改已更新，尚未保存到 config.toml。",
            en="Task model changes updated and not yet saved to config.toml.",
        ),
    )


def run_draft_llm_test(
    public_config: dict[str, Any] | None,
    *,
    draft_meta: dict | None = None,
    profile_id: str | None = None,
) -> dict[str, Any]:
    old_public = with_git_config_defaults(load_public_config())
    submitted = _prepare_submitted_public_config(public_config, old_public)
    validate_llm_public_config(submitted)
    return _run_draft_test_llm_connection(submitted, profile_id, _normalize_draft_meta(draft_meta))


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


def _discover_openai_compatible_model_list(
    api_base: str,
    *,
    api_key: str = "",
    timeout: int = 10,
    api_key_source: str = "",
) -> list[dict[str, Any]]:
    last_error: Exception | None = None
    attempted_urls = _model_discovery_urls(api_base)
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    with httpx.Client(timeout=timeout, headers=headers) as client:
        for url in attempted_urls:
            try:
                response = client.get(url)
                response.raise_for_status()
                models = _normalize_discovered_models(response.json())
                if models:
                    return models
            except Exception as exc:
                last_error = exc
                continue
    if last_error is not None:
        attempted_text = ", ".join(attempted_urls) if attempted_urls else "(无)"
        key_source = api_key_source or ("已提供密钥" if api_key else "未提供密钥")
        raise ValueError(f"{_http_status_hint(last_error)} 已尝试：{attempted_text}。密钥来源：{key_source}。") from last_error
    raise ValueError("模型发现没有返回可用模型。")


def discover_config_models(
    public_config: dict[str, Any] | None,
    *,
    draft_meta: dict | None = None,
    provider: dict[str, Any] | None = None,
    api_key: str = "",
) -> dict[str, Any]:
    old_public = with_git_config_defaults(load_public_config())
    current = _prepare_submitted_public_config(public_config, old_public)
    current_meta = _normalize_draft_meta(draft_meta)
    validate_llm_public_config(current)
    provider_input = copy.deepcopy(provider or {})
    validate_llm_provider_target(provider_input, context="llm.model_discovery")
    api_key_env = str(provider_input.get("api_key_env", "") or "").strip()
    resolved_api_key, api_key_source = _discovery_key_source_label(
        explicit_api_key=api_key,
        api_key_env=api_key_env,
        draft_meta=current_meta,
    )
    models = _normalize_discovered_models(_discover_openai_compatible_model_list(
        str(provider_input.get("base_url", "") or "").strip(),
        api_key=resolved_api_key,
        timeout=10,
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
            _run_schtasks(["schtasks.exe", "/Delete", "/TN", _OPEN_ENVIRONMENT_TASK_NAME, "/F"])
        except Exception:
            pass
    return {"opened": True, "focused": focused, "method": "interactive-scheduled-task"}


def apply_config_workspace(
    public_config: dict[str, Any] | None,
    *,
    draft_meta: dict | None = None,
    base_hash: str = "",
) -> dict[str, Any]:
    old_public = with_git_config_defaults(load_public_config())
    submitted = _prepare_submitted_public_config(public_config, old_public)
    lang = _resolve_workspace_language(submitted)
    _assert_base_hash_matches(base_hash, old_public, lang)
    validate_llm_public_config(submitted)
    _validate_required_llm_profiles(submitted, lang)
    build_effective_config(submitted)
    save_public_config(submitted)

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

    persisted = with_git_config_defaults(load_public_config())
    runtime_config = reload_config(str(CONFIG_PATH))
    primary_profile = runtime_config.llm.get_profile(role="primary")
    primary_provider = runtime_config.llm.get_provider(primary_profile.provider_id)
    primary_transport = (
        primary_profile.transport
        or getattr(primary_provider, "transport", "")
        or ("responses" if primary_provider.kind == "relay" else "chat_completions")
    )
    workspace = _build_workspace(
        persisted,
        message=text_for(
            _resolve_workspace_language(persisted),
            zh="配置已保存到 config.toml。",
            en="Config saved to config.toml.",
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
            "runtimeConfigReloaded": True,
            "primaryProviderId": primary_profile.provider_id,
            "primaryProviderKind": primary_provider.kind,
            "primaryTransport": primary_transport,
            "primaryModel": primary_profile.model,
        },
        lifecycle=True,
    )
    return workspace


__all__ = [
    "ConfigConflictError",
    "apply_config_workspace",
    "draft_add_model",
    "draft_add_profile",
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
